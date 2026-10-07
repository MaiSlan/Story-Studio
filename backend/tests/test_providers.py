import os

import pytest

from app.generator import generate_story
from app.models import StoryRequest
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMError
from app.providers.openai_compat import OpenAICompatProvider
from tests.fake_llm import FakeServer


@pytest.fixture()
def fake():
    with FakeServer(8791) as srv:
        yield srv


def _req(**kw):
    base = dict(track="pinyin", topic="a monkey and the clouds", length="short", level=2)
    base.update(kw)
    return StoryRequest(**base)


def test_anthropic_client_builds_a_valid_request(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{fake.port}")
    prov = AnthropicProvider("Claude", "claude-sonnet-5-5", "sk-test")
    res = prov.complete("SYSTEM TEXT", "TASK: outline\nTRACK: pinyin\nBEATS_REQUIRED: 2\n", max_tokens=1000, temperature=0.7)
    kind, headers, body = fake.log[-1]
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 1000 and "temperature" not in body
    assert body["system"][0]["text"] == "SYSTEM TEXT" and body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert headers["x-api-key"] == "sk-test"
    assert '"beats"' in res.text and res.input_tokens == 11 and res.output_tokens == 22


def test_full_story_through_the_anthropic_client(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{fake.port}")
    story = generate_story(_req(), AnthropicProvider("Claude", "claude-sonnet-5-5", "sk-test"))
    assert len(story.lines) == 50 and story.usage["input_tokens"] > 0
    system_prompt = fake.log[0][2]["system"][0]["text"]
    assert "PINYIN TRACK" in system_prompt and "Level 2" in system_prompt  # style guide really sent


def test_openai_compatible_client_and_quirks(fake):
    base = f"http://127.0.0.1:{fake.port}/v1"
    fake.behaviour["openai_reject_response_format"] = True
    fake.behaviour["openai_rate_limit_once"] = True
    prov = OpenAICompatProvider("Groq", "llama-3.3-70b-versatile", base, "gsk-test")
    res = prov.complete("S", "TASK: ideas\nTRACK: french\nCOUNT: 3\n")
    assert '"ideas"' in res.text and res.input_tokens == 7
    sent = [b for k, h, b in fake.log if k == "openai"]
    assert len(sent) == 3                       # 429, then 400 (response_format), then success
    assert "response_format" not in sent[-1]
    assert fake.log[-1][1]["authorization"] == "Bearer gsk-test"


def test_full_french_story_through_the_openai_client(fake):
    story = generate_story(_req(track="french", level=1), OpenAICompatProvider("Groq", "m", f"http://127.0.0.1:{fake.port}/v1", "k"))
    assert len(story.lines) == 50 and story.lines[0].primary.startswith("Il ")


def test_missing_key_gives_a_helpful_error(monkeypatch):
    from app.providers import get_provider

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        get_provider("groq")
