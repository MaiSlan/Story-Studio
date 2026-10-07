import time

import pytest
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def wait_job(job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_config_lists_everything_the_ui_needs():
    c = client.get("/api/config").json()
    assert {t["id"] for t in c["tracks"]} == {"pinyin", "french"}
    assert [l["id"] for l in c["lengths"]] == ["short", "medium", "long", "custom"]
    assert any(p["id"] == "mock" and p["configured"] for p in c["providers"])


def test_job_pdf_edit_repair_delete_roundtrip():
    r = client.post("/api/jobs", json={"track": "pinyin", "topic": "a monkey", "length": "short", "level": 2, "provider": "mock"})
    assert r.status_code == 200
    job = wait_job(r.json()["job_id"])
    assert job["status"] == "done", job
    sid = job["story_id"]

    data = client.get(f"/api/stories/{sid}").json()
    assert len(data["story"]["lines"]) == 50 and data["validation"]["errors"] == 0

    pdf = client.get(f"/api/stories/{sid}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 20000

    edit = {"title": data["story"]["title"],
            "lines": [{"n": l["n"], "primary": l["primary"], "hanzi": l["hanzi"], "english": l["english"]} for l in data["story"]["lines"]]}
    edit["lines"][0]["primary"] += " oops"
    saved = client.put(f"/api/stories/{sid}", json=edit).json()
    assert saved["validation"]["errors"] == 1 and "1" in saved["validation"]["lines"]

    fixed = client.post(f"/api/stories/{sid}/lines/1/repair").json()
    assert fixed["validation"]["errors"] == 0

    assert client.delete(f"/api/stories/{sid}").status_code == 200
    assert client.get(f"/api/stories/{sid}").status_code == 404


def test_french_pdf_and_ideas():
    r = client.post("/api/jobs", json={"track": "french", "topic": "le renard", "length": "custom", "custom_lines": 12, "level": 1, "provider": "mock"})
    job = wait_job(r.json()["job_id"])
    assert job["status"] == "done"
    assert client.get(f"/api/stories/{job['story_id']}/pdf?scale=0.8").status_code == 200
    ideas = client.post("/api/ideas", json={"track": "french", "theme": "", "count": 4, "provider": "mock"}).json()["ideas"]
    assert len(ideas) == 4 and all(i["title"] for i in ideas)


def test_missing_key_is_reported_before_a_job_starts(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/jobs", json={"track": "pinyin", "topic": "x y z", "provider": "anthropic"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_bad_requests_are_rejected():
    assert client.post("/api/jobs", json={"track": "klingon", "topic": "abc", "provider": "mock"}).status_code == 422
    assert client.get("/api/stories/../../etc/passwd").status_code in (404, 422)


def test_password_gate(monkeypatch):
    import app.api as api

    monkeypatch.setattr(api, "APP_PASSWORD", "s3cret")
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", auth=("me", "wrong")).status_code == 401
    assert client.get("/api/config", auth=("me", "s3cret")).status_code == 200
