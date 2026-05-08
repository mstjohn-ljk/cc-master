---
name: impact
description: Compute blast radius for a target (file, symbol, task id, or feature id) from the Kuzu graph. Standalone, query-only, no JSON fallback — stops with a clear diagnostic when the graph is absent or stale.
---

# cc-master:impact — Blast Radius Analysis

Compute the blast radius of a change before making it. Given a target — a file path, a symbol name, a kanban task id, or a roadmap feature id — the skill queries `.cc-master/graph.kuzu` to surface direct references, transitive references, affected files, affected tests, owning modules, owning features, and in-flight tasks or specs touching the same modules. The output is a structured markdown + JSON report written to `.cc-master/impact/<slug>.md` and `.cc-master/impact/<slug>.json`.

Unlike every other graph-backed cc-master skill, `cc-master:impact` does NOT fall back to JSON computation when the graph is absent, stale, or erroring. The skill's semantic value depends on symbol-level `REFERENCES` edges that only exist in the graph — there is no meaningful JSON substitute for a reverse-reference traversal. On any pre-query check failure, the skill prints a one-line diagnostic instructing the operator to rebuild the graph, then exits.

## Task Persistence Protocol

Tasks are persisted to `.cc-master/kanban.json` — the sole source of truth.
Never use CC's TaskCreate, TaskGet, TaskList, or TaskUpdate tools.

