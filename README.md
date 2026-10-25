# Aidemy: an open-source alternative to Udemy and Coursera

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

The `-T` flag is not decoration: without it a non-interactive call loses its output. Voice models are downloaded once into `D:\llm\aidemy`, which is mounted at `/opt/aidemy/models`; the container writes nothing outside that folder, and it never sees the rest of your model directory.

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

## Who built it

Original skill by Assaf Kipnis — more of his work: [askconsulting.io](https://askconsulting.io). This fork adapts it to Docker, Russian and free local voices.

## License

MIT. Free to use, change and share.
