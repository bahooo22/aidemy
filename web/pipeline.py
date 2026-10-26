"""One course from the pages already on disk: notes are ours, the writing is the model's.

The web container cannot search the internet, so this builds only from `raw/`.
When there are too few pages it refuses in words a person can act on, instead of
producing a course with invented citations — the gate would fail it anyway.
"""
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"))
import runners  # noqa: E402

MIN_PAGES = 3
ATTEMPTS = 3
CARD_SECTIONS = ["**Слушать:**", "**Идея в трёх строках**", "**Зачем:**", "**Кто говорит:**",
                 "**Попробуй**", "**Правило**", "**Пропустить**", "**Глубже (опционально)**"]


def pages(workspace):
    """(url, title, text) for every scraped page, shortest last."""
    found = []
    for path in sorted(Path(workspace).glob("raw/*/*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        url = next((line[5:].strip() for line in text.splitlines()[:12] if line.startswith("url: ")), "")
        title = next((line[7:].strip() for line in text.splitlines()[:12] if line.startswith("title: ")), path.stem)
        body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S).strip()
        if url and body:
            found.append((url, title, body))
    return found


def prompt_for(topic, style, note, number, total, page_list):
    sources = "\n\n".join(f"[{i + 1}] {title} — {url}\n{body[:2500]}"
                          for i, (url, title, body) in enumerate(page_list))
    allowed = "\n".join(f"- {url}" for url, _, _ in page_list)
    return f"""Ты пишешь один урок аудиокурса по-русски.

Тема курса: {topic}. Стиль: {style}. {"Уточнение: " + note if note else ""}
Это урок {number} из {total}.

Ниже — источники. Опирайся только на них, ничего не выдумывай.

{sources}

Верни ровно два блока, каждый в тройных обратных кавычках, без текста между ними.

Блок 1 — script.txt: диалог двух ведущих, каждая строка начинается с "A: " или "B: ".
300-383 слова. Живая речь, короткие реплики, без приказных форм («ты должен», «тебе нужно»),
без тире и двойных дефисов. Внутри — идея урока, насколько источники сходятся,
история или число из источника со ссылкой, затем одно маленькое дело.

Блок 2 — card.md:
# Урок {number}. <название из 2-3 слов>
**Слушать:** lesson-{number:02d}.mp3 (2 мин)
**Идея в трёх строках**
- ...
**Зачем:** ...
**Кто говорит:** N из M источников сходятся; кто возражает и как, одной строкой
**Попробуй** · Быстрая победа · 10 минут
<шаги>
**Правило** <одно предложение>
**Пропустить** · без потерь. Урок {number + 1} — просто урок {number + 1}.
**Глубже (опционально)**
- <url из списка ниже>

Ссылаться можно только на эти адреса, дословно:
{allowed}
"""


def blocks(reply):
    """The two fenced blocks of a model reply: script first, card second."""
    found = re.findall(r"```[a-z]*\n(.*?)```", reply, flags=re.S)
    if len(found) < 2:
        raise ValueError("ответ без двух блоков: нужен script.txt и card.md в ```")
    return found[0].strip() + "\n", found[1].strip() + "\n"


def build(workspace, topic, lessons, style="менторский", note="", ask=None, progress=None, log=None):
    """Write the course into <workspace> and return a short report. Raises RuntimeError
    with a readable reason when the course cannot be built at all."""
    workspace = Path(workspace)
    page_list = pages(workspace)
    if len(page_list) < MIN_PAGES:
        raise RuntimeError(f"в raw/ только {len(page_list)} страниц(ы), нужно хотя бы {MIN_PAGES}: "
                           "сначала соберите страницы (scrape.py) или запустите заявку из диалога")
    ask = ask or runners.ask
    written = []
    for number in range(1, int(lessons) + 1):
        if progress:
            progress(f"пишет урок {number} из {lessons}")
        problem = ""
        for attempt in range(1, ATTEMPTS + 1):
            reply = ask(prompt_for(topic, style, note, number, lessons, page_list)
                        + (f"\n\nПрошлая попытка не прошла проверку:\n{problem}\n" if problem else ""),
                        reasoning="none")
            try:
                script_text, card_text = blocks(reply)
            except ValueError as error:
                problem = str(error)
                continue
            folder = workspace / "class" / f"{number:02d}-lesson-{number}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "script.txt").write_text(script_text, encoding="utf-8")
            (folder / "card.md").write_text(card_text, encoding="utf-8")
            problem = gate(workspace, folder)
            if not problem:
                written.append(folder)
                break
        else:
            raise RuntimeError(f"урок {number} не прошёл проверку за {ATTEMPTS} попытки: {problem}")
    if log:
        log(f"написано уроков: {len(written)}")
    return written


def gate(workspace, folder):
    """Empty string when the lesson passes `check_lessons.py`, else its complaints."""
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "skills" / "aidemy"
                                                  / "scripts" / "check_lessons.py"),
                             str(workspace), str(folder)],
                            capture_output=True, text=True)
    return "" if result.returncode == 0 else (result.stdout + result.stderr).strip()[:1500]
