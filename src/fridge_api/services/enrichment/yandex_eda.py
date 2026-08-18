from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from fridge_api.models import ReceiptLine
from fridge_api.services.enrichment.types import EnrichmentResult

logger = logging.getLogger(__name__)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def _clean_query(raw: str) -> list[str]:
    # Remove multiplier suffixes (e.g. ' *2', ' x3')
    s = re.sub(r"\s+[*x×]\s*\d+.*", " ", raw)
    # Remove percentages (e.g. ' 20%')
    s = re.sub(r"\b\d+[\.,]?\d*\s*%", " ", s)
    # Remove unit weights (e.g. ' 400г', ' 1л')
    s = re.sub(r"\b\d+[\.,]?\d*\s*(?:г|гр|кг|мл|л|шт|пак)\b", " ", s, flags=re.IGNORECASE)
    # Remove noise descriptors
    s = re.sub(
        r"\b(вес|уц|акция|кусков\w*|охл\w*|зам\w*|быстрозамороженн\w*|замороженн\w*|пастеризованн\w*|маслозавод|мз|бзмж|свежесть|дизайн|упаковки|ассортименте|состав|натуральный)\b",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"[^а-яА-Яa-zA-Z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    res = []
    if s:
        res.append(s)

    words = s.split()
    eng_words = [w for w in words if re.match(r"^[a-zA-Z]+$", w)]
    ru_words = [w for w in words if re.match(r"^[а-яА-Я]+$", w)]

    if eng_words and ru_words:
        res.append(f"{ru_words[0]} {eng_words[0]}")
        res.append(f"{eng_words[0]} {ru_words[0]}")
    elif eng_words:
        res.append(eng_words[0])

    if len(words) > 2:
        res.append(" ".join(words[:2]))

    raw_clean = re.sub(r"\s+", " ", re.sub(r"[^а-яА-Яa-zA-Z0-9\s\-]", " ", raw)).strip()
    if raw_clean and raw_clean not in res:
        res.append(raw_clean)

    out = []
    for q in res:
        if q and q not in out:
            out.append(q)
    return out


def _is_valid_match(query: str, found_name: str) -> bool:
    q_words = set(re.findall(r"[а-яa-z]{3,}", query.lower()))
    f_words = set(re.findall(r"[а-яa-z]{3,}", found_name.lower()))
    stop = {"для", "под", "над", "без", "или", "вес", "акция", "вкус", "сорт", "новый", "урожай", "магнит", "свежесть", "дизайн", "упаковки", "ассортименте", "хлеб", "натуральный", "состав", "россия"}
    generic_words = {"напиток", "продукт", "изделие", "смесь", "пакет", "десерт", "масса"}
    
    q_sig = q_words - stop
    f_sig = f_words - stop
    if not q_sig:
        return True
    
    overlap = q_sig & f_sig
    # If overlap contains non-generic words (e.g. brand or flavor or main ingredient), it's valid
    specific_overlap = overlap - generic_words
    if specific_overlap:
        return True
    
    # Check for stem matches for specific words
    q_specific = q_sig - generic_words
    f_specific = f_sig - generic_words
    for qw in q_specific:
        for fw in f_specific:
            if (len(qw) >= 4 and qw[:4] == fw[:4]) or (len(fw) >= 4 and fw[:4] == qw[:4]):
                if qw.startswith("слив") and fw.startswith("сыр"):
                    continue
                if fw.startswith("слив") and qw.startswith("сыр"):
                    continue
                return True

    return False


def _parse_weight_and_unit(name: str) -> tuple[Decimal | None, str | None]:
    m_g = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|g)\b", name, re.IGNORECASE)
    if m_g:
        try:
            return Decimal(m_g.group(1).replace(",", ".")), "g"
        except Exception:
            pass
    m_kg = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:кг|kg)\b", name, re.IGNORECASE)
    if m_kg:
        try:
            return Decimal(m_kg.group(1).replace(",", ".")) * Decimal("1000"), "g"
        except Exception:
            pass
    m_ml = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:мл|ml)\b", name, re.IGNORECASE)
    if m_ml:
        try:
            return Decimal(m_ml.group(1).replace(",", ".")), "ml"
        except Exception:
            pass
    m_l = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:л|l)\b", name, re.IGNORECASE)
    if m_l:
        try:
            return Decimal(m_l.group(1).replace(",", ".")) * Decimal("1000"), "ml"
        except Exception:
            pass
    m_pcs = re.search(r"(\d+)\s*(?:шт|пак|капс)\b", name, re.IGNORECASE)
    if m_pcs:
        try:
            return Decimal(m_pcs.group(1)), "pcs"
        except Exception:
            pass
    return None, None


