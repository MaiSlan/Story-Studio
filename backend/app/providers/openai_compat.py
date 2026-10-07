from __future__ import annotations

import time

import httpx

from .base import LLMError, LLMResult, Provider


class OpenAICompatProvider(Provider):
    """Works with anything that speaks the OpenAI "chat completions" protocol:
    Groq, OpenAI, xAI, OpenRouter, Together, Mistral, a local Ollama or LM Studio server, ..."""

    def __init__(self, label: str, model: str, base_url: str, api_key: str | None, max_tokens_factor: float = 1.0):
        super().__init__(label, model)
        self.max_tokens_factor = max_tokens_factor
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, system, user, *, max_tokens=4096, temperature=0.8, json_mode=True) -> LLMResult:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": int(max_tokens * self.max_tokens_factor),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"

        last_err = ""
        adjusted: set[str] = set()
        for attempt in range(6):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=240.0)
            except httpx.HTTPError as exc:
                last_err = f"network error: {exc}"
                time.sleep(min(2 ** attempt, 20))
                continue

            if resp.status_code == 200:
                data = resp.json()
                try:
                    text = (data["choices"][0]["message"]["content"] or "").strip()
                except (KeyError, IndexError, TypeError) as exc:
                    raise LLMError(f"{self.label}: unexpected response shape: {str(data)[:300]}") from exc
                if not text:
                    raise LLMError(f"{self.label} returned an empty answer.")
                usage = data.get("usage") or {}
                return LLMResult(
                    text=text,
                    input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    output_tokens=int(usage.get("completion_tokens", 0) or 0),
                )

            body = resp.text[:500]
            low = body.lower()
            if resp.status_code in (401, 403):
                raise LLMError(f"{self.label} rejected the API key ({resp.status_code}). Check your .env file.")
            if resp.status_code == 404:
                raise LLMError(f"{self.label}: model or endpoint not found ({self.model}). {body}")
            if resp.status_code == 400:
                # Adapt once to provider quirks, then retry immediately.
                if "response_format" in low and "response_format" in payload and "rf" not in adjusted:
                    payload.pop("response_format")
                    adjusted.add("rf")
                    continue
                if "max_completion_tokens" in low and "max_tokens" in payload and "mct" not in adjusted:
                    payload["max_completion_tokens"] = payload.pop("max_tokens")
                    adjusted.add("mct")
                    continue
                if "temperature" in low and "temperature" in payload and "temp" not in adjusted:
                    payload.pop("temperature")
                    adjusted.add("temp")
                    continue
                raise LLMError(f"{self.label}: bad request. {body}")
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = resp.headers.get("retry-after")
                try:
                    delay = min(float(wait), 60.0) if wait else min(2 ** attempt * 2, 30)
                except ValueError:
                    delay = 5.0
                last_err = f"HTTP {resp.status_code}: {body[:200]}"
                time.sleep(delay)
                continue
            raise LLMError(f"{self.label}: HTTP {resp.status_code}: {body}")

        raise LLMError(f"{self.label} kept failing ({last_err}).")
