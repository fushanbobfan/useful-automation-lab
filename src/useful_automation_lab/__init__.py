"""Safe, inspectable automation helpers."""

from typing import Any

__all__ = [
    "InvalidInventoryError",
    "InvalidEnvContractError",
    "InvalidPolicyError",
    "audit_inventory_policy",
    "audit_csv",
    "audit_env_contract",
    "audit_jsonl",
    "audit_jsonl_event_order",
    "audit_jsonl_references",
    "audit_path_portability",
    "audit_sqlite",
    "audit_tar",
    "audit_text_file",
    "audit_zip",
    "build_inventory",
    "compare_inventories",
    "compare_jsonl_records",
    "compare_jsonl_structures",
    "compare_sqlite_schemas",
    "find_duplicates",
    "load_inventory",
    "load_jsonl_records",
    "load_env_contract",
    "load_policy",
    "parse_env_file",
    "verify_directory",
]


def __getattr__(name: str) -> Any:
    if name == "compare_jsonl_records":
        from .jsonl_record_diff import compare_jsonl_records

        return compare_jsonl_records
    if name in {"compare_jsonl_structures", "load_jsonl_records"}:
        from .jsonl_structure import compare_jsonl_structures, load_jsonl_records

        return {
            "compare_jsonl_structures": compare_jsonl_structures,
            "load_jsonl_records": load_jsonl_records,
        }[name]
    if name in {
        "InvalidEnvContractError",
        "audit_env_contract",
        "load_env_contract",
        "parse_env_file",
    }:
        from .env_contract import (
            InvalidEnvContractError,
            audit_env_contract,
            load_env_contract,
            parse_env_file,
        )

        return {
            "InvalidEnvContractError": InvalidEnvContractError,
            "audit_env_contract": audit_env_contract,
            "load_env_contract": load_env_contract,
            "parse_env_file": parse_env_file,
        }[name]
    if name == "compare_sqlite_schemas":
        from .sqlite_schema_diff import compare_sqlite_schemas

        return compare_sqlite_schemas
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
    if name == "audit_jsonl_event_order":
        from .jsonl_event_order import audit_jsonl_event_order

        return audit_jsonl_event_order
    if name == "audit_jsonl_references":
        from .jsonl_references import audit_jsonl_references

        return audit_jsonl_references
    if name == "audit_path_portability":
        from .portability import audit_path_portability

        return audit_path_portability
    if name == "audit_sqlite":
        from .sqlite_audit import audit_sqlite

        return audit_sqlite
    if name == "audit_tar":
        from .tar_audit import audit_tar

        return audit_tar
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
