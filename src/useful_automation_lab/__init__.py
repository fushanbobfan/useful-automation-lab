"""Safe, inspectable automation helpers."""

from typing import Any

__all__ = [
    "InvalidInventoryError",
    "build_inventory",
    "compare_inventories",
    "load_inventory",
]


def __getattr__(name: str) -> Any:
    if name == "build_inventory":
        from .inventory import build_inventory

        return build_inventory
    if name in {"InvalidInventoryError", "compare_inventories", "load_inventory"}:
        from .compare import InvalidInventoryError, compare_inventories, load_inventory

        return {
            "InvalidInventoryError": InvalidInventoryError,
            "compare_inventories": compare_inventories,
            "load_inventory": load_inventory,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
