import json

from app.generator import beats_for, extract_json, generate_story, split_counts
from app.models import StoryRequest
from app.providers.base import LLMResult, Provider
from app.providers.mock import MockProvider
from app.validate import validate_story


def _req(**kw):
    base = dict(track="pinyin", topic="a monkey and the clouds", length="short", level=2, provider="mock")
    base.update(kw)
    return StoryRequest(**base)


def test_chunk_arithmetic():
    assert beats_for(50) == 2 and beats_for(130) == 5 and beats_for(200) == 8
    assert sum(split_counts(130, 5)) == 130 and sum(split_counts(37, 2)) == 37


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": 1} Hope it helps') == {"a": 1}
    salvaged = extract_json('{"lines": [{"hanzi": "你好", "pinyin": "Nǐ hǎo", "english": "Hi"}, {"hanzi": "再见", "pin')
    assert len(salvaged["lines"]) == 1  # truncated output keeps the complete lines


def test_pinyin_story_end_to_end():
    story = generate_story(_req(), MockProvider("demo", "demo"))
    assert len(story.lines) == 50
    assert [l.n for l in story.lines] == list(range(1, 51))
    names = [(c["hanzi"], c["primary"]) for c in story.characters]
    report = validate_story("pinyin", [l.model_dump() for l in story.lines], names, story.target_lines)
    assert report["errors"] == 0


def test_french_story_and_custom_length():
    story = generate_story(_req(track="french", length="custom", custom_lines=30, level=1), MockProvider("demo", "demo"))
    assert len(story.lines) == 30
    assert "é" in "".join(l.primary for l in story.lines)


class BadPinyinProvider(MockProvider):
    """Writes a wrong pinyin line every time; the pipeline must repair it from the hanzi."""

    def complete(self, system, user, **kw):
        res = super().complete(system, user, **kw)
        data = json.loads(res.text)
        for ln in data.get("lines", []):
            ln["pinyin"] = "Nǐ hǎo"  # wrong syllable count for every line
        return LLMResult(json.dumps(data, ensure_ascii=False), res.input_tokens, res.output_tokens)


def test_bad_pinyin_is_repaired():
    story = generate_story(_req(), BadPinyinProvider("bad", "bad"))
    names = [(c["hanzi"], c["primary"]) for c in story.characters]
    report = validate_story("pinyin", [l.model_dump() for l in story.lines], names, story.target_lines)
    assert report["errors"] == 0
    assert story.usage["repaired_lines"] >= 45 and story.usage["retries"] > 0


class FlakyJSONProvider(MockProvider):
    """First answer of every call is not JSON at all."""

    def __init__(self, *a):
        super().__init__(*a)
        self.turn = 0

    def complete(self, system, user, **kw):
        self.turn += 1
        if self.turn % 2 == 1:
            return LLMResult("Sure, here is your story! (no JSON)", 5, 5)
        return super().complete(system, user, **kw)


def test_non_json_answers_are_retried():
    story = generate_story(_req(), FlakyJSONProvider("flaky", "flaky"))
    assert len(story.lines) == 50 and story.usage["retries"] >= 3
