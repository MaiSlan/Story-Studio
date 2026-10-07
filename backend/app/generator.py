"""The story pipeline: plan -> write in chunks -> check -> repair -> save.

Why chunks? A 200-line trilingual story is 15-20k tokens. Asking for it in one go makes the
AI lose focus (and sometimes hit its output limit). So we first ask for an outline, then write
the story in parts of about 25 lines, each time showing the AI the outline, the character
spellings and the last lines written. Each part is checked (pinyin vs hanzi, simplified
characters, empty fields, line count) and retried with precise feedback when it is bad.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from . import prompts
from .models import Line, Story, StoryRequest, Title
from .pinyin_tools import check_pinyin, pinyin_from_hanzi
from .providers import LLMError, Provider
from .storage import new_id, now_iso, save_story
from .tracks import LINES_PER_CHUNK, SOURCE_MODES, TRACKS, VOICES
from .validate import names_from_outline, normalize_line, validate_line

MAX_ATTEMPTS = 3
REPAIRABLE = {"syllable_mismatch", "extra_pinyin", "tone_numbers", "hanzi_in_pinyin", "empty_primary"}


class Cancelled(Exception):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    retries: int = 0
    repaired_lines: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Ctx:
    provider: Provider
    usage: Usage = field(default_factory=Usage)
    progress: Callable[[dict], None] = lambda _p: None
    cancelled: Callable[[], bool] = lambda: False

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()


# ------------------------------------------------------------------------ JSON handling
def extract_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    # truncated output: salvage every complete {...} object that looks like a line
    objs = []
    for m in re.finditer(r"\{[^{}]*\}", t):
        try:
            o = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and "hanzi" in o:
            objs.append(o)
    if objs:
        return {"lines": objs}
    raise ValueError("no JSON found in the answer")


def call_json(ctx: Ctx, system: str, user: str, *, max_tokens: int, temperature: float = 0.8) -> dict:
    """Call the model and parse JSON; retry once or twice when the answer is not usable JSON."""
    last = ""
    for attempt in range(3):
        ctx.check()
        res = ctx.provider.complete(system, user, max_tokens=max_tokens, temperature=temperature, json_mode=True)
        ctx.usage.calls += 1
        ctx.usage.input_tokens += res.input_tokens
        ctx.usage.output_tokens += res.output_tokens
        try:
            return extract_json(res.text)
        except ValueError as exc:
            last = str(exc)
            ctx.usage.retries += 1
            user = user + "\n\nYour previous answer was not valid JSON. Reply with ONE JSON object only."
    raise LLMError(f"The AI did not return usable JSON ({last}).")


# ------------------------------------------------------------------------ planning
def beats_for(target: int) -> int:
    return max(1, round(target / LINES_PER_CHUNK))


def split_counts(target: int, n_beats: int) -> list[int]:
    base, extra = divmod(target, n_beats)
    counts = [base + (1 if i < extra else 0) for i in range(n_beats)]
    return counts


def make_outline(ctx: Ctx, req: StoryRequest, system: str) -> dict:
    n = beats_for(req.target_lines())
    data = call_json(ctx, system, prompts.outline_prompt(req, n), max_tokens=2500, temperature=0.9)
    beats = [b for b in (data.get("beats") or []) if isinstance(b, dict) and b.get("summary")]
    if not beats:
        raise LLMError("The AI returned an outline without any beats.")
    while len(beats) < n:  # pad if the model returned fewer beats than asked
        beats.append({"summary": "Continue and develop the story, building toward the ending."})
    beats = beats[:n]
    title = data.get("title") or {}
    outline = {
        "title": {k: str(title.get(k, "")).strip() for k in ("primary", "hanzi", "english")},
        "synopsis": str(data.get("synopsis", "")).strip(),
        "characters": [c for c in (data.get("characters") or []) if isinstance(c, dict)],
        "beats": beats,
    }
    if not outline["title"]["english"]:
        outline["title"]["english"] = req.topic.strip()[:60]
    return outline


# ------------------------------------------------------------------------ writing a chunk
def _line_from_raw(raw: dict, primary_name: str) -> dict:
    return normalize_line(
        {
            "primary": raw.get(primary_name) or raw.get("primary") or "",
            "hanzi": raw.get("hanzi") or "",
            "english": raw.get("english") or "",
        }
    )


def _feedback(lines: list[dict], names, want: int, track: str) -> str:
    notes = []
    if abs(len(lines) - want) > max(2, round(0.12 * want)):
        notes.append(f"You wrote {len(lines)} lines but exactly {want} are required.")
    shown = 0
    for i, ln in enumerate(lines, 1):
        errs = [x for x in validate_line(track, ln, names) if x.level == "error"]
        if errs and shown < 6:
            notes.append(f"Line {i} ({ln['hanzi'][:20]}): {errs[0].msg}")
            shown += 1
    return "\n".join(notes)


def write_chunk(ctx: Ctx, req: StoryRequest, system: str, outline: dict, beat: int, want: int,
                done: list[dict], names) -> list[dict]:
    track = TRACKS[req.track]
    best: tuple[tuple[int, int], list[dict]] | None = None
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ctx.check()
        prompt = prompts.chunk_prompt(req, outline, beat, want, len(done), done[-8:], feedback)
        data = call_json(ctx, system, prompt, max_tokens=min(8000, 600 + 150 * want))
        raw = data.get("lines") if isinstance(data, dict) else None
        raw = [r for r in (raw or []) if isinstance(r, dict)]
        lines = [_line_from_raw(r, track.primary_name) for r in raw]
        lines = [ln for ln in lines if ln["hanzi"] or ln["primary"]]
        if len(lines) > want * 1.3:
            lines = lines[: int(want * 1.3)]

        bad = sum(1 for ln in lines if any(i.level == "error" for i in validate_line(req.track, ln, names)))
        count_ok = abs(len(lines) - want) <= max(2, round(0.12 * want))
        score = (0 if count_ok else 1, bad)
        if lines and (best is None or score < best[0]):
            best = (score, lines)
        if count_ok and bad <= max(0, int(0.1 * len(lines))):
            return lines
        ctx.usage.retries += 1
        feedback = _feedback(lines, names, want, req.track)
    if best is None:
        raise LLMError("The AI returned no usable lines for one part of the story.")
    return best[1]


def repair_lines(ctx: Ctx, track: str, lines: list[dict], names) -> list[dict]:
    """Last line of defence: rebuild pinyin from the hanzi for lines that still fail the checker."""
    if track != "pinyin":
        return lines
    for ln in lines:
        codes = {i.code for i in validate_line(track, ln, names) if i.level == "error"}
        if codes & REPAIRABLE:
            ln["primary"] = pinyin_from_hanzi(ln["hanzi"], names)
            ctx.usage.repaired_lines += 1
    return lines


# ------------------------------------------------------------------------ the whole story
def generate_story(
    req: StoryRequest,
    provider: Provider,
    progress: Callable[[dict], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Story:
    ctx = Ctx(provider=provider, progress=progress or (lambda _p: None), cancelled=cancelled or (lambda: False))
    target = req.target_lines()
    system = prompts.system_prompt(req)

    ctx.progress({"stage": "outline", "message": "Planning the story...", "done_lines": 0, "total_lines": target})
    outline = make_outline(ctx, req, system)
    names = names_from_outline(outline)
    counts = split_counts(target, len(outline["beats"]))

    all_lines: list[dict] = []
    for i, want in enumerate(counts):
        ctx.progress({
            "stage": "writing",
            "message": f"Writing part {i + 1} of {len(counts)}...",
            "done_lines": len(all_lines),
            "total_lines": target,
        })
        all_lines.extend(write_chunk(ctx, req, system, outline, i, want, all_lines, names))

    ctx.progress({"stage": "checking", "message": "Checking pinyin and characters...", "done_lines": len(all_lines), "total_lines": target})
    all_lines = repair_lines(ctx, req.track, all_lines, names)

    title = {k: v for k, v in outline["title"].items()}
    title_line = normalize_line(title)
    if req.track == "pinyin" and title_line["hanzi"]:
        if any(i.level == "error" for i in check_pinyin(title_line["hanzi"], title_line["primary"], names)) or not title_line["primary"]:
            title_line["primary"] = pinyin_from_hanzi(title_line["hanzi"], names)
            ctx.usage.repaired_lines += 1

    story = Story(
        id=new_id(title_line["english"] or req.topic),
        track=req.track,
        title=Title(**title_line),
        lines=[Line(n=i, **ln) for i, ln in enumerate(all_lines, 1)],
        level=req.level,
        length=req.length,
        target_lines=target,
        topic=req.topic.strip(),
        voice=req.voice,
        source_mode=req.source_mode,
        notes=req.notes.strip(),
        synopsis=outline.get("synopsis", ""),
        characters=[
            {"english": str(c.get("english", "")), "hanzi": str(c.get("hanzi", "")), "primary": str(c.get("primary", ""))}
            for c in outline.get("characters", [])
        ],
        provider=provider.label,
        model=provider.model,
        created=now_iso(),
        usage=ctx.usage.as_dict(),
    )
    save_story(story)
    ctx.progress({"stage": "done", "message": "Done.", "done_lines": len(all_lines), "total_lines": target, "story_id": story.id})
    return story


# ------------------------------------------------------------------------ ideas
def generate_ideas(track: str, theme: str, count: int, provider: Provider, existing_titles: list[str]) -> list[dict]:
    ctx = Ctx(provider=provider)
    data = call_json(
        ctx,
        prompts.ideas_system(track),
        prompts.ideas_prompt(track, theme, count, existing_titles),
        max_tokens=2500,
        temperature=1.0,
    )
    ideas = []
    for it in data.get("ideas") or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        mode = it.get("source_mode") if it.get("source_mode") in SOURCE_MODES else "auto"
        voice = it.get("voice") if it.get("voice") in VOICES else "auto"
        ideas.append({"title": str(it["title"]).strip(), "pitch": str(it.get("pitch", "")).strip(),
                      "source_mode": mode, "voice": voice})
    if not ideas:
        raise LLMError("The AI returned no ideas.")
    return ideas[:count]
