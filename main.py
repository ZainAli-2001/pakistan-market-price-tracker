"""
=============================================================
  main.py — Scrape Orchestrator
=============================================================

"""

import logging
import sys
from datetime import datetime

from daraz_scraper import scrape_daraz
from naheed_scraper import scrape_naheed
from database import save_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


def main():
    log.info("=" * 60)
    log.info("Pakistan Market Price Tracker")
    log.info("Run: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 60)

    all_items = []

    # --- Daraz ---
    log.info("\n[1/2] Daraz.pk")
    try:
        daraz_items = scrape_daraz()
        all_items.extend(daraz_items)
        log.info("Daraz: %d items", len(daraz_items))
    except Exception as e:
        log.error("Daraz scraper failed: %s", e)

    # --- Naheed ---
    log.info("\n[2/2] Naheed.pk")
    try:
        naheed_items = scrape_naheed()
        all_items.extend(naheed_items)
        log.info("Naheed: %d items", len(naheed_items))
    except Exception as e:
        log.error("Naheed scraper failed: %s", e)

    # --- Save ---
    log.info("\n[DB] Saving %d total items to Supabase...", len(all_items))
    try:
        save_all(all_items)
    except Exception as e:
        log.error("Database save failed: %s", e)
        sys.exit(1)   # non-zero exit → GitHub Actions marks run as failed

    log.info("\nDone.")


if __name__ == "__main__":
    main()
