import uuid
from decimal import Decimal
from fastapi.testclient import TestClient

from fridge_api.main import app
from fridge_api.db import SessionLocal
from fridge_api.models import Product, InventoryLot, InventoryStatus, MealPrepBatch, BatchStatus, ContainerStatus


def test_web_ui_routes_and_static_mounts():
    """Verify that the Web UI is served at /fridge/ and root redirects to /fridge/."""
    client = TestClient(app)
    
    # Root route redirects to /fridge/
    root_res = client.get("/", follow_redirects=True)
    assert root_res.status_code == 200
    assert "Холодильник" in root_res.text
    
    # Fridge route serves HTML UI
    fridge_res = client.get("/fridge/")
    assert fridge_res.status_code == 200
    assert "Холодильник" in fridge_res.text


def test_inventory_direct_consumption_full_and_partial():
    """Verify direct consumption from fridge (both 100% and partial weight/pieces)."""
    owner_id = uuid.uuid4()
    headers = {"X-User-Id": str(owner_id)}
    client = TestClient(app)
    
    session = SessionLocal()
    # 1. Create a product and inventory lot
    product = Product(
        owner_id=owner_id,
        canonical_name="Свежий творог 5%",
        net_quantity=Decimal("400"),
        net_unit="g",
        piece_weight_g=Decimal("400"),
        kcal_per_100=Decimal("120"),
        protein_per_100=Decimal("16"),
        fat_per_100=Decimal("5"),
        carbs_per_100=Decimal("3"),
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    
    from datetime import datetime, timezone

    lot = InventoryLot(
        owner_id=owner_id,
        product_id=product.id,
        display_name="Свежий творог 5%",
        original_quantity=Decimal("400"),
        remaining_quantity=Decimal("400"),
        unit="g",
        status=InventoryStatus.AVAILABLE,
        purchased_at=datetime.now(timezone.utc),
    )
    session.add(lot)
    session.commit()
    session.refresh(lot)
    session.close()

    # 2. Test Partial Consumption (eating 150g out of 400g)
    consume_part_res = client.post(
        "/inventory/consume",
        headers=headers,
        json={
            "items": [{"lot_id": str(lot.id), "quantity": "150", "unit": "g"}],
            "reason": "consumed"
        }
    )
    assert consume_part_res.status_code == 200
    data = consume_part_res.json()
    updated_lot = next(item for item in data if item["id"] == str(lot.id))
    assert Decimal(updated_lot["remaining_quantity"]) == Decimal("250")
    assert updated_lot["status"] == "available"

    # 3. Test Full Consumption of remaining 250g
    consume_full_res = client.post(
        "/inventory/consume",
        headers=headers,
        json={
            "items": [{"lot_id": str(lot.id), "quantity": "250", "unit": "g"}],
            "reason": "consumed"
        }
    )
    assert consume_full_res.status_code == 200
    data2 = consume_full_res.json()
    depleted_lot = next(item for item in data2 if item["id"] == str(lot.id))
    assert Decimal(depleted_lot["remaining_quantity"]) == Decimal("0")
    assert depleted_lot["status"] == "depleted"


def test_discrete_packaged_product_partial_gram_consumption_and_display():
    """Verify discrete product (e.g. 2 packs of yogurt x 130g) consuming in grams (130g, 65g)."""
    owner_id = uuid.uuid4()
    headers = {"X-User-Id": str(owner_id)}
    client = TestClient(app)
    
    from datetime import datetime, timezone
    session = SessionLocal()
    
    yogurt = Product(
        owner_id=owner_id,
        canonical_name="Epica йогурт без сахара",
        net_quantity=Decimal("130"),
        net_unit="g",
        kcal_per_100=Decimal("90"),
        protein_per_100=Decimal("10"),
        fat_per_100=Decimal("4.8"),
        carbs_per_100=Decimal("4"),
    )
    session.add(yogurt)
    session.commit()
    session.refresh(yogurt)
    
    # 2 packs in inventory
    lot = InventoryLot(
        owner_id=owner_id,
        product_id=yogurt.id,
        display_name="Epica йогурт без сахара",
        original_quantity=Decimal("2.000"),
        remaining_quantity=Decimal("2.000"),
        unit="pcs",
        status=InventoryStatus.AVAILABLE,
        purchased_at=datetime.now(timezone.utc),
    )
    session.add(lot)
    session.commit()
    session.refresh(lot)
    session.close()

    # Step 1: Consume 1 pack (130g)
    res1 = client.post(
        "/inventory/consume",
        headers=headers,
        json={
            "items": [{"lot_id": str(lot.id), "quantity": "130", "unit": "g"}],
            "reason": "consumed"
        }
    )
    assert res1.status_code == 200
    data1 = res1.json()
    updated1 = next(item for item in data1 if item["id"] == str(lot.id))
    assert Decimal(updated1["remaining_quantity"]) == Decimal("1.000")
    assert updated1["unit"] == "pcs"
    assert Decimal(updated1["weight_grams"]) == Decimal("130")

    # Step 2: Consume half of remaining pack (65g)
    res2 = client.post(
        "/inventory/consume",
        headers=headers,
        json={
            "items": [{"lot_id": str(lot.id), "quantity": "65", "unit": "g"}],
            "reason": "consumed"
        }
    )
    assert res2.status_code == 200
    data2 = res2.json()
    updated2 = next(item for item in data2 if item["id"] == str(lot.id))
    assert Decimal(updated2["remaining_quantity"]) == Decimal("0.500")
    assert Decimal(updated2["weight_grams"]) == Decimal("65")

    # Step 3: Consume final 65g
    res3 = client.post(
        "/inventory/consume",
        headers=headers,
        json={
            "items": [{"lot_id": str(lot.id), "quantity": "65", "unit": "g"}],
            "reason": "consumed"
        }
    )
    assert res3.status_code == 200
    data3 = res3.json()
    updated3 = next(item for item in data3 if item["id"] == str(lot.id))
    assert Decimal(updated3["remaining_quantity"]) == Decimal("0.000")
    assert updated3["status"] == "depleted"


def test_mealprep_wizard_full_flow_with_custom_naming_and_rename():
    """Verify complete mealprep flow: create -> AI name -> custom name -> portions -> finalize -> rename -> writeoff."""
    owner_id = uuid.uuid4()
    headers = {"X-User-Id": str(owner_id)}
    client = TestClient(app)
    
    session = SessionLocal()
    p1 = Product(
        owner_id=owner_id,
        canonical_name="Куриное филе",
        net_quantity=Decimal("500"),
        net_unit="g",
        kcal_per_100=Decimal("110"),
        protein_per_100=Decimal("23"),
        fat_per_100=Decimal("1.5"),
        carbs_per_100=Decimal("0"),
    )
    p2 = Product(
        owner_id=owner_id,
        canonical_name="Гречневая крупа",
        net_quantity=Decimal("300"),
        net_unit="g",
        kcal_per_100=Decimal("330"),
        protein_per_100=Decimal("12"),
        fat_per_100=Decimal("2"),
        carbs_per_100=Decimal("68"),
    )
    session.add_all([p1, p2])
    session.commit()
    
    from datetime import datetime, timezone

    lot1 = InventoryLot(owner_id=owner_id, product_id=p1.id, display_name="Куриное филе", original_quantity=Decimal("500"), remaining_quantity=Decimal("500"), unit="g", status=InventoryStatus.AVAILABLE, purchased_at=datetime.now(timezone.utc))
    lot2 = InventoryLot(owner_id=owner_id, product_id=p2.id, display_name="Гречневая крупа", original_quantity=Decimal("300"), remaining_quantity=Decimal("300"), unit="g", status=InventoryStatus.AVAILABLE, purchased_at=datetime.now(timezone.utc))
    session.add_all([lot1, lot2])
    session.commit()
    session.close()

    # Step 1: Start Composer (create reservation batch)
    create_res = client.post(
        "/meal-prep/batches",
        headers=headers,
        json={
            "idempotency_key": "test-flow-" + str(uuid.uuid4()),
            "name": "Куриное филе с гречкой",
            "ingredients": [
                {"lot_id": str(lot1.id), "quantity": "500", "unit": "g"},
                {"lot_id": str(lot2.id), "quantity": "300", "unit": "g"}
            ]
        }
    )
    assert create_res.status_code == 201
    batch_data = create_res.json()
    batch_id = batch_data["id"]

    # Step 2: Name Suggestion
    suggest_res = client.post(
        f"/meal-prep/batches/{batch_id}/suggest-name",
        headers=headers,
        json={"mode": "fast"}
    )
    assert suggest_res.status_code == 200

    # Step 2 & 4: User Custom Dish Naming
    custom_name = "Сытный обед спортсмена"
    update_res = client.patch(
        f"/meal-prep/batches/{batch_id}",
        headers=headers,
        json={"name": custom_name, "name_source": "user"}
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == custom_name

    # Step 3: Portioning Plan (3 equal portions)
    portions_res = client.put(
        f"/meal-prep/batches/{batch_id}/portions",
        headers=headers,
        json={
            "mode": "equal",
            "cooked_yield_g": "800",
            "container_count": 3,
            "tare_weight_g": "0"
        }
    )
    assert portions_res.status_code == 200
    assert len(portions_res.json()["containers"]) == 3

    # Step 4: Finalize Batch
    finalize_res = client.post(
        f"/meal-prep/batches/{batch_id}/finalize",
        headers=headers
    )
    assert finalize_res.status_code == 200
    final_batch = finalize_res.json()
    assert final_batch["status"] == "ready"
    assert final_batch["name"] == custom_name
    containers = final_batch["containers"]
    assert len(containers) == 3

    # Test Rename Action on Ready Batch
    renamed_name = "Обед на рабочую неделю"
    rename_res = client.patch(
        f"/meal-prep/batches/{batch_id}",
        headers=headers,
        json={"name": renamed_name, "name_source": "user"}
    )
    assert rename_res.status_code == 200
    assert rename_res.json()["name"] == renamed_name

    # Test Thermal Label Endpoint
    c1_id = containers[0]["id"]
    label_res = client.get(
        f"/containers/{c1_id}/label",
        headers=headers
    )
    assert label_res.status_code == 200
    label_data = label_res.json()
    assert label_data["dish_name"] == renamed_name
    assert "public_code" in label_data

    # Test Container Consumption / Writeoff
    consume_cont_res = client.post(
        f"/containers/{c1_id}/consume",
        headers=headers,
        json={"consumed_weight_g": containers[0]["net_weight_g"]}
    )
    assert consume_cont_res.status_code == 201
    assert Decimal(consume_cont_res.json()["consumed_weight_g"]) == Decimal(containers[0]["net_weight_g"])

    # Verify container status is consumed
    batches_res = client.get("/meal-prep/batches", headers=headers)
    assert batches_res.status_code == 200
    b = next(item for item in batches_res.json() if item["id"] == batch_id)
    c1_status = next(c for c in b["containers"] if c["id"] == c1_id)
    assert c1_status["status"] == "consumed"
    assert Decimal(c1_status["remaining_weight_g"]) == Decimal("0")
