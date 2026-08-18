from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    canonical_name: str
    brand: str | None
    gtin: str | None
    net_quantity: Decimal | None
    net_unit: str | None
    kcal_per_100: Decimal
    protein_per_100: Decimal
    fat_per_100: Decimal
    carbs_per_100: Decimal
    image_url: str | None
    piece_weight_g: Decimal | None = None
    nutrition_source_url: str = ""
    image_source_url: str | None = None
    confidence: Decimal = Decimal("0.8")
    provider: str = ""
    verified: bool = False

    def as_json(self) -> dict[str, object]:
        result = asdict(self)
        for key, value in result.items():
            if isinstance(value, Decimal):
                result[key] = str(value)
        return result


class TemporaryEnrichmentError(RuntimeError):
    """The lookup should be retried later."""
