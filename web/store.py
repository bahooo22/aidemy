"""Queue of course requests in one SQLite file on the shared volume.

No framework: the page, the status list and the file links are small enough for
the standard library, and the image does not grow a web stack.
"""
import os, re, shutil, sqlite3, time
from contextlib import contextmanager
from pathlib import Path

STATUSES = ("queued", "mapping", "reading", "writing", "synthesizing", "done", "error")


def root():
    return Path(os.environ.get("AIDEMY_WEB_ROOT") or ".")


def db_path():
    return Path(os.environ.get("AIDEMY_WEB_DB") or Path(root()) / "queue.db")


def connect(path=None):
    target = Path(path) if path else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        topic TEXT NOT NULL,
        style TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        lessons INTEGER NOT NULL,
        runner TEXT NOT NULL DEFAULT '',
        engine_a TEXT, voice_a TEXT, pitch_a REAL,
        engine_b TEXT, voice_b TEXT, pitch_b REAL,
        one_voice INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        message TEXT NOT NULL DEFAULT '',
        created REAL NOT NULL,
        updated REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        ts REAL NOT NULL)""")
    conn.commit()
    return conn


@contextmanager
def session(path=None):
    """A connection per request, closed even when the handler raises."""
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def slugify(topic):
    """A readable, stable folder name: `НЛП: фокусы языка` -> `нлп-фокусы-языка`."""
    slug = re.sub(r"[^\w\s-]", "", topic.lower(), flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:60] or "course"


def create(conn, topic, lessons, style="", note="", runner="", hosts=None, one_voice=False):
    """Insert a job. A second request for the same topic is refused, not queued:
    two runs would write into the same course folder."""
    hosts = hosts or {}
    slug = slugify(topic)
    now = time.time()
    try:
        cursor = conn.execute(
            """INSERT INTO jobs (slug, topic, style, note, lessons, runner, engine_a, voice_a, pitch_a,
                                 engine_b, voice_b, pitch_b, one_voice, created, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, topic.strip(), style, note, int(lessons), runner,
             hosts.get("engine_a"), hosts.get("voice_a"), hosts.get("pitch_a"),
             hosts.get("engine_b"), hosts.get("voice_b"), hosts.get("pitch_b"),
             1 if one_voice else 0, now, now))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"курс по теме «{topic.strip()}» уже есть в очереди") from None
    return cursor.lastrowid


FIELDS = {"status", "message", "lessons", "runner", "engine_a", "voice_a", "pitch_a",
          "engine_b", "voice_b", "pitch_b", "one_voice", "style", "note", "calls"}


def update(conn, job_id, **fields):
    allowed = {k: v for k, v in fields.items() if k in FIELDS}
    if not allowed:
        return
    if "status" in allowed and allowed["status"] not in STATUSES:
        raise ValueError(f"unknown status {allowed['status']}")
    allowed["updated"] = time.time()
    columns = ", ".join(f"{name} = ?" for name in allowed)
    conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", (*allowed.values(), job_id))
    if "status" in fields or "message" in fields:
        # A log of every step a person can read later: the live status line only
        # shows the newest message, and a failed course is explained by its history.
        row = conn.execute("SELECT status, message FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            conn.execute("INSERT INTO events (job_id, status, message, ts) VALUES (?,?,?,?)",
                         (job_id, row["status"], row["message"], allowed["updated"]))
    conn.commit()


def history(conn, job_id, limit=12):
    """The last steps of one request, oldest first."""
    rows = conn.execute("SELECT status, message, ts FROM events WHERE job_id = ? ORDER BY id DESC LIMIT ?",
                        (job_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def resume(conn):
    """Close the jobs a dead process was running. Recreating the container kills the
    thread, and a page stuck on «пишет» forever is worse than an honest error; the
    person reads it and presses the button again."""
    ids = [row["id"] for row in conn.execute(
        "SELECT id FROM jobs WHERE status IN ('writing', 'synthesizing')").fetchall()]
    for job_id in ids:
        update(conn, job_id, status="error", message="прогон прерван перезапуском сервиса")
    return ids


def get(conn, job_id):
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def by_slug(conn, slug):
    row = conn.execute("SELECT * FROM jobs WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def jobs(conn, limit=30):
    return [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def delete(conn, job_ids):
    """Forget requests and remove the course folder each one owns.

    A person selects several cards on the page and presses delete, so this takes a
    list and returns what actually disappeared. Two guards matter here: an id that
    is not in the queue is skipped instead of guessed at, and a slug that is not a
    direct child of the root (a hand-edited row, an empty slug) refuses to remove
    anything at all — a mistake here would delete the volume, not one course.
    """
    base = root().resolve()
    removed = []
    for job_id in job_ids:
        row = conn.execute("SELECT slug, topic FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            continue
        slug = row["slug"] or ""
        folder = (base / slug).resolve()
        if folder.parent != base:
            conn.execute("DELETE FROM events WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            removed.append({"id": job_id, "topic": row["topic"], "folder": None})
            continue
        if folder.is_dir():
            shutil.rmtree(folder)
        conn.execute("DELETE FROM events WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        removed.append({"id": job_id, "topic": row["topic"], "folder": slug})
    return removed


def next_queued(conn):
    row = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None
