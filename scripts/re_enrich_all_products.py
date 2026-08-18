#!/usr/bin/env python3
"""Batch enrich all products in fridge.db with genuine images from Yandex Eda."""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal

from fridge_api.db import SessionLocal
from fridge_api.models import Product

# Import proven Chrome CDP scraper logic
sys.path.insert(0, "/home/megusto/.hermes/skills/health/glucotracker-coach/scripts")
from magnit_catalog import ChromePage, create_page, close_page, extract_products, store_slug, search_url, wait_until, current_location


def clean_query_term(raw: str) -> str:
    s = re.sub(r"\s+[*x×]\s*\d+.*", " ", raw)
    s = re.sub(r"\b\d+[\.,]?\d*\s*%", " ", s)
    s = re.sub(r"\b\d+[\.,]?\d*\s*(?:г|гр|кг|мл|л|шт|пак)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(вес|уц|акция|кусков\w*|охл\w*|зам\w*|быстрозамороженн\w*|замороженн\w*|пастеризованн\w*|маслозавод|мз|бзмж|свежесть|дизайн|упаковки|ассортименте|состав|натуральный|в вафельном рожке|со сгущенкой|слоеный)\b",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"[^а-яА-Яa-zA-Z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_name_match(target: str, cand: str) -> bool:
    t_words = set(re.findall(r"[а-яa-z]{3,}", target.lower()))
    c_words = set(re.findall(r"[а-яa-z]{3,}", cand.lower()))
    stop = {"для", "под", "над", "без", "или", "вес", "акция", "вкус", "сорт", "новый", "урожай", "магнит", "свежесть", "дизайн", "упаковки", "ассортименте", "хлеб", "продукт", "натуральный", "состав"}
    t_sig = t_words - stop
    c_sig = c_words - stop
    if not t_sig or not c_sig:
        return True
    overlap = t_sig & c_sig
    if overlap:
        return True
    for tw in t_sig:
        for cw in c_sig:
            if (len(tw) >= 4 and tw[:4] == cw[:4]) or (len(cw) >= 4 and cw[:4] == tw[:4]):
                return True
    return False


def main() -> None:
    session = SessionLocal()
    products = session.query(Product).all()

    # Find products needing genuine images
    targets: dict[str, list[Product]] = {}
    for p in products:
        if not p.canonical_name:
            continue
        if p.image_url and "avatars.mds.yandex.net/get-eda" in p.image_url:
            continue
        targets.setdefault(p.canonical_name, []).append(p)

    print(f"Total products in DB: {len(products)}. Unique products needing images: {len(targets)}.")
    if not targets:
        print("All products are already enriched with genuine images!")
        return

    cdp_url = "http://127.0.0.1:9222"
    base_store_url = "https://eda.yandex.ru/retail/magnit_celevaya?placeSlug=magnit_celevaya_sh97c&relatedBrandSlug=magnit_celevaya"

    print("Opening Yandex Eda catalog tab via Chrome CDP...")
    page_info = create_page(cdp_url, base_store_url)
    page_id = page_info["id"]
    ws_url = page_info["webSocketDebuggerUrl"]

    page = ChromePage(ws_url, timeout=25.0)
    page.call("Page.enable")
    page.call("Runtime.enable")
    time.sleep(8.0)

    resolved_url = current_location(page)
    resolved_slug = store_slug(resolved_url) or store_slug(base_store_url)
    print(f"Store initialized: {resolved_slug} ({resolved_url})")

    updated_unique = 0
    try:
        for idx, (canonical_name, prod_list) in enumerate(targets.items(), 1):
            q_clean = clean_query_term(canonical_name)
            queries = [q_clean]
            
            # Additional brand keyword if available
            words = q_clean.split()
            eng_words = [w for w in words if re.match(r"^[a-zA-Z]+$", w)]
            if eng_words and eng_words[0] not in queries:
                queries.append(eng_words[0])
            if len(words) > 2:
                queries.append(" ".join(words[:2]))

            print(f"\n[{idx}/{len(targets)}] Searching for: \"{canonical_name}\"")
            
            matched_card = None
            for query in queries:
                if not query:
                    continue
                url = search_url(base_store_url, resolved_slug, query)
                page.navigate(url)
                wait_until(
                    page,
                    "location.hostname === 'eda.yandex.ru' && document.readyState !== 'loading'",
                    15.0,
                )
                time.sleep(1.5)
                wait_until(
                    page,
                    "document.querySelector('[data-testid=\"product-card-root\"]') || document.body.innerText.includes('Ничего не найдено')",
                    10.0,
                )
                time.sleep(1.0)
                cards = extract_products(page, limit=15)
                
                for card in cards:
                    card_name = card.get("name") or ""
                    if is_name_match(canonical_name, card_name) and card.get("image_url"):
                        matched_card = card
                        break
                
                if matched_card:
                    break

            if matched_card:
                img_url = matched_card["image_url"]
                print(f"   ✓ MATCH: {matched_card['name']}")
                print(f"     Image: {img_url}")
                for p in prod_list:
                    p.image_url = img_url
                    p.image_source_url = img_url
                session.commit()
                updated_unique += 1
            else:
                print(f"   — No match in catalog.")

    finally:
        page.close()
        close_page(cdp_url, page_id)

    print(f"\n🎉 Enrichment complete! Enriched {updated_unique}/{len(targets)} unique products.")


if __name__ == "__main__":
    main()
