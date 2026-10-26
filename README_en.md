# Aidemy: an open-source alternative to Udemy and Coursera

> Русская версия: [README.md](README.md)

You wanted to learn negotiation. You got a 40-hour course, a syllabus someone wrote years ago, and a tab you never reopened.

Aidemy is a free agent skill that builds the course you will actually finish. You name a topic. It researches the web and hands back about 12 audio lessons of 2 minutes each.

```
> teach me negotiation
```

![Aidemy demo: type a topic, get 2-minute audio lessons, each with a card, one thing to try and a rule to keep](https://raw.githubusercontent.com/assafkip/claudemy/assets/claudemy-demo.gif)

With sound:

https://github.com/user-attachments/assets/d6447515-f442-4b77-a482-544d95dc4799

## What lesson 1 looks like

The demo above is a real negotiation course. Lesson 1 is "Your Walk-Away", 2:27 of two hosts talking. The card next to it gives you:

- **The idea in three lines.** Decide what you will do if the ask fails, before you ask.
- **How many sources agree**, and who does not.
- **One small thing to try**, with the time it takes.
- **Links to the pages it came from.**

Listen for 2 minutes. Try one thing. Keep one rule.

## What you get

- **About 12 audio lessons, 2 minutes each.** Two hosts talking, not a lecture. MP3 files you can play anywhere.
- **A card per lesson.** Three-line idea, source agreement, one practice, links to go deeper.
- **A playbook.** One rule per lesson, collected in one file you keep.
- **A lesson plan that shows where the experts split.** Laid out as decisions, not lessons.
- **Real citations.** A checker refuses any lesson that cites a page the research did not actually read.

## How it works

1. **Maps the topic** into sub-topics, based on how it is usually taught.
2. **Researches the web.** 20 to 40 pages from practitioners, official docs, research summaries and a few dissenting views. No more than 3 pages from one site, so no single voice dominates.
3. **Reads and compares.** Reader agents pull cited notes. One agent merges them into themes with agreement counts.
4. **Plans the course** in arcs of about 4 lessons, foundations first.
5. **Makes one sample lesson** and waits for your reaction. Then it writes and records the rest.

Want a class built from one person's work instead? Say so: `teach me negotiation from <name>'s writing`. It reads their Substack or blog and builds the class from that.

## Install

This is a fork of [assafkip/claudemy](https://github.com/assafkip/claudemy), adapted to run in Docker, in Russian, and without any paid voice service.

As an agent skill, copy `skills/aidemy/` into your agent's skills directory — for Qoder that is `~/.qoder/skills/aidemy/`, for Claude Code `~/.claude/skills/aidemy/`.

Then ask for any topic: `teach me <topic>`.

## Needs

- An agent with web search (Qoder Desktop or Claude Code).
- Python 3 with `beautifulsoup4` (`pip install beautifulsoup4`), and `ffmpeg`.
- Audio: rendered on your machine with the free macOS voices (`say`). No API key is used anywhere in this fork; other engines are added in the following commits.
- Optional: `pandoc` for a Word copy of the cards.

Voices can be changed with `AIDEMY_SAY_A` / `AIDEMY_SAY_B` (macOS voices).

## Run in Docker

Everything version-sensitive — Python 3.12, torch, the voice models — lives in one long-running container, so the host Python stays untouched. The container is started once and every step runs inside it; nothing is built per command.

```powershell
cd E:\eXample\Documents\Source\Github\Fork\aidemy
docker compose up -d aidemy          # the GPU profile is the default
docker compose ps
docker compose exec -T aidemy python -c "import torch; print(torch.cuda.is_available())"
```

CPU fallback, for a machine without a card and for the GPU-versus-CPU measurement:

```powershell
docker compose --profile cpu build aidemy-cpu
docker compose --profile cpu up -d aidemy-cpu
docker compose --profile cpu exec -T aidemy-cpu python -m unittest discover -s tests
```

Every script is called the same way:

```
docker compose exec -T aidemy python skills/aidemy/scripts/<script>.py ...
```

The `-T` flag keeps the call non-interactive: no pseudo-TTY is allocated, which is what you want from a script. (Measured here: with and without `-T` the output bytes were identical and both returned 0, so nothing is lost either way; `-T` is the form that never blocks waiting for a terminal.)

### Voice models, once

```powershell
docker compose exec -T aidemy python skills/aidemy/scripts/get_voices.py --list ru
docker compose exec -T aidemy python skills/aidemy/scripts/get_voices.py piper:ru_RU-denis-medium piper:ru_RU-irina-medium
```

The first command prints what exists for Russian in the Piper catalog: exactly four voices, `denis`, `dmitri`, `irina`, `ruslan`, all `medium` — which is why the default pair is a man and a woman. The second fetches the two models (121 MiB together) and checks each file against the size and md5 the catalog publishes; a truncated download would otherwise crash the synthesis three lessons later.

Models go to `D:\llm\aidemy\piper`, which the container sees as `/opt/aidemy/models/piper`. Only that subfolder is mounted: the container never sees the rest of your model directory, and writes nothing outside it. Point the hosts at them with `AIDEMY_VOICE_A` / `AIDEMY_VOICE_B` (`piper:<voice>`, defaults `ru_RU-denis-medium` and `ru_RU-irina-medium`), and force an engine with `AIDEMY_TTS` when you do not want the automatic choice.

### Kokoro-ru, the neural pair

```powershell
docker compose exec -T aidemy python skills/aidemy/scripts/get_voices.py kokoro:sveta kokoro:dima
```

635 MiB across 374 files: two 312 MiB checkpoints (`sveta` and `masha` share one, `dima` has his own), three voice packs, the Russian G2P and the espeak data it reads. Weights are OpenRAIL, the G2P code Apache-2.0; `sveta` and `masha` are studio voices, `dima` is the male one. Everything lands in `D:\llm\aidemy\kokoro`, and the Hugging Face cache for the stress model goes to `D:\llm\aidemy\.hf`, so a recreated container does not fetch it again.

Measured in the CPU container on the lab fixture (six turns): the Kokoro pair 35.9 s of wall clock for 25 s of audio, the Piper pair 7.0 s for 22 s, a mixed Kokoro-plus-Piper pair 22.7 s for 24 s. Current code writes `wrote ... via kokoro (dima) / kokoro (sveta) on cpu`.

### Silero v5

```powershell
docker compose exec -T aidemy python skills/aidemy/scripts/get_voices.py silero:aidar silero:baya
```

One 141 MiB weights file carries all five speakers (`aidar`, `baya`, `kseniya`, `eugene`, `xenia`), so naming any of them downloads the same file; a second run reuses it after a size check, because the host publishes no md5. Lines come out at 48 kHz through `apply_tts`. Measured steady-state RTF 0.04 with a 2.7 s first-call initialisation; on the lab fixture the `aidar` + `baya` pair took 14.8 s of wall clock for 22 s of audio (first run, including load), `aidar` + `kseniya` 6.8 s, and a mixed `baya` + Piper pair 10.6 s for 24 s.

Licence: the v5 Russian weights are CC BY-NC-SA — non-commercial, personal use. Kokoro-ru and Piper are the options that travel with an open-source project.

### Listening to pairs

```powershell
docker compose exec -T aidemy python skills/aidemy/scripts/voice_lab.py --grid all
docker compose exec -T aidemy python skills/aidemy/scripts/voice_lab.py --pairs "kokoro:dima+piper:ru_RU-irina-medium"
```

Each pair is rendered from one fixture dialogue into its own mp3 plus a record; `lab.json` collects seconds, audio length and the device that was used, and pairs whose engine is not available are listed with their reason instead of stopping the run. A second run adds to the record instead of replacing it. The same code path renders lessons, so what you hear here is what a lesson gets.

All eleven pairs, CPU container, six-turn fixture (22 to 25 seconds of audio), two runs each:

| pair | wall clock |
|---|---|
| kokoro dima + sveta | 34.6 / 36.7 s |
| kokoro dima + masha | 26.7 / 27.0 s |
| silero aidar + baya | 7.3 / 7.1 s |
| silero aidar + kseniya | 7.8 / 7.3 s |
| piper denis + irina | 6.6 / 6.7 s |
| piper dmitri + irina | 6.5 / 6.8 s |
| piper ruslan + irina | 6.7 / 6.5 s |
| kokoro dima + piper irina | 27.4 / 28.2 s |
| piper denis + kokoro sveta | 25.8 / 27.8 s |
| piper irina + irina at −4 | 5.4 / 4.8 s |
| kokoro sveta + sveta at +3 | 34.6 / 35.9 s |

GPU against CPU for Kokoro, same fixture: 25.6 s on `cuda` against 36.7 s on `cpu`. The first run inside a freshly started GPU container took 211.7 s, because the 312 MiB checkpoints move to VRAM then; after that the engine is a third faster. Silero and Piper stay on CPU by design, so `AIDEMY_DEVICE` changes nothing for them.

### The lesson gate

`check_lessons.py` reads a Russian card: `**Слушать:**`, `**Идея в трёх строках**`, `**Зачем:**`, `**Кто говорит:**`, `**Попробуй**`, `**Правило**`, `**Пропустить**`, `**Глубже (опционально)**`. Demand phrases are matched in Russian and in English; a double hyphen is refused on the card and in a `say` script. The em dash is allowed everywhere except `say`: the same phrase with and without it gave Piper a 0.16 s pause against 0.13 s, Silero grew 0.14 s, and the Kokoro G2P dropped the sign — no engine reads it out loud. The ban came from a guess and cost the first live course run three wasted attempts on one lesson; `say` keeps it because there is nothing here to measure it with.

The word corridor follows the engine's measured pace rather than one number for all: 300–383 words on Piper, 280–350 on Silero, 250–313 on Kokoro, and a mixed pair gets the intersection so the lesson fits both hosts. Russian pacing measured here at 0.392 s per word on Piper over 57, 114 and 228 words (22.1 s, 45.0 s, 89.5 s of audio).

### Web page for the phone

```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"   # write it to .env as AIDEMY_WEB_TOKEN
docker compose up -d aidemy-web
```

The page listens on `0.0.0.0:8090` and is reachable from the home network at `http://192.168.50.221:8090` on this machine (port 8080 belongs to a Windows service here, so 8090 is the host port; inside the container it is always 8080). Without the token every page answers 403; the token is typed once and kept in a cookie for 30 days. `AIDEMY_WEB_TOKEN` lives in `.env`, stays out of git and is never printed.

The form asks for a topic, a style preset plus a free-text note, the lesson count, a pair of hosts (`engine:voice` with an optional pitch) and the storyteller switch. A request becomes a row in `aidemy/queue.db` with one of the statuses «в очереди / карта тем / читает / пишет / синтезирует / готово / ошибка»; a second request for the same topic is refused, because two runs would write into the same folder. Finished files are served from `aidemy/<slug>/`: mp3s, cards and the zips.

The «Прослушать пробник» button renders the fixture dialogue with the chosen pair through the same `voice_lab.py` a lesson uses and streams the mp3 back, so a pair is judged by ear before any generation is paid for. Measured: `200`, `audio/mpeg`, 353 637 bytes in 22.6 s for the Piper pair.

A small tick drains the queue and never writes lessons: it records who will run the request. `AIDEMY_RUNNER=auto|api|local|qoder`; `auto` takes `api` when `AIDEMY_LLM_API_KEY` is set, otherwise `local` if LM Studio answers, otherwise the Qoder queue. `local` asks `GET /v1/models` on `host.docker.internal:1234` and separates «сервер не поднят» from «модель не загружена», so the message on the page names the fix (`lms server start`, then `lms load`). Routine steps send `reasoning_effort: "none"`, and an empty `content` is treated as a failed step, not as an empty lesson.

When the pages are already on disk (`raw/` holds at least three), the same tick starts the job: the model writes each lesson **from those pages only**, the gate checks every one, and a lesson gets up to three attempts before the job is marked with a readable error. Then the lessons are voiced with the pair from the form and packed into `deliver/`. Without pages the request says how many it has and waits for an agent — the container cannot search the web, so a brand-new topic still needs the scrape step from a Qoder dialogue.

Measured on this machine: `/health` answers 200 over the LAN address, `/` answers 403 without the token, the token form answers 200, a request returns 303 to its job page.

A request keeps a journal: every status or message change writes a row into the `events` table of the same database, and the job page shows the last twelve steps with their times, so a run that stalls is visible rather than mysterious. One model call gets fifteen minutes, settable with `AIDEMY_LLM_TIMEOUT`: a lesson is a 10 000-character prompt and a 300-word answer, and the first live run died exactly at the old five-minute deadline. When the service starts, a run left in «пишет» or «синтезирует» is closed with «прогон прерван перезапуском сервиса», because recreating the container kills the thread and the page must not claim it is still writing.

The model answers in a structured form: the request carries a `json_schema` with a `turns` field (an array of turns, `minItems` 24, `maxItems` 28, every item matching `^[AB]: .+`) and a `card` field. It is `minItems` that holds the length, because in prose the model answered a "24 turns" request with ten turns and ended on "we will cover this later", and the `pattern` keeps the card out of the turns — the second live lesson brought its card inside the turns array. Measured on `qwen3.8-9b-distill@q5_k_m` with an 8192 context: 18–88 s per lesson, 24 turns, 334 and 433 words in two runs, `reasoning_tokens` zero because the request sends `reasoning_effort: "none"`; without that parameter the model turns reasoning on and returns an empty `content`. A server without schema support answers with the same two fenced blocks, and the prompt describes both formats.

Every page in `raw/` starts with front matter: `author`, `title`, `date`, `url`, `paywalled`, `words`. The title is written as a JSON string without escaping non-ASCII, so it stays a word rather than `\u041c...` both in the file and in the prompt the model gets; the reader strips the quotes itself and still understands files written before the fix. The gate takes only `url` from the front matter — a citation on a card has to match it exactly.

### Russian instructions

`SKILL.md` and the five briefs in `references/` are written in Russian, and the card sections they ask for are the ones the gate checks: `**Слушать:**`, `**Идея в трёх строках**`, `**Зачем:**`, `**Кто говорит:**`, `**Попробуй**`, `**Правило**`, `**Пропустить**`, `**Глубже (опционально)**`. `references/lesson-example.md` is a complete Russian lesson — 312 words over 24 turns, every citation on disk — and it passes `check_lessons.py` as written, which is the point of keeping it in the repository.

`SKILL.md` now walks the agent through the container: `docker compose ps` first (and `docker compose up -d aidemy` when the service is not running), then every script called as `docker compose exec -T aidemy python skills/aidemy/scripts/<script>.py ...` from the repository root, with the course workspace inside `./aidemy/<topic-slug>/` because only that folder is mounted into the container. Outside Docker the same commands stay plain `python3`, stated once in the "Before you start" section. Proved with the literal command from the file: `check_lessons.py` on the reference lesson answered `ok 01-tri-dveri (312 words)`, rc=0.

Narration style is now part of the input: `sources.json` carries `"style": {"preset": "менторский", "note": "для 10 лет"}` next to the topic and the level, and `references/style-briefs.md` spells out six presets — mentoring, light, strict, conversational, for children, playful — with four tone examples each. A free-form note is added to a preset rather than replacing it, and it changes the register only: the lesson skeleton, the required card sections, the word corridor per engine, the page citations and the ban on demand phrases stay as they are, which `writer-brief.md` and `lesson-design.md` repeat.

Documentation outside the code is Russian too: `llms.txt` (the file agents read) is translated, its English version sits next to it as `llms_en.txt`, and `docs/index.html` is translated and renamed to Aidemy. It carries `lang="ru"`, canonical and `og:url` point at `https://github.com/bahooo22/aidemy`, JSON-LD `codeRepository` is the fork while `sameAs` keeps upstream. Paid synthesis is gone from the page: audio comes from Piper, Kokoro-ru and Silero v5 locally and needs no key. The fork installs by copying `skills/aidemy/`, while the plugin and `claudemy.skill` from v0.2.0 are marked as the upstream path. The measured numbers match this README: eleven pairs in the CPU container at 4.8–36.7 s for a six-turn fixture, Kokoro at 25.6 s on `cuda` against 36.7 s on `cpu`, 211.7 s on the first run in a fresh GPU container, models at 121 / 635 / 141 MiB.

All three fork pages now carry a preview and an icon: `og:image` and `twitter:image` point at `docs/assets/preview.png` (1792x1024) and `link rel="icon"` at `docs/assets/logo.png` (1024x1024), with `og:image:width`/`og:image:height` matching the PNG header. The image address is absolute, through `raw.githubusercontent.com/bahooo22/aidemy/main/`, so the preview card appears in messengers only once those files are pushed to `origin`.

The page now has a morning checklist: the section "Утро: как показать курс с телефона" in `docs/index.html`, eight steps from the home-network address to finished MP3s. A phone on the same network opens `http://<machine address>:8090` (on this machine `http://192.168.50.221:8090`), the token is entered once and lives in a cookie for thirty days, "Прослушать" gives twenty seconds of the chosen pair before any course starts, and the "Файлы" block serves the lesson MP3s, the audio archives, `cards.md` and `manifest.txt`. Without the token the page answers 403, and only the `/health` endpoint stays open.

The page is built for a person without a terminal and for a child: large fields and buttons, questions instead of field names ("What should it teach?", "How should it sound?", "How many lessons?"), while the voices, the pitch and the single-narrator switch hide inside a "Voices and sound (optional)" disclosure — a course is made without them just fine. Two languages: the RU/EN switch sets the `aidemy_lang` cookie and the English dictionary lives in `web/app.py` next to the Russian one. Two themes, light and dark in the cover palette (dark navy, amber, teal); the choice is kept in `localStorage`, and without a choice the system preference wins. The "Files" block now also lists `cards.docx` when `pandoc` built one.

### The end-to-end run and the peaks

The request "НЛП: фокусы языка" went the whole way from the page: five scraped pages (four proponents and one scientific critique), three lessons, the gate at `rc=0` on the whole course, voicing by the `piper denis + irina` pair, and a `deliver/` with the archive, `cards.md` and `manifest.txt`. The lessons of 330, 344 and 359 words run 2:22, 2:19 and 2:39 (142.1 / 139.5 / 159.1 s), 7:20 for the course. Live Russian pace on Piper is 0.405–0.443 s per word, above the laboratory 0.392 because a dialogue has pauses between turns; the third lesson is nine seconds over the planned 150, and the open item is to lower the top of the word corridor from 383 to 345 without touching the morning copy.

Kokoro peaks (`dima + sveta`, the six-turn fixture, 25 s of audio): on `cuda` 7347 MiB of video memory out of 8192 and 4983 MiB of process RSS in 199.4 s; on `cpu` 4171 MiB of RSS. Writing a lesson with the answer schema takes 18–88 s on `qwen3.8-9b-distill@q5_k_m` with an 8192 context; at the 101 120 context the model was loaded with earlier, the same lesson took over fifteen minutes because the KV cache did not fit the card.

### Two hosts

Each host is an independent triple, `engine:voice[:pitch]`, so the two hosts may speak through different engines and one voice can be shifted by semitones:

```powershell
$env:AIDEMY_VOICE_A = "piper:ru_RU-denis-medium"
$env:AIDEMY_VOICE_B = "piper:ru_RU-irina-medium:-4"   # four semitones down
$env:AIDEMY_ONE_VOICE = "1"                            # B borrows A's triple
```

`AIDEMY_DEVICE=auto|cuda|cpu` decides where torch engines run; what was really used is written to `render.json` next to the mp3, together with the engine, voice and pitch of each host. A lesson rendered on this machine: `wrote /tmp/lesson.mp3 (0:12) from 3 turns via piper (ru_RU-denis-medium) / piper (ru_RU-irina-medium) on cpu`.

Every part is brought to 44.1 kHz mono and levelled with `dynaudnorm` before the concat, so a mixed pair or a shifted voice still splices cleanly; pitch is applied there as `asetrate` + `atempo`, which is engine-independent.

`package_class.py` turns those records into `deliver/manifest.txt`: one tab-separated line per lesson — folder, mp3, real length, `A: engine/voice/pitch`, `B: engine/voice/pitch`, `device=` — then the course total in lessons, audio time and the devices used. The folder leads the line because two lessons can carry the same `x.mp3`. A lesson with no `render.json` is named instead of stopping the package. On a two-lesson fixture in this container: `01-fokusy	x.mp3	0:10	A: piper/ru_RU-denis-medium/none	B: piper/ru_RU-irina-medium/-4	device=cpu`, `02-bez-json	нет render.json`, `итог: 2 урока · 0:10 · устройства: cpu`. The card carries the same fact as a `**Синтез:**` line under «Слушать», replaced on every re-render instead of stacking, and `stamp_card` now finds both the Russian «Слушать:» and the English «Listen:» literal, so the real running time lands on the card.

**No edge engine.** The free Microsoft voices were the obvious online fallback, but `ru-RU-DmitryNeural` answered `NoAudioReceived` on four of five test lines while `ru-RU-SvetlanaNeural` read the same lines, so it would have silently dropped turns. The branch is not shipped rather than shipped flaky.

## Data
Aidemy runs on your machine inside the agent. It fetches the public web pages it researches and saves them in a local workspace folder. Audio is rendered locally — no lesson text leaves the machine for synthesis. The skill has no server, collects no analytics, and stores nothing outside your machine.

## FAQ

**Is Aidemy free?**
Yes. The skill is MIT licensed. You pay only for what you already use: your agent plan. The voices cost nothing.

**How is it different from Udemy or Coursera?**
Course sites sell a fixed course someone recorded once. Aidemy builds a course on the topic you name, at your level, from current sources, and shows you where those sources disagree. Lessons are 2 minutes and end in one thing to try, so the course is built to be finished.

**What topics does it work for?**
Anything people write about well on the open web. Skills (negotiation, public speaking, sourdough), professional topics (pricing, hiring, SQL), and subjects (stoicism, music theory). Health, legal and financial topics get a note where advice depends on your situation.

**Does it copy other people's content?**
No. It reads pages the way a researcher does, writes its own lessons, and links to the sources. Pages it reads are saved only in your local workspace for your own study.

**Does audio need an account or a key?**
No. Audio is rendered on your machine. The cards and playbook work with no audio at all.

**How long does a course take to make?**
A 12-lesson course is a long-running agent session: research, reading, writing and about 25 minutes of generated audio.

**Can I learn from one specific expert?**
Yes. Name them in the request. Aidemy finds their Substack or blog and builds the course from their writing.

## Supporting the fork

The fork is free and offline and asks for no keys; the most useful help is a reproducible bug report and a patch by the rules in `CONTRIBUTING.md`. If you would rather help with money: the "Sponsor" button on the repository page leads to DonationAlerts and to `.github/wallets.md` with the crypto wallets. Donations change nothing: not access to courses, not the code, not the releases.

## Where to ask

`.github/SUPPORT.md` keeps the channels apart: getting it to run is in `docs/index.html`, a question that is not a defect goes to Discussions, a breakage uses the `bug-report` template, a feature idea the `feature-request` template, and a vulnerability follows `SECURITY.md` instead of a public issue.

## Who built it

Original skill by Assaf Kipnis — more of his work: [askconsulting.io](https://askconsulting.io). This fork adapts it to Docker, Russian and free local voices.

## License

MIT. Free to use, change and share.
