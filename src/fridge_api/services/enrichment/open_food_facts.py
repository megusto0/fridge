from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from fridge_api.services.enrichment.types import EnrichmentResult, TemporaryEnrichmentError

FIELDS = ",".join(
    (
        "code",
        "product_name",
        "product_name_ru",
        "brands",
        "quantity",
        "product_quantity",
        "product_quantity_unit",
        "nutriments",
        "image_front_url",
        "image_url",
    )
)


def normalize_gtin(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 14 and digits.startswith("0"):
        return digits[1:]
    return digits


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _nutrition(product: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    nutriments = product.get("nutriments") or {}
    values = (
        _decimal(nutriments.get("energy-kcal_100g")),
        _decimal(nutriments.get("proteins_100g")),
        _decimal(nutriments.get("fat_100g")),
        _decimal(nutriments.get("carbohydrates_100g")),
    )
    if any(value is None for value in values):
        return None
    kcal, protein, fat, carbs = values
    if kcal > 1000 or any(value > 100 for value in (protein, fat, carbs)):
        return None
    return kcal, protein, fat, carbs


class OpenFoodFactsProvider:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        self.client.close()

    def lookup(self, gtin: str | None) -> EnrichmentResult | None:
        if not gtin:
            return None
        code = normalize_gtin(gtin)
        try:
            response = self.client.get(
                f"{self.base_url}/api/v2/product/{code}", params={"fields": FIELDS}
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TemporaryEnrichmentError(f"Open Food Facts lookup failed: {exc}") from exc
        if payload.get("status") != 1 or not isinstance(payload.get("product"), dict):
            return None
        product = payload["product"]
        nutrition = _nutrition(product)
        if nutrition is None:
            return None
        kcal, protein, fat, carbs = nutrition
        canonical_name = (
            product.get("product_name_ru") or product.get("product_name") or code
        ).strip()
        product_url = f"{self.base_url}/product/{code}"
        image_url = product.get("image_front_url") or product.get("image_url")
        quantity = _decimal(product.get("product_quantity"))
        unit = product.get("product_quantity_unit")
        return EnrichmentResult(
            canonical_name=canonical_name,
            brand=(product.get("brands") or None),
            gtin=normalize_gtin(str(product.get("code") or code)),
            net_quantity=quantity,
            net_unit=unit,
            kcal_per_100=kcal,
            protein_per_100=protein,
            fat_per_100=fat,
            carbs_per_100=carbs,
            image_url=image_url,
            nutrition_source_url=product_url,
            image_source_url=product_url if image_url else None,
            confidence=Decimal("1"),
            provider="open_food_facts_gtin",
            verified=True,
        )
