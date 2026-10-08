"""Reusable string validation helpers."""

from __future__ import annotations

import re

from ..domain.errors import ValidationError

_WHITESPACE = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def require_non_empty(value: object, field: str = "value") -> str:
    """Return ``value`` as a stripped string, or raise if it is blank.

    Non-string inputs are stringified first so CLI arguments (always
    strings) and JSON values (often not) share one code path.
    """
    if value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    return text


def normalise_name(value: object, field: str = "name") -> str:
    """Trim and collapse internal whitespace so names compare reliably."""
    return _WHITESPACE.sub(" ", require_non_empty(value, field))


def slugify(value: object, field: str = "value") -> str:
    """Convert a display name into a lowercase dash-separated identifier.

    ``"Cluster 1 Feb"`` becomes ``"cluster-1-feb"``.
    """
    text = normalise_name(value, field).lower()
    slug = _NON_SLUG.sub("-", text).strip("-")
    if not slug:
        raise ValidationError(f"{field} must contain at least one letter or digit")
    return slug


def truncate(value: str, limit: int = 40) -> str:
    """Shorten a string for tabular output without splitting mid-word."""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
