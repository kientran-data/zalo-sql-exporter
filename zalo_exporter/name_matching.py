"""
Unicode-aware name normalization and SQL-keyword matching.

Zalo uses \\xa0 (non-breaking space) between name parts in the UI tree.
Names may contain Vietnamese diacritics, brackets, underscores, etc.
"""

import re
import unicodedata


def normalize_for_match(name: str) -> str:
    """
    Normalize a display name for case-insensitive 'sql' matching.

    Steps:
      1. Replace non-breaking spaces (\\xa0) with regular spaces.
      2. Apply Unicode NFC normalization (compose diacritics).
      3. Strip invisible / control characters (category C) except space.
      4. Casefold for locale-independent case-insensitive comparison.
      5. Collapse multiple spaces and strip edges.
    """
    # Replace NBSP with regular space
    name = name.replace('\xa0', ' ')
    # NFC normalization — compose combining characters
    name = unicodedata.normalize('NFC', name)
    # Strip invisible / control chars but keep regular space
    name = ''.join(c for c in name if unicodedata.category(c)[0] != 'C' or c == ' ')
    # Casefold (stronger than .lower() for some scripts)
    name = name.casefold()
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def matches_sql(name: str) -> bool:
    """Return True if the normalized name contains the substring 'sql'."""
    return 'sql' in normalize_for_match(name)


def is_pua_only(text: str) -> bool:
    """
    Return True if *text* consists entirely of Private Use Area codepoints
    and whitespace.  Zalo renders font-icon glyphs (e.g. \\uec65) as PUA
    characters; these are never real message content or contact names.
    """
    return bool(text) and all(
        0xE000 <= ord(c) <= 0xF8FF or c.isspace()
        for c in text
    )


_DATE_SHORT = re.compile(r'^\d{2}/\d{2}/\d{2}$')       # 24/06/24
_DATE_LONG = re.compile(r'^\d{2}/\d{2}/\d{4}$')         # 24/06/2024
_TIME_ONLY = re.compile(r'^\d{2}:\d{2}$')               # 11:23
_DATETIME = re.compile(r'^\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4}$')  # 21:40 14/06/2024


def classify_text(text: str) -> str:
    """
    Classify a UI text element into one of:
      'date', 'time', 'datetime', 'text'.
    """
    t = text.strip()
    if _DATE_LONG.match(t) or _DATE_SHORT.match(t):
        return 'date'
    if _TIME_ONLY.match(t):
        return 'time'
    if _DATETIME.match(t):
        return 'datetime'
    return 'text'


def is_sidebar_date(text: str) -> bool:
    """Return True if text looks like a sidebar date (DD/MM/YY or DD/MM/YYYY)."""
    t = text.strip()
    return bool(_DATE_SHORT.match(t) or _DATE_LONG.match(t))
