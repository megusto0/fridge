"""The enrichment queue, read back for a screen instead of a log file."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fridge_api.models import (
    EnrichmentJob,
    EnrichmentJobStatus,
    Receipt,
    ReceiptLine,
    ReceiptOperation,
)

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _job(session, name: str, status: EnrichmentJobStatus, **fields) -> EnrichmentJob:
    unique = uuid.uuid4().hex[:12]
    receipt = Receipt(
        owner_id=OWNER,
        provider="test",
        fiscal_fn=unique,
        fiscal_fd=unique,
        fiscal_fp=unique,
        operation=ReceiptOperation.SALE,
        merchant_name="Магнит",
        purchased_at=datetime.now(UTC),
        total_minor=10000,
    )
    session.add(receipt)
    session.flush()
    line = ReceiptLine(
        owner_id=OWNER,
        receipt_id=receipt.id,
        position=1,
        raw_name=name,
        normalized_name=name.lower(),
        quantity=Decimal("1"),
        unit="pcs",
        unit_price_minor=10000,
        total_minor=10000,
    )
    session.add(line)
    session.flush()
    job = EnrichmentJob(
        owner_id=OWNER, receipt_line_id=line.id, status=status, **fields
    )
    session.add(job)
    session.commit()
    return job


def test_the_queue_reports_what_is_still_owed_an_answer(client, owner_headers, session_factory):
    with session_factory() as session:
        _job(session, "Яйцо куриное", EnrichmentJobStatus.PENDING)
        _job(session, "Кефир", EnrichmentJobStatus.RUNNING)
        _job(session, "Сметана", EnrichmentJobStatus.COMPLETED)

    body = client.get("/enrichment/status", headers=owner_headers).json()

    assert body["pending"] == 1
    assert body["running"] == 1
    assert body["completed"] == 1
    # The number worth watching after putting a receipt in.
    assert body["in_flight"] == 2


def test_a_finished_job_says_which_provider_answered(
    client, owner_headers, session_factory
):
    """«Completed» alone only says that something worked, not what."""
    with session_factory() as session:
        _job(
            session,
            "Сметанник",
            EnrichmentJobStatus.COMPLETED,
            result={"provider": "hermes", "product_id": str(uuid.uuid4())},
            completed_at=datetime.now(UTC),
        )

    row = client.get("/enrichment/status", headers=owner_headers).json()["jobs"][0]

    assert row["name"] == "Сметанник"
    assert row["provider"] == "hermes"
    assert row["last_error"] is None


def test_a_failure_keeps_its_reason(client, owner_headers, session_factory):
    with session_factory() as session:
        _job(
            session,
            "Нечто неопознанное",
            EnrichmentJobStatus.FAILED,
            attempts=3,
            last_error="No sufficiently confident product match",
        )

    row = client.get("/enrichment/status", headers=owner_headers).json()["jobs"][0]

    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert "confident" in row["last_error"]


def test_someone_elses_queue_is_not_shown(
    client, owner_headers, other_owner_headers, session_factory
):
    with session_factory() as session:
        _job(session, "Кефир", EnrichmentJobStatus.PENDING)

    body = client.get("/enrichment/status", headers=other_owner_headers).json()

    assert body["in_flight"] == 0
    assert body["jobs"] == []


def test_the_trail_says_who_was_asked_and_what_they_said(
    client, owner_headers, session_factory
):
    """«Готово» hides the three providers that missed before one answered."""
    with session_factory() as session:
        _job(
            session,
            "Сметана Для всей семьи 15% 250 г",
            EnrichmentJobStatus.COMPLETED,
            result={
                "provider": "hermes",
                "attempts": [
                    {"provider": "yandex_eda", "outcome": "miss", "ms": 1200},
                    {"provider": "open_food_facts", "outcome": "miss", "ms": 380},
                    {"provider": "hermes", "outcome": "hit", "ms": 48000},
                ],
                "enrichment": {
                    "nutrition_source_url": "https://calorizator.ru/product/smetana",
                    "image_source_url": "https://eda.yandex/photo.jpg",
                    "confidence": "0.9",
                },
            },
            completed_at=datetime.now(UTC),
        )

    row = client.get("/enrichment/status", headers=owner_headers).json()["jobs"][0]

    assert [a["provider"] for a in row["attempts_trail"]] == [
        "yandex_eda",
        "open_food_facts",
        "hermes",
    ]
    assert [a["outcome"] for a in row["attempts_trail"]] == ["miss", "miss", "hit"]
    assert row["attempts_trail"][2]["ms"] == 48000
    # The two halves of the answer come from different places, and both are named.
    assert row["nutrition_source_url"] == "https://calorizator.ru/product/smetana"
    assert row["image_source_url"] == "https://eda.yandex/photo.jpg"
    assert row["confidence"] == "0.9"


def test_a_job_that_never_ran_has_an_empty_trail(client, owner_headers, session_factory):
    with session_factory() as session:
        _job(session, "Пончик", EnrichmentJobStatus.PENDING)

    row = client.get("/enrichment/status", headers=owner_headers).json()["jobs"][0]

    assert row["attempts_trail"] == []
    assert row["nutrition_source_url"] is None
