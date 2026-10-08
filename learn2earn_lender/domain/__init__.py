"""Domain layer: entities, value objects and business errors."""

from __future__ import annotations

# ``errors`` is imported first on purpose. ``validators`` imports it back, and
# binding it here before any other submodule runs keeps that cycle harmless.
from .errors import (
    ConflictError,
    ImportConflict,
    InvariantViolation,
    LenderError,
    NotFoundError,
    StorageError,
    ValidationError,
)

from . import equipment, events, groups, people, taxonomy, transactions

__all__ = [
    "ConflictError",
    "ImportConflict",
    "InvariantViolation",
    "LenderError",
    "NotFoundError",
    "StorageError",
    "ValidationError",
    "equipment",
    "events",
    "groups",
    "people",
    "taxonomy",
    "transactions",
]
