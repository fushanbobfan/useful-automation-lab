"""Safe, inspectable automation helpers."""

from typing import Any

__all__ = [
    "InvalidInventoryError",
    "build_inventory",
    "compare_inventories",
    "find_duplicates",
    "load_inventory",
    "verify_directory",
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
    if name == "verify_directory":
        from .verify import verify_directory

        return verify_directory
    if name == "find_duplicates":
        from .duplicates import find_duplicates

        return find_duplicates
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
