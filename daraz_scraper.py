"""
=============================================================
  daraz_scraper.py — Forecasting-Ready Daraz Scraper
=============================================================
"""

import requests
import pandas as pd
import re
import time
import logging
from datetime import datetime

log = logging.getLogger(__name__)


# -----------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------

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

PAGES_PER_PRODUCT = 2   # ~40 items per page → ~80 per keyword

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

SOURCE = "daraz"


# -----------------------------------------------------------
# UNIT EXTRACTION 

# Supported units:
#   kg / kgs / g / gm / grams → unit_type = 'kg'
#   l / litre / liter / ml    → unit_type = 'liter'
#   lb / lbs                  → converted to kg, unit_type = 'kg'
#   unrecognised               → unit_type = 'unit' (raw count)
# -----------------------------------------------------------
WEIGHT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|grams|litre|liter|l|ml|lbs|lb)\b",
    re.IGNORECASE
)

def extract_weight_base_unit(title: str):
    """
    Parse product title and return (unit_value, unit_type).

    Examples:
        "Sunridge Atta 10KG"        → (10.0,  'kg')
        "Dalda Oil 5 Litre"         → (5.0,   'liter')
        "Tapal Tea 200g"            → (0.2,   'kg')
        "Nestle Milk 1000ml"        → (1.0,   'liter')
        "Rice 2 lbs"                → (0.907, 'kg')
        "Random Product"            → (None,  'unit')
    """
    match = WEIGHT_PATTERN.search(title)
    if not match:
        return None, "unit"

    value = float(match.group(1))
    unit  = match.group(2).lower()

    if unit in ("g", "gm", "grams"):
        return value / 1000, "kg"
    elif unit == "ml":
        return value / 1000, "liter"
    elif unit in ("l", "litre", "liter"):
        return value, "liter"
    elif unit in ("lb", "lbs"):
        return round(value * 0.453592, 4), "kg"
    else:
        return value, "kg"   # kg / kgs → already in kg


# -----------------------------------------------------------
# PRICE CLEANER
# Daraz returns prices as strings like "Rs. 1,250".
# Strip non-numeric characters and cast to float.
# -----------------------------------------------------------
def clean_price(raw):
    if raw is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


# -----------------------------------------------------------
# FETCH DARAZ PAGE — internal XHR API
# -----------------------------------------------------------
def fetch_daraz_page(keyword: str, page: int) -> list:
    """
    Call Daraz's internal search API for one page of results.
    Returns raw list of product dicts from the JSON response.
    """
    url = "https://www.daraz.pk/catalog/?ajax=true"
    params = {"q": keyword, "page": page, "sort": "salesOld"}

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=15)
        response.raise_for_status()
        items = response.json().get("mods", {}).get("listItems", [])
        log.info("  daraz '%s' page %d → %d items", keyword, page, len(items))
        return items
    except Exception as e:
        log.error("  daraz FAIL '%s' page %d: %s", keyword, page, e)
        return []


# -----------------------------------------------------------
# PARSE ITEM — forecasting-ready 3-layer output
#
# Layer 1 — Raw prices:
#   original_price, sale_price, final_price
#
# Layer 2 — Normalized price:
#   unit_value, unit_type, unit_price
#   → this is what Prophet/ML will use as the target variable
#   → comparable across scrape runs and between stores
#
# Layer 3 — Context metadata:
#   name, url, category, keyword, source, run_id, scraped_at
#   → enables grouping, filtering, and time-series construction
# -----------------------------------------------------------
def parse_item(raw: dict, keyword: str, category: str, run_id: str):
    """
    Extract and clean a single Daraz API product dict.
    Returns a forecasting-ready record, or None if invalid.
    """
    name = raw.get("name", "").strip()
    if not name:
        return None

    # --- Layer 1: Raw prices ---
    original_price = clean_price(raw.get("originalPrice"))
    sale_price     = clean_price(raw.get("price"))

    valid_prices = [p for p in [sale_price, original_price] if p is not None]
    final_price  = min(valid_prices) if valid_prices else None

    if final_price is None:
        return None   # skip items with no usable price

    # --- Layer 2: Normalized price ---
    unit_value, unit_type = extract_weight_base_unit(name)
    unit_price = (
        round(final_price / unit_value, 2)
        if unit_value and unit_value > 0
        else None
    )

    # Product URL
    url = raw.get("itemUrl", "")
    if url and not url.startswith("http"):
        url = "https:" + url

    # Rating
    try:
        rating = float(raw.get("ratingScore")) if raw.get("ratingScore") else None
    except (ValueError, TypeError):
        rating = None

    # --- Layer 3: Context metadata ---
    return {
        # identity
        "run_id":       run_id,
        "source":       SOURCE,
        "keyword":      keyword,
        "category":     category,
        "name":         name,
        "url":          url,

        # Layer 1: raw prices
        "original_price": original_price,
        "sale_price":     sale_price,
        "final_price":    final_price,

        # Layer 2: normalised unit price
        "unit_value":  unit_value,
        "unit_type":   unit_type,
        "unit_price":  unit_price,

        # quality signals
        "rating":        rating,
        "review_count":  raw.get("review"),

        # time series anchor
        "scraped_at":    datetime.now().isoformat(),
    }


# -----------------------------------------------------------
# MAIN SCRAPE FUNCTION
# Called by main.py — returns all items as a flat list.
# -----------------------------------------------------------
def scrape_daraz() -> list:
    """
    Scrape all configured products from Daraz.pk.
    Returns a forecasting-ready list of item dicts.
    """
    log.info("--- Daraz scrape starting ---")
    all_items = []
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")

    for keyword, category in PRODUCTS.items():
        log.info("Scraping: '%s' (%s)", keyword, category)

        for page in range(1, PAGES_PER_PRODUCT + 1):
            raw_items = fetch_daraz_page(keyword, page)

            for raw in raw_items:
                parsed = parse_item(raw, keyword, category, run_id)
                if parsed:
                    all_items.append(parsed)

            time.sleep(2)    # polite delay between pages
        time.sleep(3)        # longer pause between keywords

    log.info("Daraz total: %d items", len(all_items))
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    items = scrape_daraz()
    df = pd.DataFrame(items)
    print(df[["name", "category", "final_price", "unit_price", "unit_type"]].to_string())