This skill does not create, update, or delete kanban tasks. Its only kanban interaction is indirect — Step 3 (subtask #86) queries the `Task` and `Subtask` nodes in the graph to surface in-flight work touching the affected modules. No write-back path exists. The protocol line above is stated for consistency with the rest of the plugin.

## Input Validation Rules

The skill accepts a single `<target>` positional argument. The argument describes what the operator wants the blast radius for. Four target types are recognised; each may be specified with an explicit prefix or as a bare form that the parser auto-detects.

**Accepted target forms (auto-detection order matters — explicit prefix is checked first, bare-form heuristics are tried in the documented order):**

1. **File target.** Explicit form `file:<path>`. Bare form: any argument containing a forward slash `/` OR ending with one of the known file extensions `.md`, `.py`, `.ts`, `.js`, `.tsx`, `.jsx`, `.go`, `.java`, `.rs`, `.sh`, `.json`, `.yaml`, `.yml`. The path is relative to the project root.

2. **Symbol target.** Explicit form `symbol:<name>`. Optional disambiguation qualifier: `symbol:<name>@<module>` or `symbol:<name>@<file>` — the `@<qualifier>` suffix narrows an ambiguous symbol name to a specific owning module or file. The qualifier syntax is recognised here; resolution of the qualifier against the graph happens in Step 3 (subtask #86). Bare form: any argument matching the regex `^[A-Za-z_][A-Za-z0-9_.]*$` that is NOT a pure integer AND does NOT match the feature-id pattern `^feat-[0-9]+$`.

3. **Task target.** Explicit form `task:<id>`. Bare form: any argument matching `^[0-9]+$`. The id refers to a kanban task id as stored in `.cc-master/kanban.json`.

4. **Feature target.** Explicit form `feature:<id>`. Bare form: any argument matching `^feat-[0-9]+$`. The id refers to a roadmap feature id as stored in `.cc-master/roadmap.json`.

**Rejections (checked in order, before target-type resolution):**

1. **Shell metacharacter rejection.** If the raw target contains any of `;`, `&&`, `||`, `|`, `>`, `<`, backtick (`` ` ``), or `$`, print:

   ```
   Invalid target: shell metacharacters are not permitted.
   ```

   Print the literal string above — do NOT echo the offending target value back to the operator, and do NOT indicate which metacharacter triggered the rejection. Echoing the value back through subsequent processing risks a second injection path.

2. **Path traversal rejection.** If the raw target contains the literal substring `..`, print:

   ```
   Invalid target: path traversal (..) is not permitted.
   ```

   This rejection fires on any occurrence of `..` anywhere in the string — not only a leading `../`. A `foo/../bar` style argument is rejected.

3. **Absolute path rejection.** If the raw target begins with `/`, print:

   ```
   Invalid target: absolute paths are not permitted — use a path relative to the project root.
   ```

4. **Null byte rejection.** If the raw target contains a null byte (`\x00`), print:

   ```
   Invalid target: null bytes are not permitted.
   ```

5. **Length rejection.** The maximum permitted target length is 200 characters (measured after whitespace trim, before prefix stripping). If the trimmed target exceeds 200 characters, print:

   ```
   Invalid target: target exceeds 200-character maximum.
   ```

All five rejection messages are printed verbatim. On any rejection the skill exits immediately without running any graph query, writing any file, or consulting any further input. No partial output is produced.

## Process

### Step 1: Parse Target

Resolve the raw argument string to a `{type, value}` pair that Steps 2 and 3 consume. Execute the algorithm in the order written — order is load-bearing because auto-detection precedence determines which heuristic wins when two could match.

1. **Strip whitespace.** Strip leading and trailing whitespace from the raw argument. An argument that is empty after trimming is rejected with `"Invalid target: target is empty."` and the skill exits.

2. **Length check.** Assert the trimmed length is ≤ 200 characters. On violation emit the length-rejection message and exit.

3. **Run the rejection list.** Apply the five rejections from the Input Validation Rules section in order: shell metacharacters, path traversal, absolute path, null byte, length. Any rejection exits the skill immediately with the documented verbatim message. The order matters — shell-metacharacter rejection is checked before any path or identifier interpretation so a malicious argument never reaches the auto-detection branch.

4. **Explicit prefix resolution.** If the trimmed argument starts with one of the four recognised prefixes — `file:`, `symbol:`, `task:`, `feature:` — strip the prefix and set the target type directly from the prefix name. The remainder after the prefix becomes the target value. Empty value after stripping (e.g. `file:`) is rejected with `"Invalid target: <prefix> value is empty."` and the skill exits. When the explicit prefix path is taken, skip auto-detection entirely — the operator's explicit intent wins even if the value would otherwise match a different bare form.

5. **Auto-detection (bare form).** If no explicit prefix was present, apply the following heuristics in order and stop on the first match:

   a. If the argument matches `^[0-9]+$` → set type = `task`, value = the argument.

   b. If the argument matches `^feat-[0-9]+$` → set type = `feature`, value = the argument.

   c. If the argument contains `/` OR ends with one of the known file extensions (`.md`, `.py`, `.ts`, `.js`, `.tsx`, `.jsx`, `.go`, `.java`, `.rs`, `.sh`, `.json`, `.yaml`, `.yml`) → set type = `file`, value = the argument.

   d. If the argument matches the symbol regex `^[A-Za-z_][A-Za-z0-9_.]*$` → set type = `symbol`, value = the argument. Symbol disambiguation qualifiers (`@<module>` or `@<file>`) only appear with an explicit `symbol:` prefix, so the bare-form symbol regex intentionally excludes `@`.

   e. If none of the heuristics match, print:

      ```
      Cannot infer target type. Use explicit prefix: file:<path>, symbol:<name>, task:<id>, or feature:<id>.
      ```

      Exit immediately. Do NOT guess, do NOT pick the closest match, do NOT prompt for clarification — the operator supplies an explicit prefix and re-runs.

6. **Freeze the resolution.** After resolution the pair `{type, value}` is frozen for the rest of the invocation. Steps 2 and 3 consume only the resolved pair — they never re-parse the raw argument. This prevents inconsistent interpretation across steps.

### Step 2: Pre-Query Checks

This skill is graph-backed and has NO JSON fallback. Paste the following contract block verbatim before executing any Cypher query — the text is the required citation of `prompts/graph-read-protocol.md` and propagates the three pre-query checks, the one-warning-per-session rule, and the JSON-fallback fragment downstream. The fragment is preserved verbatim even though it does not apply to this skill, because the contract propagation is what earns the citation; the no-JSON-fallback exception that follows the block is what overrides it locally.

```
First-run check — if .cc-master/graph.kuzu is absent, follow the ## First-Run Prompt section of this protocol before Check 1.
Before any graph query, this skill MUST follow the three pre-query checks in prompts/graph-read-protocol.md (directory exists, _source hash matches, query executes cleanly). On any check failure, fall back to JSON and emit one warning per session.
Check 1 — `.cc-master/graph.kuzu` exists on disk (file or directory, readable).
Check 2 — `_source.content_hash` matches the current on-disk hash for every dependent JSON/markdown artifact.
Check 3 — the Cypher query executes cleanly via `${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py` (exit code 0, empty stderr).
Emit at most one fallback warning per session; do NOT retry the graph query after fallback has started.
Emit the Graph: <state> output indicator per the ## Output Indicator section as the last line of the primary summary.
If any pre-query check above fails for this query, fall back to reading
.cc-master/<artifact>.json directly and computing the same result in memory.
Print one warning line per session on first fallback:
  "Graph absent/stale — falling back to JSON read for <artifact>"
Do NOT retry the graph query during the same session once fallback has
started — retries mask real corruption and waste tokens.
```

**No-JSON-fallback exception.** Unlike every other graph-backed cc-master skill, `cc-master:impact` does NOT fall back to JSON computation when any pre-query check fails. The skill's semantic value depends on symbol-level `REFERENCES` edges that only exist in the graph — there is no meaningful JSON substitute. When any of the three pre-query checks below fails, the skill prints `"Impact analysis requires the graph — run /cc-master:index --full first. <reason>"` where `<reason>` is one of:

- `(graph.kuzu not found)` — Check 1 failed: `.cc-master/graph.kuzu` does not exist or is not readable.
- `(source hash mismatch for <file>)` — Check 2 failed: the `_source.content_hash` for that file in the graph differs from the on-disk canonical hash.
- `(Cypher error: <stderr first line>)` — Check 3 failed: a Cypher query returned a non-zero exit code or non-empty stderr.

After printing the diagnostic, the skill exits without writing any output file. No retry, no partial result. The operator is told exactly what to do next (`/cc-master:index --full`) and the session proceeds without a stale or partial impact report polluting downstream reasoning.

**Execute the checks in order.** All three must pass before Step 3 runs.

1. **Check 1 — Graph path exists and is readable.** Test that `.cc-master/graph.kuzu` exists and is readable. Kuzu 0.11.2 stores the database as a single file on disk, but earlier versions stored it as a directory — `test -e` works for both representations, `test -d` does not. Run:

   ```
   test -e .cc-master/graph.kuzu
   ```

   If the test fails (non-zero exit) or the path exists but is unreadable by the current process, print the diagnostic:

   ```
   Impact analysis requires the graph — run /cc-master:index --full first. (graph.kuzu not found)
   ```

   Exit immediately. Do NOT attempt any Cypher query. Do NOT fall back to JSON.

2. **Check 2 — Source hash matches for every dependent artifact.** The set of artifacts whose hashes must match depends on the resolved target type. Dependencies vary by target type; Step 3 (subtask #86) specifies which artifacts each target type reads and therefore which `_source` rows this check must verify. In this subtask it is sufficient to describe the check mechanics; Step 3 enumerates the dependent artifacts per target type.

   For each dependent artifact, run the `_source` lookup via the Kuzu client:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu "MATCH (s:_source {file_path: '<path>'}) RETURN s.content_hash AS stored"
   ```

   `<path>` is the full relative path as stored in `_source.file_path` — for artifacts under `.cc-master/` the stored path retains the `.cc-master/` prefix, so the query MUST include that prefix or no rows match.

   Compute the on-disk hash using the canonical algorithm for the artifact's file type, as documented in `prompts/graph-read-protocol.md`, section `## Hash Comparison Rule`. Use the JSON-artifact one-liner for `*.json` dependencies (canonical-json + SHA-256):

   ```
   python3 -c "import json,hashlib,sys; o=json.load(open(sys.argv[1])); print(hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':')).encode()).hexdigest())" <path>
   ```

   Use the raw-bytes one-liner for markdown dependencies (`.cc-master/specs/*.md` and similar):

   ```
   python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>
   ```

   If the `_source` query returns no row for a required path, OR the stored `content_hash` differs from the freshly computed on-disk hash, print the diagnostic:

   ```
   Impact analysis requires the graph — run /cc-master:index --full first. (source hash mismatch for <file>)
   ```

   where `<file>` is the dependent artifact's path. Exit immediately. Do NOT re-index from within this skill — read-side skills are forbidden from writing to the graph (`prompts/graph-read-protocol.md` invariant). Do NOT fall back to JSON.

3. **Check 3 — Every Cypher shell-out is guarded.** Every Cypher invocation in Step 3 (and every invocation in this step's Check 2 lookups) MUST inspect its exit code and stderr. On any non-zero exit code from `kuzu_client.py query` (codes 2, 3, 4, or any other), OR any non-empty stderr, capture the first line of stderr as `<stderr first line>` and print the diagnostic:

   ```
   Impact analysis requires the graph — run /cc-master:index --full first. (Cypher error: <stderr first line>)
   ```

   Exit immediately. Discard any partial rowset. Do NOT retry the query. Do NOT fall back to JSON. The three kuzu_client exit codes that matter in this context are 2 (Python binding missing), 3 (database path corrupted or unreadable), and 4 (Cypher parse or runtime error) — all three map to the same diagnostic here because the operator's remedy is identical (rebuild the graph).

Step 3 consumes these queries using the `--params-json` parameter-binding pattern established by `skills/kanban-add/SKILL.md` — target values (especially file paths and symbol names) MUST flow through `--params-json` as bound parameters, never string-concatenated or f-string-interpolated into Cypher text.

With all three pre-query checks passed, proceed to Step 3 (Graph Queries).

### Step 3: Graph Queries

Execute the Cypher queries for the resolved target type. Every row returned from every query is mapped into the output structure that Step 4 composes — the mapping rules are specified per-query below.

**Parameter-Binding Contract (Security / Correctness).** Every Cypher call in this step MUST bind target values as parameters via `kuzu_client.py`'s `--params-json` option — NEVER string-concatenated or f-string-interpolated into the Cypher text. This is a hard correctness and security requirement analogous to SQL injection prevention:

- Target values may come from user-supplied arguments (file paths, symbol names, task ids) that can contain single quotes, backticks, Cypher keywords, or characters that would break a literal Cypher string.
- String interpolation into Cypher is a query-injection vector. A crafted file path like `foo' OR true OR f.path = 'bar` would change the query semantics if concatenated in.
- `--params-json` binds the value as a parameter at execution time, so `$path`, `$task_id`, `$name`, etc. are always treated as opaque values by Kuzu's parser.

The `--params-json` JSON object MUST be built with a real JSON serializer — never hand-built by string concatenation. The established pattern (from `skills/kanban-add/SKILL.md`) is:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"path": sys.argv[1]}))' "$TARGET_PATH")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu "<cypher with \$path>" --params-json "$PARAMS_JSON"
```

Any helper implementation that builds the Cypher by concatenating target text violates this contract. Violations are a CRITICAL review finding.

After each `kuzu_client.py query` invocation, inspect exit code and stderr per Step 2 Check 3 — any non-zero exit code or non-empty stderr triggers the Cypher-error diagnostic and immediate exit, discarding any partial rowset.

---

#### `task:<id>` target

**Dependent artifacts for Step 2 Check 2.** Hash-verify `.cc-master/kanban.json` (for the `Task`, `Subtask`, `BLOCKED_BY`, `HAS_SPEC`, and `IMPLEMENTS` edges). Additionally, if the resolved task has a `HAS_SPEC` edge (determined by the presence of a corresponding `Spec` node), hash-verify `.cc-master/specs/<id>.md` (for the `Spec` node and `TOUCHES` edges). Both hashes MUST match before any query below runs.

**Q1 — Downstream blast radius.** Transitively expand `BLOCKED_BY` inbound from the target task up to 5 hops, yielding every downstream task that this change will unblock when it lands. The Cypher is Query 4 from `docs/plans/2026-04-graph-engine-v1.md` (lines 598–614), verbatim:

```cypher
MATCH (start:Task {id: $task_id})<-[:BLOCKED_BY*1..5]-(downstream:Task)
WITH DISTINCT downstream
RETURN downstream.id AS id,
       downstream.subject AS subject,
       downstream.status AS status,
       downstream.priority AS priority
ORDER BY downstream.priority, downstream.id
LIMIT 50
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"task_id": int(sys.argv[1])}))' "$TASK_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (start:Task {id: \$task_id})<-[:BLOCKED_BY*1..5]-(downstream:Task) WITH DISTINCT downstream RETURN downstream.id AS id, downstream.subject AS subject, downstream.status AS status, downstream.priority AS priority ORDER BY downstream.priority, downstream.id LIMIT 50" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each returned row becomes one entry in `transitive_references[]` shaped `{"kind": "downstream_task", "id": <id>, "subject": <subject>, "status": <status>, "priority": <priority>}`.

