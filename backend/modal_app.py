"""Run the Story Studio API on Modal (https://modal.com) - free Starter plan credits are enough for personal use.

One-time setup (from the backend/ folder). If the `modal` command is "not recognized" (common on Windows),
write `python -m modal` instead of `modal` everywhere below.
    pip install modal python-dotenv
    modal setup                                   # sign in, opens the browser
    # put GEMINI_API_KEY, GROQ_API_KEY, APP_PASSWORD, ALLOWED_ORIGINS in a file called modal.env, then:
    modal secret create story-studio --from-dotenv modal.env --force
    modal deploy modal_app.py                     # prints the public URL -> put it in frontend/config.js

Stories are kept on a Modal Volume mounted at /data, so they survive restarts and redeploys.
The first two sample stories are copied in the first time, when the volume is still empty.
"""
from pathlib import Path

import modal

HERE = Path(__file__).parent


def _skip_upload(path: Path) -> bool:
    """True = this file stays on your computer. An allow-list, so a stray .env, modal.env or .venv can never be uploaded.
    `path` is relative to backend/. It works the same on Windows, because it only looks at path parts."""
    parts = path.parts
    if not parts:
        return False
    if "__pycache__" in parts or path.suffix == ".pyc":
        return True
    if parts[0] in ("app", "style", "fonts"):
        return False
    if parts[0] == "data":  # only the two sample stories, never generated PDFs
        return len(parts) > 1 and parts[1] != "stories"
    return True


volume = modal.Volume.from_name("story-studio-data", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .env({"STORY_DATA_DIR": "/data", "FRONTEND_DIR": "/nonexistent", "HOSTED": "1"})  # frontend lives on Vercel
    .add_local_dir(HERE, "/root/backend", ignore=lambda path: _skip_upload(path))
)

app = modal.App("story-studio", image=image)


@app.function(
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name("story-studio")],
    # A single container: jobs run in background threads and are polled from the browser, so every
    # request must reach the same process. This is also what keeps the free credits from being burned.
    max_containers=1,
    scaledown_window=900,  # stays warm 15 minutes after the last request (long stories keep it busy anyway)
    timeout=3600,
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, "/root/backend")
    from app import storage
    from app.api import app as fastapi_app

    storage.AFTER_WRITE.append(volume.commit)  # make every saved story durable right away
    storage.seed_if_empty(Path("/root/backend/data/stories"))
    return fastapi_app
