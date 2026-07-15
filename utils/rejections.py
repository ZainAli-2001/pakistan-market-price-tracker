"""
=============================================================
  rejections.py — Centralized Rejection Collection
=============================================================

Builds a consistent rejection record regardless of which scraper
produced it, so all rejected items share the same schema.
"""

from datetime import datetime, timezone


def add_rejection(
    rejections,
    run_id,
    scraper,
    category=None,
    name=None,
    url=None,
    reason=None,
    unit_value=None,
    unit_type=None,
    unit_price=None,
    threshold_used=None,
    threshold_type=None,
    pipeline_version=None,
):
    rejections.append({
        "run_id": run_id,
        "scraper": scraper,
        "category": category,
        "reason": reason,
        "product_name": name,
        "product_url": url,

        "unit_value": unit_value,
        "unit_type": unit_type,
        "unit_price": unit_price,
        "threshold_used": threshold_used,
        "threshold_type": threshold_type,
        "pipeline_version": pipeline_version,

        "rejected_at": datetime.now(timezone.utc).isoformat(),
    })