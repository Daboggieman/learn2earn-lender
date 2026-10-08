"""Filesystem layout.

Every path the application touches is derived here, so relocating the data
directory (``--data-dir``, or a test's temporary directory) is a single
constructor argument rather than a scattered set of relative paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent

DEFAULT_DATA_DIRNAME = "data"


@dataclass(frozen=True)
class DataPaths:
    """Resolved locations of the application's data files.

    Layout (BUILD_PLAN §6)::

        <root>/
        ├── seed/          pristine startup data, never written at runtime
        ├── current/       projections — safe to delete, rebuilt from the log
        └── transactions/  the append-only daily event log (source of truth)
    """

    root: Path

    @classmethod
    def default(cls) -> "DataPaths":
        """``<project>/data`` — the location used when no override is given."""
        return cls(PROJECT_ROOT / DEFAULT_DATA_DIRNAME)

    @classmethod
    def at(cls, root: str | Path) -> "DataPaths":
        return cls(Path(root).expanduser().resolve())

    @property
    def seed_dir(self) -> Path:
        return self.root / "seed"

    @property
    def current_dir(self) -> Path:
        return self.root / "current"

    @property
    def transactions_dir(self) -> Path:
        return self.root / "transactions"

    # -- current-state projections -------------------------------------

    @property
    def inventory_file(self) -> Path:
        return self.current_dir / "inventory.json"

    @property
    def taxonomy_file(self) -> Path:
        return self.current_dir / "taxonomy.json"

    @property
    def groups_file(self) -> Path:
        return self.current_dir / "groups.json"

    @property
    def people_file(self) -> Path:
        return self.current_dir / "people.json"

    @property
    def loans_file(self) -> Path:
        return self.current_dir / "loans.json"

    # -- seed ----------------------------------------------------------

    @property
    def seed_resources_file(self) -> Path:
        return self.seed_dir / "resources.json"

    @property
    def seed_people_file(self) -> Path:
        return self.seed_dir / "people.json"

    # -- log -----------------------------------------------------------

    def transaction_file(self, date_key: str) -> Path:
        """``"2026-02-01"`` -> ``<root>/transactions/2026-02-01.json``."""
        return self.transactions_dir / f"{date_key}.json"

    def ensure(self) -> None:
        """Create the directory skeleton if it is missing."""
        for directory in (self.seed_dir, self.current_dir, self.transactions_dir):
            directory.mkdir(parents=True, exist_ok=True)
