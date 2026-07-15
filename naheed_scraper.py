"""
=============================================================
  naheed_scraper.py — Forecasting-Ready Naheed.pk Scraper
=============================================================
"""

import logging
import statistics
import time
from datetime import datetime
import random

from bs4 import BeautifulSoup

from utils.commodity_filters import is_valid_commodity
from utils.config import DEBUG_NAHEED, MIN_SAMPLE_FOR_MEDIAN, PAGE_DELAY, SCRAPER_VERSION, PIPELINE_VERSION, USER_AGENTS
from utils.debug import log_parsed_item, log_rejected_item, save_failed_request, save_html
from utils.http import create_session, get_with_retry
from utils.prices import calculate_unit_price, clean_price
from utils.rejections import add_rejection
from utils.statistics import create_stats, create_scrape_result, increment, increment_category, print_summary
from utils.text import preprocess_title
from utils.units import extract_pack_multiplier, extract_unit
from utils.validation import validate_unit_price

log = logging.getLogger(__name__)

SCRAPER_NAME = "naheed"

CATEGORIES = {
    "https://www.naheed.pk/groceries-pets/baking-cooking/cooking-oil":  "oil_ghee",
    "https://www.naheed.pk/groceries-pets/baking-cooking/rice":         "rice",
    "https://www.naheed.pk/groceries-pets/baking-cooking/flours-meals": "flour",
}

PAGES_PER_CATEGORY = 3
CATEGORY_DELAY = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.naheed.pk/",
}

SOURCE = "naheed"

PRODUCT_CARD_SELECTOR = "li.item.product.product-item"


def detect_category(name: str, default: str) -> str:
    """
    Splits oil_ghee -> 'oil' or 'ghee' from product title.
    Banaspati/Vanaspati are hydrogenated fats, grouped with ghee for forecasting.
    """
    if default != "oil_ghee":
        return default
    name_lower = name.lower()
    if any(k in name_lower for k in ["ghee", "banaspati", "vanaspati"]):
        return "ghee"
    return "oil"


def fetch_category_page(session, url: str, page: int, stats: dict) -> list:
    """
    Fetch one page of a Naheed category URL.
    Returns list of BeautifulSoup product card tags.
    """
    if page > 1:
        separator     = "&" if "?" in url else "?"
        paginated_url = f"{url}{separator}p={page}"
    else:
        paginated_url = url

    response = get_with_retry(session, paginated_url)
    if response is None:
        save_failed_request(SCRAPER_NAME, {
            "category": url, "page": page,
            "status_code": None, "url": paginated_url, "error": "request failed after retries",
        })
        return []

    soup  = BeautifulSoup(response.text, "lxml")
    cards = soup.select(PRODUCT_CARD_SELECTOR)
    label = url.split("/")[-1].split("?")[0]

    # zero cards is ambiguous: either the category genuinely ran out of
    # pages, or Naheed changed its markup and PRODUCT_CARD_SELECTOR no
    # longer matches. A broader class-based search tells them apart.
    if not cards:
        possible_cards = soup.select("[class*='product-item']")
        if possible_cards:
            log.warning("  %s page %d: selector matched 0 but page has product-like markup — possible layout change", label, page)
            if DEBUG_NAHEED:
                save_html(SCRAPER_NAME, f"layout_change_{label}_{page}.html", response.text)

    log.info("  %s page %d → %d cards", label, page, len(cards))
    return cards


def parse_card(card, default_category: str, run_id: str, stats: dict, rejections: list):
    """
    Parse a single Naheed product card into a forecasting-ready dict.
    Returns None if invalid.

    3-layer output, identical schema to daraz_scraper.py:
        Layer 1: original_price, sale_price, final_price
        Layer 2: unit_value, unit_type, unit_price
        Layer 3: run_id, source, keyword, category, name, url, rating, review_count, scraped_at
    """
    increment(stats, "total_received")

    name_tag = card.select_one("a.product-item-link")
    if not name_tag:
        increment(stats, "missing_title")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=default_category,
            reason="missing_name_tag",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_NAHEED:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    original_title = name_tag.get_text(strip=True)
    name = preprocess_title(original_title)
    url  = name_tag.get("href", "")

    category = detect_category(name, default_category)
    increment_category(stats, category, "cards")

    # Remove non-commodity variants before price/unit processing
    if not is_valid_commodity(name, category):
        increment(stats, "filtered_products")
        increment_category(stats, category, "filtered_products")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=category,
            name=name,
            url=url,
            reason="commodity_filter",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_NAHEED:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    # data-price-amount is cleanest — raw number, no Rs. parsing
    price_tag = card.select_one("span[data-price-type='finalPrice']")
    if not price_tag:
        increment(stats, "missing_price")
        reject_kwargs = dict(
            run_id=run_id,
            scraper=SCRAPER_NAME,
            category=category,
            name=name,
            url=url,
            reason="missing_price_tag",
            pipeline_version=PIPELINE_VERSION,
        )
        if DEBUG_NAHEED:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    final_price = clean_price(price_tag.get("data-price-amount"))
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
        if DEBUG_NAHEED:
            log_rejected_item(SCRAPER_NAME, reject_kwargs)
        add_rejection(rejections, **reject_kwargs)
        return None

    original_price = final_price   # Naheed shows one price only
    sale_price     = None

    unit_value, unit_type, pack_applied = extract_unit(name)
    if unit_value is None:
        increment(stats, "missing_unit")
        increment_category(stats, category, "missing_unit")
    elif not pack_applied:
        # "Soya Supreme 1 Liter Each, 5-Pack" -> 1L x 5 = 5L total
        pack = extract_pack_multiplier(name)
        if pack > 1:
            unit_value = round(unit_value * pack, 4)

    unit_price = calculate_unit_price(final_price, unit_value)

    if DEBUG_NAHEED:
        log_parsed_item(SCRAPER_NAME, {
            "original_title": original_title,
            "normalized_title": name,
            "category": category,
            "unit_value": unit_value,
            "unit_type": unit_type,
            "unit_price": unit_price,
        })

    increment(stats, "parsed")
    increment_category(stats, category, "parsed")

    return {
        "run_id":   run_id,

        "source":   SOURCE,
        "keyword":  category,   # category used as keyword for schema consistency
        "category": category,
        "name":     name,
        "url":      url,

        "original_price": original_price,
        "sale_price":     sale_price,
        "final_price":    final_price,

        "unit_value": unit_value,
        "unit_type":  unit_type,
        "unit_price": unit_price,

        "rating":       None,
        "review_count": None,

        "scraper_version": SCRAPER_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "scraped_at": datetime.now().isoformat(),
    }


