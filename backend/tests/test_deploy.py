"""Things that only matter once the site is split (static site + API) or hosted: auth, CORS, storage hooks,
the Claude-login provider (against a fake `claude` program) and the Gemini preset."""
import importlib
import json
import shutil
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, storage
from app.generator import generate_story
from app.models import StoryRequest
from app.providers import get_provider
from app.providers.base import LLMError
from app.providers.openai_compat import OpenAICompatProvider
from tests.fake_llm import FakeServer

BACKEND = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ auth + health
def _fresh_app(monkeypatch, **env):
    """Re-import app.api with the given settings (they are read once, at import time)."""
    for k, v in env.items():
        monkeypatch.setattr(config, k, v)
    import app.api as api

    return importlib.reload(api).app


@pytest.fixture()
def restore_api():
    yield
    import app.api as api

    importlib.reload(api)


def test_bearer_password_and_open_health(monkeypatch, restore_api):
    c = TestClient(_fresh_app(monkeypatch, APP_PASSWORD="s3cret"))
    health = c.get("/api/health")
    assert health.json()["ok"] is True and health.json()["password_required"] is True  # no password needed
    assert len(health.json()["build"]) == 10  # tells you which code a server is really running
    assert c.get("/api/config").status_code == 401
    assert c.get("/api/config", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = c.get("/api/config", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"  # never serve a stale provider list
    assert c.get("/api/config", auth=("me", "s3cret")).status_code == 200  # curl-style Basic still works
    assert "www-authenticate" not in c.get("/api/config").headers          # no browser pop-up in the web app
    assert c.get("/api/config", headers={"Authorization": "Bearer h\u00e9llo".encode("latin-1")}).status_code == 401  # odd bytes must not crash
    assert c.get("/api/config", auth=("me", "\u5bc6\u7801")).status_code == 401


def test_unicode_password(monkeypatch, restore_api):
    c = TestClient(_fresh_app(monkeypatch, APP_PASSWORD="m\u00e9ssage\u5bc6\u7801"))
    assert c.get("/api/config", auth=("story", "m\u00e9ssage\u5bc6\u7801")).status_code == 200  # what the web app sends
    assert c.get("/api/config", auth=("story", "message")).status_code == 401


def test_cors_is_outermost_so_even_401_answers_carry_it(monkeypatch, restore_api):
    app = _fresh_app(monkeypatch, APP_PASSWORD="s3cret", ALLOWED_ORIGINS=["https://story.vercel.app"], ALLOWED_ORIGIN_REGEX=None)
    c = TestClient(app)
    origin = {"Origin": "https://story.vercel.app"}

    pre = c.options("/api/stories", headers={**origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "https://story.vercel.app"
    assert "authorization" in pre.headers["access-control-allow-headers"].lower()

    denied = c.get("/api/stories", headers=origin)
    assert denied.status_code == 401 and denied.headers["access-control-allow-origin"] == "https://story.vercel.app"

    ok = c.get("/api/stories", headers={**origin, "Authorization": "Bearer s3cret"})
    assert ok.status_code == 200

    stranger = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers


def test_pdf_filename_is_readable_by_the_browser(monkeypatch, restore_api):
    app = _fresh_app(monkeypatch, APP_PASSWORD="", ALLOWED_ORIGINS=["https://story.vercel.app"], ALLOWED_ORIGIN_REGEX=None)
    c = TestClient(app)
    sample = BACKEND / "data" / "stories" / "sample-wukong-and-the-moon.json"
    shutil.copy(sample, storage.STORIES_DIR / sample.name)
    try:
        r = c.get(f"/api/stories/{sample.stem}/pdf?download=true", headers={"Origin": "https://story.vercel.app"})
        assert r.status_code == 200 and "content-disposition" in r.headers["access-control-expose-headers"].lower()
    finally:
        (storage.STORIES_DIR / sample.name).unlink()


# ------------------------------------------------------------------ storage hooks (Modal volume commit)
def test_storage_hook_and_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORIES_DIR", tmp_path / "stories")
    (tmp_path / "stories").mkdir()
    calls = []
    monkeypatch.setattr(storage, "AFTER_WRITE", [lambda: calls.append(1)])

    assert storage.seed_if_empty(BACKEND / "data" / "stories") == 2        # first start: samples copied
    assert storage.seed_if_empty(BACKEND / "data" / "stories") == 0        # never overwrites afterwards

    sid = storage.list_stories()[0]["id"]
    story = storage.load_story(sid)
    storage.save_story(story)
    storage.delete_story(sid)
    assert len(calls) == 2                                                  # one flush per save and per delete

    def boom():
        raise RuntimeError("volume offline")

    monkeypatch.setattr(storage, "AFTER_WRITE", [boom])
    storage.save_story(story)                                               # a failed flush must not lose the story
    assert storage.load_story(sid).id == sid


# ------------------------------------------------------------------ Gemini preset
def test_groq_default_model_is_one_the_free_tier_still_serves(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    # Groq removed the Llama models from the free tier in August 2026.
    assert "llama" not in config.PROVIDERS["groq"].model()
    assert config.PROVIDERS["groq"].model() == "openai/gpt-oss-120b"


def test_daily_limit_fails_fast_instead_of_retrying(monkeypatch):
    import httpx

    calls = []

    class Resp:
        status_code = 429
        headers: dict = {}
        text = '{"error":{"message":"Rate limit reached: limit 1000 requests per day (RPD)"}}'

    monkeypatch.setattr(httpx, "post", lambda *a, **k: (calls.append(1), Resp())[1])
    with pytest.raises(LLMError, match="daily limit"):
        OpenAICompatProvider("Groq", "m", "https://x/v1", "k").complete("S", "U")
    assert len(calls) == 1


def test_gemini_preset_and_default_choice(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY", "DEFAULT_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert config.default_provider_id() == "mock"
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    assert config.default_provider_id() == "gemini"
    spec = config.PROVIDERS["gemini"]
    assert spec.url().startswith("https://generativelanguage.googleapis.com") and spec.max_tokens_factor > 1


def test_gemini_gets_extra_token_headroom_for_thinking():
    with FakeServer(8792) as fake:
        OpenAICompatProvider("Gemini", "m", f"http://127.0.0.1:{fake.port}/v1", "k", 2.0).complete("S", "TASK: ideas\nTRACK: french\nCOUNT: 2\n", max_tokens=1000)
        assert [b for k, h, b in fake.log if k == "openai"][-1]["max_tokens"] == 2000


# ------------------------------------------------------------------ Claude login via a fake `claude` program
@pytest.fixture()
def fake_claude(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    script = tmp_path / "claude"
    script.write_text(f'''#!{sys.executable}
import json, os, sys
sys.path.insert(0, {str(BACKEND)!r})
from app.providers.mock import MockProvider
stdin = sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({{"args": sys.argv[1:], "api_key_seen": "ANTHROPIC_API_KEY" in os.environ, "cwd": os.getcwd(), "stdin": stdin}}) + "\\n")
if mode == "login":
    print(json.dumps({{"type": "result", "is_error": True, "result": "Not logged in. Please run /login"}})); sys.exit(1)
if mode == "limit":
    print(json.dumps({{"type": "result", "is_error": True, "result": "Claude usage limit reached"}})); sys.exit(1)
if mode == "garbage":
    print("hello"); sys.exit(0)
out = MockProvider("f", "f").complete("", stdin)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": out.text,
                   "usage": {{"input_tokens": 5, "output_tokens": 7, "cache_read_input_tokens": 3}}}}))
''')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAUDE_BIN", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")
    monkeypatch.setattr(config, "HOST", "127.0.0.1")

    def calls():
        return [json.loads(l) for l in log.read_text().splitlines()]

    return calls


def test_claude_login_runs_the_cli_safely(fake_claude):
    prov = get_provider("claude_code")
    res = prov.complete("SYSTEM TEXT", "TASK: ideas\nTRACK: french\nCOUNT: 3\n")
    assert '"ideas"' in res.text and res.input_tokens == 8 and res.output_tokens == 7

    call = fake_claude()[-1]
    args = call["args"]
    assert args[0] == "-p" and "--bare" not in args                      # --bare would ignore the subscription login
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--system-prompt") + 1] == "SYSTEM TEXT"
    assert args[args.index("--tools") + 1] == ""                          # no file or shell access
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    assert call["api_key_seen"] is False                                  # an API key in the environment must not hijack billing
    assert call["stdin"].startswith("TASK: ideas") and "story-studio-" in call["cwd"]


def test_full_story_through_claude_login(fake_claude):
    story = generate_story(StoryRequest(track="pinyin", topic="a monkey and the clouds", length="short", level=2), get_provider("claude_code"))
    assert len(story.lines) == 50 and len(fake_claude()) >= 3


def test_long_instructions_go_through_stdin(fake_claude, monkeypatch):
    big = "RULES " * 5000
    get_provider("claude_code").complete(big, "TASK: ideas\nTRACK: french\nCOUNT: 2\n")
    call = fake_claude()[-1]
    assert big in call["stdin"] and len(call["args"][call["args"].index("--system-prompt") + 1]) < 1000


@pytest.mark.parametrize("mode,words", [("login", "not signed in"), ("limit", "usage limit"), ("garbage", "unreadable")])
def test_claude_login_errors_are_readable(fake_claude, monkeypatch, mode, words):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(LLMError) as err:
        get_provider("claude_code").complete("S", "TASK: ideas\nTRACK: french\nCOUNT: 2\n")
    assert words in str(err.value).lower()


def test_claude_login_is_refused_on_a_public_server_or_without_claude(fake_claude, monkeypatch):
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    with pytest.raises(LLMError, match="own computer"):
        get_provider("claude_code")
    assert config.PROVIDERS["claude_code"].configured() is False

    # A hosted backend listens on 127.0.0.1 behind its own proxy (Modal), so HOST alone is not enough.
    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    monkeypatch.setattr(config, "HOSTED", True)
    with pytest.raises(LLMError, match="runs in the cloud"):
        get_provider("claude_code")
    monkeypatch.setattr(config, "HOSTED", False)

    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    monkeypatch.setenv("CLAUDE_BIN", "definitely-not-installed")
    with pytest.raises(LLMError, match="not installed"):
        get_provider("claude_code")
