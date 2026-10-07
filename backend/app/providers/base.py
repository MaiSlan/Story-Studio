from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(RuntimeError):
    """Raised when a provider call fails in a way the user should read."""


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Provider(ABC):
    """One thin method: send a system prompt + user prompt, get text back.

    Everything else (outlines, chunking, validation) lives in generator.py, so adding a new AI
    provider means writing just this one method.
    """

    def __init__(self, label: str, model: str):
        self.label = label
        self.model = model

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.8,
        json_mode: bool = True,
    ) -> LLMResult: ...
