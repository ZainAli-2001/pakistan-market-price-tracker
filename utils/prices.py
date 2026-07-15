"""
Price cleaning and unit-price calculation. Pure math/string helpers —
domain rules like MAX_UNIT_PRICE outlier rejection live in validation.py.
"""

import re


def clean_price(raw) -> float:
    """Clean a raw price string (e.g. "Rs. 1,250") into a float, or None."""
    if raw is None:
        return None
    match = re.search(r"\d[\d,]*\.?\d*", str(raw))
    if not match:
        return None
    cleaned = match.group().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def calculate_unit_price(final_price, unit_value):
    """Price per standardized unit. Self-contained rather than trusting
    callers to have already validated inputs."""
    if final_price is None or unit_value is None or unit_value <= 0:
        return None
    return round(final_price / unit_value, 2)
