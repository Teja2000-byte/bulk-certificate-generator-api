# Bulk Certificate Generator API

A production-minded FastAPI service for creating personalized PDF certificates in bulk. A client submits one job containing up to 1,000 recipients, receives a job ID immediately, and can inspect progress, individual failures, or download successful files individually or as a ZIP archive.

## Why this assignment

I selected the **Bulk Certificate Generator API** assessment. It is a strong fit for an SDA intern because it demonstrates broadly useful backend skills: API contracts, relational persistence, validation, asynchronous work, partial-failure handling, generated files, HTTP downloads, and automated tests. The alternative geospatial assessment requires specialist CRS and native GIS tooling; that additional domain complexity makes local setup and evaluation less predictable.

## Features

- One bulk request for 1–1,000 recipients
- FastAPI-generated OpenAPI documentation
- SQLite relational storage for jobs and recipient-level results
- Background processing after an HTTP `202 Accepted` response
- Per-recipient validation and generation failure isolation
- Job progress and `COMPLETED_WITH_ERRORS` status for partial success
- Personalized landscape PDF certificates using a predefined template
- Individual PDF and bulk ZIP downloads
- Atomic file writes to avoid serving incomplete PDFs
- Docker and local development workflows
- Tests for every required assessment scenario

## Quick start

Requirements: Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open the interactive API documentation at <http://127.0.0.1:8000/docs>. Runtime data is written to `./data` by default.

To use Docker instead:

```bash
docker compose up --build
```

## Run the tests

```bash
pytest
```

The suite covers job creation, request validation, actual PDF generation, status and progress, invalid recipient isolation, a simulated renderer failure, individual retrieval, bulk ZIP retrieval, and missing resources.

## API workflow

### 1. Create a generation job

```bash
curl -i -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  --data @examples/create-job.json
```

The API returns `202 Accepted` and a representation such as:

```json
{
  "id": "7419be13-a98e-4f31-92da-f061c76bac6d",
  "status": "PENDING",
  "total_count": 2,
  "processed_count": 0,
  "success_count": 0,
  "failure_count": 0,
  "progress_percent": 0.0,
  "certificate": {
    "title": "Certificate of Completion",
    "course": "Backend Engineering Foundations",
    "organization": "Aereo Academy",
    "issued_on": "2026-10-08"
  },
  "created_at": "2026-10-08T12:00:00+00:00",
  "started_at": null,
  "completed_at": null,
  "certificates_url": "http://127.0.0.1:8000/api/v1/jobs/7419be13-a98e-4f31-92da-f061c76bac6d/certificates",
  "download_url": null
}
```

Recipients remain raw at job creation so one malformed entry does not cause FastAPI to reject every valid recipient. Each item is validated independently during processing. The outer request, certificate details, batch size, and basic JSON shape are still validated before a job is created.

### 2. Check status and progress

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
```

Job states are `PENDING`, `PROCESSING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, and `FAILED`. Progress is based on recipients that reached either `COMPLETED` or `FAILED`.

### 3. Inspect recipient results

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID/certificates
```

Each record includes its status, any concise failure message, and a `download_url` when generation succeeded. This makes a mixed-result job actionable without parsing server logs.

### 4. Download files

Download one generated PDF:

```bash
curl -OJ http://127.0.0.1:8000/api/v1/jobs/JOB_ID/certificates/CERTIFICATE_ID/download
```

Download all successful PDFs as one ZIP:

```bash
curl -o certificates.zip http://127.0.0.1:8000/api/v1/jobs/JOB_ID/download
```

## Architecture

```text
HTTP request
    │
    ▼
FastAPI route ── validates job envelope ──► SQLite job + recipient rows
    │                                              │
    └── 202 Accepted                               ▼
                                      Background job processor
                                                  │
                               validate each recipient independently
                                                  │
                         ┌────────────────────────┴───────────────────────┐
                         ▼                                                ▼
                  ReportLab PDF                                   failure recorded
                         │
                atomic file replace
                         │
                         ▼
            status API / PDF / ZIP retrieval
```

The code is separated by responsibility:

- `app/main.py`: HTTP routes and response mapping
- `app/schemas.py`: public request/response contracts
- `app/database.py`: SQLite initialization and transaction boundaries
- `app/service.py`: job orchestration, progress, and failure isolation
- `app/generator.py`: predefined certificate renderer
- `app/config.py`: environment-based paths

### Data model

`jobs` stores certificate-wide metadata and aggregate counters. `certificates` stores one row per submitted recipient, including the original JSON, processing state, normalized recipient fields, output path, and failure message. A foreign key and unique `(job_id, recipient_index)` constraint preserve job membership and request order.

## Design decisions

### Background processing

FastAPI `BackgroundTasks` keeps the API simple while demonstrating the intended asynchronous contract: creation responds with `202`, and status is queried separately. It is appropriate for a single-process assessment and needs no broker. In production I would move `JobService.process_job` unchanged behind Celery, Dramatiq, or a cloud queue so work survives process restarts and scales across workers.

### Partial failures

Each recipient has its own validation, generation, and database update boundary. A bad email or renderer error records `FAILED` for that certificate and processing continues. The final job becomes `COMPLETED_WITH_ERRORS` when at least one item succeeds and at least one fails.

### Relational database

SQLite provides transactions, constraints, persistence, and a zero-service local setup. The SQL is deliberately portable. For concurrent production workers I would use PostgreSQL and claim pending work with row locking.

### File generation and storage

ReportLab creates real PDFs without external binaries. Files are written to a temporary path and atomically renamed only after rendering succeeds. Local disk keeps the submission easy to run; production would store outputs in object storage and return time-limited download URLs.

### Validation boundary

Rejecting the entire request because one recipient is malformed conflicts with the requirement that valid recipients continue. The job envelope is validated synchronously. Recipient records are validated independently by the worker and expose their failures through the status API.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CERTIFICATE_DATA_DIR` | `./data` | Base runtime data directory |
| `CERTIFICATE_DATABASE_PATH` | `$DATA_DIR/certificates.db` | SQLite file |
| `CERTIFICATE_OUTPUT_DIR` | `$DATA_DIR/generated` | Generated PDF root |

## Assumptions and limits

- A request contains at most 1,000 recipients to bound request size and in-process work.
- Email validation is intentionally practical and does not attempt RFC mailbox verification.
- Generated files are retained until external cleanup; no expiration requirement was specified.
- The predefined template supports Latin text through built-in PDF fonts. A production internationalized version would embed a Unicode font.
- Authentication and tenant isolation are outside the assignment scope.

## Learning and future scope

This implementation reinforced how API-level bulk success differs from per-item success: the job must preserve and expose both. It also demonstrates why generated files should become visible only after an atomic write.

The next production steps would be a durable queue with retries and idempotency keys, PostgreSQL, object storage, authenticated tenant-scoped access, metrics and structured logs, file retention policies, Unicode fonts, pagination for very large result sets, and callback/webhook support.

## License

MIT
