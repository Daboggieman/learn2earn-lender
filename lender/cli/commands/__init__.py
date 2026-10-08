from __future__ import annotations

from . import data, inventory, reports, taxonomy

MODULES = (taxonomy, inventory, reports, data)


def register_all(subparsers) -> None:
    for module in MODULES:
        module.register(subparsers)
