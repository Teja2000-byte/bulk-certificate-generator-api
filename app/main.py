from __future__ import annotations

import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.config import Settings
from app.database import Database
from app.generator import generate_certificate
from app.schemas import CertificateDetails, CertificateRecord, JobCreate, JobResponse
from app.service import Generator, JobService


def create_app(settings: Settings | None = None, generator: Generator = generate_certificate) -> FastAPI:
    settings = settings or Settings.from_environment()
    database = Database(settings.database_path)
    database.initialize()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    service = JobService(database, settings.output_dir, generator)

    app = FastAPI(
        title="Bulk Certificate Generator API",
        version="1.0.0",
        description="Create, track, and retrieve fault-tolerant bulk certificate jobs.",
    )
    app.state.database = database
    app.state.service = service

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/v1/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["jobs"],
    )
    def create_job(payload: JobCreate, background_tasks: BackgroundTasks, request: Request):
        job_id = service.create_job(payload)
        background_tasks.add_task(service.process_job, job_id)
        return _job_response(database, job_id, request)

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
    def get_job(job_id: str, request: Request):
        return _job_response(database, job_id, request)

    @app.get(
        "/api/v1/jobs/{job_id}/certificates",
        response_model=list[CertificateRecord],
        tags=["certificates"],
    )
    def list_certificates(job_id: str, request: Request):
        with database.connect() as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="Job not found")
            rows = connection.execute(
                "SELECT * FROM certificates WHERE job_id = ? ORDER BY recipient_index",
                (job_id,),
            ).fetchall()
        return [
            CertificateRecord(
                id=row["id"],
                recipient_index=row["recipient_index"],
                recipient_name=row["recipient_name"],
                recipient_email=row["recipient_email"],
                recipient_id=row["recipient_external_id"],
                status=row["status"],
                error=row["error"],
                download_url=(
                    str(request.url_for("download_certificate", job_id=job_id, certificate_id=row["id"]))
                    if row["status"] == "COMPLETED"
                    else None
                ),
            )
            for row in rows
        ]

    @app.get(
        "/api/v1/jobs/{job_id}/certificates/{certificate_id}/download",
        tags=["certificates"],
    )
    def download_certificate(job_id: str, certificate_id: str):
        row = _completed_certificate(database, job_id, certificate_id)
        path = Path(row["file_path"])
        if not path.is_file():
            raise HTTPException(status_code=410, detail="Generated file is no longer available")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.get("/api/v1/jobs/{job_id}/download", tags=["certificates"])
    def download_job(job_id: str):
        with database.connect() as connection:
            job = connection.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            rows = connection.execute(
                "SELECT file_path FROM certificates WHERE job_id = ? AND status = 'COMPLETED'",
                (job_id,),
            ).fetchall()
        files = [Path(row["file_path"]) for row in rows if Path(row["file_path"]).is_file()]
        if not files:
            raise HTTPException(status_code=409, detail="No generated certificates are available")
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(path, path.name)
        archive.seek(0)
        return StreamingResponse(
            archive,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
        )

    return app


def _job_response(database: Database, job_id: str, request: Request) -> JobResponse:
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    processed = row["success_count"] + row["failure_count"]
    progress = round((processed / row["total_count"]) * 100, 2) if row["total_count"] else 0
    return JobResponse(
        id=row["id"],
        status=row["status"],
        total_count=row["total_count"],
        processed_count=processed,
        success_count=row["success_count"],
        failure_count=row["failure_count"],
        progress_percent=progress,
        certificate=CertificateDetails(
            title=row["title"],
            course=row["course"],
            organization=row["organization"],
            issued_on=row["issued_on"],
        ),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        certificates_url=str(request.url_for("list_certificates", job_id=job_id)),
        download_url=(
            str(request.url_for("download_job", job_id=job_id))
            if row["success_count"] > 0
            else None
        ),
    )


def _completed_certificate(database: Database, job_id: str, certificate_id: str) -> sqlite3.Row:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM certificates WHERE id = ? AND job_id = ?",
            (certificate_id, job_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if row["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail="Certificate is not available")
    return row


app = create_app()

