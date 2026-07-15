"""
Unit extraction.

Public interface:
    extract_unit(title)             -> (unit_value, unit_type)
    extract_pack_multiplier(title)  -> int

extract_unit() only parses the title — it does not apply the pack
multiplier. That's a pricing-pipeline decision left to each scraper's
parse_item()/parse_card(), so a future source can represent packs
differently without touching extraction logic.
"""

import re

from utils.text import preprocess_title

WEIGHT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(kg|g|gm|liter|litres?|l|ml|lb|lbs|oz|ounces?|ounce)\b",
    re.IGNORECASE
)

# "1/2 kg" fraction notation. Digits capped at 1-2 so genuine small
# fractions ("1/2", "3/4") aren't confused with tiered-size slashes like
# "100/200 gm" (100g or 200g options, not the fraction 0.5g).
FRACTION_PATTERN = re.compile(
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*(kg|g|gm|liter|litres?|l|ml|lb|lbs|oz|ounces?|ounce)\b",
    re.IGNORECASE
)

# "10,15,20 kg" -- ambiguous multi-size listing, only last number has a
# unit. Matched so extract_unit() can bail out instead of guessing.
TIERED_LISTING_PATTERN = re.compile(
    r"\d+\s*,\s*\d+(?:\s*,\s*\d+)*\s*(kg|g|gm|liter|litres?|l|ml|lb|lbs|oz|ounces?|ounce)\b",
    re.IGNORECASE
)

# "1kg / 2kg / 5kg" -- same as above, slash-separated with each tier
# carrying its own unit. Distinct from FRACTION_PATTERN, which has only
# one unit at the end.
SLASH_TIERED_LISTING_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:kg|g|gm|liter|litres?|l|ml|lb|lbs|oz|ounces?|ounce)\s*/\s*"
    r"\d+(?:\.\d+)?\s*(?:kg|g|gm|liter|litres?|l|ml|lb|lbs|oz|ounces?|ounce)\b",
    re.IGNORECASE
)

# "500g x 3" vs "3 x 500g" — order of quantity and multiplier differs
MULTIPACK_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|g|gm|liter|l|ml|lb|lbs|oz)\s*[x×X]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE
)
MULTIPACK_PATTERN2 = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×X]\s*(\d+(?:\.\d+)?)\s*(kg|g|gm|liter|l|ml|lb|lbs|oz)",
    re.IGNORECASE
)

PACK_PATTERN = re.compile(
    r"\b(\d{1,3})\s*-?\s*pack|pack\s+of\s+(\d+)|(\d+)\s*pcs?|(\d+)\s*sachets?",
    re.IGNORECASE
)

# "245gram each" — per-unit qty in a pack listing; pack count applied
# separately via extract_pack_multiplier()
EACH_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kg|g|gm|liter|litres?|l|ml|lb|lbs|oz)\s+each",
    re.IGNORECASE
)

CONVERSIONS = {
    'kg': 1.0,      'g': 0.001,     'gm': 0.001,
    'lb': 0.453592, 'lbs': 0.453592,
    'oz': 0.0283495,'ounce': 0.0283495, 'ounces': 0.0283495,
    'liter': 1.0,   'l': 1.0,       'ml': 0.001,
}

STANDARD_UNIT = {
    'kg': 'kg',     'g': 'kg',      'gm': 'kg',
    'lb': 'kg',     'lbs': 'kg',
    'oz': 'kg',     'ounce': 'kg',  'ounces': 'kg',
    'liter': 'liter','l': 'liter',  'ml': 'liter',
}

# Alternate spellings, folded to canonical unit at match time.
_UNIT_ALIASES = {
    'litre': 'liter',
    'litres': 'liter',
}


def _normalize_unit(unit: str) -> str:
    unit = unit.lower()
    return _UNIT_ALIASES.get(unit, unit)


def _convert(qty: float, unit: str):
    factor = CONVERSIONS.get(unit)
    if factor is None:
        return None, None
    return round(qty * factor, 6), STANDARD_UNIT[unit]


def extract_unit(title: str):
    """
    Parse product title and return (unit_value, unit_type, pack_applied).

    pack_applied is True when a multipack phrasing ("500g x 3") was matched
    and its multiplier is already folded into unit_value — callers must NOT
    also call extract_pack_multiplier() on the same title in that case, or
    a title matching both a multipack pattern and a separate "N Pack" phrase
    (e.g. "1000ml x 6 Pack") gets its multiplier applied twice.

        "Sunridge Atta 10KG"  -> (10.0,  'kg',    False)
        "Dalda Oil 5 Litre"   -> (5.0,   'liter', False)
        "500g x 3"            -> (1.5,   'kg',    True)
        "Random Product"      -> (None,  None,    False)
    """
    title = preprocess_title(title)

    if re.search(r'\bhalf\s*-?\s*kg\b', title, re.IGNORECASE):
        return 0.5, 'kg', False

    # Ambiguous multi-size listing -- bail out instead of guessing.
    if TIERED_LISTING_PATTERN.search(title) or SLASH_TIERED_LISTING_PATTERN.search(title):
        return None, None, False

    frac = FRACTION_PATTERN.search(title)
    if frac:
        numerator, denominator, unit = frac.groups()
        denominator = float(denominator)
        if denominator != 0:
            qty = float(numerator) / denominator
            converted = _convert(qty, _normalize_unit(unit))
            if converted[0] is not None:
                return converted[0], converted[1], False

    # multipack patterns checked before the simple pattern, which would
    # otherwise extract only the per-unit quantity and ignore the multiplier
    m = MULTIPACK_PATTERN.search(title)
    if m:
        qty  = float(m.group(1)) * float(m.group(3))
        unit = _normalize_unit(m.group(2))
        converted = _convert(qty, unit)
        if converted[0] is not None:
            return converted[0], converted[1], True

    m2 = MULTIPACK_PATTERN2.search(title)
    if m2:
        qty  = float(m2.group(1)) * float(m2.group(2))
        unit = _normalize_unit(m2.group(3))
        converted = _convert(qty, unit)
        if converted[0] is not None:
            return converted[0], converted[1], True

    # finditer + take the largest match: .search() would stop at the first
    # hit, which can be a nutritional value (e.g. "1g Net Carb") appearing
    # before the actual package size. The package size is reliably the
    # largest candidate.
    candidates = []

    e = EACH_PATTERN.search(title)
    if e:
        qty  = float(e.group(1))
        unit = _normalize_unit(e.group(2))
        converted = _convert(qty, unit)
        if converted[0] is not None:
            candidates.append(converted)

    for match in WEIGHT_PATTERN.finditer(title):
        qty  = float(match.group(1))
        unit = _normalize_unit(match.group(2))
        converted = _convert(qty, unit)
        if converted[0] is not None:
            candidates.append(converted)

    if candidates:
        best = max(candidates, key=lambda x: x[0])
        return best[0], best[1], False

    return None, None, False


def extract_pack_multiplier(title: str) -> int:
    """
    Detect pack sizes like '5-Pack', 'Pack of 24', '100PCS', '150 Sachet'.
    Returns 1 if the title isn't a pack product.
    """
    match = PACK_PATTERN.search(title)
    if not match:
        return 1
    value = match.group(1) or match.group(2) or match.group(3) or match.group(4)
    return int(value)