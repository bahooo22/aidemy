"""Tests for the web layer: the queue and the token gate. No network, no browser."""
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import http.client
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "web"))

import app as web_app  # noqa: E402
import store  # noqa: E402
import worker  # noqa: E402


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "queue.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_slug_is_readable_for_russian(self):
        self.assertEqual(store.slugify("НЛП: фокусы языка"), "нлп-фокусы-языка")
        self.assertEqual(store.slugify("  "), "course")

    def test_job_lifecycle_and_statuses(self):
        job_id = store.create(self.conn, "НЛП: фокусы языка", lessons=3, style="менторский")
        job = store.get(self.conn, job_id)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["lessons"], 3)
        store.update(self.conn, job_id, status="writing", message="пишет урок 1")
        job = store.get(self.conn, job_id)
        self.assertEqual((job["status"], job["message"]), ("writing", "пишет урок 1"))
        with self.assertRaises(ValueError):
            store.update(self.conn, job_id, status="что-то")

    def test_same_topic_is_refused_not_queued_twice(self):
        store.create(self.conn, "НЛП: фокусы языка", lessons=3)
        with self.assertRaises(ValueError) as ctx:
            store.create(self.conn, "НЛП: фокусы языка", lessons=5)
        self.assertIn("уже есть", str(ctx.exception))
        self.assertEqual(len(store.jobs(self.conn)), 1)

    def test_next_queued_takes_the_oldest(self):
        first = store.create(self.conn, "первая тема", lessons=2)
        store.create(self.conn, "вторая тема", lessons=2)
        store.update(self.conn, first, status="done")
        job = store.next_queued(self.conn)
        self.assertEqual(job["topic"], "вторая тема")

    def test_hosts_are_stored(self):
        job_id = store.create(self.conn, "тема", lessons=2,
                              hosts={"engine_a": "kokoro", "voice_a": "dima", "pitch_a": -2,
                                     "engine_b": "piper", "voice_b": "irina", "pitch_b": None},
                              one_voice=True)
        job = store.get(self.conn, job_id)
        self.assertEqual((job["engine_a"], job["voice_a"], job["pitch_a"]), ("kokoro", "dima", -2))
        self.assertEqual(job["one_voice"], 1)

    def test_a_step_written_to_the_journal_is_a_status_or_a_message(self):
        job_id = store.create(self.conn, "НЛП: фокусы языка", lessons=3)
        store.update(self.conn, job_id, status="writing", message="пишет урок 1 из 3")
        store.update(self.conn, job_id, message="пишет урок 2 из 3")
        store.update(self.conn, job_id, lessons=4)
        log = store.history(self.conn, job_id)
        self.assertEqual([(entry["status"], entry["message"]) for entry in log],
                         [("writing", "пишет урок 1 из 3"), ("writing", "пишет урок 2 из 3")])

    def test_a_restarted_service_closes_the_runs_it_killed(self):
        running = store.create(self.conn, "тема одна", lessons=3)
        waiting = store.create(self.conn, "тема две", lessons=3)
        store.update(self.conn, running, status="synthesizing", message="озвучивает уроки")
        self.assertEqual(store.resume(self.conn), [running])
        self.assertEqual(store.get(self.conn, running)["status"], "error")
        self.assertIn("перезапуском", store.get(self.conn, running)["message"])
        self.assertEqual(store.get(self.conn, waiting)["status"], "queued")


    def test_delete_forgets_the_row_and_its_journal(self):
        keep = store.create(self.conn, "тема которую оставили", lessons=2)
        gone = store.create(self.conn, "тема которую удалили", lessons=2)
        store.update(self.conn, gone, status="error", message="заявка проверки")
        (Path(self.tmp.name) / store.slugify("тема которую удалили")).mkdir()
        with mock.patch.dict(os.environ, {"AIDEMY_WEB_ROOT": self.tmp.name}):
            removed = store.delete(self.conn, [gone, 9999])
        self.assertEqual([item["id"] for item in removed], [gone])
        self.assertIsNone(store.get(self.conn, gone))
        self.assertIsNotNone(store.get(self.conn, keep))
        self.assertEqual(store.history(self.conn, gone), [])

    def test_delete_refuses_a_slug_that_is_not_a_course_folder(self):
        """A hand-edited `../` slug must not take the volume with it."""
        job_id = store.create(self.conn, "кривая заявка", lessons=1)
        self.conn.execute("UPDATE jobs SET slug = '../outside' WHERE id = ?", (job_id,))
        self.conn.commit()
        outside = Path(self.tmp.name).parent / "outside-check-aidemy"
        if outside.exists():
            outside.rmdir()
        with mock.patch.dict(os.environ, {"AIDEMY_WEB_ROOT": self.tmp.name}):
            store.delete(self.conn, [job_id])
        self.assertFalse(outside.exists())
        self.assertIsNone(store.get(self.conn, job_id))


