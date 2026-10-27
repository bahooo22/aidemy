"""The page a phone in the home network opens: pick a topic, start a course, get the files.

Standard library only. The server never renders audio and has no lesson logic: it
writes a request into the queue and serves what the pipeline produced.
"""
import hmac, html, os, random, re, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe
import store
import worker

ENGINES = {
    "piper": ("ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium", "ru_RU-ruslan-medium"),
    "kokoro": ("dima", "sveta", "masha"),
    "silero": ("aidar", "baya", "kseniya", "eugene", "xenia"),
}
STYLES = ("менторский", "лёгкий", "строгий", "разговорный", "для детей", "шуточный")
# The topic box opens with one of these so a manual test run is two taps instead of a
# sentence typed on glass. The text disappears on focus, see the script at the bottom.
TOPICS = {
    "ru": ("как договариваться о зарплате", "почему мы откладываем важные разговоры",
           "как слушать, чтобы тебя услышали", "что делает привычка раннего подъёма",
           "как читать таблицы и не обмануться", "чем отличается усталость от выгорания",
           "как перестать перебивать", "что такое первый принцип и зачем он"),
    "en": ("how to negotiate your salary", "why we postpone the hard conversations",
           "how to listen so you get heard", "what an early rise actually buys",
           "how to read a chart without fooling yourself", "tiredness versus burnout",
           "how to stop interrupting people", "first principles and what they are for"),
}
STATUS_RU = {"queued": "в очереди", "mapping": "карта тем", "reading": "читает",
             "writing": "пишет", "synthesizing": "синтезирует", "done": "готово", "error": "ошибка"}


def token():
    return os.environ.get("AIDEMY_WEB_TOKEN", "").strip()


STR = {
    "ru": {
        "token_label": "Код доступа", "token_button": "Войти", "token_need": "Нужен код доступа.",
        "token_bad": "Неверный код доступа.", "token_ok": "Готово.", "token_next": "Дальше",
        "new_course": "Новый курс", "topic_label": "О чём рассказать?",
        "topic_ph": "Например: как договариваться о своём",
        "style_label": "Как рассказывать?", "note_ph": "своими словами: совсем просто",
        "lessons_label": "Сколько уроков?", "voices_details": "Голоса и звук (необязательно)",
        "voice_a": "Первый голос", "voice_b": "Второй голос", "pitch_a": "высота первого",
        "pitch_b": "высота второго", "one_voice": "пусть говорит один человек",
        "start": "Сделать курс", "probe_h": "Послушать голоса",
        "probe_p": "Двадцать секунд разговора выбранной пары. Курс при этом не начнётся.",
        "probe_btn": "Прослушать", "courses_h": "Мои курсы", "empty": "Пока пусто.",
        "files_h": "Файлы", "files_none": "Файлов пока нет.", "journal_h": "Журнал",
        "back": "← новый курс", "no_job": "Нет такой заявки.", "not_found": "Не найдено.",
        "theme": "Тема", "lang": "Язык", "lessons_word": "ур.", "done_hint":
            "Готово: забери файлы ниже и послушай с телефона.",
        "error_hint": "Что-то пошло не так. Прочитай последнюю строку журнала.",
        "lessons_h": "Уроки", "listen": "Слушать урок", "no_card": "Карточка ещё не готова.",
        "select_all": "выделить все", "delete_btn": "Удалить отмеченные",
        "delete_ask": "Удалить отмеченные курсы вместе с их файлами?",
        "deleted": "Удалено: {n}.", "nothing_marked": "Не отмечено ни одного курса.",
    },
    "en": {
        "token_label": "Access code", "token_button": "Enter", "token_need": "The access code is required.",
        "token_bad": "Wrong access code.", "token_ok": "Done.", "token_next": "Continue",
        "new_course": "New course", "topic_label": "What should it teach?",
        "topic_ph": "For example: how to negotiate your worth",
        "style_label": "How should it sound?", "note_ph": "in your words: very simple",
        "lessons_label": "How many lessons?", "voices_details": "Voices and sound (optional)",
        "voice_a": "First voice", "voice_b": "Second voice", "pitch_a": "pitch of the first",
        "pitch_b": "pitch of the second", "one_voice": "let one person speak",
        "start": "Make the course", "probe_h": "Listen to the voices",
        "probe_p": "Twenty seconds of the chosen pair talking. No course starts.",
        "probe_btn": "Play the sample", "courses_h": "My courses", "empty": "Nothing yet.",
        "files_h": "Files", "files_none": "No files yet.", "journal_h": "Journal",
        "back": "← new course", "no_job": "No such request.", "not_found": "Not found.",
        "theme": "Theme", "lang": "Language", "lessons_word": "lessons", "done_hint":
            "Done: take the files below and listen on your phone.",
        "error_hint": "Something went wrong. Read the last journal line.",
        "lessons_h": "Lessons", "listen": "Play the lesson", "no_card": "The card is not ready yet.",
        "select_all": "select all", "delete_btn": "Delete the marked ones",
        "delete_ask": "Delete the marked courses together with their files?",
        "deleted": "Deleted: {n}.", "nothing_marked": "No course is marked.",
    },
}

