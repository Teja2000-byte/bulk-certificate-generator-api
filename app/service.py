from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from pydantic import ValidationError

from app.database import Database
from app.generator import generate_certificate, safe_filename
from app.schemas import CertificateDetails, JobCreate, Recipient

logger = logging.getLogger(__name__)
Generator = Callable[[Recipient, CertificateDetails, Path], None]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobService:
    def __init__(self, database: Database, output_dir: Path, generator: Generator = generate_certificate):
        self.database = database
        self.output_dir = output_dir
        self.generator = generator

    def create_job(self, request: JobCreate) -> str:
        job_id = str(uuid4())
        now = utc_now()
        details = request.certificate
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, title, course, organization, issued_on,
                    total_count, created_at
                ) VALUES (?, 'PENDING', ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    details.title,
                    details.course,
                    details.organization,
                    details.issued_on.isoformat(),
                    len(request.recipients),
                    now,
                ),
            )
            connection.executemany(
                """
                INSERT INTO certificates (
                    id, job_id, recipient_index, raw_recipient, status, created_at
                ) VALUES (?, ?, ?, ?, 'PENDING', ?)
                """,
                [
                    (str(uuid4()), job_id, index, json.dumps(raw), now)
                    for index, raw in enumerate(request.recipients)
                ],
            )
        return job_id

    def process_job(self, job_id: str) -> None:
        started_at = utc_now()
        with self.database.connect() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None or job["status"] != "PENDING":
                return
            connection.execute(
                "UPDATE jobs SET status = 'PROCESSING', started_at = ? WHERE id = ?",
                (started_at, job_id),
            )
            items = connection.execute(
                "SELECT * FROM certificates WHERE job_id = ? ORDER BY recipient_index",
                (job_id,),
            ).fetchall()

        details = CertificateDetails(
            title=job["title"],
            course=job["course"],
            organization=job["organization"],
            issued_on=job["issued_on"],
        )
        for item in items:
            self._process_recipient(job_id, item, details)
            self._refresh_counts(job_id)

        with self.database.connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures
                FROM certificates WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            successes = counts["successes"] or 0
            failures = counts["failures"] or 0
            if successes and failures:
                status = "COMPLETED_WITH_ERRORS"
            elif failures:
                status = "FAILED"
            else:
                status = "COMPLETED"
            connection.execute(
                """
                UPDATE jobs SET status = ?, success_count = ?, failure_count = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, successes, failures, utc_now(), job_id),
            )

    def _refresh_counts(self, job_id: str) -> None:
        """Persist live counters so status polling shows meaningful progress."""
        with self.database.connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures
                FROM certificates WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            connection.execute(
                "UPDATE jobs SET success_count = ?, failure_count = ? WHERE id = ?",
                (counts["successes"] or 0, counts["failures"] or 0, job_id),
            )

    def _process_recipient(self, job_id: str, item, details: CertificateDetails) -> None:
        certificate_id = item["id"]
        raw = json.loads(item["raw_recipient"])
        try:
            recipient = Recipient.model_validate(raw)
        except ValidationError as exc:
            self._mark_failed(certificate_id, self._validation_message(exc), raw)
            return

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE certificates SET status = 'GENERATING', recipient_name = ?,
                    recipient_email = ?, recipient_external_id = ? WHERE id = ?
                """,
                (recipient.name, recipient.email, recipient.recipient_id, certificate_id),
            )

        filename = f"{item['recipient_index'] + 1:04d}-{safe_filename(recipient.name)}"
        destination = self.output_dir / job_id / filename
        try:
            self.generator(recipient, details, destination)
        except Exception as exc:  # isolate each recipient failure by design
            logger.exception("Certificate generation failed for %s", certificate_id)
            self._mark_failed(certificate_id, f"Generation failed: {exc}", raw)
            return

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE certificates SET status = 'COMPLETED', file_path = ?,
                    completed_at = ? WHERE id = ?
                """,
                (str(destination), utc_now(), certificate_id),
            )

    def _mark_failed(self, certificate_id: str, error: str, raw: dict) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE certificates SET status = 'FAILED', recipient_name = ?,
                    recipient_email = ?, recipient_external_id = ?, error = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    str(raw.get("name", ""))[:120] or None,
                    str(raw.get("email", ""))[:254] or None,
                    str(raw.get("recipient_id", ""))[:80] or None,
                    error[:500],
                    utc_now(),
                    certificate_id,
                ),
            )

    @staticmethod
    def _validation_message(exc: ValidationError) -> str:
        errors = [f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors()]
        return "Invalid recipient: " + "; ".join(errors)
