"""Builds the prompts sent to the AI. The *rules* live in the editable files in style/;
this module only assembles them and defines the exact JSON shape asked for on each task.

Every user prompt starts with machine-readable header lines (TASK:, TRACK:, ...). Real models
just read them as part of the instructions; the offline demo provider uses them to answer.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .config import STYLE_DIR
from .models import StoryRequest
from .tracks import SOURCE_MODES, TRACKS, VOICES


def _read(name: str) -> str:
    return (STYLE_DIR / name).read_text(encoding="utf-8").strip()


def _sections(name: str) -> dict[str, str]:
    """Parse a markdown file made of '## key' sections."""
    text = _read(name)
    parts = re.split(r"^## +(\w+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def system_prompt(req: StoryRequest) -> str:
    """Style guide + level + voice + source mode. Identical for all calls of one story, so it can be cached."""
    track = TRACKS[req.track]
    voices = _sections("voices.md")
    modes = _sections("source_modes.md")
    return "\n\n".join(
        [
            _read("common.md"),
            _read(f"{req.track}_track.md"),
            "LEVEL\n" + track.levels[req.level],
            f"VOICE ({VOICES[req.voice]})\n" + voices[req.voice],
            f"SOURCE MODE ({SOURCE_MODES[req.source_mode]})\n" + modes[req.source_mode],
        ]
    )


def ideas_system(track_id: str) -> str:
    modes = _sections("source_modes.md")
    voices = _sections("voices.md")
    return "\n\n".join(
        [
            "You are a creative editor who proposes story ideas for a graded-reader series for language learners.",
            _read("interests.md"),
            "SOURCE MODES you can recommend:\n" + "\n".join(f"- {k}: {modes[k].splitlines()[0]}" for k in modes if k != "auto"),
            "VOICES you can recommend:\n" + "\n".join(f"- {k}: {voices[k].splitlines()[0]}" for k in voices if k != "auto"),
            "Reply with ONE JSON object and nothing else. Ideas must be varied (different worlds, moods and "
            "shapes), concrete enough to start writing immediately, and suitable for short stories of simple sentences. "
            "Apply the standing rule: licensed pop-culture worlds must be recommended with source_mode 'lore_only'.",
        ]
    )


# --------------------------------------------------------------------------- user prompts
def ideas_prompt(track_id: str, theme: str, count: int, existing_titles: list[str]) -> str:
    track = TRACKS[track_id]
    already = "\n".join(f"- {t}" for t in existing_titles[:60]) or "(nothing yet)"
    return (
        f"TASK: ideas\nTRACK: {track_id}\nCOUNT: {count}\n\n"
        f"The stories are for the track: {track.label}.\n"
        f"The learner's thoughts or mood for today (may be empty): {theme.strip() or '(none: surprise me)'}\n\n"
        f"Stories already written, do not repeat them:\n{already}\n\n"
        f"Propose exactly {count} ideas. Return JSON:\n"
        '{"ideas": [{"title": "English working title", "pitch": "two sentences: who, what happens, why it is a good '
        'read", "source_mode": "original|myth|lore_only|adaptation", "voice": "ancient_tale|storyteller|chronicle|'
        'fairytale|faithful"}]}'
    )


def outline_prompt(req: StoryRequest, n_beats: int) -> str:
    track = TRACKS[req.track]
    p = track.primary_name
    notes = f"\nExtra notes from the learner: {req.notes.strip()}" if req.notes.strip() else ""
    return (
        f"TASK: outline\nTRACK: {req.track}\nBEATS_REQUIRED: {n_beats}\nTOTAL_LINES: {req.target_lines()}\n\n"
        f"Plan a story for the learner. Topic: {req.topic.strip()}{notes}\n\n"
        f"The finished story will have about {req.target_lines()} lines, written later in {n_beats} parts. "
        "Plan now; do not write the story yet.\n"
        f"- title: a short title in {track.primary_label}, in simplified hanzi, and in English.\n"
        "- synopsis: 2-3 sentences in English.\n"
        f"- characters: everyone who is named. For each give the English name, the hanzi name and the "
        f'"{p}" spelling that must be used everywhere'
        + (' (pinyin with tone marks, capitalised, e.g. "Sūn Wùkōng")' if req.track == "pinyin" else " (the French form)")
        + ".\n"
        f"- beats: exactly {n_beats} beats of roughly equal weight, each one or two English sentences. Beat 1 opens "
        "the story, the beats build a single arc with a turn, and the last beat ends the story with a strong final image. "
        "For adaptations the beats follow the source's order of events.\n\n"
        "Return JSON:\n"
        f'{{"title": {{"primary": "...", "hanzi": "...", "english": "..."}}, "synopsis": "...", '
        '"characters": [{"english": "...", "hanzi": "...", "primary": "..."}], '
        '"beats": [{"summary": "..."}]}'
    )


def chunk_prompt(
    req: StoryRequest,
    outline: dict,
    beat_index: int,
    n_lines: int,
    lines_done: int,
    recent: list[dict],
    feedback: str = "",
) -> str:
    track = TRACKS[req.track]
    p = track.primary_name
    beats = outline["beats"]
    n_beats = len(beats)
    title = outline["title"]
    chars = "\n".join(
        f"- {c.get('english', '')} = {c.get('hanzi', '')} = {c.get('primary', '')}" for c in outline.get("characters", [])
    ) or "(none listed)"
    plan = "\n".join(
        f"{i + 1}. {b['summary']}" + ("   <== WRITE THIS PART NOW" if i == beat_index else "   [already written]" if i < beat_index else "")
        for i, b in enumerate(beats)
    )
    ctx = "\n".join(f"{ln['hanzi']} | {ln['english']}" for ln in recent) or "(this is the very first part)"
    extra = []
    if beat_index == 0:
        extra.append("This is the opening: set the scene and hook the reader in the first lines.")
    if beat_index == n_beats - 1:
        extra.append("This is the final part: bring the story to a satisfying end and finish on a strong last image.")
    else:
        extra.append("Do NOT conclude the story; it continues after this part.")
    if feedback:
        extra.append("PROBLEMS WITH YOUR PREVIOUS ATTEMPT (fix them):\n" + feedback)
    return (
        f"TASK: chunk\nTRACK: {req.track}\nBEAT: {beat_index + 1} of {n_beats}\nLINES_REQUIRED: {n_lines}\n"
        f"LINES_DONE: {lines_done}\n\n"
        f"STORY TITLE: {title.get('english', '')} / {title.get('primary', '')}\n"
        f"SYNOPSIS: {outline.get('synopsis', '')}\n"
        f"CHARACTERS (keep these spellings exactly, English = hanzi = {p}):\n{chars}\n\n"
        f"PLAN:\n{plan}\n\n"
        f"LAST LINES WRITTEN SO FAR (for continuity; do not repeat them):\n{ctx}\n\n"
        f"Write exactly {n_lines} lines for part {beat_index + 1}.\n" + "\n".join(extra) + "\n\n"
        "Return JSON:\n"
        f'{{"lines": [{{"{p}": "...", "hanzi": "...", "english": "..."}}]}}'
    )
