from __future__ import annotations

from datetime import date, datetime, timedelta

from ..domain.errors import ValidationError

DATE_FORMAT = "%Y-%m-%d"


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def now_iso() -> str:
    return now().isoformat()


def to_iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def parse_datetime(value: object, field: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = _require_text(value, field)
    try:
        return datetime.fromisoformat(text).replace(microsecond=0)
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be an ISO 8601 timestamp "
            f"(e.g. 2026-02-01T09:30:00), got {text!r}"
        ) from exc


def parse_date(value: object, field: str = "date") -> date:
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
    return value.strftime(DATE_FORMAT)


def date_from_timestamp(timestamp: str) -> str:
    return parse_datetime(timestamp, "timestamp").strftime(DATE_FORMAT)


def require_not_before(
    later: datetime,
    earlier: datetime,
    later_field: str = "due date",
    earlier_field: str = "issue date",
) -> None:
    if later < earlier:
        raise ValidationError(
            f"{later_field} ({to_iso(later)}) must not precede "
            f"{earlier_field} ({to_iso(earlier)})"
        )


def add_days(moment: datetime, days: int) -> datetime:
    return moment + timedelta(days=days)


def _require_text(value: object, field: str) -> str:
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field} must not be empty")
    return text
