from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fridge_api.services.enrichment.types import (
    EnrichmentQuery,
    EnrichmentResult,
    nutrition_plausible,
)

logger = logging.getLogger(__name__)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_STORE_URL = (
    "https://eda.yandex.ru/retail/magnit_celevaya"
    "?placeSlug=magnit_celevaya_sh97c&relatedBrandSlug=magnit_celevaya"
)

_STOP = {
    "для",
    "под",
    "над",
    "без",
    "или",
    "вес",
    "акция",
    "вкус",
    "сорт",
    "новый",
    "урожай",
    "магнит",
    "свежесть",
    "дизайн",
    "упаковки",
    "упаковка",
    "ассортименте",
    "натуральный",
    "состав",
    "россия",
    "полутвердый",
    "быстрозамороженная",
    "быстрозамороженный",
    "замороженная",
    "охлажденный",
    "охл",
}

_GENERIC = {"напиток", "продукт", "изделие", "смесь", "пакет", "десерт", "масса"}

_EXTRACT_CARDS = """
JSON.stringify(
  [...document.querySelectorAll('[data-testid="product-card-root"]')]
    .filter(card => !card.closest('[data-testid="slided-carousel-root"]'))
    .map(card => ({
      name: card.querySelector('[data-testid="product-card-name"]')?.innerText?.trim() || '',
      weight: card.querySelector('[data-testid="product-card-weight"]')?.innerText?.trim() || '',
      image_url: card.querySelector('img')?.src
        || card.querySelector('picture source')?.srcset?.split(' ')[0] || '',
      url: card.querySelector('a[href*="/product/"]')?.href || '',
    }))
    .filter(x => x.name.length > 3)
)
"""

_EXTRACT_NUTRIENTS = """
JSON.stringify({
  name: document.querySelector('[data-testid="product-full-card-name"]')?.innerText || null,
  weight: document.querySelector('[data-testid="product-full-card-weight"]')?.innerText || null,
  image_url: null,
  nutrients: [...document.querySelectorAll('[data-testid="product-card-nutrients-item-title"]')]
    .map((title, index) => ({
      title: title.innerText.trim(),
      value: document.querySelectorAll('[data-testid="product-card-nutrients-item-value"]')[index]
        ?.innerText?.trim() || null,
    })),
})
"""


def _tokens(name: str) -> list[str]:
    normalized = name.casefold().replace("ё", "е")
    return re.findall(r"[а-яa-z0-9]+", normalized)


def _sig_tokens(name: str) -> set[str]:
    return {token for token in _tokens(name) if len(token) >= 3 and token not in _STOP}


def _stems(words: set[str]) -> set[str]:
    return {word[:5] if len(word) >= 5 else word for word in words}


def parse_percent(name: str) -> Decimal | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", name)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None


def parse_weight_and_unit(name: str) -> tuple[Decimal | None, str | None]:
    patterns = (
        (r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|g)\b", Decimal("1"), "g"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:кг|kg)\b", Decimal("1000"), "g"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:мл|ml)\b", Decimal("1"), "ml"),
        (r"(\d+(?:[.,]\d+)?)\s*(?:л|l)\b", Decimal("1000"), "ml"),
        (r"(\d+)\s*(?:шт|пак|капс)\b", Decimal("1"), "pcs"),
    )
    for pattern, multiplier, unit in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if not match:
            continue
        try:
            return Decimal(match.group(1).replace(",", ".")) * multiplier, unit
        except InvalidOperation:
            return None, None
    return None, None


def is_strict_match(
    receipt_name: str,
    found_name: str,
    *,
    receipt_qty: Decimal | None = None,
    receipt_unit: str | None = None,
) -> bool:
    query = _sig_tokens(receipt_name) - _GENERIC
    found = _sig_tokens(found_name)
    if not query:
        return False
    overlap = _stems(query) & _stems(found)
    if len(overlap) * 10 < len(_stems(query)) * 7:
        return False
    receipt_percent = parse_percent(receipt_name)
    found_percent = parse_percent(found_name)
    if (
        receipt_percent is not None
        and found_percent is not None
        and receipt_percent != found_percent
    ):
        return False
    found_qty, found_unit = parse_weight_and_unit(found_name)
    query_qty, query_unit = parse_weight_and_unit(receipt_name)
    qty = receipt_qty or query_qty
    unit = (receipt_unit or query_unit or "").casefold()
    found_unit = (found_unit or "").casefold()
    if qty is not None and found_qty is not None:
        if unit and found_unit and unit != found_unit and {unit, found_unit} != {"g", "ml"}:
            return False
        if abs(qty - found_qty) > qty * Decimal("0.2"):
            return False
    return True