**Q2 — Upstream blockers.** Walk `BLOCKED_BY` outbound up to 10 hops to surface every task that must complete before the target can start. The Cypher is Query 5 from `docs/plans/2026-04-graph-engine-v1.md` (lines 644–651), verbatim:

```cypher
MATCH (start:Task {id: $task_id})-[:BLOCKED_BY*1..10]->(blocker:Task)
WITH DISTINCT blocker
RETURN blocker.id AS id,
       blocker.subject AS subject,
       blocker.status AS status
ORDER BY blocker.status, blocker.id
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"task_id": int(sys.argv[1])}))' "$TASK_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (start:Task {id: \$task_id})-[:BLOCKED_BY*1..10]->(blocker:Task) WITH DISTINCT blocker RETURN blocker.id AS id, blocker.subject AS subject, blocker.status AS status ORDER BY blocker.status, blocker.id" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each returned row becomes one entry in `in_flight_tasks[]` tagged `{"kind": "upstream_blocker", "id": <id>, "subject": <subject>, "status": <status>}`.

**Q3 — Spec → modules → files.** Resolves the set of files that the task's spec authorizes/touches by walking `HAS_SPEC → TOUCHES → CONTAINS`.

```cypher
MATCH (t:Task {id: $task_id})-[:HAS_SPEC]->(s:Spec)-[:TOUCHES]->(m:Module)
MATCH (m)-[:CONTAINS]->(f:File)
RETURN DISTINCT f.path AS path, m.name AS module_name
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"task_id": int(sys.argv[1])}))' "$TASK_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (t:Task {id: \$task_id})-[:HAS_SPEC]->(s:Spec)-[:TOUCHES]->(m:Module) MATCH (m)-[:CONTAINS]->(f:File) RETURN DISTINCT f.path AS path, m.name AS module_name" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each row's `path` becomes an entry in `affected_files[]`; each row's `module_name` becomes an entry in `owning_modules[]` (deduplicate `owning_modules[]` on `module_name` before emitting).

