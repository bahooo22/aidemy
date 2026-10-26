"""Run one request end to end: pages → lessons → audio → package. One job at a time."""
import os, subprocess, sys, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402
import store  # noqa: E402

RUNNING = {}
LOCK = threading.Lock()
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"


def render(workspace, job):
    """Voice every lesson with the pair from the request; failures are named."""
    env = dict(os.environ)
    for host, field in (("A", "engine_a"), ("B", "engine_b")):
        engine, voice, pitch = job[f"{field}"], job[f"voice_{host.lower()}"], job[f"pitch_{host.lower()}"]
        if engine and voice:
            spec = f"{engine}:{voice}" + (f":{pitch:g}" if pitch is not None else "")
            env[f"AIDEMY_VOICE_{host}"] = spec
    if job["one_voice"]:
        env["AIDEMY_ONE_VOICE"] = "1"
    rendered = []
    for folder in sorted((Path(workspace) / "class").glob("[0-9][0-9]-*")):
        script = folder / "script.txt"
        if not script.exists():
            continue
        result = subprocess.run([sys.executable, str(SCRIPTS / "render_audio.py"), str(script),
                                 str(folder / f"{folder.name.split('-', 1)[1]}.mp3")],
                                capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"озвучка {folder.name}: {(result.stdout + result.stderr).strip()[-400:]}")
        rendered.append(folder)
    subprocess.run([sys.executable, str(SCRIPTS / "package_class.py"), str(workspace)],
                   capture_output=True, text=True)
    return rendered


def run(job_id, conn=None, build=pipeline.build, render_lessons=render):
    """The whole request in one thread. Every ending writes a status a person can read."""
    own = conn is None
    conn = conn or store.connect()
    job = store.get(conn, job_id)
    if not job:
        return
    workspace = store.root() / job["slug"]
    try:
        store.update(conn, job_id, status="writing", message="пишет уроки по скачанным страницам")
        build(workspace, job["topic"], job["lessons"], style=job["style"] or "менторский",
              note=job["note"] or "", progress=lambda text: store.update(conn, job_id, message=text))
        store.update(conn, job_id, status="synthesizing", message="озвучивает уроки")
        render_lessons(workspace, job)
        store.update(conn, job_id, status="done", message=f"готово: {job['lessons']} уроков в {job['slug']}/")
    except Exception as error:
        store.update(conn, job_id, status="error", message=f"{type(error).__name__}: {error}"[:900])
    finally:
        with LOCK:
            RUNNING.pop(job_id, None)
        if own:
            conn.close()


def start(job_id, conn=None):
    """Start a job once: the queue refuses duplicates, the registry refuses double starts."""
    with LOCK:
        if job_id in RUNNING:
            return False
        thread = threading.Thread(target=run, args=(job_id,), daemon=True)
        RUNNING[job_id] = thread
    thread.start()
    return True
