"""Host LLM: one health check, one ask, and the runner choice.

The server is LM Studio on the host (`lms server start`), reached from the
container as host.docker.internal:1234. Overrides: AIDEMY_LLM_URL, AIDEMY_LLM_KEY,
AIDEMY_LLM_MODEL, AIDEMY_RUNNER.
"""
import json, os, urllib.error, urllib.request

DEFAULT_URL = "http://host.docker.internal:1234/v1"


def base_url(environ=None):
    environ = os.environ if environ is None else environ
    return (environ.get("AIDEMY_LLM_URL") or DEFAULT_URL).rstrip("/")


def health(url=None, timeout=5):
    """('ok' | 'no-model' | 'down', detail): a dead server and a server with no
    model loaded need different fixes, so they are different answers."""
    target = (url or base_url()).rstrip("/")
    try:
        with urllib.request.urlopen(target + "/models", timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        return "down", f"HTTP {error.code}"
    except (urllib.error.URLError, OSError) as error:
        return "down", str(getattr(error, "reason", error))
    models = [m.get("id") for m in data.get("data", []) if m.get("id")]
    if not models:
        return "no-model", "сервер отвечает, но ни одна модель не загружена (lms load ...)"
    return "ok", models[0]


def ask(prompt, system=None, model=None, reasoning="none", url=None, timeout=None, environ=None,
        schema=None):
    """One chat completion. An empty `content` is an error, not an empty lesson:
    a model that spends the whole budget on reasoning returns nothing to write with.

    The deadline is 900 seconds, not the 300 this used to have: a lesson is a
    10 000-character prompt and a 300-word answer, and the first live run died at
    five minutes on a healthy model. `AIDEMY_LLM_TIMEOUT` overrides, in seconds.

    `schema` asks for a json_schema answer; a server without structured output
    answers 400 and the caller falls back to the fenced-block prompt."""
    environ = os.environ if environ is None else environ
    if timeout is None:
        timeout = float(environ.get("AIDEMY_LLM_TIMEOUT") or 900)
    target = (url or base_url()).rstrip("/")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"messages": messages, "temperature": 0.4, "max_tokens": 2000,
            "model": model or environ.get("AIDEMY_LLM_MODEL") or "local"}
    if schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "lesson", "schema": schema, "strict": True}}
    if reasoning:
        body["reasoning_effort"] = reasoning
    request = urllib.request.Request(
        target + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + (environ.get("AIDEMY_LLM_KEY") or "local")},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"LLM ответил HTTP {error.code}: {error.read()[:200]!r}") from None
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(f"LLM недоступен: {getattr(error, 'reason', error)}") from None
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("пустой content: модель потратила ответ на размышления "
                           "(нужен reasoning_effort=none)")
    return content


def choose(environ=None, probe=health):
    """`auto`: `api` when a key is present, else the local server if it answers, else
    the Qoder queue. The cloud branch is an option, never a default: with no key in
    the environment nothing here calls a paid endpoint, and the fork ships no key."""
    environ = os.environ if environ is None else environ
    wanted = (environ.get("AIDEMY_RUNNER") or "auto").strip().lower()
    if wanted in ("api", "local", "qoder"):
        return wanted
    if (environ.get("AIDEMY_LLM_API_KEY") or "").strip():
        return "api"
    state, _ = probe(environ.get("AIDEMY_LLM_URL"))
    return "local" if state in ("ok", "no-model") else "qoder"
