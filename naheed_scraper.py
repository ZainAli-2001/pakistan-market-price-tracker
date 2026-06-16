"""
=============================================================
  naheed_scraper.py — Forecasting-Ready Naheed.pk Scraper
=============================================================

"""

import requests
import pandas as pd
import re
import time
import logging
from datetime import datetime
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# -----------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------
CATEGORIES = {
    "https://www.naheed.pk/groceries-pets/baking-cooking/cooking-oil":  "oil_ghee",
    "https://www.naheed.pk/groceries-pets/baking-cooking/rice":         "rice",
    "https://www.naheed.pk/groceries-pets/baking-cooking/flours-meals": "flour",
}

PAGES_PER_CATEGORY = 3

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

SOURCE         = "naheed"
MAX_UNIT_PRICE = 10000


# -----------------------------------------------------------
# CATEGORY DETECTOR
# Splits oil_ghee → 'oil' or 'ghee' from product title.
# Banaspati/Vanaspati are hydrogenated fats — grouped
# with ghee for forecasting purposes.
# -----------------------------------------------------------
def detect_category(name: str, default: str) -> str:
    if default != "oil_ghee":
        return default
    name_lower = name.lower()
    if any(k in name_lower for k in ["ghee", "banaspati", "vanaspati"]):
        return "ghee"
    return "oil"


# -----------------------------------------------------------
# UNIT EXTRACTION
# Identical logic to daraz_scraper.py — self-contained so
# each file can run independently.
# -----------------------------------------------------------
WEIGHT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|grams|litres|liters|litre|liter|l|ml|lbs|lb)\b",
    re.IGNORECASE
)

PACK_PATTERN = re.compile(r"(\d+)\s*-?\s*pack", re.IGNORECASE)


def extract_unit(title: str):
    """
    Parse weight/volume from product title.
    Returns (unit_value, unit_type) or (None, None).

    Examples:
        "Sunridge Atta 5KG"              → (5.0,   'kg')
        "Young's Oil 1 Liter"            → (1.0,   'liter')
        "Dalda Corn Oil 1000ml"          → (1.0,   'liter')
        "Rice 2 lbs"                     → (0.907, 'kg')
        "Random Product"                 → (None,  None)
    """
    match = WEIGHT_PATTERN.search(title)
    if not match:
        return None, None

    value = float(match.group(1))
    unit  = match.group(2).lower()

    if unit in ("g", "gm", "grams"):
        return value / 1000, "kg"
    elif unit in ("ml",):
        return value / 1000, "liter"
    elif unit in ("l", "litre", "liter", "litres", "liters"):
        return value, "liter"
    elif unit in ("lb", "lbs"):
        return round(value * 0.453592, 4), "kg"
    else:
        return value, "kg"


def extract_pack_multiplier(title: str) -> int:
    """
    Detect pack sizes like '5-Pack', '3 Pack', '2-Pack'.
    Returns multiplier or 1 if not a pack product.

    Examples:
        "Soya Supreme 1 Liter Each, 5-Pack" → 5
        "Young's Orla 5 Liter Bottle"       → 1
    """
    match = PACK_PATTERN.search(title)
    return int(match.group(1)) if match else 1


def clean_price(raw):
    if raw is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


