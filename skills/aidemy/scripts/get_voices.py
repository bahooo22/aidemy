"""Fetch the offline voice models a host pair needs.

Two checks happen here that the engine itself never makes: the free space is
measured before the first byte moves, and every downloaded file is compared with
the size and md5 the catalog publishes. A model truncated on a full disk
otherwise surfaces as a crash inside the synth, three lessons into a course.

Usage:
    python3 get_voices.py piper:ru_RU-denis-medium piper:ru_RU-irina-medium
    python3 get_voices.py --list ru            # voices for a language prefix
    python3 get_voices.py --force piper:ru_RU-denis-medium

Models land in $AIDEMY_MODEL_DIR/piper/, which the Docker service mounts from
D:\\llm\\aidemy. Set AIDEMY_MODEL_DIR to move them elsewhere.
"""
import argparse, hashlib, json, os, shutil, sys, urllib.request
from pathlib import Path

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES_JSON = BASE + "voices.json?download=true"
# The volume has to stay usable after the download, so space is counted with a margin.
HEADROOM = 64 * 1024 * 1024
MIB = 1024 * 1024


def model_dir():
    return Path(os.environ.get("AIDEMY_MODEL_DIR") or Path(__file__).resolve().parents[2] / "voices")


def catalog():
    with urllib.request.urlopen(VOICES_JSON, timeout=60) as response:
        return json.load(response)


def split_spec(value):
    """`piper:ru_RU-denis-medium` -> ("piper", "ru_RU-denis-medium")."""
    engine, sep, voice = value.partition(":")
    return (engine.strip() or "piper", voice.strip()) if sep else ("piper", value.strip())


def plans(catalog_dict, names):
    """(url, target, size_bytes, md5) for every file of every requested voice.
    MODEL_CARD is the one catalog name that is not voice-specific, so the voice is
    appended: two hosts in one folder would otherwise overwrite each other's
    license card and re-download it on every run."""
    out = []
    for name in names:
        entry = catalog_dict.get(name)
        if entry is None:
            raise KeyError(f"no such voice in the catalog: {name}")
        for key, meta in sorted(entry["files"].items()):
            file_name = Path(key).name
            if file_name == "MODEL_CARD":
                file_name = f"MODEL_CARD-{name}"
            out.append((BASE + key, model_dir() / "piper" / file_name,
                        int(meta["size_bytes"]), meta["md5_digest"]))
    return out


def md5_of(path, chunk=1024 * 1024):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def is_current(path, size, md5):
    """A file counts as done only when size and md5 both match the catalog. A
    zero-length file is a killed download, not a completed one."""
    path = Path(path)
    return (path.is_file() and size > 0 and path.stat().st_size == size
            and md5_of(path) == md5)


def room_ok(target_dir, needed, force=False):
    """Free space on the volume that will hold the download, with headroom."""
    probe = target_dir if target_dir.exists() else target_dir.parent
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return free >= needed + HEADROOM, free


def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        with open(target, "wb") as handle:
            shutil.copyfileobj(response, handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("voice", nargs="*", help="piper:<voice>, or a bare voice name")
    parser.add_argument("--list", metavar="PREFIX", help="list catalog voices for a language prefix")
    parser.add_argument("--force", action="store_true", help="re-download even if the file is already correct")
    args = parser.parse_args(argv)

    voices = catalog()
    if args.list:
        for name in sorted(n for n in voices if n.startswith(args.list)):
            print(name)
        return 0
    if not args.voice:
        parser.error("name at least one voice, or use --list")

    specs = [split_spec(v) for v in args.voice]
    unknown = [e for e, _ in specs if e != "piper"]
    if unknown:
        sys.exit(f"engine '{unknown[0]}' has no catalog here: get_voices.py downloads piper voices")
    wanted = [name for _, name in specs]
    entries = plans(voices, wanted)

    needed = sum(size for _, _, size, _ in entries)
    print(f"{len(wanted)} voice(s), {needed / MIB:.0f} MiB into {model_dir() / 'piper'}")
    ok, free = room_ok(model_dir() / "piper", needed)
    if not ok:
        sys.exit(f"not enough space: {free / MIB:.0f} MiB free, needs {needed / MIB:.0f} "
                 f"+ {HEADROOM / MIB:.0f} MiB headroom. Free up disk or set AIDEMY_MODEL_DIR")

    downloaded = 0
    for url, target, size, md5 in entries:
        if not args.force and is_current(target, size, md5):
            print(f"ok       {target.name}")
            continue
        fetch(url, target)
        if target.stat().st_size != size:
            target.unlink(missing_ok=True)
            sys.exit(f"size mismatch for {target.name}: got {target.stat().st_size if target.exists() else 0}, "
                     f"expected {size}")
        got = md5_of(target)
        if got != md5:
            target.unlink(missing_ok=True)
            sys.exit(f"md5 mismatch for {target.name}: got {got}, expected {md5}")
        downloaded += size
        print(f"fetched  {target.name} ({size / MIB:.1f} MiB, md5 {md5[:8]})")
    print(f"done: {needed / MIB:.0f} MiB ready, {downloaded / MIB:.1f} MiB newly downloaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
