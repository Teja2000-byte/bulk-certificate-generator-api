from __future__ import annotations

from threading import Event, Thread

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import JobCreate


def test_creates_bulk_job_and_reports_complete_progress(client, payload):
    response = client.post("/api/v1/jobs", json=payload)

    assert response.status_code == 202
    job = response.json()
    assert job["total_count"] == 2

    status = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert status["status"] == "COMPLETED"
    assert status["processed_count"] == 2
    assert status["success_count"] == 2
    assert status["failure_count"] == 0
    assert status["progress_percent"] == 100.0


def test_rejects_empty_bulk_request(client, payload):
    payload["recipients"] = []
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422


def test_invalid_recipient_does_not_block_valid_recipient(client, payload):
    payload["recipients"][1]["email"] = "not-an-email"
    response = client.post("/api/v1/jobs", json=payload)
    job_id = response.json()["id"]

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    certificates = client.get(f"/api/v1/jobs/{job_id}/certificates").json()

    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["success_count"] == 1
    assert status["failure_count"] == 1
    assert certificates[0]["status"] == "COMPLETED"
    assert certificates[1]["status"] == "FAILED"
    assert "valid email address" in certificates[1]["error"]


def test_renderer_failure_is_isolated(settings, payload, failing_generator):
    payload["recipients"][1] = {"name": "Failure Case", "email": "fail@example.com"}
    with TestClient(create_app(settings, generator=failing_generator)) as client:
        response = client.post("/api/v1/jobs", json=payload)
        job_id = response.json()["id"]
        status = client.get(f"/api/v1/jobs/{job_id}").json()
        records = client.get(f"/api/v1/jobs/{job_id}/certificates").json()

    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["success_count"] == 1
    assert status["failure_count"] == 1
    assert records[1]["error"] == "Generation failed: simulated renderer failure"


def test_progress_updates_while_job_is_processing(settings, payload):
    second_started = Event()
    continue_processing = Event()
    calls = 0

    def controlled_generator(recipient, details, destination):
        nonlocal calls
        from app.generator import generate_certificate

        calls += 1
        if calls == 2:
            second_started.set()
            assert continue_processing.wait(timeout=2)
        generate_certificate(recipient, details, destination)

    app = create_app(settings, generator=controlled_generator)
    service = app.state.service
    job_id = service.create_job(JobCreate.model_validate(payload))
    worker = Thread(target=service.process_job, args=(job_id,))
    worker.start()
    assert second_started.wait(timeout=2)

    with TestClient(app) as client:
        in_progress = client.get(f"/api/v1/jobs/{job_id}").json()

    assert in_progress["status"] == "PROCESSING"
    assert in_progress["processed_count"] == 1
    assert in_progress["progress_percent"] == 50.0
    continue_processing.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
