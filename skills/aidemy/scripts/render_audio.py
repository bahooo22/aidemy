"""Render a two-host lesson script to one MP3.

Script format, one turn per line:
    A: So here's the thing about pricing...
    B: Right, and that's where most people...

Hosts are two independent triples `engine:voice[:pitch]` in AIDEMY_VOICE_A and
AIDEMY_VOICE_B, so the hosts may speak through different engines and one voice
can be shifted by a few semitones. AIDEMY_TTS fills the engine in when a triple
carries none; empty means the best engine usable here (kokoro, silero, piper,
then the macOS `say`). AIDEMY_ONE_VOICE=1 makes host B use host A's triple.
AIDEMY_DEVICE=auto|cuda|cpu decides where the torch engines run; the device that
was really used goes into render.json next to the mp3.

Every part is brought to 44.1 kHz mono and levelled with dynaudnorm before the
concat, so mixed engines, mixed sample rates and pitch-shifted voices splice
cleanly. The final pass is the same warm EQ and loudness pass in ffmpeg.

Usage: python3 render_audio.py <script.txt> <out.mp3>
"""
import importlib.util, json, os, re, shutil, subprocess, sys, tempfile, wave
from pathlib import Path

POLISH_AF = (
    "highpass=f=90,equalizer=f=200:t=q:w=1:g=-2,equalizer=f=3000:t=q:w=1:g=2.5,"
    "deesser,lowpass=f=13500,acompressor=ratio=2.5,aecho=0.8:0.5:40:0.08,loudnorm=I=-16"
)

# Best first. `edge` is not here on purpose: its Russian male voice answered
# NoAudioReceived on four of five test lines while the female voice read the same
# lines, so the engine silently loses turns — see the README.
ENGINES = ("kokoro", "silero", "piper", "say")
DEFAULT_VOICES = {
    "kokoro": ("dima", "sveta"),
    "silero": ("aidar", "baya"),
    "piper": ("ru_RU-denis-medium", "ru_RU-irina-medium"),
}
# Host B reads a touch slower, so one voice used by both hosts still reads as
# two people talking.
PACE = {"A": 1.0, "B": 1.04}
SEMITONE = 2.0 ** (1 / 12)


def parse_turns(text):
    turns = []
    for line in text.splitlines():
        speaker, sep, said = line.partition(":")
        if sep and speaker.strip() in ("A", "B") and said.strip():
            turns.append((speaker.strip(), said.strip()))
    if not turns:
        raise ValueError("no 'A:' or 'B:' lines found in the script")
    return turns


def model_dir():
    return Path(os.environ.get("AIDEMY_MODEL_DIR") or Path(__file__).resolve().parents[2] / "voices")


def piper_model(voice):
    return model_dir() / "piper" / f"{voice}.onnx"


def strip_tags(said):
    return re.sub(r"\[[^\]]+\]", "", said).strip()


def split_spec(value):
    """`piper:ru_RU-denis-medium:-4` -> ("piper", "ru_RU-denis-medium", -4.0);
    a bare voice name carries neither engine nor pitch."""
    if not value.strip():
        return None, "", None
    parts = [p.strip() for p in value.split(":")]
    if len(parts) == 1:
        return None, parts[0], None
    pitch = float(parts[2]) if len(parts) > 2 and parts[2] else None
    return parts[0] or None, parts[1], pitch


def default_pair(engine):
    if engine == "say":
        return (os.environ.get("AIDEMY_SAY_A", "Samantha"),
                os.environ.get("AIDEMY_SAY_B", "Daniel"))
    return DEFAULT_VOICES[engine]


def ready(engine):
    """Whether this engine can run here at all: its branch exists in this build,
    the module imports, and the weights (or the macOS voice) are in place. A pip
    package alone is not readiness."""
    if engine not in ENGINE_PARTS:
        return False
    if engine == "say":
        return shutil.which("say") is not None
    if importlib.util.find_spec(engine) is None:
        return False
    if engine == "kokoro":
        return (model_dir() / "kokoro" / "kokoro-ru-v2-base.pth").is_file()
    if engine == "piper":
        return all(piper_model(v).is_file() for v in DEFAULT_VOICES["piper"])
    return True


def hosts():
    """{host: (engine, voice, pitch)} from the environment. Refusals name the
    cause, because "no engine" and "engine not wired yet" need different fixes."""
    forced = os.environ.get("AIDEMY_TTS", "").strip() or None
    specs = [split_spec(os.environ.get(f"AIDEMY_VOICE_{host}", "")) for host in ("A", "B")]
    out = {}
    for host, (engine, voice, pitch) in zip(("A", "B"), specs):
        engine = engine or forced
        if engine is None:
            engine = next((e for e in ENGINES if ready(e)), None)
            if engine is None:
                sys.exit("no audio engine here: fetch voices with get_voices.py, "
                         "or set AIDEMY_TTS to one of " + ", ".join(ENGINES))
        if engine not in ENGINES:
            sys.exit(f"engine '{engine}' is not in this build: this script knows "
                     + ", ".join(ENGINES))
        voice = voice or default_pair(engine)[0 if host == "A" else 1]
        out[host] = (engine, voice, pitch)
    if os.environ.get("AIDEMY_ONE_VOICE", "").strip() not in ("", "0"):
        out["B"] = out["A"]
    return out


