from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from fridge_api.models import ReceiptOperation
from fridge_api.schemas import ReceiptImportRequest, ReceiptItemInput

PARSER_NAME = "magnit-ofd-email"
PARSER_VERSION = 1
MAX_EMAIL_BYTES = 5 * 1024 * 1024

_MONEY_RE = re.compile(r"^-?\d+(?:[.,]\d{1,2})?$")
_GTIN_RE = re.compile(r"(?:^|\D)01(\d{14})")
_PACKAGE_RE = re.compile(
    r"(?P<quantity>\d+(?:[.,]\d+)?)\s*(?P<unit>кг|г|мл|л)(?![а-я])",
    re.IGNORECASE,
)
_MULTIPACK_RE = re.compile(
    r"(?P<count>\d+)\s*(?:шт\.?|пак(?:ет(?:ов|а)?)?)?\s*[*xх×]\s*"
    r"(?P<quantity>\d+(?:[.,]\d+)?)\s*(?P<unit>кг|г|мл|л)(?![а-я])",
    re.IGNORECASE,
)
_NON_INVENTORY_NAME_RE = re.compile(
    r"(?:^|\s)(?:доставка|сборка(?:\s+и\s+упаковка)?|пакет(?:-|\s|$)|пакет-майка)",
    re.IGNORECASE,
)


class MagnitReceiptParseError(ValueError):
    """Raised when a message is not a supported, complete Magnit receipt."""


class _TableRowsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._rows.append([])
        elif tag in {"td", "th"}:
            self._cells.append([])
        elif tag == "br" and self._cells:
            self._cells[-1].append(" ")

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cells:
            value = " ".join("".join(self._cells.pop()).split())
            if self._rows:
                self._rows[-1].append(value)
        elif tag == "tr" and self._rows:
            row = self._rows.pop()
            if any(row):
                self.rows.append(row)


@dataclass
class _ParsedLine:
    name: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    unit: str = "pcs"
    marking_code: str | None = None
    calculation_subject: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def gtin(self) -> str | None:
        if not self.marking_code:
            return None
        match = _GTIN_RE.search(self.marking_code)
        return match.group(1) if match else None

    @property
    def inventory_effect(self) -> bool:
        if self.calculation_subject and "УСЛУГА" in self.calculation_subject.upper():
            return False
        return _NON_INVENTORY_NAME_RE.search(self.name) is None


def _money_to_minor(value: Decimal) -> int:
    return int((value * 100).quantize(Decimal("1")))


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value.strip().replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise MagnitReceiptParseError(f"Invalid decimal value in receipt: {value!r}") from exc


def _normalize_key(value: str) -> str:
    return " ".join(value.upper().replace("Ё", "Е").split()).rstrip(":")


def _html_part(message: Message) -> str:
    candidates: list[str] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        try:
            content = part.get_content()
            if isinstance(content, str):
                candidates.append(content)
        except Exception:
            payload = part.get_payload(decode=True) or b""
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
                candidates.append(content)
    if not candidates:
        # Fallback: check whole message payload or raw string
        raw_text = str(message)
        if "<table" in raw_text.lower():
            return raw_text
        raise MagnitReceiptParseError("Email does not contain an HTML receipt")
    return max(candidates, key=len)


def _is_item_row(row: list[str]) -> bool:
    return (
        len(row) == 4
        and bool(row[0])
        and row[0].upper() != "НАИМ. ПР."
        and all(_MONEY_RE.match(value.replace(" ", "")) for value in row[1:])
    )


def _parse_lines(rows: list[list[str]]) -> list[_ParsedLine]:
    lines: list[_ParsedLine] = []
    current: _ParsedLine | None = None

    for row in rows:
        if _is_item_row(row):
            current = _ParsedLine(
                name=row[0],
                quantity=_parse_decimal(row[1]),
                unit_price=_parse_decimal(row[2]),
                total=_parse_decimal(row[3]),
            )
            lines.append(current)
            continue
        if current is None or len(row) < 2:
            continue
        key = _normalize_key(row[0])
        value = " ".join(row[1:]).strip()
        current.metadata[key] = value
        if key == "МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА":
            current.unit = "kg" if "кг" in value.lower() else "pcs"
        elif key == "КОД ТОВАРА":
            current.marking_code = value or None
        elif key == "ПРИЗНАК ПР. РАСЧЕТА":
            current.calculation_subject = value

    if not lines:
        raise MagnitReceiptParseError("No receipt item rows found")
    return lines


def _extract_package(name: str) -> tuple[Decimal | None, str | None]:
    multipack = _MULTIPACK_RE.search(name)
    if multipack:
        quantity = _parse_decimal(multipack.group("quantity")) * Decimal(multipack.group("count"))
        return quantity, multipack.group("unit").lower()
    matches = list(_PACKAGE_RE.finditer(name))
    if not matches:
        return None, None
    match = matches[-1]
    return _parse_decimal(match.group("quantity")), match.group("unit").lower()


