"""Render one fixture dialogue with many host pairs, for listening and timing.

Same engine code as the lesson path: a pair is just two triples, so what you hear
here is what a lesson will sound like. Unavailable pairs are reported with their
reason and skipped; the run continues.

Usage:
    python3 voice_lab.py --pairs "kokoro:dima+kokoro:sveta" "piper:ru_RU-denis-medium+piper:ru_RU-irina-medium"
    python3 voice_lab.py --grid all --out /tmp/voice-lab
    python3 voice_lab.py --grid all --one-voice          # storyteller mode too

Results: <out>/<slug>.mp3, <out>/<slug>.json and <out>/lab.json with seconds,
audio length and the device that was really used.
"""
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_audio

# The eleven pairs from the plan, best first. Silero pairs stay in the list on
# purpose: when that engine is wired in, they must show up without editing here.
GRID = [
    ("kokoro:dima", "kokoro:sveta"),
    ("kokoro:dima", "kokoro:masha"),
    ("silero:aidar", "silero:baya"),
    ("silero:aidar", "silero:kseniya"),
    ("piper:ru_RU-denis-medium", "piper:ru_RU-irina-medium"),
    ("piper:ru_RU-dmitri-medium", "piper:ru_RU-irina-medium"),
    ("piper:ru_RU-ruslan-medium", "piper:ru_RU-irina-medium"),
    ("kokoro:dima", "piper:ru_RU-irina-medium"),
    ("piper:ru_RU-denis-medium", "kokoro:sveta"),
    ("piper:ru_RU-irina-medium", "piper:ru_RU-irina-medium:-4"),
    ("kokoro:sveta", "kokoro:sveta:3"),
]

FIXTURE = (
    "A: Смотри на договорённость как на выбор, а не как на удачу.\n"
    "B: То есть сначала решаешь, что будешь делать, если цена не устроит.\n"
    "A: Именно. Это и есть точка выхода, её называют до разговора.\n"
    "B: И тогда первая цифра перестаёт быть страшной.\n"
    "A: При этом важно не спорить с человеком, а спорить с задачей.\n"
    "B: Хорошо. С чего начнём на этой неделе?\n"
)


def slug(spec_a, spec_b, one_voice=False):
    """A file name that still says which triples were used."""
    def clean(spec):
        return "".join(c if c.isalnum() else "-" for c in spec).strip("-").lower()

    name = f"{clean(spec_a)}__{clean(spec_b)}"
    return f"{name}__one" if one_voice else name


def parse_pairs(values, grid_all=False):
    if grid_all:
        return list(GRID)
    pairs = []
    for value in values or []:
        left, sep, right = value.partition("+")
        if not sep or not left.strip() or not right.strip():
            raise SystemExit(f"pair '{value}' is not A+B, for example kokoro:dima+kokoro:sveta")
        pairs.append((left.strip(), right.strip()))
    return pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pairs", nargs="*", help="A+B, each side a triple engine:voice[:pitch]")
    parser.add_argument("--grid", choices=["all"], help="the eleven pairs from the plan")
    parser.add_argument("--out", default="voice-lab", help="folder for the mp3s and the record")
    parser.add_argument("--script", help="use this dialogue instead of the built-in fixture")
    parser.add_argument("--one-voice", action="store_true", help="render storyteller mode as well")
    args = parser.parse_args(argv)

    pairs = parse_pairs(args.pairs, args.grid == "all")
    if not pairs:
        parser.error("give --pairs or --grid all")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    script = out / "fixture.txt"
    script.write_text(Path(args.script).read_text(encoding="utf-8") if args.script else FIXTURE,
                      encoding="utf-8")

    saved = {k: os.environ.get(k) for k in ("AIDEMY_VOICE_A", "AIDEMY_VOICE_B", "AIDEMY_ONE_VOICE")}
    results, skipped = [], []
    try:
        for spec_a, spec_b in pairs:
            for one_voice in ([False, True] if args.one_voice else [False]):
                label = slug(spec_a, spec_b, one_voice)
                mp3 = out / f"{label}.mp3"
                os.environ["AIDEMY_VOICE_A"] = spec_a
                os.environ["AIDEMY_VOICE_B"] = spec_b
                os.environ["AIDEMY_ONE_VOICE"] = "1" if one_voice else ""
                started = time.perf_counter()
                try:
                    render_audio.main(str(script), str(mp3))
                except SystemExit as refusal:
                    skipped.append({"pair": f"{spec_a}+{spec_b}", "one_voice": one_voice,
                                    "reason": str(refusal)})
                    print(f"skip {label}: {refusal}", file=sys.stderr)
                    continue
                seconds = round(time.perf_counter() - started, 1)
                record = json.loads(mp3.with_suffix(".json").read_text(encoding="utf-8"))
                results.append({"label": label, "pair": f"{spec_a}+{spec_b}",
                                "one_voice": one_voice, "seconds": seconds,
                                "audio": record["length"], "device": record["device"]})
                print(f"{label}: {seconds}s, {record['length']}, {record['device']}")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    (out / "lab.json").write_text(json.dumps({"fixture": str(script), "rendered": results,
                                              "skipped": skipped}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    print(f"done: {len(results)} rendered, {len(skipped)} skipped, records in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
