from __future__ import annotations

import re

from ..domain.errors import ValidationError

_WHITESPACE = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def require_non_empty(value: object, field: str = "value") -> str:
    if value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    return text


def normalise_name(value: object, field: str = "name") -> str:
    return _WHITESPACE.sub(" ", require_non_empty(value, field))


def slugify(value: object, field: str = "value") -> str:
    text = normalise_name(value, field).lower()
    slug = _NON_SLUG.sub("-", text).strip("-")
    if not slug:
        raise ValidationError(f"{field} must contain at least one letter or digit")
    return slug


def truncate(value: str, limit: int = 40) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
