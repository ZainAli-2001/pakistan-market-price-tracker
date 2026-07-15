"""
Debug artifacts: failed-request/rejected-item CSVs, raw response
snapshots, and verbose parse logging.

Failed-request CSVs are always written because they help diagnose
network and scraper failures in any environment. Rejected-item CSVs,
HTML/JSON snapshots, and verbose parsed-item logging are intended for
local debugging; callers enable them via DEBUG_DARAZ/DEBUG_NAHEED.
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DEBUG_DIR = "debug"
RESPONSES_DIR = os.path.join(DEBUG_DIR, "responses")


def _append_csv(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def save_failed_request(scraper_name: str, row: dict) -> None:
    row = {"timestamp": datetime.now(timezone.utc).isoformat(), **row}
    path = os.path.join(DEBUG_DIR, f"{scraper_name}_failed_requests.csv")
    _append_csv(path, row)


def log_rejected_item(scraper_name: str, row: dict) -> dict:
    """
    row is expected to carry the same keys used for add_rejection()
    (run_id, category, name, url, reason, and — for outlier rejections —
    unit_value/unit_type/unit_price/threshold_used/threshold_type/
    pipeline_version). Callers should build one shared kwargs dict and
    pass it to both add_rejection() and this function so the DB row and
    the debug CSV row never drift apart.
    """
    row = {
        "scraper": scraper_name,
        "rejected_at": datetime.now(timezone.utc).isoformat(),

        "run_id": row.get("run_id"),
        "category": row.get("category"),

        "product_name": row.get("name"),
        "product_url": row.get("url"),

        "reason": row.get("reason"),

        "unit_value": row.get("unit_value"),
        "unit_type": row.get("unit_type"),
        "unit_price": row.get("unit_price"),
        "threshold_used": row.get("threshold_used"),
        "threshold_type": row.get("threshold_type"),
        "pipeline_version": row.get("pipeline_version"),
    }
    path = os.path.join(DEBUG_DIR, f"{scraper_name}_rejected_items.csv")
    _append_csv(path, row)
    return row


def save_html(scraper_name: str, filename: str, html: str) -> None:
    os.makedirs(RESPONSES_DIR, exist_ok=True)
    path = os.path.join(RESPONSES_DIR, f"{scraper_name}_{filename}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def save_json(scraper_name: str, filename: str, data) -> None:
    os.makedirs(RESPONSES_DIR, exist_ok=True)
    path = os.path.join(RESPONSES_DIR, f"{scraper_name}_{filename}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def log_parsed_item(scraper_name: str, fields: dict) -> None:
    details = " | ".join(f"{k}={v}" for k, v in fields.items())
    log.debug("[%s] %s", scraper_name, details)