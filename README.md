# Useful Automation Lab

Small automations that save time without hiding what they do.

The initial tool creates deterministic JSON inventories of a directory, including file sizes and SHA-256 hashes. This can be used to detect changed, added, or missing files in backups and exports.

```powershell
python -m useful_automation_lab.inventory . --output inventory.json
python -m unittest discover -s tests
```

Tools in this repository should be safe by default: read-only unless an action is explicitly requested, narrow in scope, and covered by tests.

