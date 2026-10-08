from __future__ import annotations

from . import data, inventory, lending, people, reports, taxonomy

MODULES = (taxonomy, inventory, people, lending, reports, data)


def register_all(subparsers) -> None:
    for module in MODULES:
        module.register(subparsers)
