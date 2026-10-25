"""Render a two-host lesson script to one MP3.

Script format, one turn per line:
    A: So here's the thing about pricing...
    B: Right, and that's where most people...

Engine, best first:
- piper (offline): ONNX voices fetched by get_voices.py into AIDEMY_MODEL_DIR.
  Hosts: AIDEMY_VOICE_A / AIDEMY_VOICE_B, as `piper:<voice>` or a bare voice name.
- macOS `say` (free, offline, plainer): AIDEMY_SAY_A / AIDEMY_SAY_B, default
  Samantha and Daniel.
AIDEMY_TTS forces one engine; empty means the first engine usable here. Audio
tags like [laughs] are dropped, since both engines would read them aloud.
The path finishes with the same warm EQ and loudness pass in ffmpeg.

Usage: python3 render_audio.py <script.txt> <out.mp3>
"""
import importlib.util, os, re, shutil, subprocess, sys, tempfile, wave
from pathlib import Path

POLISH_AF = (
    "highpass=f=90,equalizer=f=200:t=q:w=1:g=-2,equalizer=f=3000:t=q:w=1:g=2.5,"
    "deesser,lowpass=f=13500,acompressor=ratio=2.5,aecho=0.8:0.5:40:0.08,loudnorm=I=-16"
)


def parse_turns(text):
    turns = []
    for line in text.splitlines():
        speaker, sep, said = line.partition(":")
        if sep and speaker.strip() in ("A", "B") and said.strip():
            turns.append((speaker.strip(), said.strip()))
    if not turns:
        raise ValueError("no 'A:' or 'B:' lines found in the script")
    return turns


PIPER_DEFAULT = ("ru_RU-denis-medium", "ru_RU-irina-medium")
ENGINES = ("piper", "say")


def model_dir():
    return Path(os.environ.get("AIDEMY_MODEL_DIR") or Path(__file__).resolve().parents[2] / "voices")


def piper_model(voice):
    return model_dir() / "piper" / f"{voice}.onnx"


def strip_tags(said):
    return re.sub(r"\[[^\]]+\]", "", said).strip()


def split_spec(value):
    """`piper:ru_RU-denis-medium` -> ("piper", "ru_RU-denis-medium"); a bare voice
    name carries no engine."""
    engine, sep, voice = value.partition(":")
    return (engine.strip() or None, voice.strip()) if sep else (None, value.strip())


def piper_pair():
    """The two piper voices the environment asks for, or None when it asks for a
    different engine."""
    pair = []
    for value, default in zip((os.environ.get("AIDEMY_VOICE_A", ""),
                               os.environ.get("AIDEMY_VOICE_B", "")), PIPER_DEFAULT):
        engine, voice = split_spec(value)
        if engine not in (None, "piper"):
            return None
        pair.append(voice or default)
    return tuple(pair)


def pick_engine(voices):
    """The forced engine if AIDEMY_TTS names one, else the first usable here."""
    forced = os.environ.get("AIDEMY_TTS", "").strip()
    if forced:
        return forced
    if voices and all(piper_model(v).is_file() for v in voices):
        return "piper"
    if shutil.which("say"):
        return "say"
    return None


def say_parts(turns, tmp, voices):
    parts = []
    for i, (who, said) in enumerate(turns):
        part = tmp / f"turn{i:03d}.aiff"
        subprocess.run(["say", "-v", voices[who], "-o", str(part), strip_tags(said)], check=True)
        parts.append(part)
    return parts


def piper_parts(turns, tmp, voices):
    """One WAV per turn, each host model loaded once for the whole lesson. The
    CLI path reloads the 63 MB model on every call: 2.2 s per turn, and a
    two-host lesson is about 30 turns."""
    from piper import PiperVoice
    loaded, parts = {}, []
    for i, (who, said) in enumerate(turns):
        model = str(piper_model(voices[who]))
        if model not in loaded:
            loaded[model] = PiperVoice.load(model)
        part = tmp / f"turn{i:03d}.wav"
        with wave.open(str(part), "wb") as wav:
            loaded[model].synthesize_wav(strip_tags(said), wav)
        parts.append(part)
    return parts


def stitch(parts, tmp, out_path):
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-af", POLISH_AF, "-ar", "44100", "-b:a", "128k", str(out_path)], check=True)


def main(script_path, out_path):
    if not shutil.which("ffmpeg"):
        sys.exit("missing dependency: ffmpeg (apt install ffmpeg, brew on macOS)")
    turns = parse_turns(Path(script_path).read_text())
    pair = piper_pair()
    engine = pick_engine(pair)
    if engine is None:
        sys.exit("no audio engine here: fetch a voice with get_voices.py, or set AIDEMY_TTS=say on macOS")
    if engine == "piper":
        if pair is None:
            sys.exit("AIDEMY_VOICE_* names another engine; unset AIDEMY_TTS to use it")
        voices = {"A": pair[0], "B": pair[1]}
        if importlib.util.find_spec("piper") is None:
            sys.exit("piper is not installed in this Python: pip install piper-tts")
        missing = [v for v in pair if not piper_model(v).is_file()]
        if missing:
            sys.exit("voice model missing, fetch it first: python3 get_voices.py "
                     + " ".join(f"piper:{v}" for v in missing))
    elif engine == "say":
        voices = {"A": os.environ.get("AIDEMY_SAY_A", "Samantha"),
                  "B": os.environ.get("AIDEMY_SAY_B", "Daniel")}
    else:
        sys.exit(f"engine '{engine}' is not in this build: this script knows {', '.join(ENGINES)}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts = (piper_parts if engine == "piper" else say_parts)(turns, tmp, voices)
        stitch(parts, tmp, out_path)
    length = stamp_card(Path(script_path).with_name("card.md"), out_path)
    hosts = f"{voices['A']} + {voices['B']}" if voices["A"] != voices["B"] else voices["A"]
    print(f"wrote {out_path} ({length}) from {len(turns)} turns via {engine} ({hosts})")


def stamp_card(card, mp3):
    """Write the real running time onto the card's Listen line. A hand-typed
    "(2 min)" sat on a 2:32 lesson in the first full test run."""
    secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(mp3)], capture_output=True, text=True, check=True).stdout.strip())
    length = f"{int(secs // 60)}:{int(secs % 60):02d}"
    if card.exists():
        text = card.read_text()
        card.write_text(re.sub(r"^(\*\*Listen:\*\*.*?)\s*\([^)]*\)\s*$", rf"\1 ({length})", text, count=1, flags=re.M))
    return length


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
