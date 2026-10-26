"""The page a phone in the home network opens: pick a topic, start a course, get the files.

Standard library only. The server never renders audio and has no lesson logic: it
writes a request into the queue and serves what the pipeline produced.
"""
import hmac, html, os, sys, threading, time, urllib.parse
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
STATUS_RU = {"queued": "в очереди", "mapping": "карта тем", "reading": "читает",
             "writing": "пишет", "synthesizing": "синтезирует", "done": "готово", "error": "ошибка"}


def token():
    return os.environ.get("AIDEMY_WEB_TOKEN", "").strip()


def page(title, body):
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f6f5f2;color:#1d1d1b}}
 main{{max-width:640px;margin:0 auto;padding:20px 16px 60px}}
 h1{{font-size:1.4rem;margin:8px 0 16px}} h2{{font-size:1.05rem;margin:24px 0 8px}}
 label{{display:block;margin:12px 0 4px;font-weight:600;font-size:.95rem}}
 input,select{{width:100%;padding:12px;font-size:1rem;border:1px solid #ccc;border-radius:10px;box-sizing:border-box}}
 .row{{display:flex;gap:8px}} .row>*{{flex:1}}
 button{{margin-top:18px;width:100%;padding:14px;font-size:1.05rem;border:0;border-radius:12px;background:#1d1d1b;color:#fff}}
 .card{{background:#fff;border:1px solid #e3e0d8;border-radius:14px;padding:14px;margin:10px 0}}
 .muted{{color:#6b6a66;font-size:.9rem}} a{{color:#14532d}}
 .bad{{background:#fde8e8;border-color:#f5b5b5}}
</style></head><body><main>{body}</main></body></html>"""


def token_form(message=""):
    note = f'<p class="bad card">{html.escape(message)}</p>' if message else ""
    return page("Aidemy", f"""<h1>Aidemy</h1>{note}
<form method="post" action="/token">
 <label>Токен доступа</label>
 <input name="token" type="password" autocomplete="current-password" required>
 <button>Войти</button>
</form>""")


def host_options(selected=None):
    out = []
    for engine, voices in ENGINES.items():
        options = "".join(f'<option value="{engine}:{v}">{engine} · {v}</option>' for v in voices)
        out.append(f'<optgroup label="{engine}">{options}</optgroup>')
    if selected:
        out = [o.replace(f'value="{selected}"', f'value="{selected}" selected') for o in out]
    return "".join(out)


def form(jobs):
    styles = "".join(f'<option value="{s}">{s}</option>' for s in STYLES)
    rows = "".join(
        f'<div class="card"><a href="/job/{j["id"]}">{html.escape(j["topic"])}</a>'
        f'<div class="muted">{STATUS_RU.get(j["status"], j["status"])} · {j["lessons"]} ур.'
        f' · {html.escape(j["style"] or "менторский")}</div></div>'
        for j in jobs) or '<p class="muted">Пока пусто.</p>'
    return page("Aidemy — новый курс", f"""<h1>Новый курс</h1>
<form method="post" action="/start">
 <label>Тема</label>
 <input name="topic" placeholder="НЛП: фокусы языка" required>
 <label>Стиль</label>
 <div class="row">
   <select name="style">{styles}</select>
   <input name="note" placeholder="уточнение: для 10 лет">
 </div>
 <label>Сколько уроков</label>
 <input name="lessons" type="number" min="1" max="12" value="3">
 <label>Ведущие</label>
 <div class="row">
   <select name="voice_a">{host_options("piper:ru_RU-denis-medium")}</select>
   <select name="voice_b">{host_options("piper:ru_RU-irina-medium")}</select>
 </div>
 <div class="row">
   <input name="pitch_a" type="number" step="1" min="-12" max="12" placeholder="питч A">
   <input name="pitch_b" type="number" step="1" min="-12" max="12" placeholder="питч B">
 </div>
 <label><input type="checkbox" name="one_voice" value="1" style="width:auto"> один рассказчик</label>
 <button>Запустить</button>
</form>
<h2>Пробник голосов</h2>
<p class="muted">Двадцать секунд фикстурного диалога выбранной парой. Курс не трогается.</p>
<form method="get" action="/probe">
 <div class="row">
   <select name="voice_a">{host_options("piper:ru_RU-denis-medium")}</select>
   <select name="voice_b">{host_options("piper:ru_RU-irina-medium")}</select>
 </div>
 <label><input type="checkbox" name="one_voice" value="1" style="width:auto"> один рассказчик</label>
 <button>Прослушать</button>
</form>
<h2>Курсы</h2>{rows}""")


def job_page(job):
    files = []
    base = store.root() / job["slug"]
    for rel in ("deliver", "class"):
        folder = base / rel
        if folder.exists():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".mp3", ".md", ".zip", ".txt", ".wav"}:
                    shown = path.relative_to(base).as_posix()
                    files.append(f'<li><a href="/files/{job["slug"]}/{shown}">{html.escape(shown)}</a></li>')
    status = STATUS_RU.get(job["status"], job["status"])
    listing = f"<ul>{''.join(files)}</ul>" if files else '<p class="muted">Файлов пока нет.</p>'
    message = f'<p class="muted">{html.escape(job["message"])}</p>' if job["message"] else ""
    return page(f"Aidemy — {job['topic']}", f"""<h1>{html.escape(job['topic'])}</h1>
<div class="card"><b>{status}</b>{message}
<div class="muted">{job['lessons']} ур. · {html.escape(job['style'] or 'менторский')} · {html.escape(job['note'] or '')}</div></div>
<h2>Файлы</h2>{listing}
<p><a href="/">← новый курс</a></p>""")


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

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            self.send_html("ok")
            return
        if not self.authorized():
            self.send_html(token_form("Нужен токен."), 403)
            return
        if path == "/":
            with store.session() as conn:
                self.send_html(form(store.jobs(conn)))
        elif path == "/probe":
            self.send_probe(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        elif path.startswith("/job/"):
            try:
                job_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                job_id = None
            job = None
            if job_id:
                with store.session() as conn:
                    job = store.get(conn, job_id)
            self.send_html(job_page(job) if job else page("Aidemy", "<p>Нет такой заявки.</p>"),
                           200 if job else 404)
        elif path.startswith("/files/"):
            self.send_file(path[len("/files/"):])
        else:
            self.send_html(page("Aidemy", "<p>Не найдено.</p>"), 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        path = urllib.parse.urlparse(self.path).path
        if path == "/token":
            given = (data.get("token") or [""])[0]
            if token() and hmac.compare_digest(given, token()):
                self.send_html(page("Aidemy", '<p>Готово.</p><p><a href="/">Дальше</a></p>'),
                               cookie=f"aidemy_token={given}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000")
            else:
                self.send_html(token_form("Неверный токен."), 403)
            return
        if not self.authorized():
            self.send_html(token_form("Нужен токен."), 403)
            return
        if path != "/start":
            self.send_html(page("Aidemy", "<p>Не найдено.</p>"), 404)
            return
        topic = (data.get("topic") or [""])[0].strip()
        if not topic:
            with store.session() as conn:
                page_html = form(store.jobs(conn))
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
        self.send_header("Content-Disposition", f'inline; filename="{mp3.name}.mp3"')
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
    threading.Thread(target=ticker, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"aidemy-web on http://0.0.0.0:{port} (token required)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
