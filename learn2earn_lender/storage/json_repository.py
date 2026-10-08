"""JSON file reading and writing.

Two properties matter throughout the app:

* **Writes are atomic.** A crash mid-write must not leave a half-written file
  where the inventory used to be, so every write goes to a sibling temp file
  and is then moved into place with :func:`os.replace`, which is atomic on
  both POSIX and Windows.
* **Failures are typed.** Callers catch :class:`StorageError`, not ``OSError``
  or ``json.JSONDecodeError``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..domain.errors import StorageError

ENCODING = "utf-8"


def read_json(path: Path, default: Any = None) -> Any:
    """Read a JSON document.

    Returns ``default`` when the file does not exist. Anything else that goes
    wrong — bad JSON, a directory where a file should be, a permission error —
    raises :class:`StorageError` with the path attached, because a corrupt
    data file is never something to paper over.
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding=ENCODING) as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise StorageError(
            f"{path} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
    except OSError as exc:
        raise StorageError(f"could not read {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    """Write a JSON document atomically, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    handle = None
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        temp_path = Path(temp_name)
        handle = os.fdopen(descriptor, "w", encoding=ENCODING, newline="\n")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, path)
    except OSError as exc:
        raise StorageError(f"could not write {path}: {exc}") from exc
    finally:
        if handle is not None:
            handle.close()
        # If the replace succeeded the temp file is already gone; this only
        # cleans up after a failure partway through.
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def list_json_files(directory: Path) -> list[Path]:
    """Every ``*.json`` file in ``directory``, sorted by name (so by date)."""
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix == ".json"),
        key=lambda path: path.name,
    )


def delete_file(path: Path) -> None:
    """Remove a file if it exists; missing files are not an error."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise StorageError(f"could not delete {path}: {exc}") from exc
