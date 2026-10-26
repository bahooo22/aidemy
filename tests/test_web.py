"""Tests for the web layer: the queue and the token gate. No network, no browser."""
import json
import os
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
        conn.close()
        return status, location, set_cookie, payload

    def test_health_needs_no_token(self):
        status, _, _, body = self.request("GET", "/health")
        self.assertEqual((status, body), (200, "ok"))

    def test_page_without_token_is_refused(self):
        status, _, _, body = self.request("GET", "/")
        self.assertEqual(status, 403)
        self.assertIn("Токен", body)

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

    def test_probe_streams_an_mp3(self):
        with tempfile.TemporaryDirectory() as td:
            mp3 = Path(td) / "pair__one.mp3"
            mp3.write_bytes(b"ID3fake-mp3")
            with mock.patch.object(web_app.probe, "probe", return_value=(mp3, "wrote pair")):
                status, _, _, body = self.request("GET", "/probe?voice_a=piper:a&voice_b=piper:b",
                                                  cookie="aidemy_token=t0ken")
        self.assertEqual(status, 200)

    def test_probe_failure_is_reported_not_hidden(self):
        with mock.patch.object(web_app.probe, "probe", side_effect=RuntimeError("voice model missing")):
            status, _, _, body = self.request("GET", "/probe?voice_a=piper:a&voice_b=piper:b",
                                              cookie="aidemy_token=t0ken")
        self.assertEqual(status, 500)
        self.assertIn("voice model missing", body)

    def test_file_outside_the_root_is_refused(self):
        status, _, _, _ = self.request("GET", "/files/../../etc/passwd", cookie="aidemy_token=t0ken")
        self.assertEqual(status, 404)


class WorkerTick(unittest.TestCase):
    """The tick moves a request to a status a person can act on; it never writes lessons."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "queue.db")

    def tearDown(self):
        self.conn.close()
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

    def test_local_ready_says_the_orchestrator_is_next(self):
        job_id = store.create(self.conn, "тема", lessons=2, runner="local")
        worker.tick(self.conn, choose=lambda: "local", health=lambda: ("ok", "qwen"))
        self.assertIn("оркестратор", store.get(self.conn, job_id)["message"])


if __name__ == "__main__":
    unittest.main()
