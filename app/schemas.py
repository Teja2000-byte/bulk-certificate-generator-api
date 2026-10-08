from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CertificateDetails(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    course: str = Field(min_length=1, max_length=160)
    organization: str = Field(default="Aereo Academy", min_length=1, max_length=120)
    issued_on: date = Field(default_factory=date.today)


class Recipient(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    recipient_id: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("must be a valid email address")
        return value.lower()


class JobCreate(BaseModel):
    certificate: CertificateDetails
    recipients: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class CertificateRecord(BaseModel):
    id: str
    recipient_index: int
    recipient_name: str | None
    recipient_email: str | None
    recipient_id: str | None
    status: Literal["PENDING", "GENERATING", "COMPLETED", "FAILED"]
    error: str | None
    download_url: str | None


class JobResponse(BaseModel):
    id: str
    status: Literal[
        "PENDING", "PROCESSING", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"
    ]
    total_count: int
    processed_count: int
    success_count: int
    failure_count: int
    progress_percent: float
    certificate: CertificateDetails
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    certificates_url: str
    download_url: str | None

