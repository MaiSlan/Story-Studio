"""Web API. The UI is a separate static site (frontend/); it is also served from here when that folder exists."""
from __future__ import annotations

import base64
import secrets
import time

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import jobs, storage
from .config import (
    ALLOWED_ORIGIN_REGEX,
    ALLOWED_ORIGINS,
    APP_PASSWORD,
    FRONTEND_DIR,
    PDF_DIR,
    PROVIDERS,
    default_provider_id,
)
from .generator import generate_ideas
from .models import IdeasRequest, Line, StoryEdit, StoryRequest
from .pdf import render_pdf
from .pinyin_tools import pinyin_from_hanzi
from .providers import LLMError, get_provider
from .tracks import LENGTHS, SOURCE_MODES, TRACKS, VOICES
from .validate import normalize_line, validate_story

app = FastAPI(title="Story Studio")


# ------------------------------------------------------------------ optional password (API only)
def _password_ok(request: Request) -> bool:
    """Accepts `Authorization: Bearer <password>` (the web app) or HTTP Basic (curl / browsers)."""
    header = request.headers.get("authorization", "")
    given = ""
    if header.lower().startswith("bearer "):
        given = header[7:].strip()
    elif header.lower().startswith("basic "):
        try:
            given = base64.b64decode(header[6:]).decode("utf-8").partition(":")[2]
        except Exception:
            given = ""
    return secrets.compare_digest(given.encode("utf-8"), APP_PASSWORD.encode("utf-8"))


@app.middleware("http")
async def password_gate(request: Request, call_next):
    path = request.url.path
    protected = path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS"
    if APP_PASSWORD and protected and not _password_ok(request):
        return JSONResponse({"detail": "Password required"}, status_code=401)
    return await call_next(request)


# Added after the gate so it is the outermost layer: even 401 answers carry CORS headers.
if ALLOWED_ORIGINS or ALLOWED_ORIGIN_REGEX:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_origin_regex=ALLOWED_ORIGIN_REGEX or None,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )


@app.get("/api/health")
def health():
    """No password: lets the UI wake a sleeping server and tell 'offline' from 'wrong password'."""
    return {"ok": True, "password_required": bool(APP_PASSWORD)}


def _story_or_404(story_id: str):
    try:
        return storage.load_story(story_id)
    except KeyError:
        raise HTTPException(404, "Story not found")


def _names(story) -> list[tuple[str, str]]:
    return [(c.get("hanzi", ""), c.get("primary", "")) for c in story.characters if c.get("hanzi") and c.get("primary")]


def _report(story) -> dict:
    return validate_story(story.track, [ln.model_dump() for ln in story.lines], _names(story), story.target_lines)


# ------------------------------------------------------------------ config
@app.get("/api/config")
def config():
    return {
        "tracks": [{"id": t.id, "label": t.label, "primary_label": t.primary_label} for t in TRACKS.values()],
        "levels": {t.id: t.levels for t in TRACKS.values()},
        "lengths": [{"id": k, "label": v["label"], "lines": v["lines"]} for k, v in LENGTHS.items()],
        "voices": [{"id": k, "label": v} for k, v in VOICES.items()],
        "source_modes": [{"id": k, "label": v} for k, v in SOURCE_MODES.items()],
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "configured": p.configured(),
                "model": p.model(),
                "suggestions": list(p.model_suggestions),
                "note": p.note,
                "key_env": p.key_env,
            }
            for p in PROVIDERS.values()
        ],
        "default_provider": default_provider_id(),
    }


@app.post("/api/providers/test")
def test_provider(body: dict):
    try:
        provider = get_provider(body.get("provider", ""), body.get("model"))
        t0 = time.time()
        res = provider.complete("Reply with JSON only.", 'Return exactly {"ok": true}', max_tokens=30, temperature=0, json_mode=True)
        return {"ok": True, "model": provider.model, "seconds": round(time.time() - t0, 1), "reply": res.text[:80]}
    except LLMError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Unexpected error: {exc}"}


# ------------------------------------------------------------------ ideas
@app.post("/api/ideas")
def ideas(req: IdeasRequest):
    try:
        provider = get_provider(req.provider, req.model)
        existing = [s["title"].get("english", "") for s in storage.list_stories()]
        return {"ideas": generate_ideas(req.track, req.theme, req.count, provider, existing)}
    except LLMError as exc:
        raise HTTPException(502, str(exc))


# ------------------------------------------------------------------ jobs
@app.post("/api/jobs")
def create_job(req: StoryRequest):
    # fail fast on missing keys, before a job is created
    try:
        get_provider(req.provider, req.model)
    except LLMError as exc:
        raise HTTPException(400, str(exc))
    job = jobs.start_story_job(req)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    if not jobs.cancel_job(job_id):
        raise HTTPException(404, "Unknown job")
    return {"ok": True}


# ------------------------------------------------------------------ stories
@app.get("/api/stories")
def stories():
    return {"stories": storage.list_stories()}


@app.get("/api/stories/{story_id}")
def story(story_id: str):
    s = _story_or_404(story_id)
    return {"story": s.model_dump(), "validation": _report(s)}


@app.put("/api/stories/{story_id}")
def save_story(story_id: str, edit: StoryEdit):
    s = _story_or_404(story_id)
    title = normalize_line({"primary": edit.title.primary, "hanzi": edit.title.hanzi, "english": edit.title.english})
    s.title = s.title.model_copy(update=title)
    s.lines = [Line(n=i, **normalize_line(ln.model_dump())) for i, ln in enumerate(edit.lines, 1)]
    storage.save_story(s)
    return {"story": s.model_dump(), "validation": _report(s)}


@app.delete("/api/stories/{story_id}")
def delete_story(story_id: str):
    try:
        storage.delete_story(story_id)
    except KeyError:
        raise HTTPException(404, "Story not found")
    return {"ok": True}


@app.post("/api/stories/{story_id}/lines/{n}/repair")
def repair_line(story_id: str, n: int):
    s = _story_or_404(story_id)
    if s.track != "pinyin":
        raise HTTPException(400, "Only pinyin stories have pinyin to rebuild.")
    for ln in s.lines:
        if ln.n == n:
            ln.primary = pinyin_from_hanzi(ln.hanzi, _names(s))
            storage.save_story(s)
            return {"story": s.model_dump(), "validation": _report(s)}
    raise HTTPException(404, "Line not found")


@app.get("/api/stories/{story_id}/pdf")
def story_pdf(story_id: str, scale: float = Query(1.0, ge=0.7, le=1.4), download: bool = False):
    s = _story_or_404(story_id)
    cache = PDF_DIR / f"{story_id}.pdf"
    if scale == 1.0 and cache.exists():
        data = cache.read_bytes()
    else:
        data = render_pdf(s, font_scale=scale)
        if scale == 1.0:
            cache.write_bytes(data)
    name = f"{storage.slugify(s.title.english or s.title.primary)}.pdf"
    disp = "attachment" if download else "inline"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{name}"'})


@app.get("/api/stories/{story_id}/json")
def story_json(story_id: str):
    s = _story_or_404(story_id)
    return JSONResponse(s.model_dump(), headers={"Content-Disposition": f'attachment; filename="{story_id}.json"'})


# ------------------------------------------------------------------ UI (optional)
# On your own computer one process serves both. On Vercel the frontend/ folder is deployed on its own.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:

    @app.get("/")
    def root():
        return {"app": "Story Studio API", "docs": "/docs", "health": "/api/health"}