STATUS_EN = {"queued": "queued", "mapping": "topic map", "reading": "reading",
             "writing": "writing", "synthesizing": "voicing", "done": "done", "error": "error"}

STYLE = """
 :root{--bg:#f6f5f2;--fg:#1d1d1b;--card:#ffffff;--line:#e3e0d8;--muted:#6b6a66;
       --accent:#0f766e;--accent-fg:#ffffff;--good:#14532d;--bad-bg:#fde8e8;--bad-line:#f5b5b5}
 [data-theme="dark"]{--bg:#0d1b2a;--fg:#e8eef4;--card:#132437;--line:#24405c;--muted:#93a6b8;
       --accent:#2ec4b6;--accent-fg:#06222b;--good:#7ee2a8;--bad-bg:#3a1d20;--bad-line:#7c3a3f}
 body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:var(--bg);
      color:var(--fg);font-size:17px;line-height:1.5}
 main{max-width:680px;margin:0 auto;padding:20px 16px 70px}
 header{display:flex;justify-content:space-between;align-items:center;gap:8px}
 header .brand{font-weight:700;letter-spacing:.02em}
 header nav a,header nav button{color:var(--muted);text-decoration:none;font-size:.9rem;
      background:none;border:1px solid var(--line);border-radius:999px;padding:6px 12px;cursor:pointer}
 h1{font-size:1.5rem;margin:14px 0 16px} h2{font-size:1.1rem;margin:26px 0 8px}
 label{display:block;margin:14px 0 6px;font-weight:600}
 input,select{width:100%;padding:14px;font-size:1.05rem;border:1px solid var(--line);
      border-radius:12px;box-sizing:border-box;background:var(--card);color:var(--fg)}
 input::placeholder{color:var(--muted)}
 .row{display:flex;gap:10px} .row>*{flex:1}
 button.primary{margin-top:20px;width:100%;padding:16px;font-size:1.15rem;font-weight:700;border:0;
      border-radius:14px;background:var(--accent);color:var(--accent-fg);cursor:pointer}
 button.secondary{margin-top:12px;width:100%;padding:14px;font-size:1.05rem;border:1px solid var(--line);
      border-radius:14px;background:var(--card);color:var(--fg);cursor:pointer}
 .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0;
      box-shadow:0 1px 2px rgb(0 0 0 / .05)}
 .muted{color:var(--muted);font-size:.92rem} a{color:var(--good)}
 .bad{background:var(--bad-bg);border-color:var(--bad-line)}
 details{margin:14px 0} summary{cursor:pointer;font-weight:600;color:var(--muted)}
 ul.journal{list-style:none;margin:8px 0;padding:0} ul.journal li{padding:6px 0;border-bottom:1px dashed var(--line);
      font-size:.92rem;color:var(--muted)}
 ul.files{margin:8px 0;padding-left:20px} ul.files li{margin:4px 0}
 .lesson audio{width:100%;margin:0 0 10px} .lesson h3{margin:0 0 8px} .lesson ul{margin:8px 0;padding-left:20px}
 .lesson p{margin:8px 0} .lesson li{margin:4px 0}
 .course{display:block} label.pick{display:flex;align-items:center;gap:10px;margin:0;font-weight:600}
 label.pick a{flex:1}
"""