def _aggregate_lines(lines: list[_ParsedLine]) -> list[_ParsedLine]:
    aggregated: list[_ParsedLine] = []
    by_key: dict[tuple[str, str, Decimal, str | None, bool], _ParsedLine] = {}
    for line in lines:
        key = (
            " ".join(line.name.casefold().split()),
            line.unit,
            line.unit_price,
            line.gtin,
            line.inventory_effect,
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = line
            aggregated.append(line)
            continue
        existing.quantity += line.quantity
        existing.total += line.total
    return aggregated


def _find_value(rows: list[list[str]], *keys: str) -> str | None:
    expected = {_normalize_key(key) for key in keys}
    for row in rows:
        if len(row) >= 2 and _normalize_key(row[0]) in expected:
            return " ".join(row[1:]).strip()
    return None


def _find_single_cell(rows: list[list[str]], pattern: re.Pattern[str]) -> str | None:
    for row in rows:
        for cell in row:
            match = pattern.search(cell)
            if match:
                return match.group(1)
    return None


def parse_magnit_receipt_email(raw_message: bytes) -> ReceiptImportRequest:
    if not raw_message:
        raise MagnitReceiptParseError("Email is empty")
    if len(raw_message) > MAX_EMAIL_BYTES:
        raise MagnitReceiptParseError(f"Email exceeds {MAX_EMAIL_BYTES} byte limit")

    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    sender = str(message.get("From", "")).casefold()

    is_trusted = any(
        domain in sender
        for domain in (
            "ofd-magnit.ru",
            "magnit",
            "ofd.ru",
            "1-ofd.ru",
            "taxcom",
            "platformaofd",
            "kontur",
        )
    )

    if not is_trusted:
        raise MagnitReceiptParseError("Email sender is not a recognized OFD provider")

    html_content = _html_part(message)
    parser = _TableRowsParser()
    parser.feed(html_content)
    rows = parser.rows
    parsed_lines = _aggregate_lines(_parse_lines(rows))

    merchant_inn = _find_single_cell(rows, re.compile(r"\bИНН\s+(\d{10,12})\b", re.I))
    purchased_raw = _find_single_cell(rows, re.compile(r"\b(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\b"))
    fiscal_fn = _find_value(rows, "N ФН")
    fiscal_fd = _find_value(rows, "N ФД")
    fiscal_fp = _find_value(rows, "ФП")
    total_raw = _find_value(rows, "ИТОГО")
    if not all((merchant_inn, purchased_raw, fiscal_fn, fiscal_fd, fiscal_fp, total_raw)):
        raise MagnitReceiptParseError("Receipt is missing required fiscal fields")

    purchased_at = datetime.strptime(purchased_raw, "%d.%m.%Y %H:%M").replace(
        tzinfo=ZoneInfo("Europe/Moscow")
    )
    operation = (
        ReceiptOperation.RETURN
        if any("ВОЗВРАТ ПРИХОДА" in cell.upper() for row in rows for cell in row)
        else ReceiptOperation.SALE
    )

    items: list[ReceiptItemInput] = []
    for line in parsed_lines:
        package_quantity, package_unit = _extract_package(line.name)
        items.append(
            ReceiptItemInput(
                name=line.name,
                quantity=line.quantity,
                unit=line.unit,
                unit_price_minor=_money_to_minor(line.unit_price),
                total_minor=_money_to_minor(line.total),
                gtin=line.gtin,
                package_quantity=package_quantity,
                package_unit=package_unit,
                inventory_effect=line.inventory_effect,
            )
        )

    order_number = _find_value(rows, "Номер заказа")
    receipt_number = _find_single_cell(rows, re.compile(r"\bN:\s*(\d+)\b", re.I))
    message_id = str(message.get("Message-ID", "")).strip().strip("<>") or None
    subject = str(message.get("Subject", ""))[:500]

    return ReceiptImportRequest(
        provider=PARSER_NAME,
        fiscal_fn=fiscal_fn,
        fiscal_fd=fiscal_fd,
        fiscal_fp=fiscal_fp,
        operation=operation,
        merchant_name="Магнит / АО Тандер",
        merchant_inn=merchant_inn,
        purchased_at=purchased_at,
        total_minor=_money_to_minor(_parse_decimal(total_raw)),
        currency="RUB",
        source_message_id=message_id,
        items=items,
        raw_payload={
            "parser": PARSER_NAME,
            "parser_version": PARSER_VERSION,
            "subject": subject,
            "order_number": order_number,
            "receipt_number": receipt_number,
            "inventory_lines": sum(item.inventory_effect for item in items),
            "non_inventory_lines": sum(not item.inventory_effect for item in items),
        },
    )
