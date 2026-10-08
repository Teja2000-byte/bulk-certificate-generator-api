from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generator import generate_certificate
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "test.db", output_dir=tmp_path / "generated")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def payload() -> dict:
    return {
        "certificate": {
            "title": "Certificate of Completion",
            "course": "Backend Engineering Foundations",
            "organization": "Aereo Academy",
            "issued_on": "2026-10-08",
        },
        "recipients": [
            {"name": "Ada Lovelace", "email": "ada@example.com", "recipient_id": "A-1"},
            {"name": "Grace Hopper", "email": "grace@example.com", "recipient_id": "G-2"},
        ],
    }


@pytest.fixture
def failing_generator():
    def generate(recipient, details, destination):
        if recipient.email == "fail@example.com":
            raise RuntimeError("simulated renderer failure")
        generate_certificate(recipient, details, destination)

    return generate