def page(title, body, lang="ru", theme=None):
    words = STR[lang]
    other = "en" if lang == "ru" else "ru"
    head = f"""<header><span class="brand">Aidemy</span><nav>
<a href="?lang={other}">{words['lang']}: {other.upper()}</a>
<button type="button" onclick="var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;localStorage.setItem('aidemy-theme',t);this.textContent='{words['theme']}: '+t">{words['theme']}</button>
</nav></header>"""
    saved = theme or ""
    return f"""<!doctype html><html lang="{lang}" data-theme="{saved}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
<script>var t=localStorage.getItem('aidemy-theme');if(!t)t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.dataset.theme=t;</script>
<script>
document.addEventListener('DOMContentLoaded', function(){{
  /* The script sits in `head`, so without this the page would be a form of dead
     buttons: the boxes and the topic field do not exist yet when it runs. */
  document.querySelectorAll('[data-pristine]').forEach(function(f){{
    f.addEventListener('focus',function(){{if(f.dataset.pristine==='1'){{f.value='';f.dataset.pristine='0';}}}});
  }});
  document.querySelectorAll('[data-selectall]').forEach(function(box){{
    box.addEventListener('change',function(){{
      box.closest('form').querySelectorAll('input[name=del]').forEach(function(b){{b.checked=box.checked;}});
    }});
  }});
  document.querySelectorAll('[data-confirm]').forEach(function(btn){{
    btn.addEventListener('click',function(e){{if(!confirm(btn.dataset.confirm))e.preventDefault();}});
  }});
}});
</script>
</head><body><main>{head}{body}</main></body></html>"""


def token_form(message="", lang="ru"):
    words = STR[lang]
    note = f'<p class="bad card">{html.escape(message)}</p>' if message else ""
    return page("Aidemy", f"""<h1>Aidemy</h1>{note}
<form method="post" action="/token">
 <label>{words['token_label']}</label>
 <input name="token" type="password" autocomplete="current-password" required>
 <button class="primary">{words['token_button']}</button>
</form>""", lang=lang)


def md_to_html(text):
    """Card markdown into page HTML — headings, bullets and bold, nothing else.

    The card is written by a model and read on a phone, so escaping comes first and
    only then the three constructs the writer brief allows. A wider markdown would
    mean a library in the image for syntax nobody is allowed to use.
    """
    out, bullets = [], []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush = f'<ul>{"".join(f"<li>{item}</li>" for item in bullets)}</ul>' if bullets else ""
            if flush:
                out.append(flush)
            bullets = []
            continue
        escaped = html.escape(line)
        bold = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        if line.startswith("- "):
            bullets.append(bold[2:])
        elif line.startswith("### "):
            out.append(f"<h4>{bold[5:]}</h4>")
        elif line.startswith("## "):
            out.append(f"<h3>{bold[3:]}</h3>")
        elif line.startswith("# "):
            out.append(f"<h3>{bold[2:]}</h3>")
        else:
            out.append(f"<p>{bold}</p>")
    if bullets:
        out.append(f'<ul>{"".join(f"<li>{item}</li>" for item in bullets)}</ul>')
    return "".join(out)


def host_options(selected=None):
    out = []
    for engine, voices in ENGINES.items():
        options = "".join(f'<option value="{engine}:{v}">{engine} · {v}</option>' for v in voices)
        out.append(f'<optgroup label="{engine}">{options}</optgroup>')
    if selected:
        out = [o.replace(f'value="{selected}"', f'value="{selected}" selected') for o in out]
    return "".join(out)


