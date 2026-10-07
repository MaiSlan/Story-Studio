"""Use YOUR OWN Claude login (Claude Pro/Max) through the official Claude Code program, on your own computer.

How it works: for every call the app runs the `claude` command in print mode, exactly as you could type it
in a terminal:  claude -p --model sonnet ...  The prompt goes in through standard input, the answer comes
back as JSON. The app never sees, copies or stores your login; Claude Code keeps that to itself.

Rules of the road (Anthropic's terms for Claude Code subscriptions):
  * Only for personal use on the computer where you are signed in to Claude Code yourself.
  * It must never be offered on a public server or shared with other people, which is why this provider
    refuses to run unless the app listens on localhost (see config.cli_unavailable_reason).
  * It uses up your normal Claude usage allowance, and it is slower than a direct API call.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

from .base import LLMError, LLMResult, Provider

# Command lines have a length limit (about 32k characters on Windows). Longer instructions go in with the prompt.
MAX_SYSTEM_ARG_CHARS = 20_000
TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_CODE_TIMEOUT", "420"))

# If these are set, Claude Code would bill the API instead of using your subscription. Remove them for the child.
_API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_STUB_SYSTEM = (
    "You are the writing engine of a story-making tool. Follow the instructions in the user message exactly "
    "and answer only with what they ask for (no preamble, no markdown fences, no commentary)."
)


class ClaudeCodeProvider(Provider):
    def __init__(self, label: str, model: str):
        super().__init__(label, model)
        self.binary = shutil.which(os.environ.get("CLAUDE_BIN", "claude")) or ""
        if not self.binary:
            raise LLMError("Claude Code is not installed on this computer.")

    # ------------------------------------------------------------------ helpers
    def _command(self, system: str) -> list[str]:
        return [
            self.binary,
            "-p",
            "--output-format", "json",
            "--model", self.model,
            "--system-prompt", system,
            "--tools", "",  # a pure text task: no file or shell access at all
            "--no-session-persistence",
            "--setting-sources", "",  # ignore any hooks / settings of your other projects
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]

    def complete(self, system, user, *, max_tokens=4096, temperature=0.8, json_mode=True) -> LLMResult:
        if len(system) > MAX_SYSTEM_ARG_CHARS:
            stdin_text = f"{system}\n\n---\n\n{user}"
            system_arg = _STUB_SYSTEM
        else:
            stdin_text, system_arg = user, system

        env = {k: v for k, v in os.environ.items() if k not in _API_ENV}
        with tempfile.TemporaryDirectory(prefix="story-studio-") as workdir:  # nothing of yours is in here
            try:
                proc = subprocess.run(
                    self._command(system_arg),
                    input=stdin_text,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=TIMEOUT_SECONDS,
                    cwd=workdir,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMError(f"Claude Code took longer than {TIMEOUT_SECONDS} seconds. Try again, or use a shorter story.") from exc
            except OSError as exc:
                raise LLMError(f"Could not start Claude Code: {exc}") from exc

        return self._parse(proc)

    def _parse(self, proc: subprocess.CompletedProcess) -> LLMResult:
        out = (proc.stdout or "").strip()
        data = None
        if out:
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                data = None
        if isinstance(data, list):  # some versions return the whole event list
            data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)

        if not isinstance(data, dict):
            detail = (proc.stderr or out or "no output").strip()[:400]
            raise LLMError(self._explain(f"Claude Code gave an unreadable answer (exit code {proc.returncode}): {detail}"))

        result = str(data.get("result") or "").strip()
        if data.get("is_error") or proc.returncode != 0:
            raise LLMError(self._explain(result or (proc.stderr or "").strip()[:400] or "Claude Code reported an error."))
        if not result:
            raise LLMError("Claude Code returned an empty answer.")

        usage = data.get("usage") or {}
        tokens_in = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
        return LLMResult(text=result, input_tokens=tokens_in, output_tokens=int(usage.get("output_tokens", 0) or 0))

    @staticmethod
    def _explain(message: str) -> str:
        low = message.lower()
        if "login" in low or "not logged" in low or "authenticat" in low or "401" in low:
            return (
                "Claude Code is not signed in. Open a terminal, run `claude`, sign in with your Claude account, "
                f"then try again. (Details: {message[:200]})"
            )
        if "usage limit" in low or "rate limit" in low or "limit reached" in low:
            return f"Your Claude usage limit is reached for now. Wait for it to reset, or pick another AI. ({message[:200]})"
        return f"Claude Code error: {message[:400]}"
