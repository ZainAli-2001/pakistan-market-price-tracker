"""
=============================================================
  utils/statistics.py — Scrape Run Counters
=============================================================

create_stats()                                -> dict
increment(stats, field)                       -> None
increment_category(stats, category, field)    -> None
print_summary(stats, scraper_name)            -> None

Daraz uses only the top-level counters. Naheed also uses
increment_category() for its per-category breakdown. Both
scrapers share this one implementation.
"""

import logging

log = logging.getLogger(__name__)

_COUNTER_FIELDS = [
    "total_received",
    "parsed",
    "missing_title",
    "missing_price",
    "missing_unit",
    "outliers",
    "filtered_products",
    "parsing_failures",
]


def create_stats() -> dict:
    stats = {field: 0 for field in _COUNTER_FIELDS}
    stats["categories"] = {}
    return stats


def increment(stats: dict, field: str, amount: int = 1) -> None:
    if field not in _COUNTER_FIELDS:
        raise KeyError(f"Unknown stats field '{field}'. Valid fields: {_COUNTER_FIELDS}")
    stats[field] += amount


def increment_category(stats: dict, category: str, field: str, amount: int = 1) -> None:
    bucket = stats["categories"].setdefault(category, {})
    bucket[field] = bucket.get(field, 0) + amount

def create_scrape_result(items, stats, rejections, run_id, scraper, category_medians=None):
    return {
        "scraper": scraper,
        "items": items,
        "stats": stats,
        "rejections": rejections,
        "run_id": run_id,
        "category_medians": category_medians or {},
    }

def print_summary(stats: dict, scraper_name: str) -> None:
    log.info("=== %s scrape summary ===", scraper_name)
    for field in _COUNTER_FIELDS:
        log.info("  %-18s %d", field, stats[field])

    for category, counters in stats["categories"].items():
        log.info("  %s: %s", category, counters)