def form(jobs, lang="ru", notice=""):
    words = STR[lang]
    styles = "".join(f'<option value="{s}">{s}</option>' for s in STYLES)
    status = STATUS_RU if lang == "ru" else STATUS_EN
    topic = random.choice(TOPICS[lang if lang in TOPICS else "ru"])
    rows = "".join(
        f'<div class="card course"><label class="pick">'
        f'<input type="checkbox" name="del" value="{j["id"]}" style="width:auto">'
        f'<a href="/job/{j["id"]}">{html.escape(j["topic"])}</a></label>'
        f'<div class="muted">{status.get(j["status"], j["status"])} · {j["lessons"]} {words["lessons_word"]}'
        f' · {html.escape(j["style"] or "менторский")}</div></div>'
        for j in jobs) or f'<p class="muted">{words["empty"]}</p>'
    note = f'<p class="muted card">{html.escape(notice)}</p>' if notice else ""
    delete_form = (f'<form method="post" action="/delete">'
                   f'<label><input type="checkbox" data-selectall value="1" style="width:auto"> '
                   f'{words["select_all"]}</label>'
                   f'{rows}'
                   f'<button class="secondary" data-confirm="{words["delete_ask"]}">{words["delete_btn"]}</button>'
                   f'</form>') if jobs else rows
    return page("Aidemy — " + words["new_course"], f"""<h1>{words['new_course']}</h1>
<form method="post" action="/start">
 <label>{words['topic_label']}</label>
 <input name="topic" value="{html.escape(topic)}" data-pristine="1" required>
 <label>{words['style_label']}</label>
 <div class="row">
   <select name="style">{styles}</select>
   <input name="note" placeholder="{words['note_ph']}">
 </div>
 <label>{words['lessons_label']}</label>
 <input name="lessons" type="number" min="1" max="12" value="3">
 <details>
  <summary>{words['voices_details']}</summary>
  <label>{words['voice_a']}</label>
  <select name="voice_a">{host_options("piper:ru_RU-denis-medium")}</select>
  <label>{words['voice_b']}</label>
  <select name="voice_b">{host_options("piper:ru_RU-irina-medium")}</select>
  <div class="row">
   <input name="pitch_a" type="number" step="1" min="-12" max="12" placeholder="{words['pitch_a']}">
   <input name="pitch_b" type="number" step="1" min="-12" max="12" placeholder="{words['pitch_b']}">
  </div>
  <label><input type="checkbox" name="one_voice" value="1" style="width:auto"> {words['one_voice']}</label>
 </details>
 <button class="primary">{words['start']}</button>
</form>
{note}
<h2>{words['probe_h']}</h2>
<p class="muted">{words['probe_p']}</p>
<form method="get" action="/probe">
 <details open>
  <summary>{words['voices_details']}</summary>
  <div class="row">
   <select name="voice_a">{host_options("piper:ru_RU-denis-medium")}</select>
   <select name="voice_b">{host_options("piper:ru_RU-irina-medium")}</select>
  </div>
  <label><input type="checkbox" name="one_voice" value="1" style="width:auto"> {words['one_voice']}</label>
 </details>
 <button class="secondary">{words['probe_btn']}</button>
</form>
<h2>{words['courses_h']}</h2>{delete_form}""", lang=lang)


def lessons_block(job, words, lang):
    """Every lesson as a card you read here, with its own player.

    The files list below this block is for taking the course with you; a phone that
    opens the page should not have to download a `card.md` to see what the lesson
    taught. Cards come from `class/*/card.md` and audio from the same folder.
    """
    base = store.root() / job["slug"] / "class"
    if not base.is_dir():
        return ""
    blocks = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        card = folder / "card.md"
        audio = sorted(folder.glob("*.mp3"))
        # The link is relative to the course root, so `class/` belongs in it.
        where = "/".join(urllib.parse.quote(part) for part in ("class", folder.name))
        player = (f'<audio controls preload="none" src="/files/{urllib.parse.quote(job["slug"])}'
                  f'/{where}/{urllib.parse.quote(audio[0].name)}">'
                  f'</audio>') if audio else f'<p class="muted">{words["no_card"]}</p>'
        body = md_to_html(card.read_text(encoding="utf-8")) if card.is_file() else \
            f'<p class="muted">{words["no_card"]}</p>'
        blocks.append(f'<section class="card lesson">{player}{body}</section>')
    if not blocks:
        return ""
    return f'<h2>{words["lessons_h"]}</h2>{"".join(blocks)}'


