"""Background tick: look at the oldest request and record who is going to run it.

The site keeps the queue honest, not the runner: nothing here writes lessons, it
only moves a request to the status a person can act on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"))
import runners  # noqa: E402

import jobs  # noqa: E402
import store  # noqa: E402

AGENT_WAIT = "ждёт агента Qoder: заявка сохранена, курс соберётся в диалоге"
LOCAL_DOWN = "локальная модель не поднята: lms server start, затем lms load"
LOCAL_READY = "модель на хосте готова, оркестратор исследования ещё подключается"


def plan(job, choose, health):
    """Decide what one request deserves right now: (runner, status, message, start_now).

    The same answer serves a brand new request and one parked in «карта тем», so the
    parked one can be re-checked without inventing a second copy of the rules.
    """
    runner = job["runner"] if job["runner"] in ("api", "local", "qoder") else choose()
    if runner in ("api", "local"):
        state, detail = health()
        if state not in ("ok", "no-model"):
            return runner, "mapping", f"{LOCAL_DOWN} ({detail})", False
        workspace = store.root() / job["slug"]
        pages = len(list((workspace / "raw").glob("*/*.md"))) if (workspace / "raw").exists() else 0
        if pages >= 3:
            return runner, "writing", f"страниц: {pages}, пишет уроки", True
        return runner, "mapping", f"в raw/ {pages} страниц(ы), нужно 3: заявку заберёт агент", False
    return "qoder", "mapping", AGENT_WAIT, False


def tick(conn=None, choose=runners.choose, health=runners.health):
    """Move requests to a status a human can read, and re-read the parked ones.

    Returns the last id it touched, or None when nothing changed. The second half
    matters: pages are saved and `lms server start` happens while nobody watches the
    page, and a tick that only looked at «в очереди» would leave the parked request
    showing a stale reason forever. A parked request is rewritten only when the
    answer actually differs, so the journal does not gain a line every five seconds.
    """
    own = conn is None
    conn = conn or store.connect()
    try:
        touched = None
        job = store.next_queued(conn)
        if job:
            runner, status, message, start = plan(job, choose, health)
            store.update(conn, job["id"], status=status, message=message, runner=runner)
            touched = job["id"]
            if start:
                jobs.start(job["id"])
        for parked in store.waiting(conn):
            runner, status, message, start = plan(parked, choose, health)
            if (status, message) == (parked["status"], parked["message"]):
                continue
            store.update(conn, parked["id"], status=status, message=message, runner=runner)
            touched = parked["id"]
            if start:
                jobs.start(parked["id"])
        return touched
    finally:
        if own:
            conn.close()
