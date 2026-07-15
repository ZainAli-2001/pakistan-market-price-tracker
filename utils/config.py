"""
Shared configuration for both scrapers.

Only values genuinely identical across both scrapers live here.
Scraper-specific config (KEYWORD_DELAY vs CATEGORY_DELAY, PRODUCTS
vs CATEGORIES) stays in the respective scraper file.
"""

from datetime import datetime

# Date-based rather than hand-bumped: this runs as a daily GitHub Actions
# job, so every row is automatically tagged with which day's scraper logic
# produced it. Computed at import time since each run is a fresh process.
SCRAPER_VERSION = datetime.now().strftime("%Y.%m.%d")

# Rotated per scrape run so a static UA doesn't become a fingerprintable pattern
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# delay = RETRY_BASE_DELAY * (BACKOFF_FACTOR ** attempt) -> 2s, 4s, 8s
REQUEST_TIMEOUT  = 15
MAX_RETRIES      = 3
RETRY_BASE_DELAY = 2
BACKOFF_FACTOR   = 2

PAGE_DELAY = 2

# Tracks which major pipeline refactor produced this data — distinct from
# SCRAPER_VERSION (daily) since this only bumps on structural ETL changes.
PIPELINE_VERSION = "2.0.0"

OUTLIER_MULTIPLIER = 3.5      # reject if unit_price > median * this
LOWER_BOUND_MULTIPLIER = 0.3  # reject if unit_price < median * this (suspiciously low / bad parse)
MIN_SAMPLE_FOR_MEDIAN = 10    # below this, fall back to static MAX_UNIT_PRICE

# Max realistic unit price (PKR) per category, used to reject bad parses
# (e.g. a nutritional value matched instead of package weight).
MAX_UNIT_PRICE = {
    "flour":  2800,
    "rice":   2000,
    "oil":    3500,
    "pulses": 2500,
    "sugar":  2200,
    "ghee":   12000,
    "dairy":  2800,
    "tea":    8500,
}

DEBUG_DARAZ  = False
DEBUG_NAHEED = False