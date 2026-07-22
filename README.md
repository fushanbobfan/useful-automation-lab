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

## Enforce a manifest policy

Apply deterministic size, count, and path rules to a validated inventory without touching its source directory:

```powershell
python -m useful_automation_lab.policy `
  examples/snapshot-after.json examples/manifest-policy.json
```

A version 1 policy can set `max_files`, `max_total_bytes`, and `max_file_bytes`; require exact normalized paths with `required_paths`; and reject file or directory globs with `forbidden_patterns`. Forbidden patterns use the same relative POSIX and ancestor-matching rules as inventory exclusions, so `secrets` catches every file under that directory. Unknown fields, unsafe paths, duplicate rules, malformed inventories, and unsupported versions return exit code `2` instead of silently weakening the policy.

The report includes observed totals, the normalized policy, and every violation in stable order. Exit code `0` means the policy passed, while `1` means the input was valid but one or more rules failed. Use `--output policy-report.json` to save the report. Because an inventory is a snapshot, run `manifest-verify` first when current on-disk state matters.

## Audit CSV data

Validate a CSV export's header, row shape, selected values, and field sizes before a pipeline consumes it:

```powershell
python -m useful_automation_lab.csv_audit examples/events.csv `
  --require id --require occurred_on --require event `
  --not-empty id --not-empty event --unique-column id `
  --type id=integer --type occurred_on=date `
  --type duration_ms=number --type success=boolean `
  --max-field-bytes 1024 --max-errors 20
```

The strict streaming reader rejects missing, empty, or duplicate header names; missing configured columns; blank records; inconsistent row widths; duplicate values in one selected column; oversized UTF-8 fields; and malformed quoting. Optional type checks support canonical ISO dates, finite numbers, signed base-10 integers, and exact lowercase `true`/`false` booleans. Empty values skip type checks unless the column is also named with `--not-empty`.

The scanner continues after ordinary row problems so full row totals remain visible, while `--max-errors` bounds the detailed issue list. A fatal CSV parse error stops at the last trustworthy physical line and sets `stopped_early` instead of claiming a complete scan. Exit code `0` means the audit passed, `1` means data or header issues were found, and `2` means the input, output, or configuration could not be processed. Use `--output` to save the JSON report; the source CSV is never rewritten.

## Audit JSON Lines data

Check a JSONL export before a pipeline consumes it:

```powershell
python -m useful_automation_lab.jsonl_audit examples/events.jsonl `
  --require id --require event --unique-field id `
  --max-line-bytes 1024 --max-errors 20
```

Every non-blank line must be a strict JSON object. The audit rejects malformed JSON, non-standard `NaN`/`Infinity` constants, duplicate keys at any nesting level, missing required fields, repeated values for the selected unique field, and oversized UTF-8 records. Blank lines fail by default; `--allow-blank-lines` permits them while keeping their count visible.

The scanner continues through the file so summary totals reflect the full input, while `--max-errors` bounds only the detailed error list. Exit code `0` means the audit passed, `1` means validly configured checks found data issues, and `2` means the input, output, or configuration could not be processed. The command is read-only unless `--output` is supplied.

## Audit text-file hygiene

Check one text artifact before publishing or handing it to another tool:

```powershell
python -m useful_automation_lab.text_audit examples/text-audit-clean.txt `
  --max-line-bytes 120 --max-errors 20
```

The audit requires valid UTF-8, rejects NUL bytes, flags UTF-8 BOMs, mixed newline styles, bare carriage-return endings, missing final newlines, trailing spaces or tabs, and optionally oversized lines. A file using only LF or only CRLF passes the newline-style check. Use `--allow-utf8-bom` or `--allow-missing-final-newline` only when the downstream format explicitly permits those choices.

Reads are capped at 10 MiB by default and stop after one byte beyond that bound; `--max-file-bytes` can set a different explicit limit. The scanner retains total issue counts while `--max-errors` bounds detailed findings. Exit code `0` means the file passed, `1` means text issues were found, and `2` means the file could not be safely processed. The command never rewrites the source; `--output` only saves its JSON report.

## Audit ZIP archives before extraction

Inspect a ZIP central directory without decompressing or writing any member files:

```powershell
$archive = Join-Path $env:TEMP "safe-example.zip"
python examples/create_zip_demo.py $archive
python -m useful_automation_lab.zip_audit $archive
```

The audit reports absolute or drive-qualified paths, parent traversal, backslash paths, duplicate names, case collisions, symbolic links, encrypted entries, oversized files, excessive aggregate size, and suspicious compression ratios. Default limits are 100 MiB per entry, 1 GiB total uncompressed content, and a 100:1 compression ratio; each can be overridden explicitly. `--max-errors` bounds detailed findings while the summary retains complete issue counts.

Exit code `0` means the configured checks passed, `1` means archive metadata contained one or more hazards, and `2` means the archive or configuration could not be processed. Use `--output` to save the deterministic JSON report. This is a pre-extraction screening tool, not proof that archive contents are trustworthy; downstream code should still extract into a controlled destination and enforce its own resource limits.

## Test

```powershell
python -m unittest discover -s tests -v
```

Tools in this repository are safe by default: read-only unless an output action is explicitly requested, narrow in scope, and covered by tests.
