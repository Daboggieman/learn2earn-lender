"""Date and timestamp helpers.

All persisted timestamps are ISO 8601 strings. Bare dates are ``YYYY-MM-DD``
(used for loan due dates and the daily transaction filenames); event
timestamps are full local ISO 8601 with second precision.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..domain.errors import ValidationError

DATE_FORMAT = "%Y-%m-%d"


def now() -> datetime:
    """Current local time, truncated to whole seconds.

    Truncating keeps persisted timestamps stable and readable rather than
    carrying microseconds that differ on every run of the same test.
    """
    return datetime.now().replace(microsecond=0)


def now_iso() -> str:
    """Current local time as an ISO 8601 string."""
    return now().isoformat()


def to_iso(moment: datetime) -> str:
    """Format a datetime as a second-precision ISO 8601 string."""
    return moment.replace(microsecond=0).isoformat()


def parse_datetime(value: object, field: str = "timestamp") -> datetime:
    """Parse an ISO 8601 timestamp, rejecting bare dates and bad input."""
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = _require_text(value, field)
    try:
        return datetime.fromisoformat(text).replace(microsecond=0)
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be an ISO 8601 timestamp (e.g. 2026-02-01T09:30:00), got {text!r}"
        ) from exc


def parse_date(value: object, field: str = "date") -> date:
    """Parse a ``YYYY-MM-DD`` date.

    A full ISO timestamp is also accepted; only its date part is used, which
    makes CLI arguments forgiving.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _require_text(value, field)
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be a date in YYYY-MM-DD form, got {text!r}"
        ) from exc


def format_date(value: date) -> str:
    """Render a date as ``YYYY-MM-DD``."""
    return value.strftime(DATE_FORMAT)


def date_from_timestamp(timestamp: str) -> str:
    """Extract the ``YYYY-MM-DD`` portion of an ISO timestamp.

    Used to choose which daily transaction file an event belongs in.
    """
    return parse_datetime(timestamp, "timestamp").strftime(DATE_FORMAT)


def require_not_before(
    later: datetime,
    earlier: datetime,
    later_field: str = "due date",
    earlier_field: str = "issue date",
) -> None:
    """Raise unless ``later`` is on or after ``earlier``."""
    if later < earlier:
        raise ValidationError(
            f"{later_field} ({to_iso(later)}) must not precede "
            f"{earlier_field} ({to_iso(earlier)})"
        )


def add_days(moment: datetime, days: int) -> datetime:
    """Return ``moment`` shifted by ``days``."""
    return moment + timedelta(days=days)


def _require_text(value: object, field: str) -> str:
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    return text
