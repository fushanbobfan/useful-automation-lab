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

## Audit manifest path portability

Check a validated inventory for common cross-platform path hazards before moving an export or build artifact between filesystems:

```powershell
python -m useful_automation_lab.portability `
  examples/snapshot-after.json --max-path-bytes 240
```

The audit flags Windows reserved device names, forbidden characters, trailing spaces or dots, ASCII control characters, UTF-8 components longer than the default 255-byte limit, optional relative-path length limits, file-versus-directory conflicts, and whole-path collisions after case folding or Unicode NFC normalization. Pure case, pure normalization, and combined case-plus-normalization collisions remain distinct in the report.

Issue details are deterministic and bounded by `--max-errors`, while total issue counts, affected-path counts, and per-code counts remain complete. Exit code `0` means the manifest paths passed, `1` means portability hazards were found, and `2` means the inventory or configuration was invalid. A report output cannot directly, symbolically, or through a hard link overwrite the source inventory.

This command audits paths recorded in a snapshot; it does not inspect or rename live files. Run `manifest-verify` first when the directory may have changed. Filesystem rules vary, UTF-8 byte limits are only a conservative interoperability check, and a passing report does not guarantee that every archive tool, network share, checkout, or target filesystem will accept the paths.

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

## Audit JSONL references

Check a parent export and a child export before a join or load:

```powershell
python -m useful_automation_lab.jsonl_references `
  examples/reference-parents.jsonl `
  examples/reference-children.jsonl `
  --max-orphan-references 1 `
  --max-unreferenced-parents 1 `
  --max-children-per-parent 2
```

The parent stream requires one unique scalar `id` per object, and the child stream requires a scalar `parent_id` by default. Field-name flags support other top-level schemas. The report counts child references with no matching parent, parents with no children, and the largest observed children-per-parent fanout. Bounded details retain join IDs and counts only; other scalar fields are not copied. String and numeric IDs are type-sensitive, so the string `"1"` and number `1` remain distinct.

Exit code `0` means every configured orphan, unreferenced-parent, and fanout maximum passed; `1` reports all structured threshold failures; and `2` identifies malformed or oversized strict JSONL, duplicate parent IDs, unsupported ID shapes, the same file used for both inputs, unsafe output aliasing, or invalid configuration. Both inputs use the existing strict duplicate-key/non-standard-number reader with a default 10 MiB bound. Source files are never changed.

This audit checks top-level equality for two supplied snapshots. It does not validate nested foreign keys, temporal validity, relationship meaning, authorization, deletion policy, transaction isolation, or whether an unreferenced parent is intentionally allowed. IDs themselves can be sensitive, so review reports before sharing and use non-identifying keys in committed examples.

## Compare JSONL structure

Detect top-level field drift between two strict JSONL exports without copying scalar values into the report:

```powershell
python -m useful_automation_lab.jsonl_structure `
  examples/jsonl-structure-reference.jsonl `
  examples/jsonl-structure-candidate.jsonl `
  --max-presence-rate-delta 0.50 `
  --max-null-rate-delta 0.50 `
  --max-changes 2
```

Each profile reports record count plus, for every top-level field, presence and missing counts, requiredness, null rate among present records, and non-null JSON type counts. The comparison reports added or removed fields, non-null type-set changes, and presence/null-rate changes beyond explicit tolerances. `--max-details` bounds returned changes while full totals and per-kind counts remain visible. Inputs are strict JSONL object streams with duplicate-key and non-standard-number rejection and a default 10 MiB file bound.

Exit code `0` means the atomic change count is within budget, `1` reports valid structural drift above budget, and `2` identifies malformed or oversized inputs, unsafe output aliasing, or invalid configuration. Reports contain field names and aggregate structure but no scalar values; field names and type/presence patterns can still be sensitive. This is a top-level observed-sample profile, not JSON Schema validation, nested-shape comparison, semantic compatibility analysis, or proof that a downstream consumer will accept the candidate data.

## Audit dotenv configuration contracts

Check that a dotenv file supplies the expected configuration keys without copying its values into the report:

```powershell
python -m useful_automation_lab.env_contract `
  examples/env-contract.json examples/service.env.example
```

A version 1 JSON contract declares `required_keys`, `optional_keys`, `non_empty_keys`, and `allowed_prefixes`. Key names use the portable `[A-Za-z_][A-Za-z0-9_]*` form. Required and optional sets must be disjoint, every non-empty key must be declared, unknown contract fields fail closed, and duplicate rules are rejected. `--max-extra-keys` allows an explicit number of undeclared keys; prefix-matched keys do not consume that budget.

The bounded UTF-8 dotenv reader accepts comments, blank lines, ordinary `KEY=value` assignments, and an optional `export ` prefix. It rejects invalid or duplicate keys and reduces each value immediately to a blank/non-blank flag. JSON output contains contract keys, counts, line numbers, and bounded violation details, never dotenv values. Empty, `''`, and `""` are treated as blank; no interpolation, escape processing, command substitution, or inline-comment interpretation is performed.

