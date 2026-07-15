"""
Shared validation rules. Only one exists today — everything else
(missing name, missing price) is flow control inline in the scrapers,
not reusable business logic.
"""

import statistics
from utils.config import MAX_UNIT_PRICE, OUTLIER_MULTIPLIER, LOWER_BOUND_MULTIPLIER, MIN_SAMPLE_FOR_MEDIAN


def validate_unit_price(unit_price, category, reference_median=None, reference_prices=None):
    # reference_median: single scalar from borrowed/computed median
    # reference_prices: list (for when you have raw samples)
    if unit_price is None:
        return None, None, None
    if unit_price <= 0:
        return None, None, None

    # Prefer explicit median over list computation
    median = reference_median
    if median is None and reference_prices and len(reference_prices) >= MIN_SAMPLE_FOR_MEDIAN:
        median = statistics.median(reference_prices)

    if median is not None and median > 0:
        upper_threshold = median * OUTLIER_MULTIPLIER
        lower_threshold = median * LOWER_BOUND_MULTIPLIER
        if unit_price > upper_threshold:
            return None, upper_threshold, "dynamic_median"
        if unit_price < lower_threshold:
            return None, lower_threshold, "dynamic_median_low"
        return unit_price, upper_threshold, "dynamic_median"

    limit = MAX_UNIT_PRICE.get(category)
    if limit is not None and unit_price > limit:
        return None, limit, "fallback_limit"
    return unit_price, limit, ("fallback_limit" if limit is not None else None)