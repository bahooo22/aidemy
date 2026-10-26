"""One course from the pages already on disk: notes are ours, the writing is the model's.

The web container cannot search the internet, so this builds only from `raw/`.
When there are too few pages it refuses in words a person can act on, instead of
producing a course with invented citations — the gate would fail it anyway.
"""
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"))
import runners  # noqa: E402

MIN_PAGES = 3
ATTEMPTS = 3
CARD_SECTIONS = ["**Слушать:**", "**Идея в трёх строках**", "**Зачем:**", "**Кто говорит:**",
                 "**Попробуй**", "**Правило**", "**Пропустить**", "**Глубже (опционально)**"]


def front_title(lines, fallback):
    """The title line is a quoted JSON string, so files written before the
    ensure_ascii fix still read as Cyrillic here instead of \u041c... noise."""
    raw = next((line[7:].strip() for line in lines if line.startswith("title: ")), "")
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw.strip('"')
    return raw or fallback


def pages(workspace):
    """(url, title, text) for every scraped page, shortest last."""
    found = []
    for path in sorted(Path(workspace).glob("raw/*/*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        head = text.splitlines()[:12]
        url = next((line[5:].strip() for line in head if line.startswith("url: ")), "")
        title = front_title(head, path.stem)
        body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S).strip()
        if url and body:
            found.append((url, title, body))
    return found


EXAMPLE = Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "references" / "lesson-example.md"


def example_script(lines=8):
    """The opening turns of the reference lesson. A small model copies the length of a
    sample far more reliably than it obeys a word count: asked for 24 turns it wrote
    ten and ended with "we will cover this in the next lines"."""
    turns = [line for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
             if re.match(r"^[AB]: ", line)][:lines]
    return "\n".join(turns)


def prompt_for(topic, style, note, number, total, page_list):
    """Each page enters trimmed: 2500 characters a page filled an 8 GB card with the
    model and its context, and the first live attempt then needed fifteen minutes to
    answer. At 1800 the same run answers in about a minute."""
    sources = "\n\n".join(f"[{i + 1}] {title} — {url}\n{body[:1800]}"
                          for i, (url, title, body) in enumerate(page_list))
    allowed = "\n".join(f"- {url}" for url, _, _ in page_list)
    return f"""Ты пишешь один урок аудиокурса по-русски.

Тема курса: {topic}. Стиль: {style}. {"Уточнение: " + note if note else ""}
Это урок {number} из {total}.

Ниже — источники. Опирайся только на них, ничего не выдумывай.

{sources}

Верни JSON с двумя полями: "turns" — массив строк диалога, каждая начинается с "A: "
или "B: ", и "card" — текст карточки в markdown. Если сервер не принимает схему
ответа, верни вместо JSON два блока в тройных обратных кавычках: первый — script.txt,
второй — card.md, без текста между ними.

Поле turns (или блок 1): диалог двух ведущих, каждая строка начинается с "A: " или "B: ".
Реплик 24-28, каждая 12-14 слов, всего 300-339 слова. Урок — это весь разговор сразу,
от зацепки до финала: нельзя заканчивать фразой «разберём дальше» и нельзя писать
вступление без продолжения. Короткий диалог на 10 реплик проверку не проходит.
Живая речь, без приказных форм («ты должен», «тебе нужно»).
Внутри — идея урока, насколько источники сходятся,
история или число из источника со ссылкой, затем одно маленькое дело.

Так звучит начало урока, который прошёл проверку: форма и длина реплик эти,
содержание своё.
{example_script()}

Блок 2 — card.md:
# Урок {number}. <название из 2-3 слов>
**Слушать:** lesson-{number:02d}.mp3 (2 мин)
**Идея в трёх строках**
- ...
**Зачем:** ...
**Кто говорит:** N из M источников сходятся; кто возражает и как, одной строкой
**Попробуй** · Быстрая победа · 10 минут
<шаги>
**Правило** <одно предложение>
**Пропустить** · без потерь. Урок {number + 1} — просто урок {number + 1}.
**Глубже (опционально)**
- <url из списка ниже>

Ссылаться можно только на эти адреса, дословно:
{allowed}
"""


def blocks(reply):
    """The two fenced blocks of a model reply: script first, card second."""
    found = re.findall(r"```[a-z]*\n(.*?)```", reply, flags=re.S)
    if len(found) < 2:
        raise ValueError("ответ без двух блоков: нужен script.txt и card.md в ```")
    return found[0].strip() + "\n", found[1].strip() + "\n"


LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {"type": "array", "minItems": 24, "maxItems": 28,
                  "items": {"type": "string", "pattern": "^[AB]: .+"}},
        "card": {"type": "string"},
    },
    "required": ["turns", "card"],
    "additionalProperties": False,
}


def parse_reply(reply):
    """A server that accepts the schema answers JSON, and `minItems` holds the turn
    count: asked in prose for 24 turns the model wrote ten and ended with "we will
    cover this in the next lines". The pattern keeps the card out of the turns, which
    the second live lesson managed anyway. A server without json_schema answers
    fenced blocks, and the same prompt still parses."""
    try:
        parsed = json.loads(reply)
    except ValueError:
        return blocks(reply)
    turns = [str(t) for t in (parsed.get("turns") or [])]
    card = str(parsed.get("card") or "")
    if not turns or not card.strip():
        raise ValueError("ответ без реплик или без карточки")
    bad = [t for t in turns if not re.match(r"^[AB]: \S", t)]
    if bad:
        raise ValueError(f"в turns {len(bad)} строк(и) не реплика: первая {bad[0][:60]!r}")
    return "\n".join(turns) + "\n", card if card.endswith("\n") else card + "\n"


def build(workspace, topic, lessons, style="менторский", note="", ask=None, progress=None, log=None):
    """Write the course into <workspace> and return a short report. Raises RuntimeError
    with a readable reason when the course cannot be built at all."""
    workspace = Path(workspace)
    page_list = pages(workspace)
    if len(page_list) < MIN_PAGES:
        raise RuntimeError(f"в raw/ только {len(page_list)} страниц(ы), нужно хотя бы {MIN_PAGES}: "
                           "сначала соберите страницы (scrape.py) или запустите заявку из диалога")
    ask = ask or runners.ask
    written = []
    for number in range(1, int(lessons) + 1):
        if progress:
            progress(f"пишет урок {number} из {lessons}")
        problem = ""
        for attempt in range(1, ATTEMPTS + 1):
            reply = ask(prompt_for(topic, style, note, number, lessons, page_list)
                        + (f"\n\nПрошлая попытка не прошла проверку:\n{problem}\n" if problem else ""),
                        reasoning="none", schema=LESSON_SCHEMA)
            try:
                script_text, card_text = parse_reply(reply)
            except ValueError as error:
                problem = str(error)
                continue
            folder = workspace / "class" / f"{number:02d}-lesson-{number}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "script.txt").write_text(script_text, encoding="utf-8")
            (folder / "card.md").write_text(card_text, encoding="utf-8")
            problem = gate(workspace, folder)
            if not problem:
                written.append(folder)
                break
        else:
            raise RuntimeError(f"урок {number} не прошёл проверку за {ATTEMPTS} попытки: {problem}")
    if log:
        log(f"написано уроков: {len(written)}")
    return written


def gate(workspace, folder):
    """Empty string when the lesson passes `check_lessons.py`, else its complaints."""
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy"
                                                  / "scripts" / "check_lessons.py"),
                             str(workspace), str(folder)],
                            capture_output=True, text=True)
    return "" if result.returncode == 0 else (result.stdout + result.stderr).strip()[:1500]
