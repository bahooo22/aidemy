"""Tests for the orchestrator: page intake, reply shape, retries and job statuses."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

WEB = Path(__file__).resolve().parents[1] / "web"
sys.path.insert(0, str(WEB))

import jobs  # noqa: E402
import pipeline  # noqa: E402
import store  # noqa: E402

REPLY = """```text
A: Первая реплика про фокусы языка.
B: Вторая реплика и пояснение.
```

```markdown
# Урок 1. Фокусы
**Слушать:** lesson-01.mp3 (2 мин)
**Идея в трёх строках**
- раз
**Зачем:** два
**Кто говорит:** 3 из 4 источников сходятся
**Попробуй** · Быстрая победа · 10 минут
шаг
**Правило** правило
**Пропустить** · без потерь
**Глубже (опционально)**
- https://example.com/a
```
"""


class Pages(unittest.TestCase):
    def test_pages_are_read_with_url_and_title(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "raw" / "site"
            folder.mkdir(parents=True)
            (folder / "a.md").write_text("url: https://example.com/a\ntitle: Первая\n\nтекст", encoding="utf-8")
            (folder / "b.md").write_text("title: Без адреса\n\nтекст", encoding="utf-8")
            found = pipeline.pages(td)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "https://example.com/a")
        self.assertEqual(found[0][1], "Первая")
        self.assertIn("текст", found[0][2])

    def test_quoted_titles_reach_the_prompt_as_words(self):
        """Scrape writes the title as a quoted JSON string, and files from before
        the ensure_ascii fix carry it as \\u041c... escapes."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "raw" / "site"
            folder.mkdir(parents=True)
            (folder / "a.md").write_text('url: https://example.com/a\ntitle: "Фокус"\n\nтекст', encoding="utf-8")
            escaped = 'title: "' + chr(92) + 'u0424окус"'
            (folder / "b.md").write_text("url: https://example.com/b\n" + escaped + "\n\nтекст", encoding="utf-8")
            found = dict((url, title) for url, title, _ in pipeline.pages(td))
        self.assertEqual(found["https://example.com/a"], "Фокус")
        self.assertEqual(found["https://example.com/b"], "Фокус")


class ReplyShape(unittest.TestCase):
    def test_two_blocks_become_script_and_card(self):
        script, card = pipeline.blocks(REPLY)
        self.assertTrue(script.startswith("A: Первая"))
        self.assertIn("**Слушать:**", card)

    def test_one_block_is_an_error(self):
        with self.assertRaises(ValueError):
            pipeline.blocks("```\nA: один\n```")

    def test_a_schema_reply_becomes_script_and_card(self):
        reply = json.dumps({"turns": ["A: первая реплика", "B: вторая реплика"],
                            "card": "**Слушать:** x.mp3 (2 мин)"}, ensure_ascii=False)
        script, card = pipeline.parse_reply(reply)
        self.assertEqual(script, "A: первая реплика\nB: вторая реплика\n")
        self.assertTrue(card.endswith("\n"))

    def test_json_wrapped_in_a_fence_still_parses(self):
        """The live lesson 4 burned all three attempts on this: the server answered with
        the schema JSON, and the model wrapped it in ```json ... ```; the old parser saw
        one fenced block, demanded two and called it a missing card."""
        body = json.dumps({"turns": ["A: первая реплика", "B: вторая реплика"],
                           "card": "**Слушать:** x.mp3 (2 мин)"}, ensure_ascii=False)
        for reply in (f"```json\n{body}\n```", f"```\n{body}\n```", f"  ```json\n{body}\n```  "):
            script, card = pipeline.parse_reply(reply)
            self.assertEqual(script, "A: первая реплика\nB: вторая реплика\n", reply[:20])
            self.assertIn("Слушать", card)

    def test_a_real_two_block_answer_is_not_eaten_by_the_fence_strip(self):
        """The unwrapper must not swallow a prose answer: there the two blocks ARE the
        payload, and stripping the outer pair would leave one."""
        reply = ("Вот урок.\n```txt\nA: первая\nB: вторая\n```\n"
                 "А вот карточка.\n```md\n# Урок 1\n**Слушать:** x.mp3\n```")
        script, card = pipeline.parse_reply(reply)
        self.assertIn("A: первая", script)
        self.assertIn("# Урок 1", card)

    def test_the_counter_ticks_once_per_attempt_not_per_lesson(self):
        """A lesson that needed three tries must read as three calls: that is the whole
        point of the number on the page."""
        bad = json.dumps({"turns": [], "card": ""}, ensure_ascii=False)
        good = json.dumps({"turns": ["A: реплика", "B: реплика"], "card": "# Урок 1\n**Слушать:** x"},
                          ensure_ascii=False)
        answers = iter([bad, bad, good])
        seen = []
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "raw" / "web").mkdir(parents=True)
            for i in range(3):
                (ws / "raw" / "web" / f"p{i}.md").write_text(
                    f"url: https://example.com/{i}\n" + "текст страницы " * 40, encoding="utf-8")
            with mock.patch.object(pipeline, "gate", return_value=""):
                pipeline.build(ws, "тема", 1, ask=lambda *a, **k: next(answers),
                               count=lambda: seen.append(1))
        self.assertEqual(len(seen), 3)

    def test_a_schema_reply_without_turns_is_an_error(self):
        with self.assertRaises(ValueError):
            pipeline.parse_reply(json.dumps({"turns": [], "card": "карточка"}))

    def test_card_lines_inside_turns_are_refused(self):
        """Lesson 2 of the live run put the whole card into `turns`; the gate caught it
        only after the files were written, so the refusal now happens at parse time."""
        reply = json.dumps({"turns": ["A: реплика", "**Слушать:** x.mp3 (2 мин)"],
                            "card": "карточка"}, ensure_ascii=False)
        with self.assertRaises(ValueError) as ctx:
            pipeline.parse_reply(reply)
        self.assertIn("не реплика", str(ctx.exception))

    def test_the_schema_holds_the_turn_count(self):
        """minItems is the lever that prose could not pull: the model stopped at ten
        turns when only asked for 24."""
        self.assertEqual(pipeline.LESSON_SCHEMA["properties"]["turns"]["minItems"], 24)
        self.assertEqual(pipeline.LESSON_SCHEMA["properties"]["turns"]["maxItems"], 28)