**Q4 — Feature linkage.** If the task implements a roadmap feature, surface it so downstream consumers can tie the blast radius back to a roadmap item.

```cypher
MATCH (t:Task {id: $task_id})-[:IMPLEMENTS]->(f:Feature)
RETURN f.id AS id, f.title AS title, f.status AS status
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"task_id": int(sys.argv[1])}))' "$TASK_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (t:Task {id: \$task_id})-[:IMPLEMENTS]->(f:Feature) RETURN f.id AS id, f.title AS title, f.status AS status" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each row becomes one entry in `owning_features[]` shaped `{"id": <id>, "title": <title>, "status": <status>}`. Expect 0 or 1 row — a task implements at most one feature in v1.

---

#### `feature:<id>` target

**Dependent artifacts for Step 2 Check 2.** Hash-verify `.cc-master/roadmap.json` (for the `Feature` node), `.cc-master/kanban.json` (for the `IMPLEMENTS` edges and the implementing `Task` set), and `.cc-master/specs/<id>.md` for every implementing task that has a spec (for the `Spec` and `TOUCHES` edges consumed by the per-task Q3 delegation below). All hashes MUST match before any query runs.

**Q1 — Implementing tasks.** Resolve the set of tasks that implement the feature:

```cypher
MATCH (f:Feature {id: $feature_id})<-[:IMPLEMENTS]-(t:Task)
RETURN t.id AS id, t.subject AS subject, t.status AS status
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"feature_id": sys.argv[1]}))' "$FEATURE_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (f:Feature {id: \$feature_id})<-[:IMPLEMENTS]-(t:Task) RETURN t.id AS id, t.subject AS subject, t.status AS status" \
  --params-json "$PARAMS_JSON"
```

Row mapping:

- For each returned task id, run the full `task:<id>` query set (Q1, Q2, Q3, Q4) above, then union-merge every result array into the feature target's output, deduplicating on the primary key of each array element:
  - `direct_references[]` — dedup on the `(file, symbol)` pair (task-target normally emits none; this carries forward if a task's delegated chain produces any).
  - `transitive_references[]` — dedup on `id` (downstream task id).
  - `affected_files[]` — dedup on `path`.
  - `affected_tests[]` — dedup on `path`.
  - `owning_modules[]` — dedup on `module_name`.
  - `in_flight_tasks[]` — dedup on `id`.
- Populate `owning_features[]` with a single entry `{"id": <feature_id>, "title": <f.title>, "status": <f.status>}` resolved by a companion lookup:

```cypher
MATCH (f:Feature {id: $feature_id})
RETURN f.id AS id, f.title AS title, f.status AS status
```

- `recent_specs[]` — dedup on `file_path` across the tasks surfaced in `in_flight_tasks[]`.

**Empty feature case.** If Q1 returns zero rows (the feature has no implementing tasks yet), print:

```
Feature has no implementing tasks yet — nothing to analyze.
```

Write an output file with empty arrays for every field EXCEPT `owning_features[]`, which lists the feature itself (resolved via the companion lookup above). This is a valid result, not an error — proceed to Steps 4 and 5 normally.

---

#### `file:<path>` target

**Dependent artifacts for Step 2 Check 2.** The `File`/`Module`/`Symbol`/`REFERENCES` nodes are sourced from `ast-grep-walk`, which uses a composite per-module hash tracked by the indexer (not a per-file hash exposed to read-side skills). For Check 2 on a pure `file:` target, verify only that the `.cc-master/graph.kuzu` `_source` table contains at least one row — the composite hash is `cc-master:index`'s responsibility, not this skill's. Skip per-file hash verification for `_source.source_file = 'ast-grep-walk'` entries.

Additionally, if the target file is inside a discovery-sourced module (`File.source_file = '.cc-master/discovery.json'`), hash-verify `.cc-master/discovery.json` as well. Resolve this via a lookup before running Q1:

```cypher
MATCH (f:File {path: $path})
RETURN f.source_file AS source_file
```

If `source_file` is `'.cc-master/discovery.json'`, apply the standard JSON-artifact hash check from Step 2.

**Q1 — Direct references.** Enumerate every file that references a symbol declared in the target file.

```cypher
MATCH (sym:Symbol {file: $path})
MATCH (other:File)-[:REFERENCES]->(sym)
WHERE other.path <> $path
RETURN DISTINCT other.path AS path, sym.name AS symbol_name, sym.kind AS kind
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"path": sys.argv[1]}))' "$TARGET_PATH")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (sym:Symbol {file: \$path}) MATCH (other:File)-[:REFERENCES]->(sym) WHERE other.path <> \$path RETURN DISTINCT other.path AS path, sym.name AS symbol_name, sym.kind AS kind" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each row becomes an entry in `direct_references[]` shaped `{"kind": "file_to_symbol", "file": <path>, "symbol": <symbol_name>, "symbol_kind": <kind>}`.

