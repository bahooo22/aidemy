"""Tests for the host LLM runner: health states, one ask, and the choice. No network."""
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "aidemy" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import runners  # noqa: E402


def reply(payload):
    stream = io.BytesIO(json.dumps(payload).encode("utf-8"))
    stream.__enter__ = lambda: stream
    stream.__exit__ = lambda *args: False
    return stream


class Health(unittest.TestCase):
    def test_ok_names_the_model(self):
        with mock.patch.object(runners.urllib.request, "urlopen",
                               return_value=reply({"data": [{"id": "qwen3.8-9b"}]})):
            self.assertEqual(runners.health("http://llm/v1"), ("ok", "qwen3.8-9b"))

    def test_server_up_without_a_model_is_a_different_answer(self):
        with mock.patch.object(runners.urllib.request, "urlopen", return_value=reply({"data": []})):
            state, detail = runners.health("http://llm/v1")
        self.assertEqual(state, "no-model")
        self.assertIn("lms load", detail)

    def test_dead_server_is_down(self):
        with mock.patch.object(runners.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("connection refused")):
            state, detail = runners.health("http://llm/v1")
        self.assertEqual(state, "down")
        self.assertIn("refused", detail)


class Ask(unittest.TestCase):
    def body_of(self, payload, **kwargs):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return reply(payload)

        with mock.patch.object(runners.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = runners.ask("напиши урок", **kwargs)
        return seen["body"], result

    def test_reasoning_is_switched_off_for_routine_steps(self):
        body, content = self.body_of({"choices": [{"message": {"content": "A: привет"}}]}, reasoning="none")
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(content, "A: привет")

    def test_empty_content_is_an_error_not_an_empty_lesson(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.body_of({"choices": [{"message": {"content": "   "}}]})
        self.assertIn("пустой content", str(ctx.exception))

    def test_http_error_names_the_code(self):
        error = urllib.error.HTTPError("http://llm/v1/chat/completions", 429, "too many", {}, io.BytesIO(b"slow down"))
        with mock.patch.object(runners.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as ctx:
                runners.ask("текст")
        self.assertIn("429", str(ctx.exception))


class Choice(unittest.TestCase):
    def test_api_wins_when_a_key_is_present(self):
        env = {"AIDEMY_LLM_API_KEY": "sk-test"}
        self.assertEqual(runners.choose(env, probe=lambda url: ("down", "")), "api")

    def test_local_when_the_server_answers(self):
        self.assertEqual(runners.choose({}, probe=lambda url: ("ok", "qwen")), "local")

    def test_qoder_when_nothing_answers(self):
        self.assertEqual(runners.choose({}, probe=lambda url: ("down", "refused")), "qoder")

    def test_explicit_choice_is_respected(self):
        self.assertEqual(runners.choose({"AIDEMY_RUNNER": "qoder"}, probe=lambda url: ("ok", "qwen")), "qoder")

    def test_no_model_loaded_still_counts_as_local(self):
        self.assertEqual(runners.choose({}, probe=lambda url: ("no-model", "load it")), "local")


if __name__ == "__main__":
    unittest.main()