# -----------------------------------------------------------
# FETCH — category page with pagination
# Naheed uses ?p=N for pagination.
# -----------------------------------------------------------
def fetch_category_page(url: str, page: int) -> list:
    """
    Fetch one page of a Naheed category URL.
    Returns list of BeautifulSoup product card tags.
    """
    if page > 1:
        separator     = "&" if "?" in url else "?"
        paginated_url = f"{url}{separator}p={page}"
    else:
        paginated_url = url

    try:
        r = requests.get(paginated_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log.error("  fetch failed %s page %d: %s", url, page, e)
        return []

    soup  = BeautifulSoup(r.text, "lxml")
    cards = soup.select("li.item.product.product-item")
    log.info("  %s page %d → %d cards",
             url.split("/")[-1].split("?")[0], page, len(cards))
    return cards


# -----------------------------------------------------------
# PARSER
# 3-layer output — identical schema to daraz_scraper.py:
#   Layer 1: original_price, sale_price, final_price
#   Layer 2: unit_value, unit_type, unit_price
#   Layer 3: run_id, source, keyword, category, name,
#            url, rating, review_count, scraped_at
# -----------------------------------------------------------
def parse_card(card, default_category: str, run_id: str):
    """
    Parse a single Naheed product card into a
    forecasting-ready dict. Returns None if invalid.
    """
    # --- Name + URL ---
    name_tag = card.select_one("a.product-item-link")
    if not name_tag:
        return None
    name = name_tag.get_text(strip=True)
    url  = name_tag.get("href", "")

    # --- Category detection (oil vs ghee split) ---
    category = detect_category(name, default_category)

    # --- Layer 1: Raw prices ---
    # data-price-amount is cleanest — raw number, no Rs. parsing
    price_tag = card.select_one("span[data-price-type='finalPrice']")
    if not price_tag:
        return None

    final_price = clean_price(price_tag.get("data-price-amount"))
    if final_price is None:
        return None

    original_price = final_price   # Naheed shows one price only
    sale_price     = None

    # --- Layer 2: Normalised unit price ---
    unit_value, unit_type = extract_unit(name)

    # Pack multiplier:
    # "Soya Supreme 1 Liter Each, 5-Pack" → 1L × 5 = 5L total
    # Prevents unit_price being 5× too high for multi-packs
    if unit_value:
        pack = extract_pack_multiplier(name)
        if pack > 1:
            unit_value = round(unit_value * pack, 4)

    # Division by zero guard (unit_value = 0 would crash)
    unit_price = (
        round(final_price / unit_value, 2)
        if unit_value and unit_value > 0
        else None
    )

    # Outlier guard — bad weight parse (e.g. spray can 3ml)
    # produces unrealistically high unit_price
    if unit_price and unit_price > MAX_UNIT_PRICE:
        unit_price = None

    # --- Layer 3: Context metadata ---
    return {
        # time series anchor
        "run_id":   run_id,

        # identity
        "source":   SOURCE,
        "keyword":  category,   # category used as keyword for schema consistency
        "category": category,
        "name":     name,
        "url":      url,

        # Layer 1
        "original_price": original_price,
        "sale_price":     sale_price,
        "final_price":    final_price,

        # Layer 2
        "unit_value": unit_value,
        "unit_type":  unit_type,
        "unit_price": unit_price,

        # quality signals (not available from Naheed category pages)
        "rating":       None,
        "review_count": None,

        # time series
        "scraped_at": datetime.now().isoformat(),
    }


# -----------------------------------------------------------
# MAIN SCRAPE FUNCTION
# -----------------------------------------------------------
def scrape_naheed() -> list:
    """
    Scrape all configured categories from Naheed.pk.
    Stops paginating early if a page returns 0 cards.
    Returns a forecasting-ready list of item dicts.
    """
    log.info("--- Naheed scrape starting ---")
    all_items = []
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")

    for base_url, default_category in CATEGORIES.items():
        label = base_url.split("/")[-1].split("?")[0]
        log.info("Scraping: %s (%s)", label, default_category)

        for page in range(1, PAGES_PER_CATEGORY + 1):
            cards = fetch_category_page(base_url, page)

            if not cards:
                log.info("  Page %d empty — stopping early", page)
                break

            for card in cards:
                item = parse_card(card, default_category, run_id)
                if item:
                    all_items.append(item)

            time.sleep(2)

        time.sleep(3)

    log.info("Naheed total: %d items", len(all_items))
    return all_items


# -----------------------------------------------------------
# ENTRY POINT — local testing
# -----------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    items = scrape_naheed()
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