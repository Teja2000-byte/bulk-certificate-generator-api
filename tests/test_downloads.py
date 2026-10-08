from __future__ import annotations

import zipfile
from io import BytesIO


def test_generated_certificate_can_be_retrieved(client, payload):
    job = client.post("/api/v1/jobs", json=payload).json()
    records = client.get(f"/api/v1/jobs/{job['id']}/certificates").json()

    response = client.get(
        f"/api/v1/jobs/{job['id']}/certificates/{records[0]['id']}/download"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 1000


def test_bulk_zip_contains_every_successful_certificate(client, payload):
    job = client.post("/api/v1/jobs", json=payload).json()
    response = client.get(f"/api/v1/jobs/{job['id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert all(name.endswith(".pdf") for name in names)
        assert all(archive.read(name).startswith(b"%PDF") for name in names)


def test_unknown_resources_return_not_found(client):
    assert client.get("/api/v1/jobs/missing").status_code == 404
    assert client.get("/api/v1/jobs/missing/certificates").status_code == 404