def parse_nutrient_value(text: str) -> Decimal | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", (text or "").replace("\xa0", " "))
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value >= 0 else None


def parse_yandex_nutrients(
    items: list[dict[str, Any]],
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    mapped: dict[str, Decimal] = {}
    aliases = {
        "kcal": "kcal",
        "ккал": "kcal",
        "calories": "kcal",
        "protein": "protein",
        "белки": "protein",
        "белок": "protein",
        "fat": "fat",
        "жиры": "fat",
        "жир": "fat",
        "carbohydrates": "carbs",
        "carbs": "carbs",
        "углеводы": "carbs",
        "углевод": "carbs",
    }
    for item in items:
        title = str(item.get("title") or "").casefold().strip()
        key = aliases.get(title)
        if key is None:
            continue
        value = parse_nutrient_value(str(item.get("value") or ""))
        if value is not None:
            mapped[key] = value
    try:
        numbers = mapped["kcal"], mapped["protein"], mapped["fat"], mapped["carbs"]
    except KeyError:
        return None
    if not nutrition_plausible(*numbers):
        return None
    return numbers


def eda_product_image(url: str | None) -> str | None:
    if url and "avatars.mds.yandex.net/get-eda" in url:
        return url
    return None


def clean_query(raw: str) -> list[str]:
    cleaned = re.sub(r"\s+[*x×]\s*\d+.*", " ", raw)
    cleaned = re.sub(
        r"\bдизайн(?:\s+упаковки)?(?:\s+в\s+ассортименте)?\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\bцвет\s+яиц.*", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[^а-яА-Яa-zA-Z0-9%\s\-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    queries: list[str] = []
    if cleaned:
        queries.append(cleaned)
    words = cleaned.split()
    if len(words) > 4:
        queries.append(" ".join(words[:4]))
    return list(dict.fromkeys(query for query in queries if query))


@dataclass(frozen=True, slots=True)
class YandexCard:
    name: str
    url: str
    image_url: str | None
    nutrients: tuple[Decimal, Decimal, Decimal, Decimal] | None
    net_quantity: Decimal | None
    net_unit: str | None


class _CdpPage:
    def __init__(self, websocket_url: str, timeout: float) -> None:
        import websocket

        self._socket = websocket.create_connection(
            websocket_url,
            timeout=timeout,
            suppress_origin=True,
            http_proxy_host=None,
        )
        self._next_id = 0

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            pass

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        call_id = self._next_id
        self._socket.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self._socket.recv())
            if message.get("id") != call_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = result.get("result", {})
        if value.get("subtype") == "error":
            raise RuntimeError(value.get("description") or "JavaScript evaluation failed")
        return value.get("value")

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})


def _store_slug(url: str) -> str | None:
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("placeSlug")
    return values[0] if values else None


def _search_url(base_url: str, slug: str, query: str) -> str:
    parts = urllib.parse.urlsplit(base_url)
    params = urllib.parse.parse_qs(parts.query)
    params["placeSlug"] = [slug]
    params["relatedBrandSlug"] = ["magnit_celevaya"]
    params["query"] = [query]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(params, doseq=True), "")
    )