def validate_category_batch(items: list, run_id: str, stats: dict, rejections: list, reference_medians: dict = None):
    """
    Post-process one CATEGORIES loop's collected items (run once its page
    loop ends, mirroring daraz_scraper.py's validate_batch()).

    Grouped by each item's actual (post-detect_category) category, since a
    single "oil_ghee" loop can contain both "oil" and "ghee" items.
    Naheed's own median is preferred whenever that category's sample
    clears MIN_SAMPLE_FOR_MEDIAN; only then does it fall back to Daraz's
    borrowed reference_medians, and validate_unit_price() itself falls
    back further to the static MAX_UNIT_PRICE dict if neither is available.

    Returns the filtered (outlier-free) item list.
    """
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    kept_items = []
    for category, cat_items in by_category.items():
        prices = [item["unit_price"] for item in cat_items if item["unit_price"] is not None]
        own_median = statistics.median(prices) if len(prices) >= MIN_SAMPLE_FOR_MEDIAN else None
        median = own_median if own_median is not None else (reference_medians or {}).get(category)
        log.debug("  category '%s' → own median: %s, borrowed median: %s, using: %s",
                  category, own_median, (reference_medians or {}).get(category), median)

        for item in cat_items:
            raw_price = item["unit_price"]
            validated_price, threshold_used, threshold_type = validate_unit_price(
                raw_price, category, reference_median=median
            )

            if raw_price is not None and validated_price is None:
                increment(stats, "outliers")
                increment_category(stats, category, "outliers")
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
                if DEBUG_NAHEED:
                    log_rejected_item(SCRAPER_NAME, reject_kwargs)
                add_rejection(rejections, **reject_kwargs)
                continue

            item["unit_price"] = validated_price
            kept_items.append(item)

    return kept_items


def scrape_naheed(reference_medians: dict = None) -> list:
    """
    Scrape all configured categories from Naheed.pk.
    Stops paginating a category after two consecutive empty pages.
    reference_medians: per-category unit_price medians borrowed from Daraz's
    same-run scrape, used for outlier validation since Naheed's own sample
    per category is too small to compute a reliable median.
    Returns a forecasting-ready list of item dicts.
    """
    log.info("--- Naheed scrape starting ---")
    all_items = []
    seen = set()
    stats = create_stats()
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")
    rejections = []

    session = create_session(headers={**HEADERS, "User-Agent": random.choice(USER_AGENTS)})
    try:
        for base_url, default_category in CATEGORIES.items():
            label = base_url.split("/")[-1].split("?")[0]
            log.info("Scraping: %s (%s)", label, default_category)

            consecutive_empty = 0
            category_batch = []
            for page in range(1, PAGES_PER_CATEGORY + 1):
                cards = fetch_category_page(session, base_url, page, stats)

                if not cards:
                    consecutive_empty += 1
                    log.info("  Page %d empty (%d consecutive)", page, consecutive_empty)
                    if consecutive_empty >= 2:
                        log.info("  Two consecutive empty pages — stopping category")
                        break
                    continue
                consecutive_empty = 0

                for card in cards:
                    try:
                        item = parse_card(card, default_category, run_id, stats, rejections)
                    except Exception as e:
                        increment(stats, "parsing_failures")
                        log.error("  naheed parse error in '%s': %s", label, e)
                        continue

                    if not item:
                        continue

                    dedup_key = (item["name"], item["url"])
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    category_batch.append(item)

                time.sleep(PAGE_DELAY)

            validated_batch = validate_category_batch(category_batch, run_id, stats, rejections, reference_medians)
            all_items.extend(validated_batch)

            time.sleep(CATEGORY_DELAY)
    finally:
        session.close()

    log.info("Naheed total: %d items", len(all_items))
    print_summary(stats, SCRAPER_NAME)        
    return create_scrape_result(
        items=all_items,
        stats=stats,
        rejections=rejections,
        run_id=run_id,
        scraper=SCRAPER_NAME,
    )


if __name__ == "__main__":
    import pandas as pd
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    result = scrape_naheed()
    items = result["items"]

    df = pd.DataFrame(items)

    if not df.empty:
        print("\n--- Preview ---")
        print(df[["category", "name", "final_price",
                  "unit_value", "unit_type", "unit_price"]].to_string())
        print("\n--- Category breakdown ---")
        print(df.groupby("category")["name"].count())
        print(f"\nTotal: {len(df)} items")
    else:
        print("No items scraped.")