**Q2 — Owning module.** Resolve which module contains the target file:

```cypher
MATCH (m:Module)-[:CONTAINS]->(f:File {path: $path})
RETURN m.name AS module_name
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"path": sys.argv[1]}))' "$TARGET_PATH")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (m:Module)-[:CONTAINS]->(f:File {path: \$path}) RETURN m.name AS module_name" \
  --params-json "$PARAMS_JSON"
```

Row mapping: the returned `module_name` becomes a single entry in `owning_modules[]`. Expect 0 or 1 row — 0 means the file is not in any module yet, and Q3 and Q4 below are skipped.

**Q3 — Sibling test files.** Enumerate the test files in the owning module. Run this query only if Q2 returned a module; otherwise `affected_tests[]` is empty.

```cypher
MATCH (m:Module {name: $module_name})-[:CONTAINS]->(f:File)
WHERE f.is_test = true
RETURN f.path AS path
ORDER BY f.path
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"module_name": sys.argv[1]}))' "$MODULE_NAME")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (m:Module {name: \$module_name})-[:CONTAINS]->(f:File) WHERE f.is_test = true RETURN f.path AS path ORDER BY f.path" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each row's `path` becomes an entry in `affected_tests[]`.

**Q4 — In-flight tasks touching the owning module.** Join `Task → Spec → Module` for every task whose status is `pending` or `in_progress`. Run only if Q2 returned a module.

```cypher
MATCH (t:Task)-[:HAS_SPEC]->(s:Spec)-[:TOUCHES]->(m:Module {name: $module_name})
WHERE t.status IN ['pending', 'in_progress']
RETURN DISTINCT t.id AS id, t.subject AS subject, t.status AS status, s.file_path AS spec_file
ORDER BY t.id
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"module_name": sys.argv[1]}))' "$MODULE_NAME")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (t:Task)-[:HAS_SPEC]->(s:Spec)-[:TOUCHES]->(m:Module {name: \$module_name}) WHERE t.status IN ['pending', 'in_progress'] RETURN DISTINCT t.id AS id, t.subject AS subject, t.status AS status, s.file_path AS spec_file ORDER BY t.id" \
  --params-json "$PARAMS_JSON"
```

Row mapping:

- Each row becomes an entry in `in_flight_tasks[]` shaped `{"kind": "module_in_flight", "id": <id>, "subject": <subject>, "status": <status>, "spec_file": <spec_file>}`.
- Each row's `{"task_id": <id>, "file_path": <spec_file>}` becomes an entry in `recent_specs[]` (deduplicate `recent_specs[]` on `file_path`).

---

#### `symbol:<name>` target

**Dependent artifacts for Step 2 Check 2.** Same as `file:<path>` — the graph directory's `_source` table existence is the primary check. The `Symbol` and `REFERENCES` nodes originate from `ast-grep-walk`; per-file hash verification is skipped for that source. If the resolved symbol's owning file's `File.source_file` is `'.cc-master/discovery.json'`, hash-verify `.cc-master/discovery.json` as part of the delegated file-target check.

**Q0 — Disambiguation lookup.** Find all symbols with the requested name, then apply the optional `@<qualifier>` filter:

```cypher
MATCH (s:Symbol {name: $name})
RETURN s.id AS id, s.name AS name, s.kind AS kind, s.file AS file, s.module AS module
ORDER BY s.file, s.line
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1]}))' "$SYMBOL_NAME")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (s:Symbol {name: \$name}) RETURN s.id AS id, s.name AS name, s.kind AS kind, s.file AS file, s.module AS module ORDER BY s.file, s.line" \
  --params-json "$PARAMS_JSON"
```

If the Step-1 parser recorded an `@<module>` or `@<file>` qualifier, filter the returned rows in memory by matching the qualifier against `module` or `file` respectively BEFORE counting. The qualifier filter is applied client-side so Kuzu sees only a clean name lookup.

Dispatch based on post-filter row count:

- **0 rows.** Print:

  ```
  No symbol named '<name>' found in the graph.
  ```

  Exit without writing an output file. No partial result. No retry.

- **Exactly 1 row.** Set `symbol_id` = the row's `id`, `anchor_file` = the row's `file`, `symbol_kind` = the row's `kind`. Proceed to Q1 below AND delegate the remaining output-population to the `file:<path>` query set (Q2, Q3, Q4 from the `file:<path>` section above, using `anchor_file` as `$path`). The symbol's own references are handled by Q1 here; the file-level blast radius is handled by the delegated file-target path.

- **More than 1 row.** Print a disambiguation listing, one candidate per line, in the form:

  ```
  Multiple matches. Re-invoke with an explicit qualifier: /cc-master:impact symbol:<name>@<module> or /cc-master:impact symbol:<name>@<file>.
  ```

  Preceded by the candidate list formatted as:

  ```
    - <name> (<kind>) in module <module> — file <file>
  ```

  One line per candidate, in the order returned. Exit without writing an output file.

**Q1 — Direct references to the resolved symbol.** Only executed in the exactly-one-match branch:

```cypher
MATCH (f:File)-[:REFERENCES]->(sym:Symbol {id: $symbol_id})
RETURN DISTINCT f.path AS path
ORDER BY f.path
```

Invocation:

```
PARAMS_JSON=$(python3 -c 'import json,sys; print(json.dumps({"symbol_id": sys.argv[1]}))' "$SYMBOL_ID")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu \
  "MATCH (f:File)-[:REFERENCES]->(sym:Symbol {id: \$symbol_id}) RETURN DISTINCT f.path AS path ORDER BY f.path" \
  --params-json "$PARAMS_JSON"
