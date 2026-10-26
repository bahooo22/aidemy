"""Bundle a finished class for delivery: audio zips under a size cap, all cards in
one file, and a manifest of what really spoke.

Chat and file-sharing tools cap uploads (one we hit was 30 MB), so the audio is
split into numbered zips that each stay under --max-mb. Cards are combined in
lesson order into cards.md, and into cards.docx when pandoc is installed. The
manifest is built from the render.json files render_audio leaves next to each mp3,
so the engine, voice, pitch and device of every lesson are copied, never guessed.

Usage: python3 package_class.py <workspace> [--max-mb 25]
Writes to <workspace>/deliver/.
"""
import json, shutil, subprocess, sys, zipfile
from pathlib import Path


def lesson_dirs(ws):
    return sorted(p for p in (ws / "class").glob("[0-9][0-9]-*") if p.is_dir())


def zip_audio(ws, out, max_bytes):
    mp3s, names = [], {}
    for d in lesson_dirs(ws):
        found = sorted(d.glob("*.mp3"))
        if len(found) > 1:
            # Two renders in one folder used to share one member name; whichever
            # extracted last won, silently. Now each keeps its own name, and the run says so.
            print(f"{d.name}: {len(found)} mp3 files, each packed under its own name: "
                  + ", ".join(f.name for f in found), file=sys.stderr)
        for m in found:
            names[m] = f"{d.name}.mp3" if len(found) == 1 else f"{d.name}-{m.stem}.mp3"
        mp3s += found
    groups, current, size = [], [], 0
    for m in mp3s:
        if current and size + m.stat().st_size > max_bytes:
            groups.append(current)
            current, size = [], 0
        current.append(m)
        size += m.stat().st_size
    if current:
        groups.append(current)
    made = []
    for group in groups:
        first, last = group[0].parent.name[:2], group[-1].parent.name[:2]
        path = out / f"audio-lessons-{first}-to-{last}.zip"
        with zipfile.ZipFile(path, "w") as z:
            for m in group:
                z.write(m, names[m])
        made.append(path)
    return made


def combine_cards(ws, out):
    cards = [d / "card.md" for d in lesson_dirs(ws) if (d / "card.md").exists()]
    md = out / "cards.md"
    md.write_text("\n\n---\n\n".join(c.read_text() for c in cards))
    if shutil.which("pandoc"):
        subprocess.run(["pandoc", str(md), "-f", "markdown", "-t", "docx", "-o", str(out / "cards.docx")], check=True)
    return len(cards)


def mm_to_secs(text):
    """"2:05" as seconds, the unit the course total needs."""
    minutes, _, seconds = str(text).partition(":")
    return int(minutes) * 60 + int(seconds or 0)


def fmt_secs(total):
    return f"{total // 60}:{total % 60:02d}"


def plural(n, one, few, many):
    """Russian nouns agree with the last digit, not the number: 1 урок, 2 урока,
    12 уроков, but 21 урок."""
    if 11 <= n % 100 <= 14:
        return many
    return one if n % 10 == 1 else few if n % 10 in (2, 3, 4) else many


def host_spec(meta, who):
    """`piper/ru_RU-denis-medium/none`: engine, voice and the semitone shift, in the
    order the manifest column promises. `none` rather than an empty slot, so a
    reader never wonders whether the pitch was simply not recorded."""
    host = (meta.get("hosts") or {}).get(who) or {}
    pitch = host.get("pitch")
    shift = "none" if pitch is None else f"{pitch:+g}"
    return f"{host.get('engine', '?')}/{host.get('voice', '?')}/{shift}"


def manifest_lines(ws):
    """One tab-separated line per render, then the course total. The lesson folder
    leads the line: two lessons can hold the same mp3 name, and a manifest that
    cannot tell them apart is not a record. A lesson whose audio was never rendered
    through render_audio keeps a note instead of stopping the package, so an
    unfinished course can still be delivered with the gap visible."""
    lessons = lesson_dirs(ws)
    lines, total, devices = [], 0, []
    for d in lessons:
        renders = sorted(d.glob("*.json"))
        if not renders:
            lines.append(f"{d.name}\tнет render.json")
            continue
        for r in renders:
            meta = json.loads(r.read_text(encoding="utf-8"))
            length = meta.get("length", "0:00")
            total += mm_to_secs(length)
            dev = meta.get("device", "?")
            if dev not in devices:
                devices.append(dev)
            lines.append(f"{d.name}\t{meta.get('mp3', r.name)}\t{length}"
                         f"\tA: {host_spec(meta, 'A')}\tB: {host_spec(meta, 'B')}\tdevice={dev}")
    n = len(lessons)
    lines.append(f"итог: {n} {plural(n, 'урок', 'урока', 'урок')}"
                 f" · {fmt_secs(total)} · устройства: {', '.join(devices) or 'нет'}")
    return lines


def write_manifest(ws, out):
    path = out / "manifest.txt"
    path.write_text("\n".join(manifest_lines(ws)) + "\n", encoding="utf-8")
    return path


def main(ws, max_mb):
    out = ws / "deliver"
    out.mkdir(exist_ok=True)
    zips = zip_audio(ws, out, max_mb * 1024 * 1024)
    n = combine_cards(ws, out)
    manifest = write_manifest(ws, out)
    for z in zips:
        # Same unit as the cap (MiB). Printing decimal MB showed 26.0 against a 25 cap for a zip under it.
        print(f"{z}  {z.stat().st_size / (1024 * 1024):.1f} MB (cap {max_mb} MB)")
    print(f"{n} cards combined in {out / 'cards.md'}" + (" and cards.docx" if shutil.which("pandoc") else ""))
    print(f"manifest of what spoke in {manifest}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cap = int(sys.argv[sys.argv.index("--max-mb") + 1]) if "--max-mb" in sys.argv else 25
    main(Path(sys.argv[1]).expanduser().resolve(), cap)