Exit code `0` means the contract passed, `1` reports missing required keys, blank keys that must be non-empty, or excess undeclared keys, and `2` identifies malformed input, files above the default 1 MiB bound, unsafe output aliasing, or invalid configuration. This is a configuration-shape audit, not a secret scanner, dotenv runtime implementation, permission check, deployment validator, or proof that supplied values are correct or safe. Keep real environment files private and use synthetic values in committed examples.

## Audit SQLite databases

Check a SQLite file's structural health, foreign-key consistency, and schema inventory without reading business-table rows:

```powershell
$database = Join-Path $env:TEMP "sqlite-audit-demo.sqlite"
python examples/create_sqlite_demo.py $database
python -m useful_automation_lab.sqlite_audit $database `
  --max-errors 20 --output sqlite-report.json
```

The source is opened with SQLite URI `mode=ro`, connection-level `query_only`, disabled extension loading, and an untrusted-schema restriction. The report combines `quick_check`, a complete `foreign_key_check`, page and freelist metadata, user/application versions, object-type counts, and per-table column, key, foreign-key, and index counts. It records table names and structural metadata but does not select application rows or include schema SQL.

`--max-errors` bounds detailed findings while full foreign-key violation counts remain visible. Exit code `0` means both checks passed, `1` means integrity or foreign-key problems were found, and `2` means the file, configuration, or report output could not be processed. The command refuses to use the source database as its output path.

This is a read-only diagnostic, not a repair, migration, backup, malware scan, or proof of application-level correctness. Table names and schema counts can still be sensitive; review a saved JSON report before sharing it. Large databases may make SQLite's own health checks expensive even though no rows are returned to the report.

## Compare SQLite schemas

Catch an unexpected structural change before an application opens a candidate database. The demo creates two disposable databases, then the comparison enforces an explicit atomic-change budget:

```powershell
$demo = Join-Path $env:TEMP "sqlite-schema-diff-demo"
python examples/create_sqlite_schema_diff_demo.py $demo
python -m useful_automation_lab.sqlite_schema_diff `
  (Join-Path $demo "schema-reference.sqlite") `
  (Join-Path $demo "schema-candidate.sqlite") `
  --max-changes 1 --max-details 50
```

Both files are opened with SQLite URI `mode=ro`, `query_only`, disabled extension loading, and an untrusted-schema restriction. The deterministic report covers main-schema table additions and removals; table options; declared and hidden columns; index definitions; and grouped foreign-key targets, column pairs, and actions. A zero change budget is the default. Exit code `0` means the change count is within budget, `1` reports a valid schema difference above budget, and `2` identifies an invalid database, unsafe output alias, or invalid configuration.

`--max-details` bounds the returned change list while exact totals and per-kind counts remain visible. The comparison does not execute migrations, select application rows, or compare data, views, triggers, virtual-table implementations, database pragmas, or application semantics. SQLite type/default declarations are compared structurally, so a clean result is not a backward-compatibility proof. Schema identifiers and default expressions can still be sensitive; inspect JSON reports before publishing them.

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

## Audit TAR archives before extraction

Inspect TAR, TAR.GZ, TAR.BZ2, or TAR.XZ headers without extracting or reading member payloads:

```powershell
$archive = Join-Path $env:TEMP "safe-example.tar.gz"
python examples/create_tar_demo.py $archive
python -m useful_automation_lab.tar_audit $archive
```

The audit reports absolute and drive-qualified names, parent traversal, backslashes, duplicate and case-colliding paths, symbolic and hard links, unsafe link targets, device/FIFO entries, unsupported member types, oversized members, excessive declared content, excessive expansion, and an overlong member list. Link entries are reported even when their target appears contained because extraction behavior varies across tools and platforms.

Defaults reject physical archives above 512 MiB without opening them, inspect at most 10,000 members, and allow at most 100 MiB per regular member, 1 GiB of declared regular-file content, and a 100:1 declared-size-to-archive-size ratio. The scan stops after the member cap and marks totals as partial. `--max-errors` bounds only detailed issues; summary counts remain complete for the inspected prefix. Opening a compressed TAR still decompresses the stream far enough to enumerate its headers, so these checks reduce risk but do not make untrusted archives cost-free.

Exit code `0` means the configured metadata checks passed, `1` means hazards were found, and `2` means the archive, configuration, or report output could not be processed. `--output` writes JSON but refuses direct, symbolic-path, or hard-link aliases of the source archive. Member paths and link targets appear in the report and may themselves be sensitive. This is pre-extraction screening, not malware detection, content validation, or proof that extraction is safe.

## Test

```powershell
python -m unittest discover -s tests -v
```

Tools in this repository are safe by default: read-only unless an output action is explicitly requested, narrow in scope, and covered by tests.
