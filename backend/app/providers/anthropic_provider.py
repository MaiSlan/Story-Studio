from __future__ import annotations

from .base import LLMError, LLMResult, Provider


class AnthropicProvider(Provider):
    def __init__(self, label: str, model: str, api_key: str):
        super().__init__(label, model)
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'anthropic' package is not installed (pip install anthropic).") from exc
        self._anthropic = anthropic
        # ANTHROPIC_BASE_URL (if set) is picked up by the SDK itself.
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=180.0)

    def complete(self, system, user, *, max_tokens=4096, temperature=0.8, json_mode=True) -> LLMResult:
        a = self._anthropic
        # NB: current Claude models do not take a sampling `temperature` through the SDK, so none is sent.
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            # Cache the (long, identical) style-guide prompt across the chunk calls of one story.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        try:
            msg = self.client.messages.create(**kwargs)
        except a.AuthenticationError as exc:
            raise LLMError("Anthropic rejected the API key (check ANTHROPIC_API_KEY in .env).") from exc
        except a.NotFoundError as exc:
            raise LLMError(f"Anthropic does not know the model '{self.model}'. Check ANTHROPIC_MODEL.") from exc
        except a.RateLimitError as exc:
            raise LLMError("Anthropic rate limit reached; wait a minute and retry.") from exc
        except a.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        if not text:
            raise LLMError("Anthropic returned an empty answer.")
        usage = getattr(msg, "usage", None)
        return LLMResult(
            text=text,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0)
            + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
