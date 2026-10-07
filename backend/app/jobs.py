"""Background jobs. Generating a story takes 30 seconds to several minutes, so the web page
starts a job and polls for progress. Jobs live in memory (fine for a personal tool)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field

from .generator import Cancelled, generate_story
from .models import StoryRequest
from .providers import LLMError, get_provider

_LOCK = threading.Lock()
_JOBS: dict[str, "Job"] = {}
_SLOTS = threading.Semaphore(2)  # at most two stories at once: protects your API budget


@dataclass
class Job:
    id: str
    request: dict
    status: str = "queued"  # queued | running | done | error | cancelled
    stage: str = "queued"
    message: str = "Waiting to start..."
    done_lines: int = 0
    total_lines: int = 0
    story_id: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "cancel"}
        return d


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if not job:
        return False
    job.cancel.set()
    return True


def start_story_job(req: StoryRequest) -> Job:
    job = Job(id=uuid.uuid4().hex[:10], request=req.model_dump(), total_lines=req.target_lines())
    with _LOCK:
        _JOBS[job.id] = job
        for old in sorted(_JOBS.values(), key=lambda j: j.created)[:-60]:
            _JOBS.pop(old.id, None)
    threading.Thread(target=_run, args=(job, req), daemon=True).start()
    return job


def _run(job: Job, req: StoryRequest) -> None:
    with _SLOTS:
        if job.cancel.is_set():
            job.status, job.message = "cancelled", "Cancelled."
            return
        job.status = "running"
        try:
            provider = get_provider(req.provider, req.model)

            def progress(p: dict) -> None:
                job.stage = p.get("stage", job.stage)
                job.message = p.get("message", job.message)
                job.done_lines = p.get("done_lines", job.done_lines)
                job.total_lines = p.get("total_lines", job.total_lines)
                if p.get("story_id"):
                    job.story_id = p["story_id"]

            story = generate_story(req, provider, progress=progress, cancelled=job.cancel.is_set)
            job.story_id = story.id
            job.status, job.stage, job.message = "done", "done", "Done."
            job.done_lines = len(story.lines)
        except Cancelled:
            job.status, job.message = "cancelled", "Cancelled. Nothing was saved."
        except LLMError as exc:
            job.status, job.error, job.message = "error", str(exc), "Failed."
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            job.status, job.error, job.message = "error", f"Unexpected error: {exc}", "Failed."