class YandexEdaProvider:
    """Magnit storefront on Yandex Eda: exact card match plus on-page KBJU."""

    def __init__(
        self,
        *,
        cdp_url: str = DEFAULT_CDP_URL,
        store_url: str = DEFAULT_STORE_URL,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.cdp_url = cdp_url.rstrip("/")
        self.store_url = store_url
        self.timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._page: _CdpPage | None = None
        self._page_id: str | None = None
        self._slug: str | None = None

    def close(self) -> None:
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._page_id is not None:
            try:
                self._opener.open(
                    urllib.request.Request(f"{self.cdp_url}/json/close/{self._page_id}"),
                    timeout=2.0,
                )
            except Exception:
                pass
            self._page_id = None
        self._slug = None

    def lookup(self, line: EnrichmentQuery) -> EnrichmentResult | None:
        card = self.lookup_card(line)
        if card is None or card.nutrients is None:
            return None
        return self._to_result(line, card)

    def lookup_card(self, line: EnrichmentQuery) -> YandexCard | None:
        try:
            self._ensure_page()
        except Exception as exc:
            logger.warning("Yandex Eda CDP unavailable: %s", exc)
            return None
        assert self._page is not None
        for query in clean_query(line.raw_name):
            try:
                card = self._search_and_open(query, line)
            except Exception as exc:
                logger.debug("Yandex Eda search failed for %r: %s", query, exc)
                continue
            if card is not None:
                return card
        return None

    def _ensure_page(self) -> None:
        if self._page is not None:
            return
        request = urllib.request.Request(
            f"{self.cdp_url}/json/new?{urllib.parse.quote(self.store_url, safe='')}",
            method="PUT",
        )
        with self._opener.open(request, timeout=6.0) as response:
            page_info = json.load(response)
        page_id = page_info.get("id")
        ws_url = page_info.get("webSocketDebuggerUrl")
        if not page_id or not ws_url:
            raise RuntimeError("Chrome did not return a debuggable page")
        page = _CdpPage(ws_url, self.timeout_seconds)
        page.call("Page.enable")
        page.call("Runtime.enable")
        time.sleep(8.0)
        location = str(page.evaluate("location.href") or self.store_url)
        self._page = page
        self._page_id = str(page_id)
        self._slug = _store_slug(location) or _store_slug(self.store_url)

    def _search_and_open(self, query: str, line: EnrichmentQuery) -> YandexCard | None:
        assert self._page is not None
        slug = self._slug or _store_slug(self.store_url)
        if not slug:
            return None
        self._page.navigate(_search_url(self.store_url, slug, query))
        deadline = time.monotonic() + 12.0
        cards: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            payload = self._page.evaluate(_EXTRACT_CARDS)
            cards = json.loads(payload or "[]")
            if cards:
                break
            time.sleep(0.5)
        match = None
        for card in cards:
            name = str(card.get("name") or "")
            if is_strict_match(
                line.raw_name,
                name,
                receipt_qty=line.package_quantity,
                receipt_unit=line.package_unit,
            ):
                match = card
                break
        if match is None:
            return None
        clicked = self._page.evaluate(
            """
            ((target) => {
              const cards = [...document.querySelectorAll('[data-testid="product-card-root"]')]
                .filter(card => !card.closest('[data-testid="slided-carousel-root"]'));
              const name = item =>
                (item.querySelector('[data-testid="product-card-name"]')?.innerText || '').trim();
              const card = cards.find(item => name(item) === target);
              if (!card) return false;
              (card.querySelector('a') || card).click();
              return true;
            })
            """
            + f"({json.dumps(match['name'])})"
        )
        if not clicked:
            return None
        details: dict[str, Any] = {}
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            payload = self._page.evaluate(_EXTRACT_NUTRIENTS)
            details = json.loads(payload or "{}")
            if details.get("name") or details.get("nutrients"):
                break
            time.sleep(0.4)
        self._page.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))"
        )
        name = str(details.get("name") or match.get("name") or line.raw_name)
        weight_hint = details.get("weight") or match.get("weight") or ""
        qty, unit = parse_weight_and_unit(f"{name} {weight_hint}")
        image_url = eda_product_image(match.get("image_url")) or eda_product_image(
            details.get("image_url")
        )
        return YandexCard(
            name=name,
            url=str(match.get("url") or ""),
            image_url=image_url,
            nutrients=parse_yandex_nutrients(details.get("nutrients") or []),
            net_quantity=qty or line.package_quantity,
            net_unit=unit or line.package_unit,
        )

    def _to_result(self, line: EnrichmentQuery, card: YandexCard) -> EnrichmentResult:
        assert card.nutrients is not None
        kcal, protein, fat, carbs = card.nutrients
        return EnrichmentResult(
            canonical_name=card.name[:300],
            brand=None,
            gtin=line.gtin,
            net_quantity=card.net_quantity,
            net_unit=card.net_unit,
            kcal_per_100=kcal,
            protein_per_100=protein,
            fat_per_100=fat,
            carbs_per_100=carbs,
            image_url=card.image_url,
            nutrition_source_url=card.url,
            image_source_url=card.image_url,
            confidence=Decimal("0.95"),
            provider="yandex_eda_magnit",
            verified=True,
        )


# Backward-compatibility alias
YandexEdaMagnitProvider = YandexEdaProvider
