from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from fridge_api.config import Settings
from fridge_api.models import (
    EnrichmentJob,
    EnrichmentJobStatus,
    EnrichmentStatus,
    InventoryLot,
    Product,
    ReceiptLine,
)
from fridge_api.services.enrichment.types import EnrichmentResult
from fridge_api.services.enrichment.worker import EnrichmentWorker
from fridge_api.services.enrichment.yandex_eda import YandexCard


class FakeOpenFoodFacts:
    def __init__(self, result: EnrichmentResult | None) -> None:
        self.result = result
        self.seen_gtin: str | None = None

    def lookup(self, gtin: str | None) -> EnrichmentResult | None:
        self.seen_gtin = gtin
        return self.result

    def close(self) -> None:
        pass


def _payload_with_gtin() -> dict:
    return {
        "provider": "test-ofd",
        "fiscal_fn": "9280440300123456",
        "fiscal_fd": "12345",
        "fiscal_fp": "987654321",
        "operation": "sale",
        "merchant_name": "Магнит",
        "merchant_inn": "1234567890",
        "purchased_at": "2026-08-17T14:30:00+04:00",
        "total_minor": 28000,
        "items": [
            {
                "name": "ТВОРОГ СЕЛО ЗЕЛ 5% 200Г",
                "quantity": "2",
                "unit": "шт",
                "unit_price_minor": 14000,
                "total_minor": 28000,
                "gtin": "04607064311873",
                "package_quantity": "200",
                "package_unit": "г",
            }
        ],
    }


def test_worker_links_verified_nutrition_and_image_to_inventory(
    client: TestClient,
    owner_headers: dict[str, str],
    session_factory,
) -> None:
    response = client.post("/receipts/import", headers=owner_headers, json=_payload_with_gtin())
    assert response.status_code == 200
    result = EnrichmentResult(
        canonical_name="Творог Село Зелёное 5%",
        brand="Село Зелёное",
        gtin="4607064311873",
        net_quantity=Decimal("200"),
        net_unit="g",
        kcal_per_100=Decimal("105"),
        protein_per_100=Decimal("12"),
        fat_per_100=Decimal("5"),
        carbs_per_100=Decimal("3"),
        image_url="https://images.example/product.jpg",
        nutrition_source_url="https://world.openfoodfacts.org/product/4607064311873",
        image_source_url="https://world.openfoodfacts.org/product/4607064311873",
        confidence=Decimal("1"),
        provider="open_food_facts_gtin",
        verified=True,
    )
    provider = FakeOpenFoodFacts(result)
    worker = EnrichmentWorker(
        settings=Settings(
            enrichment_hermes_fallback=False,
            enrichment_yandex_eda_fallback=False,
        ),
        session_factory=session_factory,
        open_food_facts=provider,
    )

    assert worker.process_next() is True
    assert worker.process_next() is False
    assert provider.seen_gtin == "04607064311873"
    with session_factory() as session:
        product = session.scalar(select(Product))
        line = session.scalar(select(ReceiptLine))
        lot = session.scalar(select(InventoryLot))
        job = session.scalar(select(EnrichmentJob))
        assert product.nutrition_status == EnrichmentStatus.VERIFIED
        assert product.kcal_per_100 == Decimal("105.000")
        assert product.image_url == "https://images.example/product.jpg"
        assert line.product_id == product.id
        assert lot.product_id == product.id
        assert job.status == EnrichmentJobStatus.COMPLETED
        assert job.result["provider"] == "open_food_facts_gtin"


def test_worker_does_not_save_an_ambiguous_match(
    client: TestClient,
    owner_headers: dict[str, str],
    session_factory,
) -> None:
    response = client.post("/receipts/import", headers=owner_headers, json=_payload_with_gtin())
    assert response.status_code == 200
    worker = EnrichmentWorker(
        settings=Settings(
            enrichment_hermes_fallback=False,
            enrichment_yandex_eda_fallback=False,
            enrichment_reference_food_fallback=False,
        ),
        session_factory=session_factory,
        open_food_facts=FakeOpenFoodFacts(None),
    )

    assert worker.process_next() is True
    with session_factory() as session:
        assert session.scalar(select(Product)) is None
        line = session.scalar(select(ReceiptLine))
        job = session.scalar(select(EnrichmentJob))
        assert line.enrichment_status == EnrichmentStatus.AMBIGUOUS
        assert job.status == EnrichmentJobStatus.FAILED


