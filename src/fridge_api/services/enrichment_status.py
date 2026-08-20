"""Reading the enrichment queue back out, for a screen rather than a log."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from fridge_api.models import EnrichmentJob, EnrichmentJobStatus, ReceiptLine


def enrichment_status(session: Session, owner_id: uuid.UUID, limit: int) -> dict:
    counts = {status.value: 0 for status in EnrichmentJobStatus}
    rows = session.execute(
        select(EnrichmentJob.status, func.count())
        .where(EnrichmentJob.owner_id == owner_id)
        .group_by(EnrichmentJob.status)
    )
    for status, count in rows:
        counts[getattr(status, "value", str(status))] = count

    # Newest first: after putting a receipt in, the question is always about
    # what you just added, never about last week.
    jobs = session.scalars(
        select(EnrichmentJob)
        .where(EnrichmentJob.owner_id == owner_id)
        .options(joinedload(EnrichmentJob.receipt_line))
        .order_by(EnrichmentJob.created_at.desc())
        .limit(limit)
    ).all()

    return {
        "pending": counts[EnrichmentJobStatus.PENDING.value],
        "running": counts[EnrichmentJobStatus.RUNNING.value],
        "retry": counts[EnrichmentJobStatus.RETRY.value],
        "completed": counts[EnrichmentJobStatus.COMPLETED.value],
        "failed": counts[EnrichmentJobStatus.FAILED.value],
        # Anything not finished is still owed an answer, and that is the number
        # worth watching after adding items.
        "in_flight": (
            counts[EnrichmentJobStatus.PENDING.value]
            + counts[EnrichmentJobStatus.RUNNING.value]
            + counts[EnrichmentJobStatus.RETRY.value]
        ),
        "jobs": [_job_row(job) for job in jobs],
    }


def _job_row(job: EnrichmentJob) -> dict:
    line: ReceiptLine | None = job.receipt_line
    result = job.result or {}
    found = result.get("enrichment") or {}
    return {
        "id": job.id,
        "name": line.raw_name if line is not None else None,
        "status": job.status,
        "attempts": job.attempts,
        # Which of them actually answered — Hermes, Open Food Facts, Yandex, or
        # a product already on the shelf. Without it a completed job says only
        # that something worked.
        "provider": result.get("provider"),
        "last_error": job.last_error,
        # Where each half of the answer came from. The nutrition and the
        # picture routinely come from different places — Hermes reads a table
        # off some site, the photograph arrives from Yandex — and «источник:
        # hermes» alone hides that.
        "nutrition_source_url": found.get("nutrition_source_url") or None,
        "image_source_url": found.get("image_source_url") or None,
        "confidence": found.get("confidence"),
        # Everyone who was asked, in order, with what they said.
        "attempts_trail": result.get("attempts") or [],
        "next_attempt_at": job.next_attempt_at,
        "completed_at": job.completed_at,
        "created_at": job.created_at,
    }