class Build(unittest.TestCase):
    def workspace(self, td, pages=3):
        folder = Path(td) / "raw" / "site"
        folder.mkdir(parents=True)
        for i in range(pages):
            (folder / f"p{i}.md").write_text(f"url: https://example.com/{i}\ntitle: T{i}\n\nтекст {i}",
                                             encoding="utf-8")
        return Path(td)

    def test_too_few_pages_refuses_with_a_readable_reason(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self.workspace(td, pages=1)
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.build(ws, "НЛП", 1)
        self.assertIn("нужно хотя бы 3", str(ctx.exception))

    def test_lesson_is_written_after_one_passing_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self.workspace(td)
            with mock.patch.object(pipeline, "gate", return_value=""):
                written = pipeline.build(ws, "НЛП", 1, ask=lambda *a, **k: REPLY)
            self.assertEqual(len(written), 1)
            self.assertTrue((written[0] / "script.txt").is_file())
            self.assertTrue((written[0] / "card.md").is_file())

    def test_three_failed_attempts_stop_the_course(self):
        with tempfile.TemporaryDirectory() as td:
            ws = self.workspace(td)
            calls = []

            def ask(*args, **kwargs):
                calls.append(1)
                return REPLY

            with mock.patch.object(pipeline, "gate", return_value="script: emdash"):
                with self.assertRaises(RuntimeError) as ctx:
                    pipeline.build(ws, "НЛП", 1, ask=ask)
        self.assertEqual(len(calls), pipeline.ATTEMPTS)
        self.assertIn("не прошёл проверку", str(ctx.exception))

    def test_prompt_names_only_allowed_urls(self):
        text = pipeline.prompt_for("НЛП", "менторский", "", 1, 2,
                                   [("https://example.com/a", "A", "текст")])
        self.assertIn("https://example.com/a", text)
        self.assertIn("300-339", text)
        self.assertNotIn("383", text)

    def test_build_asks_the_model_for_the_schema(self):
        seen = {}

        def ask(prompt, **kwargs):
            seen.update(kwargs)
            return REPLY

        with tempfile.TemporaryDirectory() as td:
            ws = self.workspace(td)
            with mock.patch.object(pipeline, "gate", return_value=""):
                pipeline.build(ws, "НЛП", 1, ask=ask)
        self.assertIs(seen.get("schema"), pipeline.LESSON_SCHEMA)
        self.assertEqual(seen.get("reasoning"), "none")


class JobStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "queue.db")
        self.env = mock.patch.dict(os.environ, {"AIDEMY_WEB_ROOT": self.tmp.name}, clear=False)
        self.env.start()

    def tearDown(self):
        self.conn.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_success_writes_done(self):
        job_id = store.create(self.conn, "тема", lessons=1)
        jobs.run(job_id, self.conn, build=lambda *a, **k: [Path("x")], render_lessons=lambda *a: [])
        job = store.get(self.conn, job_id)
        self.assertEqual(job["status"], "done")
        self.assertIn("готово", job["message"])

    def test_failure_is_reported_with_its_reason(self):
        job_id = store.create(self.conn, "тема", lessons=1)

        def boom(*args, **kwargs):
            raise RuntimeError("нет страниц")

        jobs.run(job_id, self.conn, build=boom, render_lessons=lambda *a: [])
        job = store.get(self.conn, job_id)
        self.assertEqual(job["status"], "error")
        self.assertIn("нет страниц", job["message"])


if __name__ == "__main__":
    unittest.main()
