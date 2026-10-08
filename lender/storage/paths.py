from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent

DEFAULT_DATA_DIRNAME = "data"


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def default(cls) -> "DataPaths":
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

    @property
    def seed_resources_file(self) -> Path:
        return self.seed_dir / "resources.json"

    @property
    def seed_people_file(self) -> Path:
        return self.seed_dir / "people.json"

    def transaction_file(self, date_key: str) -> Path:
        return self.transactions_dir / f"{date_key}.json"

    def ensure(self) -> None:
        for directory in (self.seed_dir, self.current_dir, self.transactions_dir):
            directory.mkdir(parents=True, exist_ok=True)
