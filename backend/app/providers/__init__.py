from __future__ import annotations

from ..config import PROVIDERS, cli_unavailable_reason
from .base import LLMError, LLMResult, Provider


def get_provider(provider_id: str, model: str | None = None) -> Provider:
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        raise LLMError(f"Unknown provider '{provider_id}'.")
    chosen_model = (model or "").strip() or spec.model()

    if spec.kind == "mock":
        from .mock import MockProvider

        return MockProvider(spec.label, chosen_model)

    if spec.kind == "cli":
        reason = cli_unavailable_reason()
        if reason:
            raise LLMError(reason)
        from .claude_code import ClaudeCodeProvider

        return ClaudeCodeProvider(spec.label, chosen_model)

    if spec.needs_key and not spec.api_key():
        raise LLMError(
            f"{spec.label} has no API key yet. Add {spec.key_env}=... to the .env file and restart the app."
        )

    if spec.kind == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(spec.label, chosen_model, spec.api_key() or "")

    if spec.kind == "openai":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(spec.label, chosen_model, spec.url() or "", spec.api_key(), spec.max_tokens_factor)

    raise LLMError(f"Provider kind '{spec.kind}' is not supported.")


__all__ = ["get_provider", "LLMError", "LLMResult", "Provider"]
