"""Business error hierarchy.

Every error raised deliberately by the application derives from
:class:`LenderError`, so the CLI can turn it into a clean message and exit
code without catching broad ``Exception``.
"""

from __future__ import annotations


class LenderError(Exception):
    """Base class for every deliberate application error."""

    exit_code = 1


class ValidationError(LenderError):
    """User input or imported data failed validation."""

    exit_code = 2


class NotFoundError(LenderError):
    """A requested record does not exist."""

    exit_code = 3


class ConflictError(LenderError):
    """An operation contradicts existing state (duplicate ID, in-use record)."""

    exit_code = 4


class InvariantViolation(LenderError):
    """A domain invariant would be broken by the operation."""

    exit_code = 5


class StorageError(LenderError):
    """Reading or writing persisted data failed."""

    exit_code = 6


class ImportConflict(LenderError):
    """An import would overwrite data that the caller did not agree to replace."""

    exit_code = 7