class TokenGate(unittest.TestCase):
    """The server as the phone sees it: real HTTP, no redirects followed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"AIDEMY_WEB_TOKEN": "t0ken",
                                                "AIDEMY_WEB_ROOT": self.tmp.name}, clear=False)
        self.env.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web_app.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, path, fields=None, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        body = None
        if cookie:
            headers["Cookie"] = cookie
        if fields is not None:
            body = urllib.parse.urlencode(fields)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read().decode("utf-8", errors="replace")
        status, location, set_cookie = response.status, response.getheader("Location"), response.getheader("Set-Cookie")
        self.disposition = response.getheader("Content-Disposition")
        conn.close()
        return status, location, set_cookie, payload

    def test_health_needs_no_token(self):
        status, _, _, body = self.request("GET", "/health")
        self.assertEqual((status, body), (200, "ok"))

    def test_page_without_token_is_refused(self):
        status, _, _, body = self.request("GET", "/")
        self.assertEqual(status, 403)
        self.assertIn(web_app.STR["ru"]["token_label"], body)

    def test_wrong_token_is_refused(self):
        status, _, _, _ = self.request("POST", "/token", {"token": "nope"})
        self.assertEqual(status, 403)

    def test_right_token_sets_a_cookie(self):
        status, _, cookie, _ = self.request("POST", "/token", {"token": "t0ken"})
        self.assertEqual(status, 200)
        self.assertIn("aidemy_token=t0ken", cookie or "")

    def test_start_creates_a_job_and_refuses_a_duplicate(self):
        status, location, _, _ = self.request("POST", "/start",
                                              {"topic": "НЛП: фокусы языка", "lessons": "3"},
                                              cookie="aidemy_token=t0ken")
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/job/"))
        status, _, _, body = self.request("POST", "/start",
                                          {"topic": "НЛП: фокусы языка", "lessons": "3"},
                                          cookie="aidemy_token=t0ken")
        self.assertEqual(status, 409)
        self.assertIn("уже есть", body)

    def test_job_page_shows_the_status(self):
        _, location, _, _ = self.request("POST", "/start", {"topic": "тема про фокусы", "lessons": "2"},
                                         cookie="aidemy_token=t0ken")
        status, _, _, body = self.request("GET", location, cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("в очереди", body)
        self.assertIn("тема про фокусы", body)

    def test_job_page_shows_the_journal_of_steps(self):
        with store.session() as conn:
            job_id = store.create(conn, "тема про фокусы", lessons=2)
            store.update(conn, job_id, status="writing", message="пишет урок 1 из 2")
        status, _, _, body = self.request("GET", f"/job/{job_id}", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("Журнал", body)
        self.assertIn("пишет урок 1 из 2", body)

    def test_language_switch_sets_a_cookie_and_speaks_english(self):
        status, location, set_cookie, _ = self.request("GET", "/?lang=en", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 303)
        self.assertEqual(location, "/")
        self.assertIn("aidemy_lang=en", set_cookie or "")
        status, _, _, body = self.request("GET", "/", cookie="aidemy_token=t0ken; aidemy_lang=en")
        self.assertEqual(status, 200)
        self.assertIn("What should it teach?", body)
        self.assertIn('lang="en"', body)

    def test_probe_streams_an_mp3(self):
        with tempfile.TemporaryDirectory() as td:
            mp3 = Path(td) / "pair__one.mp3"
            mp3.write_bytes(b"ID3fake-mp3")
            with mock.patch.object(web_app.probe, "probe", return_value=(mp3, "wrote pair")):
                status, _, _, body = self.request("GET", "/probe?voice_a=piper:a&voice_b=piper:b",
                                                  cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn('filename="pair__one.mp3"', self.disposition or "")
        self.assertNotIn(".mp3.mp3", self.disposition or "")

    def test_probe_failure_is_reported_not_hidden(self):
        with mock.patch.object(web_app.probe, "probe", side_effect=RuntimeError("voice model missing")):
            status, _, _, body = self.request("GET", "/probe?voice_a=piper:a&voice_b=piper:b",
                                              cookie="aidemy_token=t0ken")
        self.assertEqual(status, 500)
        self.assertIn("voice model missing", body)

    def test_file_outside_the_root_is_refused(self):
        status, _, _, _ = self.request("GET", "/files/../../etc/passwd", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 404)

    def write_course(self, topic):
        """A finished course as the pipeline leaves it, so the page has something to show."""
        slug = store.slugify(topic)
        lesson = Path(self.tmp.name) / slug / "class" / "01-lesson-1"
        lesson.mkdir(parents=True)
        (lesson / "card.md").write_text(
            "# Урок 1. Три двери вместо одной стены\n"
            "**Идея в трёх строках**\n"
            "- Один вариант закрывает выбор\n"
            "- <script>alert(1)</script> в карточке обязан остаться текстом\n",
            encoding="utf-8")
        (lesson / "lesson-1.mp3").write_bytes(b"ID3fake")
        with store.session() as conn:
            return store.create(conn, topic, lessons=1), slug

    def test_the_page_shows_the_card_and_the_player(self):
        job_id, slug = self.write_course("тема про фокусы")
        status, _, _, body = self.request("GET", f"/job/{job_id}", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("<audio controls", body)
        self.assertIn(f"/files/{urllib.parse.quote(slug)}/class/01-lesson-1/lesson-1.mp3", body)
        self.assertIn("Три двери вместо одной стены", body)
        self.assertIn("<li>Один вариант закрывает выбор</li>", body)
        self.assertNotIn("<script>alert(1)</script> в", body)
        self.assertIn("&lt;script&gt;", body)

    def test_the_topic_box_opens_prefilled_and_clears_on_focus(self):
        status, _, _, body = self.request("GET", "/", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn('name="topic" value="', body)
        self.assertIn('data-pristine="1"', body)
        self.assertIn("addEventListener('focus'", body)

    def test_the_handlers_wait_for_the_page_to_exist(self):
        """The script sits in `head`; wiring it up before the body parses leaves every
        button on the page dead, and only the live browser shows that."""
        status, _, _, body = self.request("GET", "/", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        head, _, rest = body.partition("</head>")
        self.assertIn("DOMContentLoaded", head)
        for hook in ("[data-pristine]", "[data-selectall]", "[data-confirm]"):
            self.assertIn(f"querySelectorAll('{hook}')", head)
        self.assertNotIn("querySelectorAll('[data-pristine]')", rest)

    def test_delete_removes_the_row_and_the_course_folder(self):
        job_id, slug = self.write_course("тема для удаления")
        self.assertTrue((Path(self.tmp.name) / slug).is_dir())
        status, _, _, body = self.request("POST", "/delete", {"del": str(job_id)},
                                          cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("Удалено: 1", body)
        self.assertFalse((Path(self.tmp.name) / slug).exists())
        with store.session() as conn:
            self.assertIsNone(store.get(conn, job_id))

    def test_delete_without_a_mark_shows_the_page_again(self):
        self.write_course("тема которую не трогали")
        status, _, _, body = self.request("POST", "/delete", {}, cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("Не отмечено ни одного курса", body)
        with store.session() as conn:
            self.assertEqual(len(store.jobs(conn)), 1)

    def test_the_course_list_offers_a_checkbox_per_course(self):
        self.write_course("тема с галочкой")
        status, _, _, body = self.request("GET", "/", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn('action="/delete"', body)
        self.assertIn('name="del" value="', body)
        self.assertIn("data-confirm=", body)


    def test_a_lesson_without_audio_says_so_about_the_audio(self):
        """The card may well be finished while the voice is not: the page must not
        blame the card for missing audio."""
        topic = "тема без озвучки"
        slug = store.slugify(topic)
        lesson = Path(self.tmp.name) / slug / "class" / "01-lesson-1"
        lesson.mkdir(parents=True)
        (lesson / "card.md").write_text("# Урок 1. Только текст\n- пункт\n", encoding="utf-8")
        with store.session() as conn:
            job_id = store.create(conn, topic, lessons=1)
        status, _, _, body = self.request("GET", f"/job/{job_id}", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)
        self.assertIn("Аудио ещё не готово.", body)
        self.assertNotIn("Карточка ещё не готова.", body)
        self.assertIn("<h3>Урок 1. Только текст</h3>", body)
        self.assertNotIn("<audio", body)

    def test_both_languages_offer_the_same_labels(self):
        """A label added to one column only means the other language shows a key."""
        self.assertEqual(set(web_app.STR["ru"]), set(web_app.STR["en"]))
        self.assertEqual(len(web_app.TOPICS["ru"]), len(web_app.TOPICS["en"]))

    def test_every_label_is_used_by_the_markup(self):
        """Two dead labels (`listen` and `topic_ph`) slipped past every render test:
        nothing on the page referenced them, so no reader ever saw them. This measure is
        the only thing that notices, and it is the reason the tests read the source."""
        source = (REPO / "web" / "app.py").read_text(encoding="utf-8")
        unused = []
        for key in web_app.STR["ru"]:
            used = (len(re.findall(r"words\[[\"']" + re.escape(key) + r"[\"']\]", source))
                    + len(re.findall(r"STR\[lang\]\[[\"']" + re.escape(key) + r"[\"']\]", source)))
            if used == 0:
                unused.append(key)
        self.assertEqual(unused, [], f"labels nothing renders: {unused}")


class CardRendering(unittest.TestCase):
    """The mini renderer: only what the writer brief allows, and nothing that runs."""

    def test_headings_bullets_and_bold(self):
        out = web_app.md_to_html("# Заголовок\n- раз\n- два\n**полужирное**\n")
        self.assertIn("<h3>Заголовок</h3>", out)
        self.assertIn("<ul><li>раз</li><li>два</li></ul>", out)
        self.assertIn("<strong>полужирное</strong>", out)

    def test_html_from_a_model_stays_text(self):
        out = web_app.md_to_html("<img src=x onerror=alert(1)> [ссылка](http://e.g)")
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)


class WorkerTick(unittest.TestCase):
    """The tick moves a request to a status a person can act on; it never writes lessons."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"AIDEMY_WEB_ROOT": self.tmp.name}, clear=False)
        self.env.start()
        self.conn = store.connect(Path(self.tmp.name) / "queue.db")

    def tearDown(self):
        self.conn.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_empty_queue_returns_none(self):
        self.assertIsNone(worker.tick(self.conn, choose=lambda: "qoder", health=lambda: ("down", "")))

    def test_qoder_marks_the_job_as_waiting_for_an_agent(self):
        job_id = store.create(self.conn, "НЛП: фокусы языка", lessons=3, runner="qoder")
        worker.tick(self.conn, choose=lambda: "qoder", health=lambda: ("down", ""))
        job = store.get(self.conn, job_id)
        self.assertEqual(job["status"], "mapping")
        self.assertIn("ждёт агента", job["message"])

    def test_local_down_explains_how_to_start_the_model(self):
        job_id = store.create(self.conn, "тема", lessons=2, runner="local")
        worker.tick(self.conn, choose=lambda: "local", health=lambda: ("down", "refused"))
        message = store.get(self.conn, job_id)["message"]
        self.assertIn("lms server start", message)
        self.assertIn("refused", message)

    def test_local_ready_without_pages_asks_for_pages(self):
        job_id = store.create(self.conn, "тема", lessons=2, runner="local")
        worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        message = store.get(self.conn, job_id)["message"]
        self.assertIn("raw/", message)
        self.assertIn("нужно 3", message)

    def test_local_ready_with_pages_starts_the_job(self):
        job_id = store.create(self.conn, "тема", lessons=2, runner="local")
        folder = Path(self.tmp.name) / "тема" / "raw" / "site"
        folder.mkdir(parents=True)
        for i in range(3):
            (folder / f"p{i}.md").write_text(f"url: https://example.com/{i}" + chr(10) + "текст", encoding="utf-8")
        with mock.patch.object(worker.jobs, "start") as start:
            worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertTrue(start.called)
        self.assertEqual(store.get(self.conn, job_id)["status"], "writing")

    def test_a_parked_request_wakes_up_when_the_pages_arrive(self):
        """The request was already moved to «карта тем» with nothing on disk. Downloading
        the pages afterwards has to start it: a tick that only reads «в очереди» leaves
        the person staring at «нужно 3» forever."""
        job_id = store.create(self.conn, "тема с поздними страницами", lessons=2, runner="local")
        with mock.patch.object(worker.jobs, "start"):
            worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        job = store.get(self.conn, job_id)
        self.assertEqual((job["status"], "0 страниц" in job["message"]), ("mapping", True))
        folder = Path(self.tmp.name) / store.slugify("тема с поздними страницами") / "raw" / "web"
        folder.mkdir(parents=True)
        for i in range(3):
            (folder / f"p{i}.md").write_text(f"url: https://example.com/{i}" + chr(10) + "текст",
                                             encoding="utf-8")
        with mock.patch.object(worker.jobs, "start") as start:
            touched = worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertEqual(touched, job_id)
        self.assertEqual(store.get(self.conn, job_id)["status"], "writing")
        self.assertTrue(start.called)

    def test_a_parked_request_does_not_remark_the_journal(self):
        """Nothing changed, so nothing is written: the tick runs every five seconds and
        the journal has to stay readable."""
        job_id = store.create(self.conn, "тема без страниц", lessons=2, runner="local")
        with mock.patch.object(worker.jobs, "start"):
            for _ in range(4):
                worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertEqual(len(store.history(self.conn, job_id)), 1)

    def test_a_request_given_to_the_agent_is_left_alone(self):
        job_id = store.create(self.conn, "тема для агента", lessons=2, runner="qoder")
        with mock.patch.object(worker.jobs, "start"):
            worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertEqual(store.get(self.conn, job_id)["status"], "mapping")
        with mock.patch.object(worker.jobs, "start") as start:
            touched = worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertIsNone(touched)
        self.assertFalse(start.called)
        self.assertEqual(len(store.history(self.conn, job_id)), 1)


if __name__ == "__main__":
    unittest.main()
