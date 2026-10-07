"""A tiny fake of the Anthropic and OpenAI-style HTTP APIs, so the real client code can be tested
without keys or network. The 'brain' is the offline MockProvider."""
from __future__ import annotations

import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.providers.mock import MockProvider

_brain = MockProvider("fake", "fake")


def build_app(log: list, behaviour: dict) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/messages")
    async def anthropic_messages(req: Request):
        body = await req.json()
        log.append(("anthropic", dict(req.headers), body))
        user = body["messages"][0]["content"]
        out = _brain.complete("", user)
        return {
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": out.text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 11, "output_tokens": 22},
        }

    @app.post("/v1/chat/completions")
    async def openai_chat(req: Request):
        body = await req.json()
        log.append(("openai", dict(req.headers), body))
        if behaviour.get("openai_rate_limit_once") and not behaviour.get("_limited"):
            behaviour["_limited"] = True
            return JSONResponse({"error": "slow down"}, status_code=429, headers={"retry-after": "0"})
        if behaviour.get("openai_reject_response_format") and "response_format" in body:
            return JSONResponse({"error": {"message": "response_format is not supported"}}, status_code=400)
        user = body["messages"][1]["content"]
        out = _brain.complete("", user)
        return {"choices": [{"message": {"role": "assistant", "content": out.text}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 9}}

    return app


class FakeServer:
    def __init__(self, port: int):
        self.log: list = []
        self.behaviour: dict = {}
        self.port = port
        config = uvicorn.Config(build_app(self.log, self.behaviour), host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)