```

Row mapping: each row becomes an entry in `direct_references[]` shaped `{"kind": "file_to_symbol", "file": <path>, "symbol": <name>, "symbol_kind": <kind>}` where `<name>` and `<kind>` are the resolved symbol's values from Q0.

Then delegate to the `file:<path>` query set with `anchor_file` as `$path` to populate `transitive_references[]`, `affected_files[]`, `affected_tests[]`, `owning_modules[]`, `in_flight_tasks[]`, and `recent_specs[]`. The file-target Q1 (its own direct references block) is NOT re-run for the symbol target — the symbol-specific Q1 above has already populated `direct_references[]` with the correct per-symbol edges, and re-running the file-scoped reference query would dilute the result with references to unrelated symbols that happen to live in the same file.

### Step 4: Compose Output

Assemble the rows returned by Step 3 into a single output object and its companion markdown rendering. Both artifacts share the same schema — the JSON is written to `.cc-master/impact/<slug>.json` in Step 5; the markdown is printed to stdout in Step 5.

#### Output JSON schema

```json
{
  "target": {
    "type": "file" | "symbol" | "task" | "feature",
    "value": "<original target after prefix stripping and disambiguation>"
  },
  "direct_references": [],
  "transitive_references": [],
  "affected_files": [],
  "affected_tests": [],
  "owning_modules": [],
  "owning_features": [],
  "in_flight_tasks": [],
  "recent_specs": [],
  "generated_at": "<ISO-8601 UTC>",
  "graph_indexed_at": "<ISO-8601 from _source.last_indexed or null if unavailable>"
}
```

Every field is REQUIRED — arrays that end up empty remain in the output as `[]`. Downstream consumers expect the full schema; omitting a key is a schema violation.

**Per-field element shapes (all fields are lists of the documented object shape):**

| Field | Element shape | Populated by |
|-------|---------------|--------------|
| `direct_references[]` | `{"kind": "file_to_symbol", "file": <path>, "symbol": <name>, "symbol_kind": <kind>}` | file-target Q1, symbol-target Q1. Empty by design for task/feature targets. |
| `transitive_references[]` | `{"kind": "downstream_task", "id": <int>, "subject": <string>, "status": <string>, "priority": <string>}` | task-target Q1 (and feature-target's per-task Q1 union). Empty for file/symbol targets. |
| `affected_files[]` | `<path>` (string) | task-target Q3, delegated file-target path for symbol targets. |
| `affected_tests[]` | `<path>` (string) | file-target Q3 (and feature-target's per-task delegation when applicable). |
| `owning_modules[]` | `{"module_name": <name>}` | task-target Q3, file-target Q2, feature-target per-task union. Deduplicated on `module_name`. |
| `owning_features[]` | `{"id": <feature_id>, "title": <title>, "status": <status>}` | task-target Q4 (0 or 1 entry), feature-target companion lookup (always 1 entry for a valid feature target). |
| `in_flight_tasks[]` | Union of `{"kind": "upstream_blocker", "id", "subject", "status"}` (task-target Q2) and `{"kind": "module_in_flight", "id", "subject", "status", "spec_file"}` (file-target Q4). Deduplicated on `id`. |
| `recent_specs[]` | `{"task_id": <int>, "file_path": <string>}` | file-target Q4 (and feature-target's per-task delegation). Deduplicated on `file_path`. |

**Populate the envelope fields:**

- `target.type` — `"file"`, `"symbol"`, `"task"`, or `"feature"` as resolved in Step 1.
- `target.value` — the post-prefix-stripping, post-disambiguation value. For a 1-match symbol target, this is the requested name (optionally suffixed with `@<qualifier>` if one was supplied). For task targets, the integer id is represented as a string. For feature targets, the `feat-<n>` id. For file targets, the path relative to the project root.
- `generated_at` — current UTC time, ISO-8601 with `Z` suffix, produced by `date -u +%Y-%m-%dT%H:%M:%SZ`.
- `graph_indexed_at` — resolve via a single lookup against the `_source` table for the primary dependent artifact:

  ```cypher
  MATCH (s:_source {file_path: $artifact_path})
  RETURN s.last_indexed AS last_indexed
  ```

  Use `.cc-master/kanban.json` for task/feature targets and the target file's path (prefixed with `.cc-master/` only for artifacts under that directory) for file targets. For symbol targets, use the anchor file's path. If the lookup returns no row or an empty `last_indexed`, set the field to `null` — do NOT omit the key.

#### Markdown terminal output

Print the following section headers to stdout in the fixed order below. Omit a section entirely when its underlying array is empty — do NOT print a `(0)` heading. Section boundaries are blank lines.

```
# Impact: <target type> <target value>
Graph indexed at: <graph_indexed_at>

## Direct references (<count>)
- <file> — <symbol> (<symbol_kind>)
- ...

## Transitive references (<count>, 2–3 hops)
- #<task_id>: <subject> (<status>, <priority>)
- ...

## Affected files (<count>)
- <file>

## Affected tests (<count>)
- <file>

## Owning modules (<count>)
- <module_name>

## Owning features (<count>)
- <feature_id>: <title> (<status>)

## In-flight tasks touching these modules (<count>)
- #<task_id>: <subject> (<status>)

