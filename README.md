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

## Compare keyed JSONL records

Schema checks can pass while individual records are added, removed, or changed. Compare two strict JSONL snapshots by a stable top-level key:

```powershell
python -m useful_automation_lab.jsonl_record_diff `
  examples/record-diff-reference.jsonl `
  examples/record-diff-candidate.jsonl `
  --ignore-field updated_at `
  --max-added 1 --max-removed 1 --max-modified 1
```

The key defaults to `id` and accepts non-empty strings or integers without conflating values such as `1` and `"1"`. Keys must be unique within each snapshot. Records are compared as canonical JSON after repeatable `--ignore-field` exclusions, so object-key order is irrelevant while array order remains significant. The report counts additions, removals, modifications, and unchanged records. Bounded details contain IDs and changed top-level field names only; payload values are not copied. The default change budgets are all zero for strict CI use.

Exit code `0` means each configured budget passed, `1` reports valid snapshot changes above budget, and `2` identifies malformed or oversized JSONL, duplicate keys, unsafe output aliasing, or invalid configuration. IDs and field names can still be sensitive, so use non-identifying keys or set `--max-details 0` before sharing a report. Ignored fields are excluded completely and can hide meaningful changes if chosen carelessly.

This is a read-only equality comparison over two finite snapshots. It does not match renamed keys, interpret timestamps, compare nested fields semantically, repair data, validate application behavior, or prove that a change is safe. Run the structure audit separately when field presence and type drift also matter.

## Audit JSONL references

Check the join between parent and child JSONL exports before loading them into a pipeline:

```powershell
python -m useful_automation_lab.jsonl_references `
  examples/reference-parents.jsonl `
  examples/reference-children.jsonl `
  --parent-id-field id `
  --child-reference-field customer_id `
  --max-orphan-references 1 `
  --max-unreferenced-parents 1 `
  --max-children-per-parent 2
```

The audit requires unique scalar parent IDs and one scalar reference on every child. It reports orphaned child references, parents with no children, the observed maximum children per parent, and bounded join-cardinality details. String and finite numeric identifiers are supported without conflating values such as `1` and `"1"`. Both inputs use the strict JSONL object loader, including duplicate-key and non-standard-number rejection plus a configurable file-size bound.

Exit code `0` means every configured maximum passed, `1` reports referential-integrity or fan-out threshold failures, and `2` identifies malformed or oversized inputs, duplicate parent IDs, unsafe file aliasing, or invalid configuration. The JSON report omits non-ID payload values, but join identifiers themselves can be sensitive; set `--max-details 0` or review saved output before sharing it.

This is a read-only equality-join audit for two finite exports. It does not validate nested or composite keys, infer relationships, repair records, enforce database constraints, prove application-level consistency, or explain whether an orphan, unreferenced parent, or high fan-out is erroneous. Thresholds should reflect the intended data model.

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
