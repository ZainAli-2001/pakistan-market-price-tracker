"""
=============================================================
  main.py — Scrape Orchestrator
=============================================================

"""

import argparse
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


def main(dry_run: bool = False):
    log.info("=" * 60)
    log.info("Pakistan Market Price Tracker")
    log.info("Run: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 60)

    all_items = []
    results = []
    category_medians = {}

    # --- Daraz ---
    log.info("\n[1/2] Daraz.pk")
    try:
        daraz = scrape_daraz()
        all_items.extend(daraz["items"])
        results.append(daraz)
        category_medians = daraz["category_medians"]
        log.info("Daraz: %d items", len(daraz['items']))

    except Exception as e:
        log.error("Daraz scraper failed: %s", e)

    # --- Naheed ---
    # Runs after Daraz so it can borrow Daraz's same-run category medians
    # for outlier validation (falls back to {} if Daraz failed above).
    log.info("\n[2/2] Naheed.pk")
    try:
        naheed = scrape_naheed(reference_medians=category_medians)
        all_items.extend(naheed["items"])
        results.append(naheed)
        log.info("Naheed: %d items", len(naheed["items"]))
    except Exception as e:
        log.error("Naheed scraper failed: %s", e)

    # --- Save ---
    if dry_run:
        log.info("\n[DB] Dry run — skipping save_all() (%d items would have been written)", len(all_items))
    else:
        log.info("\n[DB] Saving %d total items to Supabase...", len(all_items))
        try:
            save_all(
                all_items,
                results,
            )
        except Exception as e:
            log.error("Database save failed: %s", e)
            sys.exit(1)   # non-zero exit → GitHub Actions marks run as failed

    log.info("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run the full scrape/validation pipeline without writing to the database")
    args = parser.parse_args()
    main(dry_run=args.dry_run)