def job_page(job, log=(), lang="ru"):
    words = STR[lang]
    status = STATUS_RU if lang == "ru" else STATUS_EN
    files = []
    base = store.root() / job["slug"]
    for rel in ("deliver", "class"):
        folder = base / rel
        if folder.exists():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".mp3", ".md", ".zip", ".txt", ".wav", ".docx"}:
                    shown = path.relative_to(base).as_posix()
                    files.append(f'<li><a href="/files/{job["slug"]}/{shown}">{html.escape(shown)}</a></li>')
    listing = (f'<ul class="files">{"".join(files)}</ul>' if files
               else f'<p class="muted">{words["files_none"]}</p>')
    hint = ""
    if job["status"] == "done":
        hint = f'<p class="muted">{words["done_hint"]}</p>'
    if job["status"] == "error":
        hint = f'<p class="bad card">{words["error_hint"]}</p>'
    message = f'<p class="muted">{html.escape(job["message"])}</p>' if job["message"] else ""
    # The log is what a person reads at breakfast: which step took how long, and where
    # a failed course actually failed.
    steps = "".join(f'<li>{time.strftime("%H:%M:%S", time.localtime(entry["ts"]))} · '
                    f'{status.get(entry["status"], entry["status"])} · '
                    f'{html.escape(entry["message"])}</li>' for entry in log)
    journal = f'<h2>{words["journal_h"]}</h2><ul class="journal">{steps}</ul>' if steps else ""
    return page(f"Aidemy — {job['topic']}", f"""<h1>{html.escape(job['topic'])}</h1>
<div class="card"><b>{status.get(job['status'], job['status'])}</b>{message}
<div class="muted">{job['lessons']} {words['lessons_word']} · {html.escape(job['style'] or 'менторский')} · {html.escape(job['note'] or '')}</div></div>
{hint}
{lessons_block(job, words, lang)}
<h2>{words['files_h']}</h2>{listing}
{journal}
<p><a href="/">{words['back']}</a></p>""", lang=lang)


