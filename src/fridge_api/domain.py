import re
import secrets
import unicodedata
from decimal import Decimal

ZERO = Decimal("0")
HUNDRED = Decimal("100")


_NON_FRIDGE_ITEM_RE = re.compile(
    r"""
    (?:^|\s)
    (?:
        доставка |
        сборка(?:\s+и\s+упаковка)? |
        пакет(?:-майка|ы|\s|$) |
        батаре(?:йк|ек|я) |
        губк[ауи] |
        салфетк |
        полотен[цч] |
        туалетн\w*\s+бумаг |
        бумажн\w*\s+полотен |
        стакан\w*\s+одноразов |
        одноразов |
        зубн\w*\s+паст |
        шампунь |
        мыло |
        стиральн |
        чистящ |
        средство\s+для |
        наполнитель\s+для |
        жевательн\w*\s+резинк |
        жвачк |
        резинка\s+жевательн |
        вода(?:\s+\w+){0,3}\s+(?:минеральн|питьев|негазир) |
        минеральн\w*\s+вода |
        вода\s+мензелин
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_fridge_inventory_item(name: str, *, calculation_subject: str | None = None) -> bool:
    """Return False for services, household goods, plain water, and gum."""
    if calculation_subject and "УСЛУГА" in calculation_subject.upper():
        return False
    return _NON_FRIDGE_ITEM_RE.search(name) is None


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
