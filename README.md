# Useful Automation Lab

Small automations that save time without hiding what they do.

The inventory tool creates deterministic JSON snapshots of a directory, including file sizes and SHA-256 hashes. The comparison tool validates two snapshots and reports added, removed, and modified files without touching either directory. Together they can verify what changed between backups or exports.

## Create an inventory

```powershell
python -m useful_automation_lab.inventory . --output inventory.json
```

## Compare snapshots

```powershell
python -m useful_automation_lab.compare examples/snapshot-before.json examples/snapshot-after.json
```

The comparison output is deterministic JSON. Exit code `0` means the snapshots match, `1` means changes were found, and `2` means an inventory was invalid or unreadable. Paths must be normalized and relative, hashes must be lowercase SHA-256 values, and duplicate paths are rejected rather than silently overwritten.

## Test

```powershell
python -m unittest discover -s tests -v
```

Tools in this repository are safe by default: read-only unless an output action is explicitly requested, narrow in scope, and covered by tests.
