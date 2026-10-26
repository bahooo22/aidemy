"""The 20-second probe: render the fixture dialogue with one host pair.

It calls the same `voice_lab.py` a lesson render uses, so a pair heard here is the
pair a lesson gets. Nothing about the course is touched.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(os.environ.get("AIDEMY_REPO") or "/app")
PYTHON = sys.executable
TIMEOUT = int(os.environ.get("AIDEMY_PROBE_TIMEOUT") or 300)


def probe(voice_a, voice_b, one_voice=False, out_dir=None):
    """Render one pair and return (path_to_mp3, log). Raises RuntimeError with the
    tail of stderr when the pair cannot be rendered."""
    target = Path(out_dir or tempfile.mkdtemp(prefix="aidemy-probe-"))
    target.mkdir(parents=True, exist_ok=True)
    pair = f"{voice_a}+{voice_b}"
    command = [PYTHON, str(REPO / "skills" / "aidemy" / "scripts" / "voice_lab.py"),
               "--pairs", pair, "--out", str(target)]
    if one_voice:
        command.append("--one-voice")
    env = dict(os.environ)
    env.setdefault("AIDEMY_MODEL_DIR", "/opt/aidemy/models")
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT,
                              env=env, cwd=str(REPO))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"пробник не успел за {TIMEOUT} с") from None
    log = (done.stdout or "") + (done.stderr or "")
    produced = sorted(target.glob("*.mp3"))
    if done.returncode != 0 or not produced:
        tail = "\n".join(log.strip().splitlines()[-6:])
        raise RuntimeError(tail or f"voice_lab.py вышел с кодом {done.returncode}")
    return produced[0], log