class FakeYandex:
    def __init__(self, card: YandexCard | None, result: EnrichmentResult | None = None) -> None:
        self.card = card
        self.result = result

    def lookup_card(self, _query) -> YandexCard | None:
        return self.card

    def lookup(self, _query) -> EnrichmentResult | None:
        return self.result

    def _to_result(self, _query, _card) -> EnrichmentResult | None:
        return self.result

    def close(self) -> None:
        pass


def test_worker_prefers_yandex_card_nutrition_over_open_food_facts(
    client: TestClient,
    owner_headers: dict[str, str],
    session_factory,
) -> None:
    response = client.post("/receipts/import", headers=owner_headers, json=_payload_with_gtin())
    assert response.status_code == 200
    yandex_result = EnrichmentResult(
        canonical_name="Сыр полутвердый Брест-Литовск Королевский 45% 200 г",
        brand=None,
        gtin="4607064311873",
        net_quantity=Decimal("200"),
        net_unit="g",
        kcal_per_100=Decimal("316"),
        protein_per_100=Decimal("25"),
        fat_per_100=Decimal("24"),
        carbs_per_100=Decimal("0"),
        image_url="https://avatars.mds.yandex.net/get-eda/example.jpg",
        nutrition_source_url="https://eda.yandex.ru/retail/magnit_celevaya/product/abc",
        image_source_url="https://avatars.mds.yandex.net/get-eda/example.jpg",
        confidence=Decimal("0.95"),
        provider="yandex_eda_magnit",
        verified=True,
    )
    card = YandexCard(
        name=yandex_result.canonical_name,
        url=yandex_result.nutrition_source_url,
        image_url=yandex_result.image_url,
        nutrients=(Decimal("316"), Decimal("25"), Decimal("24"), Decimal("0")),
        net_quantity=Decimal("200"),
        net_unit="g",
    )
    off = FakeOpenFoodFacts(
        EnrichmentResult(
            canonical_name="Should not win",
            brand=None,
            gtin="4607064311873",
            net_quantity=Decimal("200"),
            net_unit="g",
            kcal_per_100=Decimal("105"),
            protein_per_100=Decimal("12"),
            fat_per_100=Decimal("5"),
            carbs_per_100=Decimal("3"),
            image_url=None,
            nutrition_source_url="https://world.openfoodfacts.org/product/4607064311873",
            confidence=Decimal("1"),
            provider="open_food_facts_gtin",
            verified=True,
        )
    )
    worker = EnrichmentWorker(
        settings=Settings(
            enrichment_hermes_fallback=False,
            enrichment_reference_food_fallback=False,
        ),
        session_factory=session_factory,
        open_food_facts=off,
        yandex_eda=FakeYandex(card, yandex_result),
    )
    assert worker.process_next() is True
    with session_factory() as session:
        product = session.scalar(select(Product))
        job = session.scalar(select(EnrichmentJob))
        assert product.kcal_per_100 == Decimal("316.000")
        assert job.result["provider"] == "yandex_eda_magnit"


def test_worker_falls_through_when_yandex_has_no_nutrition(
    client: TestClient,
    owner_headers: dict[str, str],
    session_factory,
) -> None:
    response = client.post("/receipts/import", headers=owner_headers, json=_payload_with_gtin())
    assert response.status_code == 200
    off_result = EnrichmentResult(
        canonical_name="Творог Село Зелёное 5%",
        brand="Село Зелёное",
        gtin="4607064311873",
        net_quantity=Decimal("200"),
        net_unit="g",
        kcal_per_100=Decimal("105"),
        protein_per_100=Decimal("12"),
        fat_per_100=Decimal("5"),
        carbs_per_100=Decimal("3"),
        image_url="https://images.example/product.jpg",
        nutrition_source_url="https://world.openfoodfacts.org/product/4607064311873",
        confidence=Decimal("1"),
        provider="open_food_facts_gtin",
        verified=True,
    )
    card = YandexCard(
        name="Творог Село Зелёное 5% 200 г",
        url="https://eda.yandex.ru/retail/magnit_celevaya/product/abc",
        image_url="https://avatars.mds.yandex.net/get-eda/example.jpg",
        nutrients=None,
        net_quantity=Decimal("200"),
        net_unit="g",
    )
    worker = EnrichmentWorker(
        settings=Settings(
            enrichment_hermes_fallback=False,
            enrichment_reference_food_fallback=False,
        ),
        session_factory=session_factory,
        open_food_facts=FakeOpenFoodFacts(off_result),
        yandex_eda=FakeYandex(card),
    )
    assert worker.process_next() is True
    with session_factory() as session:
        product = session.scalar(select(Product))
        job = session.scalar(select(EnrichmentJob))
        assert product.kcal_per_100 == Decimal("105.000")
        assert job.result["provider"] == "open_food_facts_gtin"
