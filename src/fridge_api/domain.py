import re
import secrets
import unicodedata
from decimal import Decimal

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def normalize_product_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[^a-zа-я0-9%]+", " ", normalized)
    return " ".join(normalized.split())


def make_container_code() -> str:
    return "GT:C:" + secrets.token_hex(5).upper()


def nutrient_amount(
    per_100: Decimal | None,
    quantity: Decimal,
    unit: str,
    net_quantity: Decimal | None,
    net_unit: str | None,
) -> tuple[Decimal, bool]:
    if per_100 is None:
        return ZERO, True
    if unit in {"g", "ml"}:
        return per_100 * quantity / HUNDRED, False
    if unit == "kg":
        return per_100 * quantity * Decimal("1000") / HUNDRED, False
    if unit == "l":
        return per_100 * quantity * Decimal("1000") / HUNDRED, False
    if unit == "pcs" and net_quantity is not None and net_unit in {"g", "ml"}:
        return per_100 * quantity * net_quantity / HUNDRED, False
    return ZERO, True
