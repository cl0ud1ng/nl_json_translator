from __future__ import annotations

import re
import unicodedata


_CHINESE_NUMBER_PATTERN = re.compile(r"[零〇一二两三四五六七八九十]+")
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def normalize_location_text(value: str) -> str:
    """Normalize case, spacing, punctuation, width and common Chinese numbers."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _CHINESE_NUMBER_PATTERN.sub(
        lambda match: str(_parse_chinese_number(match.group(0))), normalized
    )
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "Z"))
    )


def _parse_chinese_number(value: str) -> int:
    if "十" in value:
        tens_text, ones_text = value.split("十", 1)
        tens = _CHINESE_DIGITS.get(tens_text, 1) if tens_text else 1
        ones = _CHINESE_DIGITS.get(ones_text, 0) if ones_text else 0
        return tens * 10 + ones
    digits = [_CHINESE_DIGITS[character] for character in value]
    return int("".join(str(digit) for digit in digits))
