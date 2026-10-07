"""Central settings. Everything is read from environment variables or a .env file.

Copy .env.example to .env and fill in the keys you want to use. Keys never leave
your machine except in the calls to the AI provider you choose.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("STORY_DATA_DIR", ROOT / "data"))
STORIES_DIR = DATA_DIR / "stories"
PDF_DIR = DATA_DIR / "pdf"
STYLE_DIR = ROOT / "style"
FONT_DIR = ROOT / "fonts"
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", ROOT.parent / "frontend"))  # only served when it exists


def build_id() -> str:
    """A short fingerprint of the code and the style guides actually running.
    /api/health reports it, so you can tell at a glance whether a deploy really picked up your changes."""
    h = hashlib.sha256()
    for f in sorted(list((ROOT / "app").rglob("*.py")) + list(STYLE_DIR.glob("*.md"))):
        h.update(f.name.encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (KEY=value per line). Real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

for _d in (STORIES_DIR, PDF_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ProviderSpec:
    """How to reach one AI provider. `kind` picks the client implementation."""

    id: str
    label: str
    kind: str  # "anthropic" | "openai" | "cli" | "mock"
    key_env: str | None
    model_env: str
    default_model: str
    base_url: str | None = None
    base_url_env: str | None = None
    needs_key: bool = True
    model_suggestions: tuple[str, ...] = ()
    note: str = ""
    max_tokens_factor: float = 1.0  # >1 for "thinking" models whose reasoning counts against max_tokens

    def api_key(self) -> str | None:
        return os.environ.get(self.key_env) if self.key_env else None

    def model(self) -> str:
        return os.environ.get(self.model_env, self.default_model)

    def url(self) -> str | None:
        if self.base_url_env and os.environ.get(self.base_url_env):
            return os.environ[self.base_url_env]
        return self.base_url

    def configured(self) -> bool:
        if self.kind == "mock":
            return True
        if self.kind == "cli":
            return cli_unavailable_reason() is None
        if self.needs_key:
            return bool(self.api_key())
        return True  # e.g. a local Ollama server needs no key


def cli_unavailable_reason() -> str | None:
    """The 'Claude login' provider drives the Claude Code program installed on THIS computer.
    It is only offered when the backend itself runs on your own machine (see README: Anthropic does not allow
    hosted apps to route requests through a Claude subscription)."""
    if HOSTED or HOST not in ("127.0.0.1", "localhost", "::1"):
        return ("This backend runs in the cloud, and a Claude plan may only be used from your own computer. "
                "To use this option, run the backend on your machine (python run.py) and open http://127.0.0.1:8000. "
                "The other AI services work from anywhere.")
    if not shutil.which(os.environ.get("CLAUDE_BIN", "claude")):
        return ("Claude Code is not installed on this computer. It is the command-line program, separate from the "
                "Claude desktop app: install it from https://claude.com/product/claude-code, then run `claude` once "
                "in a terminal and sign in with your Claude account.")
    return None


# Add your own provider by appending a ProviderSpec here. Anything that speaks the
# "OpenAI chat completions" protocol works with kind="openai" and a base_url.
PROVIDERS: dict[str, ProviderSpec] = {
    p.id: p
    for p in [
        ProviderSpec(
            id="anthropic",
            label="Claude (Anthropic API)",
            kind="anthropic",
            key_env="ANTHROPIC_API_KEY",
            model_env="ANTHROPIC_MODEL",
            default_model="claude-sonnet-5-5",
            model_suggestions=("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"),
            note="Strongest pinyin/hanzi accuracy in my experience; billed per token via console.anthropic.com.",
        ),
        ProviderSpec(
            id="groq",
            label="Groq (fast open models)",
            kind="openai",
            key_env="GROQ_API_KEY",
            model_env="GROQ_MODEL",
            default_model="openai/gpt-oss-120b",
            base_url="https://api.groq.com/openai/v1",
            model_suggestions=("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"),
            note="Groq (with a Q) hosts open models very fast. Its free tier dropped the Llama models in August 2026; gpt-oss-120b is the strongest one still free. Free limits are low (about 8k tokens a minute), so long stories pause between parts. Model names change: check console.groq.com/docs/models.",
        ),
        ProviderSpec(
            id="gemini",
            label="Google Gemini (free tier)",
            kind="openai",
            key_env="GEMINI_API_KEY",
            model_env="GEMINI_MODEL",
            default_model="gemini-3.8-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model_suggestions=("gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"),
            max_tokens_factor=2.0,
            note="Free key from aistudio.google.com. On the free tier Google may use your prompts to improve its products; check the limits shown in AI Studio.",
        ),
        ProviderSpec(
            id="openai",
            label="OpenAI",
            kind="openai",
            key_env="OPENAI_API_KEY",
            model_env="OPENAI_MODEL",
            default_model="gpt-4.1",
            base_url="https://api.openai.com/v1",
            model_suggestions=("gpt-4.1", "gpt-4.1-mini"),
        ),
        ProviderSpec(
            id="xai",
            label="xAI (Grok, with a K)",
            kind="openai",
            key_env="XAI_API_KEY",
            model_env="XAI_MODEL",
            default_model="grok-4",
            base_url="https://api.x.ai/v1",
        ),
        ProviderSpec(
            id="openrouter",
            label="OpenRouter (many models, one key)",
            kind="openai",
            key_env="OPENROUTER_API_KEY",
            model_env="OPENROUTER_MODEL",
            default_model="qwen/qwen-2.5-72b-instruct",
            base_url="https://openrouter.ai/api/v1",
        ),
        ProviderSpec(
            id="ollama",
            label="Ollama (runs on your own computer, free)",
            kind="openai",
            key_env=None,
            model_env="OLLAMA_MODEL",
            default_model="qwen2.5:14b",
            base_url="http://localhost:11434/v1",
            base_url_env="OLLAMA_BASE_URL",
            needs_key=False,
            note="Local models are free but make more pinyin mistakes; the checker will flag them.",
        ),
        ProviderSpec(
            id="claude_code",
            label="Claude via your Claude app login (this computer only)",
            kind="cli",
            key_env=None,
            model_env="CLAUDE_CODE_MODEL",
            default_model="sonnet",
            needs_key=False,
            model_suggestions=("sonnet", "opus", "haiku"),
            note="Uses the Claude Code program on your own computer, signed in with your own Claude plan. No API key, but it counts against your plan's usage limits. Not available on a hosted server.",
        ),
        ProviderSpec(
            id="mock",
            label="Demo (offline, no AI, nonsense stories)",
            kind="mock",
            key_env=None,
            model_env="MOCK_MODEL",
            default_model="demo",
            needs_key=False,
            note="Lets you try the whole app without any API key.",
        ),
    ]
}


def default_provider_id() -> str:
    wanted = os.environ.get("DEFAULT_PROVIDER")
    if wanted in PROVIDERS and PROVIDERS[wanted].configured():
        return wanted
    for pid in ("anthropic", "gemini", "groq", "openai", "xai", "openrouter"):
        if PROVIDERS[pid].configured():
            return pid
    return "mock"


# Optional password for the web UI. Set APP_PASSWORD when you put the app online,
# because anyone who can open it can spend your API credit.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
# Origins allowed to call the API from a browser (your Vercel site), comma separated, e.g.
# ALLOWED_ORIGINS=https://story-studio.vercel.app   (ALLOWED_ORIGIN_REGEX=https://.*\.vercel\.app for previews)
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
ALLOWED_ORIGIN_REGEX = os.environ.get("ALLOWED_ORIGIN_REGEX") or None
# Set by the Dockerfile and by modal_app.py: this process is a server, not someone's own computer.
HOSTED = os.environ.get("HOSTED", "").strip().lower() in ("1", "true", "yes")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
