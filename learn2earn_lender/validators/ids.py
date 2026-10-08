"""Identifier validation and generation.

Identifiers are opaque strings, but they must be non-empty, unique and
filesystem/URL safe. The sequential generators produce the human-friendly
``R001`` / ``F002`` / ``C003`` style used by the seed data, while still
accepting hand-written identifiers from imports.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..domain.errors import ValidationError

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def validate_id(value: object, field: str = "id") -> str:
    """Return a validated identifier, or raise :class:`ValidationError`."""
    if value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    if not ID_PATTERN.match(text):
        raise ValidationError(
            f"{field} {text!r} is invalid: use letters, digits, "
            "'-', '_', '.' or ':' and start with a letter or digit"
        )
    return text


def next_sequential_id(prefix: str, existing: Iterable[str], width: int = 3) -> str:
    """Return the next free ``PREFIXnnn`` identifier.

    Identifiers that do not follow the ``PREFIXnnn`` shape are ignored when
    computing the high-water mark, so imported records with custom IDs never
    block generation.
    """
    prefix = str(prefix).strip()
    if not prefix:
        raise ValidationError("id prefix must not be empty")

    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for raw in existing:
        match = pattern.match(str(raw).strip())
        if match:
            highest = max(highest, int(match.group(1)))

    number = highest + 1
    body = str(number).zfill(width)
    if len(body) > width:
        # Past 999 the zero padding simply stops applying; the ID stays unique.
        return f"{prefix}{body}"
    return f"{prefix}{body}"