## Recent specs touching these modules (<count>)
- <file_path> (task #<task_id>)
```

**Rendering rules:**

- `<count>` in each heading is the length of the rendered list (after deduplication and any filtering).
- Omit the section ENTIRELY if its array is empty after dedup. Never render a `(0)` heading.
- For `feature:` and `task:` targets, `direct_references[]` is empty by design — omit the Direct references section rather than showing `(0)`.
- The `Graph indexed at:` line prints the resolved `graph_indexed_at` timestamp verbatim, or the literal string `unknown` if the JSON field is `null`.
- List items within a section retain the order produced by the Cypher `ORDER BY` clauses — no additional sort is applied on the rendering side.

### Step 5: Write Output

Write the JSON object from Step 4 to disk under `.cc-master/impact/`, then print the markdown output from Step 4 to stdout, then print the terminal "Written" line.

#### Slug derivation

Compute `<slug>` from `target.type` and `target.value` using these exact rules:

- `target.type == "task"` → `slug = "task-" + str(target.value)`.
- `target.type == "feature"` → `slug = "feature-" + target.value` (feature ids already match `feat-<n>`, so no extra prefix is needed).
- `target.type == "file"` → `slug = "file-" + slugify(target.value)`.
- `target.type == "symbol"` → `slug = "symbol-" + slugify(name)` when no qualifier was supplied, otherwise `slug = "symbol-" + slugify(name) + "-at-" + slugify(qualifier)`.

**Slugify algorithm** (applied wherever `slugify(...)` appears above):

1. Lowercase the input.
2. Replace each occurrence of `/`, `.`, `_`, and any whitespace character (space, tab, newline) with a single hyphen `-`.
3. Collapse consecutive hyphens into a single hyphen.
4. Strip any leading or trailing hyphens.
5. Truncate to 80 characters maximum (keep the leading portion; drop any trailing characters beyond index 79).
6. Validate the result against the regex `^[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$`. If the resulting string is empty, does not match the regex, or contains only hyphens, fall back to `impact-<timestamp>` where `<timestamp>` is the current UTC time formatted as `YYYYMMDDTHHMMSSZ` (e.g., `20260418T141530Z`).

Example slugs:

- `target:value` `file:src/auth/login.ts` → `slug = "file-src-auth-login-ts"`.
- `target:value` `symbol:parseToken@auth` → `slug = "symbol-parsetoken-at-auth"`.
- `target:value` `task:86` → `slug = "task-86"`.
- `target:value` `feature:feat-12` → `slug = "feature-feat-12"`.

#### Output path containment

Before writing, enforce that the resolved output path is inside `.cc-master/impact/`. Any escape is a security violation and MUST be rejected:

1. Construct the candidate path: `.cc-master/impact/<slug>.json`.
2. Resolve the candidate to an absolute path, collapsing any `.` or `..` segments and following symlinks (`python3 -c 'import sys,os; print(os.path.realpath(sys.argv[1]))' <candidate>`).
3. Resolve the project's `.cc-master/impact/` directory to an absolute path using the same real-path resolution.
4. Verify the resolved candidate path starts with the resolved `.cc-master/impact/` directory path plus the OS path separator. Anything else — a symlink that escapes via realpath, a `..` slipped past the Step 1 validator, a slug that somehow contains a separator — fails the check.
5. Verify `.cc-master/impact/` exists. If it does not exist, create it as a regular directory with `mkdir -p .cc-master/impact`. If the path exists but is a symlink (even a symlink to a directory), refuse to create or write — print the rejection below and stop.
6. On any containment failure, print:

   ```
   Output path escapes .cc-master/impact/ — rejected.
   ```

   Exit immediately without writing any file. No partial output.

#### Write and print

With the containment check passed, perform these actions in order:

1. Use the `Write` tool to write the Step 4 JSON object to the resolved `.cc-master/impact/<slug>.json` path. The object MUST be serialized with `sort_keys=True` and `indent=2` to keep diffs stable and the file human-readable.
2. Print the markdown terminal output from Step 4 to stdout, verbatim, in the section order documented there.
3. Print exactly one final line to stdout:

   ```
   Written: .cc-master/impact/<slug>.json
   ```

   where `<slug>` matches the slug computed above.

After the "Written" line, stop. The skill invocation is complete.

### Step 6: Emit Graph Output Indicator

As the last line of the primary summary (before any chain-point prompt), print exactly ONE of these three strings based on the pre-query check outcomes from Step 2:

- `Graph: fresh` — all three pre-query checks passed and the Cypher result was consumed.
- `Graph: stale — fell back to JSON` — Check 2 hash mismatch for at least one dependent artifact (worst-state-wins per `prompts/graph-read-protocol.md § Output Indicator`).
- `Graph: absent — fell back to JSON` — Check 1 failed (directory missing or unreadable).

If the skill errored during pre-query checks before classification, default to `Graph: absent — fell back to JSON`. Do NOT omit the indicator. Do NOT duplicate it per artifact — one line at the bottom of the primary summary block.

## Chain Point

`cc-master:impact` is standalone — there is no chain point. Once Step 5 has written the output file and printed its single `Written: .cc-master/impact/<slug>.json` line, the skill stops. Do not print a follow-up menu, do not prompt the user for a next step, do not auto-invoke any other skill. This is a query-only read-side skill by design: it produces an artifact for human or downstream-skill consumption, and does not itself trigger the next pipeline step. Future readers who go looking for a "what next" section in this file will not find one, and that is the documented behavior.

## Post-Write Invalidation

Every write to `.cc-master/kanban.json` performed by this skill MUST be followed by a single graph-invalidation call at the end of the invocation, per the canonical contract in `prompts/kanban-write-protocol.md`.

```
This skill writes `.cc-master/kanban.json` and MUST follow the write-and-invalidate
contract in prompts/kanban-write-protocol.md. The four-step protocol is:
  1. Read `.cc-master/kanban.json` and parse JSON (treat missing file as
     {"version": 1, "next_id": 1, "tasks": []}).
  2. Apply all mutations in memory — assign new IDs from next_id, append new tasks,
     modify fields on existing tasks, set updated_at on every affected task.
  3. Write the entire updated JSON document back to `.cc-master/kanban.json`.
  4. After ALL kanban writes for this invocation have completed, invoke the Skill
     tool EXACTLY ONCE with:
       skill: "cc-master:index"
       args: "--touch .cc-master/kanban.json"
     These are LITERAL strings — never placeholders, never variables.

Batch coalescing — one --touch per invocation. When a single invocation produces
multiple kanban.json writes (multi-task batch, create + link-back, multi-edge
blocked_by rewrite), fire the --touch EXACTLY ONCE at the end after the LAST write,
never per write and never per task. If zero writes happened, skip the --touch
entirely.

Fail-open recovery. If cc-master:index --touch returns ANY non-zero exit code, the
kanban.json write STANDS — never roll back, never delete, never undo. Emit EXACTLY
ONE warning line per session:
  Warning: graph invalidation failed (exit code <N>) — next graph-backed skill will fall back to JSON. Run /cc-master:index --full to rebuild.
Substitute the observed exit code for <N>. Do NOT retry the touch. Do NOT prompt the
user. The single warning line is the entire write-side recovery protocol — the next
graph-backed read will hash-check, detect staleness, and fall back to JSON per
prompts/graph-read-protocol.md. Correctness is preserved unconditionally.
```

**Impact write scope.** This skill writes telemetry to `.cc-master/impact-telemetry/<batch>-wave-<n>-<ts>.json` (NOT a kanban write — does not trigger `--touch`) AND writes the per-target impact analysis to `.cc-master/impact/<slug>.json` (also NOT a kanban write). When impact is invoked from a flow that subsequently writes impact-derived metadata back to a kanban task (e.g., a future build or qa-review integration that records detected blast-radius warnings on the parent task), the calling skill — not impact itself — owns the kanban write and the subsequent `--touch` invocation per its own `## Post-Write Invalidation` section. Standalone impact invocations skip the `--touch` entirely per the zero-writes rule.

Note: this skill currently has no explicit kanban-write step in `## Process`; the section is present so any future kanban writes added to this skill inherit the contract by default.

## What NOT To Do

- Do not fall back to JSON when the graph is absent or stale. This skill has no meaningful JSON substitute — the symbol-level `REFERENCES` edges required for accurate blast radius only exist in the graph. Print the diagnostic from Step 2 and stop.
- Do not write to the graph. This skill is read-only — `MATCH` and `RETURN` only. No `CREATE`, `MERGE`, `DELETE`, `SET`, or `COPY FROM`. Writing to the graph belongs exclusively to `cc-master:index`.
- Do not auto-pick a match when symbol disambiguation returns more than one row. Auto-picking silently returns the wrong blast radius. Always list every candidate and require the user to re-invoke with `symbol:<name>@<module>` or `symbol:<name>@<file>`.
- Do not guess the target type when auto-detection fails. Print the explicit-prefix guidance from Step 1 and stop. Guessing ships wrong answers that look right.
- Do not invent a Symbol-level query from Module-level data. The v1 graph has `REFERENCES` edges from `File` to `Symbol`, NOT from `Symbol` to `Symbol`. Any traversal pattern that assumes a call-graph-style `Symbol → Symbol` edge is wrong for v1 — it must go through the File layer or be deferred to v0.22 (SCIP swap-in).
- Do not echo unsanitized target values back in error messages. Validation diagnostics name the failed category (shell metachars, path traversal, null byte, length) without reproducing the offending input.
- Do not string-concatenate target values into Cypher text under any circumstance. All parameters flow through `kuzu_client.py`'s `--params-json` — this is a correctness and security invariant matching the `kanban-add` pattern.
- Do not modify any file outside `.cc-master/impact/<slug>.json`. This skill is not allowed to touch source code, specs, `kanban.json`, `roadmap.json`, `discovery.json`, or any other artifact — its only side effect is writing its own output file.
- Do not rely on dynamic-dispatch resolution. The Wave 6 ast-grep walker does not resolve virtual method calls, duck-typed callables, or runtime interface resolution — impact queries for symbols reached only via dynamic dispatch will under-report. This is a documented v0.21 limitation, deferred to v0.22 (SCIP swap-in).

## Acceptance Criteria Checklist

1. `commands/impact.md` exists with the standard cc-master command wrapper format (description frontmatter + "Invoke the cc-master:impact skill..." body).
2. `skills/impact/SKILL.md` exists with frontmatter (`name`, `description`) and the standard section structure.
3. Target argument accepts `file:<path>`, `symbol:<name>`, `task:<id>`, `feature:<id>`, with bare-form auto-detection in the documented order.
4. Target parsing rejects shell metacharacters, `..`, absolute paths, null bytes, and targets exceeding 200 characters.
5. Step 2 cites `prompts/graph-read-protocol.md` using the verbatim 12-line citation block.
6. Step 2 includes the no-JSON-fallback exception with all three specific reason formats: `(graph.kuzu not found)`, `(source hash mismatch for <file>)`, `(Cypher error: <stderr first line>)`.
7. Task-target executes Query 4 (downstream `BLOCKED_BY*1..5`) and Query 5 (upstream `BLOCKED_BY*1..10`) verbatim from the design doc.
8. Task-target resolves spec modules via `HAS_SPEC → TOUCHES → Module → CONTAINS → File`.
9. Feature-target enumerates implementing tasks via `IMPLEMENTS` and runs task-target queries per task, merged and deduped.
10. File-target computes referencing files via `Symbol {file: $path}` and reverse `REFERENCES` edges.
11. File-target returns owning Module, sibling tests (Query 8 verbatim), and in-flight tasks touching the module.
12. Symbol-target resolves by name, disambiguates on collision, delegates to file-target when uniquely resolved.
13. Output is written to `.cc-master/impact/<slug>.json` with slug rules documented in Step 5 and path containment enforced.
14. Markdown report is printed to stdout with section order: Target, Direct references, Transitive references, Affected files, Affected tests, Owning modules, Owning features, In-flight tasks, Recent specs (omitted when empty).
15. JSON output follows the 10-field schema documented in Step 4.
16. All Cypher uses `--params-json` parameter binding — no string concatenation anywhere.
17. The skill is read-only: `MATCH` and `RETURN` only. No `CREATE`, `MERGE`, `DELETE`, `SET`, or `COPY FROM`.
18. The skill is standalone — no chain point, no menu, prints `Written: ...` and stops.
19. Plugin version in `.claude-plugin/plugin.json` is bumped one dev increment beyond its prior value.
20. MEMORY.md is updated with a Wave 7 note once the task is completed (this is a post-build note — not part of the subtask execution itself; the completer handles it).
