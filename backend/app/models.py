from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .tracks import LENGTHS, MAX_LINES, MIN_LINES, SOURCE_MODES, TRACKS, VOICES


class StoryRequest(BaseModel):
    track: str = "pinyin"
    topic: str = Field(..., min_length=3, max_length=2000)
    length: str = "medium"
    custom_lines: Optional[int] = None
    level: int = 2
    voice: str = "auto"
    source_mode: str = "auto"
    notes: str = ""
    provider: str = "mock"
    model: Optional[str] = None

    @field_validator("track")
    @classmethod
    def _track(cls, v: str) -> str:
        if v not in TRACKS:
            raise ValueError(f"unknown track {v!r}")
        return v

    @field_validator("length")
    @classmethod
    def _length(cls, v: str) -> str:
        if v not in LENGTHS:
            raise ValueError(f"unknown length {v!r}")
        return v

    @field_validator("level")
    @classmethod
    def _level(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("level must be 1-5")
        return v

    @field_validator("voice")
    @classmethod
    def _voice(cls, v: str) -> str:
        if v not in VOICES:
            raise ValueError(f"unknown voice {v!r}")
        return v

    @field_validator("source_mode")
    @classmethod
    def _source(cls, v: str) -> str:
        if v not in SOURCE_MODES:
            raise ValueError(f"unknown source_mode {v!r}")
        return v

    def target_lines(self) -> int:
        if self.length == "custom":
            n = self.custom_lines or LENGTHS["medium"]["lines"]
        else:
            n = LENGTHS[self.length]["lines"]
        return max(MIN_LINES, min(MAX_LINES, int(n)))


class Line(BaseModel):
    n: int
    primary: str
    hanzi: str
    english: str


class Title(BaseModel):
    primary: str = ""
    hanzi: str = ""
    english: str = ""


class Story(BaseModel):
    id: str
    track: str
    title: Title
    lines: list[Line]
    level: int = 2
    length: str = "medium"
    target_lines: int = 0
    topic: str = ""
    voice: str = "auto"
    source_mode: str = "auto"
    notes: str = ""
    synopsis: str = ""
    characters: list[dict] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    created: str = ""
    updated: str = ""
    usage: dict = Field(default_factory=dict)


class IdeasRequest(BaseModel):
    track: str = "pinyin"
    theme: str = ""
    count: int = Field(8, ge=3, le=15)
    provider: str = "mock"
    model: Optional[str] = None


class LineEdit(BaseModel):
    n: int
    primary: str
    hanzi: str
    english: str


class StoryEdit(BaseModel):
    title: Title
    lines: list[LineEdit]
