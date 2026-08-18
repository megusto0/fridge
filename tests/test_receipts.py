from fastapi.testclient import TestClient


def receipt_payload() -> dict:
    return {
        "provider": "test-ofd",
        "fiscal_fn": "9280440300123456",
        "fiscal_fd": "12345",
        "fiscal_fp": "987654321",
        "operation": "sale",
        "merchant_name": "Магнит",
        "merchant_inn": "1234567890",
        "purchased_at": "2026-08-17T14:30:00+04:00",
        "total_minor": 42000,
        "items": [
            {
                "name": "ТВОРОГ СЕЛО ЗЕЛ 5% 300Г",
                "quantity": "2",
                "unit": "шт",
                "unit_price_minor": 14000,
                "total_minor": 28000,
            },
            {
                "name": "ТОМАТЫ РОЗОВЫЕ",
                "quantity": "0.5",
                "unit": "кг",
                "unit_price_minor": 28000,
                "total_minor": 14000,
            },
        ],
    }


def test_receipt_import_is_idempotent_and_owner_scoped(
    client: TestClient,
    owner_headers: dict[str, str],
    other_owner_headers: dict[str, str],
) -> None:
    first = client.post("/receipts/import", headers=owner_headers, json=receipt_payload())
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True
    assert body["inventory_lots_created"] == 2
    assert body["enrichment_jobs_created"] == 2
    assert body["receipt"]["lines"][0]["unit"] == "pcs"
    assert body["receipt"]["lines"][1]["unit"] == "kg"

    duplicate = client.post("/receipts/import", headers=owner_headers, json=receipt_payload())
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["receipt"]["id"] == body["receipt"]["id"]

    inventory = client.get("/inventory", headers=owner_headers)
    assert inventory.status_code == 200
    assert len(inventory.json()) == 2

    other_inventory = client.get("/inventory", headers=other_owner_headers)
    assert other_inventory.status_code == 200
    assert other_inventory.json() == []

    other_receipts = client.get("/receipts", headers=other_owner_headers)
    assert other_receipts.status_code == 200
    assert other_receipts.json() == []


def test_owner_header_and_timezone_are_required(
    client: TestClient, owner_headers: dict[str, str]
) -> None:
    assert client.get("/inventory").status_code == 401

    payload = receipt_payload()
    payload["purchased_at"] = "2026-08-17T14:30:00"
    response = client.post("/receipts/import", headers=owner_headers, json=payload)
    assert response.status_code == 422