def device():
    """Where torch engines run: only what the machine really reports."""
    want = os.environ.get("AIDEMY_DEVICE", "").strip().lower() or "auto"
    if want == "cpu":
        return "cpu"
    try:
        import torch
    except ImportError:
        if want == "cuda":
            sys.exit("AIDEMY_DEVICE=cuda, but torch is not installed in this Python")
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if want == "cuda":
        sys.exit("AIDEMY_DEVICE=cuda, but torch.cuda.is_available() is False")
    return "cpu"


def say_parts(items, tmp, plan, dev):
    parts = {}
    for i, who, said in items:
        part = tmp / f"turn{i:03d}.aiff"
        subprocess.run(["say", "-v", plan[who][1], "-o", str(part), strip_tags(said)], check=True)
        parts[i] = (part, 22050)
    return parts


def piper_parts(items, tmp, plan, dev):
    """Each host model loads once for the whole lesson. The CLI path reloads the
    63 MB model on every call: 2.2 s per turn, and a two-host lesson is ~30."""
    from piper import PiperVoice, SynthesisConfig
    loaded, parts = {}, {}
    for i, who, said in items:
        model = piper_model(plan[who][1])
        if not model.is_file():
            sys.exit(f"voice model missing, fetch it first: python3 get_voices.py piper:{plan[who][1]}")
        if model not in loaded:
            loaded[model] = PiperVoice.load(str(model))
        part = tmp / f"turn{i:03d}.wav"
        with wave.open(str(part), "wb") as wav:
            loaded[model].synthesize_wav(strip_tags(said), wav,
                                         syn_config=SynthesisConfig(length_scale=PACE[who]))
        parts[i] = (part, loaded[model].config.sample_rate)
    return parts


ENGINE_PARTS = {"say": say_parts, "piper": piper_parts}


def build_parts(turns, tmp, plan):
    """One part per turn, in turn order, whichever engine that host speaks."""
    by_engine = {}
    for i, (who, said) in enumerate(turns):
        by_engine.setdefault(plan[who][0], []).append((i, who, said))
    dev = device() if any(e in ("kokoro", "silero") for e in by_engine) else "cpu"
    parts = {}
    for engine, items in by_engine.items():
        if engine not in ENGINE_PARTS:
            sys.exit(f"engine '{engine}' is not wired into this build yet: "
                     + ", ".join(sorted(ENGINE_PARTS)))
        parts.update(ENGINE_PARTS[engine](items, tmp, plan, dev))
    return [parts[i] + (plan[who][2],) for i, (who, _) in enumerate(turns)], dev


def normalize(parts, tmp):
    """Common format before the concat, and the one place pitch is applied:
    `asetrate` transposes the whole part, `atempo` puts the speed back."""
    out = []
    for i, (path, rate, pitch) in enumerate(parts):
        dest = tmp / f"norm{i:03d}.wav"
        filters = []
        if pitch:
            ratio = SEMITONE ** pitch
            filters += [f"asetrate={rate}*{ratio:.6f}", "aresample=44100", f"atempo={1 / ratio:.6f}"]
        filters.append("dynaudnorm")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                        "-af", ",".join(filters), "-ar", "44100", "-ac", "1", str(dest)], check=True)
        out.append(dest)
    return out


def stitch(parts, tmp, out_path):
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-af", POLISH_AF, "-ar", "44100", "-b:a", "128k", str(out_path)], check=True)


def label(plan):
    if plan["A"] == plan["B"]:
        engine, voice, pitch = plan["A"]
        shifted = "" if pitch is None else f" {pitch:+g}"
        return f"{engine} ({voice}{shifted})"
    return " / ".join(f"{plan[h][0]} ({plan[h][1]})" for h in ("A", "B"))


def describe(out_path, turns, plan, dev, length):
    """What actually spoke, next to the mp3, so a later step can put it on the
    card and in the run manifest without guessing."""
    meta = {
        "mp3": Path(out_path).name,
        "length": length,
        "turns": len(turns),
        "device": dev,
        "hosts": {h: {"engine": plan[h][0], "voice": plan[h][1], "pitch": plan[h][2]}
                  for h in ("A", "B")},
    }
    Path(out_path).with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def main(script_path, out_path):
    if not shutil.which("ffmpeg"):
        sys.exit("missing dependency: ffmpeg (apt install ffmpeg, brew on macOS)")
    turns = parse_turns(Path(script_path).read_text())
    plan = hosts()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts, dev = build_parts(turns, tmp, plan)
        stitch(normalize(parts, tmp), tmp, out_path)
    length = stamp_card(Path(script_path).with_name("card.md"), out_path)
    describe(out_path, turns, plan, dev, length)
    print(f"wrote {out_path} ({length}) from {len(turns)} turns via {label(plan)} on {dev}")


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
