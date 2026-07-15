"""
Title normalization — applies to product name/title only, never to
keyword, category, url, prices, or raw debug snapshots (those are
either controlled vocabulary or must stay untouched for reproducibility).
"""

import re
import unicodedata


def fix_encoding(name: str) -> str:
    """
    Strip Unicode combining marks via NFD decomposition.

    Daraz occasionally returns mojibake (Latin-1 read as UTF-8), e.g.
    'p̄' in 'Tap̄al'. NFD splits any such character into base letter +
    combining mark; stripping the mark fixes it regardless of which
    character was affected, without hardcoding specific cases. Safe
    here since all titles are English — no legitimate diacritics exist.
    """
    return ''.join(
        c for c in unicodedata.normalize('NFD', name)
        if unicodedata.category(c) != 'Mn'
    )

# \b sees no boundary between a digit and a letter (both are "word" chars),
# so "45gram" would never match. (?<![A-Za-z]) allows a digit before the
# unit while still refusing to match inside a real word like "program".
_NOT_LETTER_BEFORE = r'(?<![A-Za-z])'
_NOT_LETTER_AFTER = r'(?![A-Za-z])'

def preprocess_title(name: str) -> str:
    """
    Normalize unit spelling variants before extract_unit() runs, so
    WEIGHT_PATTERN only needs to match canonical forms. Pattern-based
    rather than a fixed lookup table, so new misspellings in the same
    class (e.g. another "litre" variant) resolve automatically.
    """
    if not name:
        return name

    name = fix_encoding(name)  # must run first — corrupted chars break the regexes below

    name = re.sub(
        _NOT_LETTER_BEFORE + r'lit(?:re|tres?|ter|ters?|r|rs?)' + _NOT_LETTER_AFTER
        + r'|' + _NOT_LETTER_BEFORE + r'ltr' + _NOT_LETTER_AFTER
        + r'|' + _NOT_LETTER_BEFORE + r'lt' + _NOT_LETTER_AFTER,
        'liter', name, flags=re.IGNORECASE
    )  
    name = re.sub(
        _NOT_LETTER_BEFORE + r'gr(?:am|ams?|my|s)?' + _NOT_LETTER_AFTER
        + r'|' + _NOT_LETTER_BEFORE + r'gms?' + _NOT_LETTER_AFTER
        + r'|' + _NOT_LETTER_BEFORE + r'gsm' + _NOT_LETTER_AFTER,
        'gm', name, flags=re.IGNORECASE
    )
    name = re.sub(
        _NOT_LETTER_BEFORE + r'kgs' + _NOT_LETTER_AFTER + r'|\bK\s+G\b',
        'kg', name, flags=re.IGNORECASE
    )
    name = re.sub(
        _NOT_LETTER_BEFORE + r'lkg' + _NOT_LETTER_AFTER,
        '1kg', name, flags=re.IGNORECASE
    ) # "lkg" -> "1kg", merged unit seen in data
    name = re.sub(r'\s+', ' ', name).strip()

    return name