class Handler(BaseHTTPRequestHandler):
    server_version = "aidemy-web"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_html(self, body, code=200, cookie=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        wanted = token()
        if not wanted:
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "aidemy_token" and hmac.compare_digest(value, wanted):
                return True
        return False

    def lang(self):
        """The language lives in a cookie; ?lang= sets it and bounces back without the
        parameter, so a shared link never carries the choice."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        wanted = (query.get("lang") or [""])[0].strip().lower()
        if wanted in ("ru", "en"):
            return wanted, f"aidemy_lang={wanted}; Path=/; Max-Age=31536000"
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "aidemy_lang" and value in ("ru", "en"):
                return value, None
        return "ru", None

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        lang, lang_cookie = self.lang()
        if path == "/health":
            self.send_html("ok")
            return
        if lang_cookie:
            self.send_response(303)
            self.send_header("Location", path)
            self.send_header("Set-Cookie", lang_cookie)
            self.end_headers()
            return
        if not self.authorized():
            self.send_html(token_form(STR[lang]["token_need"], lang=lang), 403)
            return
        if path == "/":
            with store.session() as conn:
                self.send_html(form(store.jobs(conn), lang=lang))
        elif path == "/probe":
            self.send_probe(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        elif path.startswith("/job/"):
            try:
                job_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                job_id = None
            job = None
            log = ()
            if job_id:
                with store.session() as conn:
                    job = store.get(conn, job_id)
                    log = store.history(conn, job_id) if job else ()
            self.send_html(job_page(job, log, lang=lang) if job
                           else page("Aidemy", f"<p>{STR[lang]['no_job']}</p>", lang=lang),
                           200 if job else 404)
        elif path.startswith("/files/"):
            self.send_file(path[len("/files/"):])
        else:
            self.send_html(page("Aidemy", f"<p>{STR[lang]['not_found']}</p>", lang=lang), 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        path = urllib.parse.urlparse(self.path).path
        lang, _ = self.lang()
        words = STR[lang]
        if path == "/token":
            given = (data.get("token") or [""])[0]
            if token() and hmac.compare_digest(given, token()):
                self.send_html(page("Aidemy", f'<p>{words["token_ok"]}</p>'
                                              f'<p><a href="/">{words["token_next"]}</a></p>', lang=lang),
                               cookie=f"aidemy_token={given}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000")
            else:
                self.send_html(token_form(words["token_bad"], lang=lang), 403)
            return
        if not self.authorized():
            self.send_html(token_form(words["token_need"], lang=lang), 403)
            return
        if path == "/delete":
            ids = []
            for raw in data.get("del") or []:
                try:
                    ids.append(int(raw))
                except ValueError:
                    continue
            if not ids:
                with store.session() as conn:
                    self.send_html(form(store.jobs(conn), lang=lang,
                                        notice=words["nothing_marked"]))
                return
            with store.session() as conn:
                gone = store.delete(conn, ids)
                left = store.jobs(conn)
            names = ", ".join(html.escape(item["topic"]) for item in gone)
            self.send_html(form(left, lang=lang, notice=words["deleted"].format(n=len(gone))
                                + (" " + names if names else "")))
            return
        if path != "/start":
            self.send_html(page("Aidemy", f"<p>{words['not_found']}</p>", lang=lang), 404)
            return
        topic = (data.get("topic") or [""])[0].strip()
        if not topic:
            with store.session() as conn:
                page_html = form(store.jobs(conn), lang=lang)
            self.send_html(page_html, 400)
            return
        hosts = {}
        for host in ("a", "b"):
            spec = (data.get(f"voice_{host}") or ["piper:ru_RU-denis-medium"])[0]
            engine, _, voice = spec.partition(":")
            hosts[f"engine_{host}"] = engine
            hosts[f"voice_{host}"] = voice
            raw_pitch = (data.get(f"pitch_{host}") or [""])[0].strip()
            hosts[f"pitch_{host}"] = float(raw_pitch) if raw_pitch else None
        try:
            with store.session() as conn:
                job_id = store.create(
                    conn, topic=topic,
                    lessons=max(1, min(12, int((data.get("lessons") or ["3"])[0] or 3))),
                    style=(data.get("style") or ["менторский"])[0],
                    note=(data.get("note") or [""])[0],
                    runner=os.environ.get("AIDEMY_RUNNER", "auto"),
                    hosts=hosts, one_voice=(data.get("one_voice") or [""])[0] == "1")
        except ValueError as refusal:
            self.send_html(page("Aidemy", f'<p class="bad card">{html.escape(str(refusal))}</p>'
                                          '<p><a href="/">← назад</a></p>'), 409)
            return
        self.send_response(303)
        self.send_header("Location", f"/job/{job_id}")
        self.end_headers()

    def send_probe(self, query):
        voice_a = (query.get("voice_a") or ["piper:ru_RU-denis-medium"])[0]
        voice_b = (query.get("voice_b") or ["piper:ru_RU-irina-medium"])[0]
        one_voice = (query.get("one_voice") or [""])[0] == "1"
        try:
            mp3, log = probe.probe(voice_a, voice_b, one_voice)
        except RuntimeError as refusal:
            self.send_html(page("Aidemy", f'<p class="bad card">{html.escape(str(refusal))}</p>'
                                          '<p><a href="/">← назад</a></p>'), 500)
            return
        data = mp3.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{mp3.name}"')
        self.end_headers()
        self.wfile.write(data)
        tail = log.strip().splitlines()
        if tail:
            sys.stderr.write("probe ok: " + tail[-1][:160] + "\n")


    def send_file(self, relative):
        base = store.root().resolve()
        target = (base / urllib.parse.unquote(relative)).resolve()
        if base not in target.parents or not target.is_file():
            self.send_html(page("Aidemy", "<p>Файла нет.</p>"), 404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg" if target.suffix == ".mp3" else "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def ticker(interval=5):
    """Move queued requests to a status a person can act on; never writes lessons."""
    while True:
        try:
            with store.session() as conn:
                worker.tick(conn)
        except Exception as error:
            sys.stderr.write(f"worker: {type(error).__name__}: {error}\n")
        time.sleep(interval)


def main(port=None):
    if not token():
        sys.exit("AIDEMY_WEB_TOKEN is empty: the page is not exposed without a token")
    port = int(port or os.environ.get("AIDEMY_WEB_PORT") or 8080)
    with store.session() as conn:
        closed = store.resume(conn)
    if closed:
        print(f"aidemy-web: закрыты прерванные прогон(ы): {', '.join(map(str, closed))}", flush=True)
    threading.Thread(target=ticker, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"aidemy-web on http://0.0.0.0:{port} (token required)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
