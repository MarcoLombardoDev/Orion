# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Showing a value the way the form shows it.

XFA stores values canonically — a date as ``2023-08-02``, an amount as
``4416.00000000`` — and a field's ``<format><picture>`` says how to *display*
them: ``date{DD/MM/YYYY}``, ``num{zzz,zz9.99}``. A converted field that shows
the stored form reads as a different document, with every amount carrying
eight decimals. This module applies the common picture clauses and leaves
anything it does not recognise exactly as stored, because a value shown raw
is still right where a value shown mangled is not.
"""

from __future__ import annotations

import re
from datetime import date

from orion.xfa.model import XfaField, XfaFieldType

__all__ = ["display_value"]

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_ISO_DATE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")
_DATE_TOKEN = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|DD|D|'[^']*'")
_NUMBER = re.compile(r"^[+-]?\d*\.?\d+(?:[eE][+-]?\d+)?$")


def _pattern(picture: str, kind: str) -> str | None:
    """The inside of ``kind{…}``, or the bare picture when it has no wrapper."""
    text = picture.strip()
    if not text:
        return None
    match = re.search(rf"{kind}(?:\([^)]*\))?\{{([^}}]*)\}}", text)
    if match:
        return match.group(1)
    if "{" in text:
        return None  # a picture for another category, or several of them
    return text


def _format_date(value: str, pattern: str) -> str | None:
    match = _ISO_DATE.match(value.strip())
    if not match:
        return None
    try:
        when = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None

    def token(found: re.Match) -> str:
        part = found.group(0)
        if part.startswith("'"):
            return part[1:-1]
        return {
            "YYYY": f"{when.year:04d}",
            "YY": f"{when.year % 100:02d}",
            "MMMM": _MONTHS[when.month - 1],
            "MMM": _MONTHS[when.month - 1][:3],
            "MM": f"{when.month:02d}",
            "M": str(when.month),
            "DD": f"{when.day:02d}",
            "D": str(when.day),
        }[part]

    return _DATE_TOKEN.sub(token, pattern)


def _format_number(value: str, pattern: str) -> str | None:
    raw = value.strip()
    if not _NUMBER.match(raw):
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    body = re.sub(r"'[^']*'", "", pattern)
    digits = "".join(ch for ch in body if ch in "9zZ8,.vV")
    if not digits:
        return None
    integer, _, fraction = digits.replace("v", ".").replace("V", ".").partition(".")
    decimals = sum(1 for ch in fraction if ch in "9zZ8")
    grouped = "," in integer
    text = f"{abs(number):,.{decimals}f}" if grouped else f"{abs(number):.{decimals}f}"
    if number < 0:
        text = "-" + text
    prefix = pattern[: len(pattern) - len(pattern.lstrip("$€£ "))]
    return prefix + text


def _plain_number(value: str) -> str:
    """``4416.00000000`` -> ``4416``: what an unformatted numeric field shows."""
    raw = value.strip()
    if not _NUMBER.match(raw) or "e" in raw.lower() or "." not in raw:
        return value
    trimmed = raw.rstrip("0").rstrip(".")
    return trimmed or "0"


def display_value(field: XfaField) -> str:
    """*field*'s value as the form would show it."""
    value = field.value or ""
    if not value:
        return value
    picture = field.picture or ""
    if field.field_type is XfaFieldType.DATE:
        pattern = _pattern(picture, "date")
        if pattern:
            return _format_date(value, pattern) or value
        return value
    if field.field_type is XfaFieldType.NUMERIC:
        pattern = _pattern(picture, "num")
        if pattern:
            return _format_number(value, pattern) or value
        return _plain_number(value)
    return value
