from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


def create_known_lot(client: TestClient, headers: dict[str, str]) -> str:
    product_response = client.post(
        "/products",
        headers=headers,
        json={
            "canonical_name": "Филе грудки индейки",
            "brand": "Индилайт",
            "net_quantity": "500",
            "net_unit": "g",
            "kcal_per_100": "110",
            "protein_per_100": "23",
            "fat_per_100": "2",
            "carbs_per_100": "0",
            "nutrition_status": "verified",
            "confidence": "1",
            "image_url": "https://images.example/turkey.jpg",
        },
    )
    assert product_response.status_code == 201, product_response.text
    product_id = product_response.json()["id"]
    alias_response = client.post(
        f"/products/{product_id}/aliases",
        headers=headers,
        json={"merchant_inn": "1234567890", "raw_name": "ФИЛЕ ИНДЕЙКИ ВЕС"},
    )
    assert alias_response.status_code == 201, alias_response.text

    receipt = client.post(
        "/receipts/import",
        headers=headers,
        json={
            "provider": "test-ofd",
            "fiscal_fn": "9280440300654321",
            "fiscal_fd": "54321",
            "fiscal_fp": "123456789",
            "merchant_name": "Магнит",
            "merchant_inn": "1234567890",
            "purchased_at": "2026-08-17T15:00:00+04:00",
            "total_minor": 33000,
            "items": [
                {
                    "name": "ФИЛЕ ИНДЕЙКИ ВЕС",
                    "quantity": "600",
                    "unit": "g",
                    "unit_price_minor": 550,
                    "total_minor": 33000,
                }
            ],
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["enrichment_jobs_created"] == 0
    inventory = client.get("/inventory", headers=headers).json()
    assert len(inventory) == 1
    return inventory[0]["id"]


def test_meal_prep_consumes_inventory_and_distributes_nutrition(
    client: TestClient,
    owner_headers: dict[str, str],
    other_owner_headers: dict[str, str],
) -> None:
    lot_id = create_known_lot(client, owner_headers)
    batch_payload = {
        "idempotency_key": "camera-session-20260817-1",
        "name": "Индейка для милпрепа",
        "identification_confidence": "0.96",
        "ingredients": [{"lot_id": lot_id, "quantity": "500", "unit": "g"}],
    }
    batch_response = client.post("/meal-prep/batches", headers=owner_headers, json=batch_payload)
    assert batch_response.status_code == 201, batch_response.text
    batch = batch_response.json()
    assert Decimal(batch["kcal_total"]) == Decimal("550")
    assert Decimal(batch["protein_total"]) == Decimal("115")
    batch_id = batch["id"]

    duplicate = client.post("/meal-prep/batches", headers=owner_headers, json=batch_payload)
    assert duplicate.status_code == 200
    inventory = client.get("/inventory", headers=owner_headers).json()
    assert Decimal(inventory[0]["remaining_quantity"]) == Decimal("100")

    first = client.post(
        f"/meal-prep/batches/{batch_id}/containers",
        headers=owner_headers,
        json={"gross_weight_g": "250", "tare_weight_g": "50"},
    )
    second = client.post(
        f"/meal-prep/batches/{batch_id}/containers",
        headers=owner_headers,
        json={"gross_weight_g": "350", "tare_weight_g": "50"},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    finalized = client.post(f"/meal-prep/batches/{batch_id}/finalize", headers=owner_headers)
    assert finalized.status_code == 200, finalized.text
    containers = finalized.json()["containers"]
    by_weight = {Decimal(item["net_weight_g"]): item for item in containers}
    assert Decimal(by_weight[Decimal("200")]["kcal"]) == pytest.approx(Decimal("220"))
    assert Decimal(by_weight[Decimal("300")]["kcal"]) == pytest.approx(Decimal("330"))
    assert sum(Decimal(item["protein"]) for item in containers) == pytest.approx(Decimal("115"))

    target = by_weight[Decimal("200")]
    code_lookup = client.get(f"/containers/by-code/{target['public_code']}", headers=owner_headers)
    assert code_lookup.status_code == 200
    assert code_lookup.json()["id"] == target["id"]
    assert (
        client.get(
            f"/containers/by-code/{target['public_code']}", headers=other_owner_headers
        ).status_code
        == 404
    )

    consumption = client.post(
        f"/containers/{target['id']}/consume",
        headers=owner_headers,
        json={"consumed_weight_g": "80"},
    )
    assert consumption.status_code == 201, consumption.text
    assert Decimal(consumption.json()["kcal"]) == pytest.approx(Decimal("88"))
    after = client.get(f"/containers/by-code/{target['public_code']}", headers=owner_headers).json()
    assert after["status"] == "partial"
    assert Decimal(after["remaining_weight_g"]) == Decimal("120")


def test_mockup_backend_flow_equal_portions_name_label_and_owner_isolation(
    client: TestClient,
    owner_headers: dict[str, str],
    other_owner_headers: dict[str, str],
) -> None:
    lot_id = create_known_lot(client, owner_headers)
    inventory = client.get("/inventory", headers=owner_headers)
    assert inventory.status_code == 200
    lot = inventory.json()[0]
    assert lot["product"]["canonical_name"] == "Филе грудки индейки"
    assert lot["product"]["image_url"] == "https://images.example/turkey.jpg"
    assert lot["product"]["nutrition_status"] == "verified"

    batch_response = client.post(
        "/meal-prep/batches",
        headers=owner_headers,
        json={
            "idempotency_key": "mockup-equal-flow",
            "name": "Новый милпреп",
            "ingredients": [{"lot_id": lot_id, "quantity": "500", "unit": "g"}],
        },
    )
    assert batch_response.status_code == 201, batch_response.text
    batch_id = batch_response.json()["id"]
    assert (
        client.patch(
            f"/meal-prep/batches/{batch_id}",
            headers=other_owner_headers,
            json={"name": "Чужое изменение"},
        ).status_code
        == 404
    )

    suggestion = client.post(
        f"/meal-prep/batches/{batch_id}/suggest-name",
        headers=owner_headers,
        json={"mode": "fast"},
    )
    assert suggestion.status_code == 200
    assert suggestion.json() == {
        "name": "Филе грудки индейки",
        "source": "fast",
        "fallback_used": False,
    }
    updated = client.patch(
        f"/meal-prep/batches/{batch_id}",
        headers=owner_headers,
        json={
            "name": suggestion.json()["name"],
            "name_source": "fast",
            "image_url": "https://images.example/meal.jpg",
            "cooked_yield_g": "480",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name_source"] == "fast"

    portions = client.put(
        f"/meal-prep/batches/{batch_id}/portions",
        headers=owner_headers,
        json={
            "mode": "equal",
            "cooked_yield_g": "480",
            "container_count": 4,
            "tare_weight_g": "50",
        },
    )
    assert portions.status_code == 200, portions.text
    portion_body = portions.json()
    assert len(portion_body["containers"]) == 4
    assert {Decimal(row["net_weight_g"]) for row in portion_body["containers"]} == {
        Decimal("120")
    }
    assert sum(Decimal(row["kcal"]) for row in portion_body["containers"]) == pytest.approx(
        Decimal("550")
    )

    finalized = client.post(
        f"/meal-prep/batches/{batch_id}/finalize", headers=owner_headers
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "ready"
    assert finalized.json()["finalized_at"] is not None
    container = finalized.json()["containers"][0]
    label = client.get(
        f"/containers/{container['id']}/label", headers=owner_headers
    )
    assert label.status_code == 200, label.text
    assert label.json()["data_matrix_value"] == container["public_code"]
    assert label.json()["dish_name"] == "Филе грудки индейки"
    assert (
        client.get(
            f"/containers/{container['id']}/label", headers=other_owner_headers
        ).status_code
        == 404
    )


def test_fixed_custom_portions_and_cancel_release_inventory(
    client: TestClient,
    owner_headers: dict[str, str],
) -> None:
    lot_id = create_known_lot(client, owner_headers)
    created = client.post(
        "/meal-prep/batches",
        headers=owner_headers,
        json={
            "idempotency_key": "mockup-fixed-flow",
            "name": "Индейка",
            "ingredients": [{"lot_id": lot_id, "quantity": "500", "unit": "g"}],
        },
    )
    batch_id = created.json()["id"]
    reserved_inventory = client.get("/inventory", headers=owner_headers).json()[0]
    assert Decimal(reserved_inventory["remaining_quantity"]) == Decimal("100")

    fixed = client.put(
        f"/meal-prep/batches/{batch_id}/portions",
        headers=owner_headers,
        json={
            "mode": "fixed",
            "cooked_yield_g": "500",
            "fixed_net_weight_g": "180",
            "include_remainder": True,
            "tare_weight_g": "40",
        },
    )
    assert fixed.status_code == 200, fixed.text
    assert [Decimal(item["net_weight_g"]) for item in fixed.json()["containers"]] == [
        Decimal("180"),
        Decimal("180"),
        Decimal("140"),
    ]

    mismatch = client.put(
        f"/meal-prep/batches/{batch_id}/portions",
        headers=owner_headers,
        json={
            "mode": "custom",
            "cooked_yield_g": "500",
            "portions": [{"net_weight_g": "200"}, {"net_weight_g": "250"}],
            "tare_weight_g": "40",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["difference_g"] == "50"

    cancelled = client.post(f"/meal-prep/batches/{batch_id}/cancel", headers=owner_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None
    restored = client.get("/inventory", headers=owner_headers).json()[0]
    assert Decimal(restored["remaining_quantity"]) == Decimal("600")


def test_image_upload_accepts_supported_content_and_rejects_arbitrary_files(
    client: TestClient,
    owner_headers: dict[str, str],
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"mock-image-content"
    uploaded = client.post(
        "/media/images",
        headers=owner_headers,
        files={"file": ("meal.png", png, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["content_type"] == "image/png"
    assert body["size"] == len(png)
    assert client.get(body["url"]).content == png

    rejected = client.post(
        "/media/images",
        headers=owner_headers,
        files={"file": ("note.txt", b"not an image", "text/plain")},
    )
    assert rejected.status_code == 422
