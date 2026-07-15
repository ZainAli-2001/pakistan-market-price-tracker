"""
=============================================================
  daraz_scraper.py — Forecasting-Ready Daraz Scraper
=============================================================
"""

import logging
import statistics
import time
from datetime import datetime
from urllib.parse import urljoin
import random

from utils.commodity_filters import is_valid_commodity
from utils.config import DEBUG_DARAZ, MIN_SAMPLE_FOR_MEDIAN, PAGE_DELAY, SCRAPER_VERSION, PIPELINE_VERSION, USER_AGENTS
from utils.debug import log_parsed_item, log_rejected_item, save_failed_request, save_html, save_json
from utils.http import create_session, get_with_retry
from utils.prices import calculate_unit_price, clean_price
from utils.rejections import add_rejection
from utils.statistics import create_stats, create_scrape_result, increment, print_summary
from utils.text import preprocess_title
from utils.units import extract_pack_multiplier, extract_unit
from utils.validation import validate_unit_price

log = logging.getLogger(__name__)

SCRAPER_NAME = "daraz"

# Only stable commodity categories tracked.
PRODUCTS = {
    "atta flour":    "flour",
    "basmati rice":  "rice",
    "cooking oil":   "oil",
    "daal chana":    "pulses",
    "daal masoor":   "pulses",
    "sugar":         "sugar",
    "desi ghee":     "ghee",
    "olpers milk":   "dairy",
    "tapal danedar": "tea",
}

KEYWORD_DELAY = 3   # longer pause between keywords than between pages

# PAGES_PER_PRODUCT = 2   # ~40 items per page → ~80 per keyword
MAX_PAGES_PER_PRODUCT = 8      # hard safety cap
MIN_ACCEPTED_PER_PAGE = 10
MAX_CONSECUTIVE_LOW_YIELD = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.daraz.pk/",
}

DARAZ_BASE_URL = "https://www.daraz.pk"
DARAZ_SEARCH_URL = "https://www.daraz.pk/catalog/?ajax=true"

SOURCE = "daraz"


def fetch_daraz_page(session, keyword: str, page: int, stats: dict) -> list:
    """
    Call Daraz's internal search API for one page of results.
    Returns raw list of product dicts from the JSON response.
    """
    params = {"q": keyword, "page": page, "sort": "salesOld"}

    response = get_with_retry(session, DARAZ_SEARCH_URL, params=params)
    if response is None:
        save_failed_request(SCRAPER_NAME, {
            "keyword": keyword, "page": page,
            "status_code": None, "url": DARAZ_SEARCH_URL, "error": "request failed after retries",
        })
        return []

    try:
        data = response.json()
    except ValueError:
        log.warning("  daraz '%s' page %d: non-JSON response (likely anti-bot challenge)", keyword, page)
        if DEBUG_DARAZ:
            save_html(SCRAPER_NAME, f"non_json_response_{keyword}_{page}.html", response.text)
        return []

    mods = data.get("mods")

    # Daraz occasionally changes its response shape without notice —
    # fail loudly and keep a snapshot instead of silently returning nothing.
    if mods is None or "listItems" not in mods:
        log.warning("  daraz '%s' page %d: unexpected JSON schema (missing mods/listItems)", keyword, page)
        if DEBUG_DARAZ:
            save_json(SCRAPER_NAME, f"unexpected_schema_{keyword}_{page}.json", data)
        return []

    items = mods["listItems"]
    log.info("  daraz '%s' page %d → %d items", keyword, page, len(items))
    return items


def parse_item(raw: dict, keyword: str, category: str, run_id: str, stats: dict, rejections: list):
    """
    Extract and clean a single Daraz API product dict.
    Returns a forecasting-ready record, or None if invalid.

    Layer 1 — Raw prices: original_price, sale_price, final_price
    Layer 2 — Normalized price: unit_value, unit_type, unit_price
    Layer 3 — Context metadata: name, url, category, keyword, source, run_id, scraped_at
    """
    increment(stats, "total_received")

    url = urljoin(DARAZ_BASE_URL, raw.get("itemUrl", ""))

    original_title = raw.get("name", "").strip()
    name = preprocess_title(original_title)
    if not is_valid_commodity(name, category):
        increment(stats, "filtered_products")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=category,
            name=name,
            url=url,
            reason="commodity_filter",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_DARAZ:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None
    if not name:
        increment(stats, "missing_title")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=category,
            name=original_title,
            url=url,
            reason="missing_title",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_DARAZ:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    original_price = clean_price(raw.get("originalPrice"))
    sale_price     = clean_price(raw.get("price"))

    valid_prices = [p for p in [sale_price, original_price] if p is not None]
    final_price  = min(valid_prices) if valid_prices else None

    if final_price is None:
        increment(stats, "missing_price")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=category,
            name=name,
            url=url,
            reason="missing_price",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_DARAZ:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    unit_value, unit_type, pack_applied = extract_unit(name)
    if unit_value is None:
        increment(stats, "missing_unit")
    elif not pack_applied:
        pack = extract_pack_multiplier(name)
        if pack > 1:
            unit_value = round(unit_value * pack, 4)

    # Outlier validation happens per-keyword in validate_batch(), once the
    # full sample is available to compute a reliable median.
    unit_price = calculate_unit_price(final_price, unit_value)

    try:
        rating = float(raw.get("ratingScore")) if raw.get("ratingScore") else None
    except (ValueError, TypeError):
        rating = None

    if DEBUG_DARAZ:
        log_parsed_item(SCRAPER_NAME, {
            "original_title": original_title,
            "normalized_title": name,
            "unit_value": unit_value,
            "unit_type": unit_type,
            "unit_price": unit_price,
        })

    increment(stats, "parsed")

    return {
        "run_id":       run_id,
        "source":       SOURCE,
        "keyword":      keyword,
        "category":     category,
        "name":         name,
        "url":          url,

        "original_price": original_price,
        "sale_price":     sale_price,
        "final_price":    final_price,

        "unit_value":  unit_value,
        "unit_type":   unit_type,
        "unit_price":  unit_price,

        "rating":        rating,
        "review_count":  raw.get("review"),

        "scraper_version": SCRAPER_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "scraped_at":    datetime.now().isoformat(),
    }


