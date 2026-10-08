from __future__ import annotations


class LenderError(Exception):
    exit_code = 1


class ValidationError(LenderError):
    exit_code = 2


class NotFoundError(LenderError):
    exit_code = 3


class ConflictError(LenderError):
    exit_code = 4


class InvariantViolation(LenderError):
    exit_code = 5


class StorageError(LenderError):
    exit_code = 6


class ImportConflict(LenderError):
    exit_code = 7
