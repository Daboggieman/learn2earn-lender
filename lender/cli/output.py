from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Sequence

from ..validators.strings import truncate

DEFAULT_WIDTHS: dict[str, int] = {
    "name": 28,
    "category": 16,
    "subcategory": 18,
    "notes": 24,
}


def configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    widths: dict[str, int] | None = None,
) -> str:
    limits = widths if widths is not None else DEFAULT_WIDTHS
    cells = [
        [
            truncate(str(value), limits.get(header, 32))
            for header, value in zip(headers, row)
        ]
        for row in rows
    ]
    if not cells:
        return ""

    sizes = [
        max(len(headers[index]), *(len(row[index]) for row in cells))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(header.ljust(sizes[index]) for index, header in enumerate(headers)),
        "  ".join("-" * size for size in sizes),
    ]
    for row in cells:
        lines.append(
            "  ".join(value.ljust(sizes[index]) for index, value in enumerate(row))
        )
    return "\n".join(lines)


def print_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    rendered = render_table(headers, rows)
    print(rendered if rendered else "(no rows)")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def print_json(payload: Any) -> None:
    print(json.dumps(to_jsonable(payload), indent=2, ensure_ascii=False))


def emit(
    as_json: bool,
    *,
    payload: Any = None,
    headers: Sequence[str] | None = None,
    rows: Iterable[Sequence[Any]] | None = None,
    empty: str = "(no rows)",
) -> None:
    if as_json:
        print_json(payload if payload is not None else [])
        return
    if headers is None:
        print_json(payload)
        return
    materialised = list(rows or [])
    if not materialised:
        print(empty)
        return
    print_table(headers, materialised)


def info(message: str) -> None:
    print(message)


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def pluralise(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"