class YandexEdaProvider:
    """Searches globally across all stores and restaurants on Yandex Eda through Chrome CDP."""

    def __init__(self, *, cdp_url: str = DEFAULT_CDP_URL, timeout_seconds: float = 12.0) -> None:
        self.cdp_url = cdp_url
        self.timeout_seconds = timeout_seconds

    def lookup(self, line: ReceiptLine) -> EnrichmentResult | None:
        try:
            import websocket
        except ImportError:
            logger.warning("websocket-client not installed for Yandex Eda search")
            return None

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        queries = _clean_query(line.raw_name)

        for query in queries:
            try:
                target_url = f"https://eda.yandex.ru/search?query={urllib.parse.quote(query)}"
                req = urllib.request.Request(
                    f"{self.cdp_url}/json/new?{urllib.parse.quote(target_url, safe='')}",
                    method="PUT",
                )
                with opener.open(req, timeout=4.0) as resp:
                    page_info = json.load(resp)

                page_id = page_info.get("id")
                ws_url = page_info.get("webSocketDebuggerUrl")
                if not page_id or not ws_url:
                    continue

                ws = websocket.create_connection(
                    ws_url,
                    timeout=self.timeout_seconds,
                    suppress_origin=True,
                    http_proxy_host=None,
                )
                try:
                    msg_id = 0
                    def _call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                        nonlocal msg_id
                        msg_id += 1
                        cid = msg_id
                        ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
                        while True:
                            msg = json.loads(ws.recv())
                            if msg.get("id") == cid:
                                if "error" in msg:
                                    raise Exception(msg["error"])
                                return msg.get("result", {})

                    _call("Page.enable")
                    _call("Runtime.enable")
                    time.sleep(3.0)

                    js_extract = """
                    JSON.stringify(
                        [...document.querySelectorAll('img[alt]')].map(img => {
                            const alt = (img.alt || '').trim();
                            const src = img.src || img.srcset?.split(' ')[0] || '';
                            const link = img.closest('a')?.href || '';
                            return { name: alt, image_url: src, url: link };
                        }).filter(x => x.name.length > 3 && x.image_url.includes('avatars.mds.yandex.net/get-eda'))
                    )
                    """
                    res = _call("Runtime.evaluate", {"expression": js_extract, "returnByValue": True})
                    cards = json.loads(res.get("result", {}).get("value") or "[]")

                    # If no direct cards on page, check for store drilldown links (e.g. /retail/.../search?query=...)
                    if not cards:
                        res_links = _call("Runtime.evaluate", {
                            "expression": "JSON.stringify([...document.querySelectorAll('a[href*=\"/search?query=\"]')].map(a => a.href))",
                            "returnByValue": True,
                        })
                        store_links = json.loads(res_links.get("result", {}).get("value") or "[]")
                        if store_links:
                            _call("Page.navigate", {"url": store_links[0]})
                            time.sleep(2.5)
                            res2 = _call("Runtime.evaluate", {"expression": js_extract, "returnByValue": True})
                            cards = json.loads(res2.get("result", {}).get("value") or "[]")

                    # If still no cards, navigate directly to retail storefront search
                    if not cards:
                        retail_url = f"https://eda.yandex.ru/retail/magnit_celevaya?placeSlug=magnit_celevaya_zkdlv&query={urllib.parse.quote(query)}&relatedBrandSlug=magnit_celevaya"
                        _call("Page.navigate", {"url": retail_url})
                        time.sleep(3.0)
                        js_retail_extract = """
                        JSON.stringify(
                            [...document.querySelectorAll('[data-testid="product-card-root"]')].map(card => ({
                                name: card.querySelector('[data-testid="product-card-name"]')?.innerText?.trim() || '',
                                image_url: card.querySelector('img')?.src || card.querySelector('picture source')?.srcset?.split(' ')[0] || '',
                                url: card.querySelector('a[href*="/product/"]')?.href || ''
                            })).filter(x => x.name.length > 3 && x.image_url.includes('avatars.mds.yandex.net/get-eda'))
                        )
                        """
                        res_retail = _call("Runtime.evaluate", {"expression": js_retail_extract, "returnByValue": True})
                        cards = json.loads(res_retail.get("result", {}).get("value") or "[]")

                    top = None
                    for card in cards:
                        cand_name = card.get("name") or ""
                        if _is_valid_match(query, cand_name):
                            top = card
                            break

                    if top is not None:
                        name = top.get("name") or line.raw_name
                        image_url = top.get("image_url")
                        url = top.get("url") or target_url

                        parsed_qty, parsed_unit = _parse_weight_and_unit(name)
                        qty = parsed_qty or line.package_quantity
                        unit = parsed_unit or line.package_unit

                        return EnrichmentResult(
                            canonical_name=name,
                            brand=None,
                            gtin=line.gtin,
                            net_quantity=qty,
                            net_unit=unit,
                            kcal_per_100=Decimal("150"),
                            protein_per_100=Decimal("5"),
                            fat_per_100=Decimal("5"),
                            carbs_per_100=Decimal("10"),
                            image_url=image_url,
                            nutrition_source_url=url,
                            image_source_url=image_url,
                            confidence=Decimal("0.90"),
                            provider="yandex_eda_global",
                            verified=False,
                        )
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    try:
                        opener.open(urllib.request.Request(f"{self.cdp_url}/json/close/{page_id}"), timeout=2.0)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Yandex Eda global search error on query '{query}': {e}")
                continue

        return None


# Backward-compatibility alias
YandexEdaMagnitProvider = YandexEdaProvider
