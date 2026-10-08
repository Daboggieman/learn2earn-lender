from __future__ import annotations

import re
from collections.abc import Iterable

from ..domain.errors import ValidationError

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def validate_id(value: object, field: str = "id") -> str:
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
    prefix = str(prefix).strip()
    if not prefix:
        raise ValidationError("id prefix must not be empty")

    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    for raw in existing:
        match = pattern.match(str(raw).strip())
        if match:
            highest = max(highest, int(match.group(1)))

    body = str(highest + 1).zfill(width)
    return f"{prefix}{body}"
