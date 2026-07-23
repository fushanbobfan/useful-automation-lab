"""Safe, inspectable automation helpers."""

from typing import Any

__all__ = [
    "InvalidInventoryError",
    "InvalidPolicyError",
    "audit_inventory_policy",
    "audit_csv",
    "audit_jsonl",
    "audit_sqlite",
    "audit_text_file",
    "audit_zip",
    "build_inventory",
    "compare_inventories",
    "find_duplicates",
    "load_inventory",
    "load_policy",
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
    if name in {"InvalidPolicyError", "audit_inventory_policy", "load_policy"}:
        from .policy import InvalidPolicyError, audit_inventory_policy, load_policy

        return {
            "InvalidPolicyError": InvalidPolicyError,
            "audit_inventory_policy": audit_inventory_policy,
            "load_policy": load_policy,
        }[name]
    if name == "audit_jsonl":
        from .jsonl_audit import audit_jsonl

        return audit_jsonl
    if name == "audit_sqlite":
        from .sqlite_audit import audit_sqlite

        return audit_sqlite
    if name == "audit_csv":
        from .csv_audit import audit_csv

        return audit_csv
    if name == "audit_text_file":
        from .text_audit import audit_text_file

        return audit_text_file
    if name == "audit_zip":
        from .zip_audit import audit_zip

        return audit_zip
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
