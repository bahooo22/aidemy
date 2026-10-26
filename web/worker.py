"""Background tick: look at the oldest request and record who is going to run it.

The site keeps the queue honest, not the runner: nothing here writes lessons, it
only moves a request to the status a person can act on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"))
import runners  # noqa: E402

import store  # noqa: E402

AGENT_WAIT = "ждёт агента Qoder: заявка сохранена, курс соберётся в диалоге"
LOCAL_DOWN = "локальная модель не поднята: lms server start, затем lms load"
LOCAL_READY = "модель на хосте готова, оркестратор исследования ещё подключается"


def tick(conn=None, choose=runners.choose, health=runners.health):
    """Take the oldest queued request and set a status a human can read. Returns the
    job id it touched, or None when the queue is empty."""
    own = conn is None
    conn = conn or store.connect()
    try:
        job = store.next_queued(conn)
        if not job:
            return None
        runner = job["runner"] if job["runner"] in ("api", "local", "qoder") else choose()
        if runner in ("api", "local"):
            state, detail = health()
            message = LOCAL_READY if state in ("ok", "no-model") else f"{LOCAL_DOWN} ({detail})"
            store.update(conn, job["id"], status="mapping", message=message, runner=runner)
        else:
            store.update(conn, job["id"], status="mapping", message=AGENT_WAIT, runner="qoder")
        return job["id"]
    finally:
        if own:
            conn.close()
