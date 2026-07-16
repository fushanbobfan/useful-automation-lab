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

## Verify a directory

Verify current files directly against a saved inventory without creating a second snapshot:

```powershell
python -m useful_automation_lab.verify . inventory.json --output verification.json
```

The verification command uses the same deterministic change report and `0`/`1`/`2` exit codes as snapshot comparison. If the manifest was written inside the verified directory but was not part of the original snapshot, it is excluded automatically instead of appearing as a false addition. The command only reads directory contents unless `--output` is provided.

## Exclude generated paths

Both inventory creation and direct verification accept repeatable relative POSIX glob exclusions. Use the same exclusions for the baseline and every later verification:

```powershell
file-inventory export --exclude "*.tmp" --exclude "cache" --output manifest.json
manifest-verify export manifest.json --exclude "*.tmp" --exclude "cache"
```

A pattern is matched against each file's relative path and its directory ancestors, so `cache` omits the whole directory while `*.tmp` omits matching files at any depth. Patterns are not stored in the manifest; keeping them explicit makes every verification command auditable. Absolute paths, parent traversal, backslashes, and non-normalized patterns are rejected with exit code `2`. The built-in `.git` and `__pycache__` directory exclusions remain active.

## Find duplicate content

Inspect a validated inventory for files with matching SHA-256 digests and sizes:

```powershell
python -m useful_automation_lab.duplicates inventory.json --min-size 1024
```

The deterministic report groups duplicate paths, counts affected files, and estimates reclaimable bytes as all but one copy in each group. Larger opportunities appear first, and `--min-size` can suppress small files. The command is read-only; it never chooses or deletes a copy. Use `--output duplicates.json` to save the report or `--fail-on-duplicates` to return exit code `1` for policy checks. Invalid inventories and arguments return `2`.

Duplicate results describe the content hashes recorded in the manifest. Run `manifest-verify` first when the files may have changed since the snapshot was created.

## Test

```powershell
python -m unittest discover -s tests -v
```

Tools in this repository are safe by default: read-only unless an output action is explicitly requested, narrow in scope, and covered by tests.
