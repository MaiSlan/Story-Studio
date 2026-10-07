"""One JSON file per story in data/stories/ (the same idea as one data file per story before)."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import PDF_DIR, STORIES_DIR
from .models import Story


# Hosts with a network disk (Modal volumes) register a function here that flushes writes.
AFTER_WRITE: list[Callable[[], None]] = []


def _notify() -> None:
    for fn in AFTER_WRITE:
        try:
            fn()
        except Exception as exc:  # never lose a story because a flush failed
            print("storage flush failed:", exc)


def seed_if_empty(src: Path) -> int:
    """Copy the sample stories into an empty data folder (first start on a fresh server)."""
    if any(STORIES_DIR.glob("*.json")) or not src.exists():
        return 0
    n = 0
    for f in src.glob("*.json"):
        shutil.copy(f, STORIES_DIR / f.name)
        n += 1
    return n


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:48] or "story"


def new_id(title: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d')}-{slugify(title)}-{uuid.uuid4().hex[:4]}"


def _path(story_id: str):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", story_id):
        raise KeyError(story_id)
    return STORIES_DIR / f"{story_id}.json"


def save_story(story: Story) -> None:
    story.updated = now_iso()
    _path(story.id).write_text(story.model_dump_json(indent=2), encoding="utf-8")
    pdf = PDF_DIR / f"{story.id}.pdf"
    if pdf.exists():
        pdf.unlink()  # cached PDF is stale after any edit
    _notify()


def load_story(story_id: str) -> Story:
    p = _path(story_id)
    if not p.exists():
        raise KeyError(story_id)
    return Story.model_validate_json(p.read_text(encoding="utf-8"))


def list_stories() -> list[dict]:
    out = []
    for p in sorted(STORIES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(
            {
                "id": data["id"],
                "track": data.get("track", "pinyin"),
                "title": data.get("title", {}),
                "level": data.get("level"),
                "length": data.get("length"),
                "lines": len(data.get("lines", [])),
                "topic": data.get("topic", ""),
                "provider": data.get("provider", ""),
                "model": data.get("model", ""),
                "created": data.get("created", ""),
            }
        )
    out.sort(key=lambda s: s["created"], reverse=True)
    return out


def delete_story(story_id: str) -> None:
    p = _path(story_id)
    if not p.exists():
        raise KeyError(story_id)
    p.unlink()
    pdf = PDF_DIR / f"{story_id}.pdf"
    if pdf.exists():
        pdf.unlink()
    _notify()
