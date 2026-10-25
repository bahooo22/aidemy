"""Check every lesson in <workspace>/class/ before its audio is rendered.

A lesson passes when its script is two-host dialogue of about 2 minutes with
no banned language, and its card has the standard sections and cites only
pages that are actually on disk in <workspace>/raw/. A citation to a page the
class never read is how invented sources get in, so it is a hard fail.

Usage: python3 check_lessons.py <workspace> [lesson-folder ...]   (default: all)
Exit 1 if any lesson fails.
"""
import os, re, sys
from pathlib import Path

CARD_SECTIONS = ["**Слушать:**", "**Идея в трёх строках**", "**Зачем:**", "**Кто говорит:**",
                 "**Попробуй**", "**Правило**", "**Пропустить**",
                 "**Глубже (опционально)**"]
# Demand words land as pressure on many learners (and on PDA profiles as a shutdown
# trigger). The English list stays: a script in English is not a reason to pass.
DEMAND = re.compile(r"\b(ты должен|тебе нужно|ты обязана|ты обязан|обязательно|не забудь"
                    r"|не забывай|you need to|you must|you should|make sure|you have to"
                    r"|don't forget)\b", re.I)
# A Russian card needs the em dash: it is normal typography there. The spoken script
# does not: the voice has no pause to give it, so the writer rewrites the phrase.
EMDASH = re.compile(r"—|–")
DOUBLE_DASH = re.compile(r"(?<!<!)--(?!>)")
TAG = re.compile(r"\[[a-zа-я ]+\]", re.I)
# Words per second differ per engine. Measured on Russian text here: piper 0.392
# (57, 114 and 228 words), silero 0.43, kokoro 0.48, so 2:00-2:30 is 300-383 words
# on piper, 280-350 on silero and 250-313 on kokoro. Two hosts on different engines
# get the intersection, so the lesson fits both.
WORD_RANGE = {"piper": (300, 383), "silero": (280, 350), "kokoro": (250, 313)}
WORDS_MIN, WORDS_MAX = WORD_RANGE["piper"]
TAGS_MAX = 3


def word_range(environ=None):
    """The word corridor for the engines the environment asks for."""
    environ = os.environ if environ is None else environ
    forced = environ.get("AIDEMY_TTS", "").strip()
    if forced in WORD_RANGE:
        return WORD_RANGE[forced]
    engines = []
    for host in ("A", "B"):
        spec = environ.get(f"AIDEMY_VOICE_{host}", "")
        engine = spec.split(":", 1)[0].strip() if ":" in spec else ""
        if engine in WORD_RANGE:
            engines.append(engine)
    if not engines:
        return WORDS_MIN, WORDS_MAX
    return (max(WORD_RANGE[e][0] for e in engines), min(WORD_RANGE[e][1] for e in engines))


# Balanced parentheses stay in the url (Wikipedia's Mercury_(planet)); a lone ")" ends
# it, as in a markdown link. Backticks, brackets and angle brackets wrap urls, never end them.
URL = re.compile(r"https?://(?:[^\s()<>\[\]`]|\([^\s()<>]*\))+")
# Bold, code spans and sentence ends trail urls in markdown; none of that is part of the url.
TRAILING = ".,;:!?*_'\"`"


def cited_urls(text):
    return [u.rstrip(TRAILING) for u in URL.findall(text)]


def same_page(url):
    """One key per page: scheme, www., #fragment and a trailing slash don't change
    the page. Exact matching failed valid citations and sent the writer round the
    fix loop up to three times for nothing. Trailing marks come off both sides,
    so a url that really ends in "_" or "!" still matches itself."""
    url = url.rstrip(TRAILING)
    m = re.match(r"https?://([^/?#]+)([^#]*)", url, re.I)
    if not m:
        return url
    path, q, query = m.group(2).partition("?")
    return m.group(1).lower().removeprefix("www.") + path.rstrip("/") + q + query


def scraped_urls(ws):
    # scrape.py writes UTF-8; reading in the locale's encoding crashed on Windows-style locales.
    return {line[5:].strip() for f in ws.glob("raw/*/*.md")
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[:12] if line.startswith("url: ")}


def banned(text, allow_emdash=False):
    found = []
    if not allow_emdash and EMDASH.search(text):
        found.append("emdash in a script (rewrite the phrase, the voice has no pause for it)")
    if DOUBLE_DASH.search(text):
        found.append("double hyphen")
    m = DEMAND.search(text)
    if m:
        found.append(f"demand phrase {m.group(0)!r}")
    return found


def check_script(text, words_range=None):
    lo, hi = words_range or word_range()
    lines = [l for l in text.splitlines() if l.strip()]
    bad = [l for l in lines if not re.match(r"^[AB]: \S", l)]
    words = len(re.sub(r"^[AB]:", "", text, flags=re.M).split())
    problems = [f"{len(bad)} lines not 'A:'/'B:' (first: {bad[0][:40]!r})"] if bad else []
    if not lo <= words <= hi:
        problems.append(f"{words} words, want {lo} to {hi} (about 2 minutes)")
    if len(TAG.findall(text)) > TAGS_MAX:
        problems.append(f"{len(TAG.findall(text))} audio tags, max {TAGS_MAX}")
    return problems + [f"script: {m}" for m in banned(text)], words


def check_card(text, urls):
    # Every check runs on what the learner sees. HTML comments (editor notes, a
    # commented-out draft section) are not content: a section that exists only
    # inside one is missing, a demand phrase inside one is not a fail.
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    problems = [f"card missing {s!r}" for s in CARD_SECTIONS if s not in body]
    problems += [f"card: {m}" for m in banned(body, allow_emdash=True)]
    cited = cited_urls(body)
    if not cited:
        problems.append("card cites no source")
    known = {same_page(u) for u in urls}
    problems += [f"card cites a page that is not in raw/: {u}" for u in cited if same_page(u) not in known]
    return problems


def check_plan(ws, urls):
    """The plan cites pages too. In the first full test, checking it by hand caught
    3 stories credited to the wrong page; a url not on disk is the part a script can catch."""
    plan = ws / "class" / "lesson-plan.md"
    if not plan.exists():
        return 0
    cited = set(cited_urls(plan.read_text(encoding="utf-8")))
    if not cited:
        # A plan that names sources without links has nothing this check can test; "ok" read as a pass.
        print("skip lesson-plan.md (cites no urls, nothing to check)")
        return 0
    known = {same_page(u) for u in urls}
    missing = sorted(u for u in cited if same_page(u) not in known)
    print(f"{'FAIL' if missing else 'ok  '} lesson-plan.md ({len(cited)} urls)")
    for u in missing:
        print(f"     plan cites a page that is not in raw/: {u}")
    return bool(missing)


def main(ws, folders):
    # A url or name the console can't show must not crash the report.
    sys.stdout.reconfigure(errors="replace")
    urls = scraped_urls(ws)
    failed = check_plan(ws, urls)
    for d in folders:
        script, card = d / "script.txt", d / "card.md"
        if not (script.exists() and card.exists()):
            print(f"FAIL {d.name}: missing script.txt or card.md")
            failed += 1
            continue
        problems, words = check_script(script.read_text(encoding="utf-8"))
        problems += check_card(card.read_text(encoding="utf-8"), urls)
        print(f"{'FAIL' if problems else 'ok  '} {d.name} ({words} words)")
        for p in problems:
            print(f"     {p}")
        failed += bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ws = Path(sys.argv[1]).expanduser().resolve()
    folders = [Path(a) for a in sys.argv[2:]] or sorted(p for p in (ws / "class").glob("[0-9][0-9]-*") if p.is_dir())
    main(ws, folders)
