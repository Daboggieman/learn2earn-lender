"""Quantity validation helpers.

Quantities arrive from the CLI as strings and from JSON as numbers, so every
helper coerces before checking. Booleans are rejected explicitly because
``bool`` is a subclass of ``int`` in Python and would otherwise pass.
"""

from __future__ import annotations

from ..domain.errors import ValidationError


def coerce_int(value: object, field: str = "quantity") -> int:
    """Return ``value`` as an ``int``, or raise :class:`ValidationError`."""
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a whole number, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(f"{field} must be a whole number, got {value}")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError(f"{field} must not be empty")
        try:
            return int(text)
        except ValueError as exc:
            raise ValidationError(f"{field} must be a whole number, got {value!r}") from exc
    raise ValidationError(f"{field} must be a whole number, got {type(value).__name__}")


def require_positive(value: object, field: str = "quantity") -> int:
    """Return a strictly positive integer."""
    number = coerce_int(value, field)
    if number <= 0:
        raise ValidationError(f"{field} must be greater than zero, got {number}")
    return number


def require_non_negative(value: object, field: str = "quantity") -> int:
    """Return an integer greater than or equal to zero."""
    number = coerce_int(value, field)
    if number < 0:
        raise ValidationError(f"{field} must not be negative, got {number}")
    return number