def validate_batch(items: list, category: str, run_id: str, stats: dict, rejections: list):
    """
    Post-process one keyword's collected items: compute the batch's own
    unit_price median (once sample size allows) and reject outliers against it.
    Returns (validated_items, median_or_None).
    """
    prices = [item["unit_price"] for item in items if item["unit_price"] is not None]
    median = statistics.median(prices) if len(prices) >= MIN_SAMPLE_FOR_MEDIAN else None

    kept_items = []
    for item in items:
        raw_price = item["unit_price"]
        validated_price, threshold_used, threshold_type = validate_unit_price(
            raw_price, category, reference_median=median
        )

        if raw_price is not None and validated_price is None:
            increment(stats, "outliers")
            reject_kwargs = dict(
                run_id=run_id,
                scraper=SCRAPER_NAME,
                category=category,
                name=item["name"],
                url=item["url"],
                reason="outlier_unit_price",
                unit_value=item["unit_value"],
                unit_type=item["unit_type"],
                unit_price=raw_price,
                threshold_used=threshold_used,
                threshold_type=threshold_type,
                pipeline_version=item.get("pipeline_version", PIPELINE_VERSION),
            )
            if DEBUG_DARAZ:
                log_rejected_item(SCRAPER_NAME, reject_kwargs)
            add_rejection(rejections, **reject_kwargs)

            # Outlier (either direction) — drop the row from the product
            # table rather than insert it with a nulled-out unit_price. The
            # full details (unit_value, unit_price, threshold) are still
            # preserved above in scrape_rejections for later inspection.
            continue

        item["unit_price"] = validated_price
        kept_items.append(item)

    return kept_items, median


def scrape_daraz() -> list:
    """
    Scrape all configured products from Daraz.pk.
    Returns a forecasting-ready list of item dicts.
    """
    log.info("--- Daraz scrape starting ---")
    all_items = []
    seen = set()
    stats = create_stats()
    rejections = []
    category_medians = {}
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")

    session = create_session(headers={**HEADERS, "User-Agent": random.choice(USER_AGENTS)})
    try:
        for keyword, category in PRODUCTS.items():
            log.info("Scraping: '%s' (%s)", keyword, category)
            consecutive_low_yield_pages = 0 # addition
            keyword_batch = []
            # for page in range(1, PAGES_PER_PRODUCT + 1):
            for page in range(1, MAX_PAGES_PER_PRODUCT + 1):    
                raw_items = fetch_daraz_page(session, keyword, page, stats)
                if not raw_items:
                    log.info("No items returned for '%s' page %d", keyword, page)
                    break
                accepted_this_page = 0
                for raw in raw_items:
                    try:
                        parsed = parse_item(raw, keyword, category, run_id, stats, rejections)
                    except Exception as e:
                        increment(stats, "parsing_failures")
                        log.error("  daraz parse error for '%s': %s", keyword, e)
                        continue

                    if not parsed:
                        continue

                    dedup_key = (parsed["name"], parsed["url"])
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    keyword_batch.append(parsed)
                    accepted_this_page += 1

                # debug block start 
                if accepted_this_page < MIN_ACCEPTED_PER_PAGE:
                    consecutive_low_yield_pages += 1
                else:
                    consecutive_low_yield_pages = 0

                if consecutive_low_yield_pages >= MAX_CONSECUTIVE_LOW_YIELD:
                    log.info(
                        "Two consecutive low-yield pages for '%s' — stopping",
                        keyword
                    )
                    break
                # debug block end
                time.sleep(PAGE_DELAY)

            validated_batch, median = validate_batch(keyword_batch, category, run_id, stats, rejections)
            all_items.extend(validated_batch)
            category_medians[category] = median

            time.sleep(KEYWORD_DELAY)
    finally:
        session.close()

    log.info("Daraz total: %d items", len(all_items))
    print_summary(stats, SCRAPER_NAME)
    return create_scrape_result(
        items=all_items,
        stats=stats,
        rejections=rejections,
        run_id=run_id,
        scraper=SCRAPER_NAME,
        category_medians=category_medians,
    )


if __name__ == "__main__":
    import pandas as pd
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    result = scrape_daraz()
    items = result["items"]

    df = pd.DataFrame(items)

    if not df.empty:
        print(df[["name", "category", "final_price", "unit_price", "unit_type"]].to_string())
    else:
        print("No items scraped.")