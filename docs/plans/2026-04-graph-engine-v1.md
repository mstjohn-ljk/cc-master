# CC-Master Graph Engine v1 — Schema Design

**Date:** 2026-04-18
**Status:** Draft (in progress — sections appended by follow-up subtasks)

## Overview

CC-Master is a Claude Code plugin that manages project state through JSON artifacts at `.cc-master/` — `discovery.json`, `roadmap.json`, `kanban.json`, and per-task specs under `specs/`. On small projects this works. On large projects it does not: whole-file reads burn tokens and degrade retrieval accuracy, because skills almost always need a small slice of a large document. Today 22 of the 37 skills read the full `kanban.json`, 27 read the full `discovery.json`, and 16 read every spec they touch end-to-end. v2 introduces an embedded Kuzu graph at `.cc-master/graph.kuzu/` as a **derived index** over the existing JSON artifacts — not a replacement for them. Graph-backed skills issue targeted Cypher queries instead of reading full files, cutting tokens by roughly 10× on the worst offenders while JSON remains the source of truth. This document is the single source of truth for the v1 schema, canonical queries, invalidation protocol, and scope boundaries. Every implementation task for the graph engine references this doc by path.

## Architectural Invariants

The following four rules govern the entire graph engine. They are not guidance — they are the contract. Any implementation that violates one of these rules is wrong, even if it passes tests.

### JSON is source of truth

The graph is a derived index over `.cc-master/*.json` and `.cc-master/specs/*.md`. The graph can be deleted and rebuilt from JSON at any time without data loss, and the user may do so at any time by removing `.cc-master/graph.kuzu/`. Every graph-backed skill MUST fall back to reading JSON when the graph is absent, stale, or corrupted — guided by `prompts/graph-read-protocol.md`. If a skill's correctness depends on the graph being authoritative, the skill is wrong, not the graph.

### Per-file full-replace upsert, never merge

When a source file changes, the indexer DELETEs all nodes and edges derived from that file and re-INSERTs them from scratch. Merging introduces drift bugs — orphaned edges, half-updated state, stale properties on nodes that were partially touched. Full replace is idempotent and boring. A file content hash lives in a `_source` metadata table so that "did anything change?" is a single cheap compare against the live hash on disk, not a walk of derived nodes.

### One skill owns writes (`cc-master:index`); all others are query-only

Only `cc-master:index` executes write Cypher — CREATE, MERGE, DELETE, SET, COPY FROM. Every other skill that reads the graph uses MATCH with RETURN only and MUST NOT mutate the graph under any condition, including to "fix" what it reads. This prevents schema drift across the 37 skills in the plugin, keeps invalidation reasoning local to one place, and means a corrupted graph has exactly one suspect.

### Every graph read follows the `prompts/graph-read-protocol.md` fallback contract

Before trusting a graph query result, each skill runs three checks in order: (1) the graph directory `.cc-master/graph.kuzu/` exists and is readable; (2) the source-file hash recorded in `_source` matches the live hash on disk for every file the query depends on; (3) the query executes without error. Any mismatch or failure in any step falls back to reading the JSON directly for the data needed. The graph never silently returns stale results. Fail-closed, never fail-open — a fast wrong answer is worse than a slow right one.

## Scaling envelope

These are the numbers v1 must meet. They are not aspirations — they are the acceptance gates. Each target lists the measurement conditions so it can be reproduced, and the consequence if a future change regresses past it. If an implementation misses a target, it earns a follow-up optimization task on the kanban; it does not earn a "good enough, ship it" pass.

| Operation | Target | Measurement conditions | If exceeded |
|-----------|--------|------------------------|-------------|
| Cold full index | ≤30s | 500-task `kanban.json`, 50-spec `specs/` directory, 10k-file codebase, `ast-grep` available on PATH | Split indexing per-module and reconsider the bulk-insert strategy (COPY FROM vs. MERGE batches) |
| `--touch kanban.json` re-index | ≤200ms | Single `kanban.json` write from a post-write skill (e.g. `kanban-add`, `build`, `complete`) | Skip synchronous re-index and fall back to async/batched indexing on a debounce timer |
| Board-render query | ≤50ms | 500 tasks, cold Kuzu query cache, all columns rendered | Add a composite index on `Task.status` and `Task.priority`; re-measure before accepting |
| 2-hop impact query | ≤200ms | Start from a single `Symbol` node on a 10k-file codebase, traverse two hops of `REFERENCES`/`DEFINED_IN` edges | Cap traversal depth, paginate results, and require callers to request additional pages explicitly |
| `--touch discovery.json` re-index | ≤5s | Full `discovery.json` re-parse after a module boundary change that invalidates entry points, key flows, and symbol tables | Re-scope to changed-modules-only by diffing the previous and current discovery snapshots |

The envelope is fixed for v1. If production usage surfaces a workload these numbers do not cover, it becomes a v1.1 entry — not a quiet relaxation of v1.

## Node schema

The v1 graph defines exactly six node types: `Task`, `Subtask`, `Spec`, `Feature`, `Module`, and `File`. Each node is derived from a specific JSON artifact or filesystem scan, carries a `source_file` property so the per-file full-replace invariant can locate every derived node in a single query, and follows the same DELETE-then-INSERT lifecycle on upstream change. Types are Kuzu native types: `STRING`, `INT64`, `BOOLEAN`, `TIMESTAMP`, and `STRING[]` / `INT64[]` for arrays.

### Task

**Purpose:** Represents a top-level kanban task — an entry in `.cc-master/kanban.json` where `metadata.parent_id` is `null`. A Task is the unit the kanban board renders as a card and the unit that build/qa-loop/complete operate on.

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| id | INT64 | no | Kanban task id, matches `tasks[].id` in `kanban.json` |
| subject | STRING | no | Short title — `tasks[].subject` |
| status | STRING | no | One of: `pending`, `in_progress`, `completed`, `blocked` |
| priority | STRING | yes | One of: `critical`, `high`, `normal`, `low` (from `metadata.priority`) |
| source | STRING | yes | `roadmap`, `insights`, `manual`, `qa-ui-review`, `smoke-test`, etc. (from `metadata.source`) |
| owner | STRING | yes | Assigned agent/user id, or null |
| created_at | TIMESTAMP | no | ISO-8601 from `kanban.json` |
| updated_at | TIMESTAMP | no | ISO-8601 from `kanban.json` |
| source_file | STRING | no | Always `.cc-master/kanban.json` for v1 |

**Primary key:** `id`

**Indexes:** `status`, `priority` (for board-render query), `source_file` (for file-scoped full-replace)

**Upsert source:** `.cc-master/kanban.json` — the `tasks` array filtered to entries where `metadata.parent_id` is `null`.

**Lifecycle rules:** On `.cc-master/kanban.json` hash change → DELETE all Task nodes WHERE `source_file = '.cc-master/kanban.json'` → re-INSERT from the current JSON. Never UPDATE in place. The hash comparison lives in the `_source` metadata table referenced by the "Per-file full-replace upsert, never merge" invariant.

### Subtask

**Purpose:** Child tasks linked to a parent Task via `metadata.parent_id` in `kanban.json`. Subtasks are what build dispatches to parallel agents in dependency waves.

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| id | INT64 | no | Kanban task id |
| parent_id | INT64 | no | `tasks[].metadata.parent_id` — the id of the owning Task |
| subject | STRING | no | Short title |
| status | STRING | no | `pending`, `in_progress`, `completed`, `blocked` |
| blocked_by | INT64[] | yes | Array of task ids this subtask is blocked by (from `tasks[].blocked_by`) |
| spec_file | STRING | yes | Path to parent spec, e.g., `.cc-master/specs/3.md` (from `metadata.spec_file`) |
| wave | INT64 | yes | Wave number from `metadata.wave` |
| created_at | TIMESTAMP | no | ISO-8601 from `kanban.json` |
| updated_at | TIMESTAMP | no | ISO-8601 from `kanban.json` |
| source_file | STRING | no | Always `.cc-master/kanban.json` for v1 |

**Primary key:** `id`

**Indexes:** `parent_id`, `status`, `source_file`

**Upsert source:** `.cc-master/kanban.json` — the `tasks` array filtered to entries where `metadata.parent_id` is not `null`.

**Lifecycle rules:** Same as Task — on `.cc-master/kanban.json` hash change → DELETE all Subtask nodes WHERE `source_file = '.cc-master/kanban.json'` → re-INSERT from the current JSON. Never UPDATE in place. Task and Subtask are always re-indexed together from the same write, so their derived state stays coherent.

### Spec

**Purpose:** A spec file under `.cc-master/specs/` linked to a parent Task by filename convention (`<task-id>.md`). Specs carry acceptance criteria, production readiness requirements, and verified API contracts that qa-review and build consult.

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| task_id | INT64 | no | Parsed from filename stem — `.cc-master/specs/3.md` → `3` |
| file_path | STRING | no | Full relative path, e.g., `.cc-master/specs/3.md` |
| has_production_readiness | BOOLEAN | no | `true` if spec contains a `## Production Readiness` heading |
| has_verified_contracts | BOOLEAN | no | `true` if spec contains a `### Verified API Contracts` heading |
| touches_modules | STRING[] | yes | Parsed from "Files to Modify" and "Files to Create" paths → module names |
| updated_at | TIMESTAMP | no | File mtime at last index |
| source_file | STRING | no | Same as `file_path` (one spec file = one source of truth) |

**Primary key:** `task_id`

**Indexes:** `file_path`, `source_file`

**Upsert source:** Files matching `.cc-master/specs/<n>.md`. Exclude `*-review.json` files (those are qa-review reports, not specs) and exclude anything under `archive*/` subdirectories.

**Lifecycle rules:** On an individual spec file's hash change → DELETE Spec WHERE `source_file = <that file path>` → re-INSERT from the parsed spec. One spec file = one Spec node. Because each spec has its own `source_file`, spec reindex is per-file and does not trigger a full `.cc-master/specs/` rescan.

### Feature

**Purpose:** A roadmap feature — an entry in `.cc-master/roadmap.json`'s `phases[].features[]` array. Features are the unit the roadmap skill emits and the unit kanban-add imports into Tasks.

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| id | STRING | no | `features[].id` like `feat-1` |
| title | STRING | no | `features[].title` |
| priority | STRING | yes | `must_have`, `should_have`, `could_have` |
| status | STRING | no | `idea`, `planned`, `in_progress`, `delivered` |
| phase | STRING | yes | `phases[].id` like `phase-1` (the phase that owns this feature) |
| complexity | STRING | yes | `low`, `medium`, `high` |
| impact | STRING | yes | `low`, `medium`, `high` |
| delivered_at | TIMESTAMP | yes | Set when status transitions to `delivered` |
| source_file | STRING | no | Always `.cc-master/roadmap.json` for v1 |

**Primary key:** `id`

**Indexes:** `status`, `phase`, `source_file`

**Upsert source:** `.cc-master/roadmap.json` — flatten `phases[].features[]`, stamping each feature with the owning phase id.

**Lifecycle rules:** On `.cc-master/roadmap.json` hash change → DELETE all Feature nodes WHERE `source_file = '.cc-master/roadmap.json'` → re-INSERT from the current JSON. Never UPDATE in place. `delivered_at` is written during re-INSERT by comparing the previous and current status for each feature id and carrying forward the prior timestamp when the status has been `delivered` across both snapshots.

### Module

**Purpose:** A logical module or service identified in `.cc-master/discovery.json`. Modules are not strictly 1:1 with a directory — they aggregate related code that discovery has grouped under a single named unit (e.g., a verticle, a package, a service boundary).

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| name | STRING | no | `modules[].name` from `discovery.json` |
| path | STRING | no | `modules[].path` — the root directory of the module |
| language | STRING | yes | Primary language inferred from files within the module |
| file_count | INT64 | yes | Number of source files in this module at index time |
| source_file | STRING | no | Always `.cc-master/discovery.json` for v1 |

**Primary key:** `name`

**Indexes:** `path`, `source_file`

**Upsert source:** `.cc-master/discovery.json` — the `modules` array.

**Lifecycle rules:** On `.cc-master/discovery.json` hash change → DELETE all Module nodes WHERE `source_file = '.cc-master/discovery.json'` → re-INSERT from the current JSON. Never UPDATE in place. File nodes that reference a module by name are re-linked during the subsequent code-graph pass; stale `File.module` values from a deleted Module are resolved when the ast-grep walk for that module runs.

### File

**Purpose:** A single source file. Populated by two paths: (a) from `discovery.json`'s enumerated files, when present, for the project-state layer; (b) from an `ast-grep` walk during code-graph indexing, for the code-graph layer (task #12 and later add this walk).

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| path | STRING | no | Relative to project root |
| module | STRING | yes | Name of the owning Module, or null if unassigned |
| language | STRING | yes | Inferred from file extension |
| content_hash | STRING | no | SHA-256 of file content at index time |
| size | INT64 | yes | Byte size at index time |
| is_test | BOOLEAN | no | True if classified as a test file (classification rules defined by task #13) |
| last_indexed | TIMESTAMP | no | When this File node was last refreshed |
| source_file | STRING | no | The artifact that caused this File to be indexed — `.cc-master/discovery.json` when from discovery, or the literal string `ast-grep-walk` when from a code-graph walk |

**Primary key:** `path`

**Indexes:** `module`, `is_test`, `content_hash`, `source_file`

**Upsert source:** `.cc-master/discovery.json` for the project-state layer in v1; `ast-grep` walk of each Module for the code-graph layer starting at task #12.

**Lifecycle rules:**

- For Files with `source_file = '.cc-master/discovery.json'`: on `discovery.json` hash change → DELETE all File nodes WHERE `source_file = '.cc-master/discovery.json'` → re-INSERT from the current JSON.
- For Files with `source_file = 'ast-grep-walk'` (v1.b and later): on a Module's hash change → DELETE File nodes WHERE `module = <that module name>` AND `source_file = 'ast-grep-walk'` → re-INSERT from the walk output.
- **Exception to the per-file full-replace invariant:** on a `content_hash` change for a File already indexed via `ast-grep-walk`, UPDATE that File node in place (setting `content_hash`, `size`, `last_indexed`, and any language reclassification). Do NOT trigger a full Module re-index for a single-file content change. This is an explicit exception because (1) File granularity is already per-file — the same unit the "never merge" rule is written against — so a targeted UPDATE does not span multiple source artifacts and cannot drift across them, and (2) a module-level full-replace would re-scan thousands of files on every single-file edit, which blows past the `--touch discovery.json` ≤5s envelope and is unusable in an interactive edit loop. The tradeoff is documented here so future changes do not silently extend this exception to other node types: the exception applies to `File` only, only when triggered by a `content_hash` change, and only for Files with `source_file = 'ast-grep-walk'`. All other File lifecycle paths follow standard DELETE + re-INSERT.

## Edge schema

The v1 graph defines exactly six edge types: `HAS_SUBTASK`, `HAS_SPEC`, `BLOCKED_BY`, `IMPLEMENTS`, `TOUCHES`, and `CONTAINS`. Each edge is derived from a specific JSON artifact or filesystem relationship and follows the same DELETE-then-INSERT lifecycle as the node on whose `source_file` it depends — when the source artifact changes, every edge derived from it is wiped and re-derived from scratch. No edge merges. No edge UPDATEs in place. Edges without a matching target node (dangling references) are silently dropped rather than materialized as half-edges.

### HAS_SUBTASK

**Purpose:** Links a parent Task to each of its Subtasks.

**Source → Target:** `Task → Subtask`

**Cardinality:** `1:N` (a Task has zero or more Subtasks; each Subtask has exactly one parent Task)

**Properties:** No properties

**Semantic:** Expresses the `metadata.parent_id` relationship in kanban.json. When the spec skill creates subtasks, each one gets `metadata.parent_id = <parent task id>` — this edge materializes that relationship for graph queries.

**Upsert source:** `.cc-master/kanban.json` — derive from `tasks[].metadata.parent_id`.

**Lifecycle rules:** On kanban.json hash change → DELETE all HAS_SUBTASK edges WHERE source Task has `source_file = '.cc-master/kanban.json'` → re-INSERT from current JSON. Edges live and die with the Task/Subtask nodes on the kanban.json full-replace cycle.

### HAS_SPEC

**Purpose:** Links a Task to its spec document.

**Source → Target:** `Task → Spec`

**Cardinality:** `1:1` (a Task has zero or one Spec; a Spec belongs to exactly one Task)

**Properties:** No properties

**Semantic:** Materializes the `tasks[].metadata.spec_file` field from kanban.json. Queryable as "which tasks still need a spec?" (MATCH (t:Task) WHERE NOT (t)-[:HAS_SPEC]->()) and "what spec covers this task?" (MATCH (t:Task {id: $tid})-[:HAS_SPEC]->(s:Spec) RETURN s).

**Upsert source:** Intersection of `.cc-master/kanban.json` (for `metadata.spec_file`) and the spec files found under `.cc-master/specs/`. Edge is created when BOTH the Task exists AND the referenced Spec file exists.

**Lifecycle rules:** Re-evaluated on EITHER kanban.json hash change OR any spec file hash change. On trigger, DELETE all HAS_SPEC edges where source Task or target Spec changed, then re-derive. Dangling references (Task.metadata.spec_file points to a missing file) do NOT create an edge — the Task exists without a HAS_SPEC edge until the spec file is authored.

### BLOCKED_BY

**Purpose:** Expresses that one Task (or Subtask) cannot start until another one completes.

**Source → Target:** `Task → Task` (or `Subtask → Subtask`, or `Task → Subtask`, or `Subtask → Task`) — accept any pair from the union of Task and Subtask

**Cardinality:** `N:M` (a task may block or be blocked by many others)

**Properties:** No properties

**Semantic:** Derived from the `blocked_by` array field in kanban.json. A BLOCKED_BY edge from X to Y means "X cannot start until Y is completed." Transitive closure is computed at query time, not materialized.

**Upsert source:** `.cc-master/kanban.json` — for each task `t` and each id `b` in `t.blocked_by`, create an edge from `t` to the task with id `b`.

**Lifecycle rules:** On kanban.json hash change → DELETE all BLOCKED_BY edges WHERE source node has `source_file = '.cc-master/kanban.json'` → re-INSERT from current JSON. Follows the kanban.json full-replace cycle exactly.

### IMPLEMENTS

**Purpose:** Links a Task to the roadmap Feature it implements.

**Source → Target:** `Task → Feature`

**Cardinality:** `N:1` (many Tasks may implement the same Feature; each Task implements at most one Feature)

**Properties:** No properties

**Semantic:** Derived from `tasks[].metadata.feature_id` in kanban.json (which matches `features[].id` in roadmap.json). Enables queries like "what tasks exist for feature `feat-3`?" and "which features have no implementing tasks yet?".

**Upsert source:** Intersection of kanban.json (for `metadata.feature_id`) and roadmap.json (for the matching `features[].id`). Edge created only when both sides resolve.

**Lifecycle rules:** Re-evaluated on EITHER kanban.json OR roadmap.json hash change. Same replace-then-reinsert pattern. If a Task's `feature_id` refers to a Feature that was deleted from the roadmap, the IMPLEMENTS edge does not materialize — the Task remains without the edge until the Feature returns or the Task is retargeted.

### TOUCHES

**Purpose:** Links a Spec to the Modules (and/or Files) that the spec says it will modify.

**Source → Target:** `Spec → Module` (v1 primary); `Spec → File` (v1.b when file-level granularity is proven useful by task #10)

**Cardinality:** `N:M` (a Spec may touch many Modules; a Module may be touched by many Specs)

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| intent | STRING | no | `modify` or `create` — parsed from the spec's "Files to Modify" vs "Files to Create" subsections |

**Semantic:** Spec files contain structured `### Files to Modify` and `### Files to Create` subsections. Each path listed is mapped to its owning Module (by longest-prefix match against Module.path). The TOUCHES edge materializes this relationship for queries like "which specs affect `src/auth/`?" and for the qa-review files-authorized check.

**Upsert source:** `.cc-master/specs/<n>.md` — parse the "Files to Modify" and "Files to Create" subsections; resolve each path to a Module via prefix match.

**Lifecycle rules:** Re-evaluated on EITHER spec file hash change OR discovery.json hash change (which may change Module.path). On trigger, DELETE all TOUCHES edges for the affected Spec (or all Specs if discovery.json changed), then re-derive. Paths that do not match any Module cause no edge — they are silently ignored in v1 (a warning may be logged by the indexer but does not block the build).

### CONTAINS

**Purpose:** Links a Module to the Files it contains.

**Source → Target:** `Module → File`

**Cardinality:** `1:N` (a Module contains many Files; a File belongs to at most one Module)

**Properties:** No properties

**Semantic:** Reflects the file-system structure: each File whose path starts with Module.path belongs to that Module. Enables "list all files in this module" and is the bridge between the project-state layer (Module from discovery) and the code-graph layer (Files discovered by ast-grep walk).

**Upsert source:** Derived from Module.path prefix matching against File.path. Not upserted directly — computed from the set of Module and File nodes.

**Lifecycle rules:** Re-evaluated whenever Module nodes change (discovery.json hash change) OR File nodes change. Because File nodes may use in-place UPDATE in the code-graph layer (see the Node schema's File section), the CONTAINS edges they own are re-resolved at the end of each index pass as a finalization step. This is idempotent: the same Module+File combo always produces the same CONTAINS edge.

## _source metadata table

**Purpose:** `_source` is the one table in the graph that is NOT derived from a JSON artifact or from source code — it is the index's own bookkeeping, tracking which source files have been indexed, what their content hash was at last index, and which indexer version produced the derived rows. Every other node and edge in the graph can be rebuilt from JSON and disk; `_source` is rebuilt from the graph's own state plus a re-hash of the live files.

### Schema

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| file_path | STRING | no | Primary key. Path relative to project root, e.g., `.cc-master/kanban.json`, `.cc-master/specs/3.md`. For code-graph walks the pseudo-path `ast-grep-walk:<module-name>` is used. |
| content_hash | STRING | no | SHA-256 hex digest of file content at last index. For the code-graph pseudo-path, a composite hash across all files in the module. |
| last_indexed_at | TIMESTAMP | no | Wall-clock UTC of the last successful index pass for this file. |
| node_count | INT64 | no | How many nodes this file currently owns in the graph. Useful for diagnostics and for the invalidation DELETE. |
| edge_count | INT64 | no | How many edges this file currently owns. |
| indexer_version | STRING | no | Semver of `cc-master:index` at the time of this pass. Forces re-index when the skill's logic changes. |

**Primary key:** `file_path`

**Indexes:** `file_path` (primary), `last_indexed_at` (for staleness queries)

### Hash computation rules

- For a JSON artifact (`kanban.json`, `discovery.json`, `roadmap.json`): `SHA-256(canonical-json(file_contents))` where canonical-json means the JSON is re-serialized with sorted keys and no insignificant whitespace. This makes `{"a":1,"b":2}` and `{"b": 2, "a": 1}` produce the same hash.
- For a markdown spec file: `SHA-256(file_contents_bytes)` — no normalization. Markdown formatting changes count as changes.
- For a code-graph module walk: `SHA-256(sorted list of "<file_path>:<file_content_hash>" for every file in the module)`. This detects file additions, deletions, or content changes inside a module without requiring per-file graph entries to be fully enumerated.

### Invalidation algorithm

```
for each tracked file_path in _source:
    observed_hash = hash_current_file(file_path)
    stored = _source.find(file_path)
    if observed_hash != stored.content_hash:
        invalidate(file_path)
    else if stored.indexer_version != current_indexer_version:
        invalidate(file_path)
    # else: skip — up to date

function invalidate(file_path):
    # Full-replace for non-code-graph sources
    # (the File UPDATE-in-place exception applies only within ast-grep-walk source — see Node schema)
    DELETE from graph WHERE source_file = file_path
    rows = parse_source(file_path)
    for row in rows:
        MERGE into graph
    _source.upsert({
        file_path,
        content_hash: observed_hash,
        last_indexed_at: now(),
        node_count: count(nodes with source_file = file_path),
        edge_count: count(edges with source_file = file_path),
        indexer_version: current_indexer_version,
    })
```

### Absence handling

If a file referenced in `_source` no longer exists on disk (e.g., a spec file was deleted), the indexer MUST delete the row from `_source` AND delete all nodes/edges with that `source_file`. Do not keep stale pointers. The check runs at the start of every index pass: for each `file_path` in `_source`, if `os.path.exists(file_path)` returns false (or, for the `ast-grep-walk:<module-name>` pseudo-path, if the Module node no longer exists), DELETE from `_source` WHERE `file_path = <that path>` AND DELETE from graph WHERE `source_file = <that path>` as a single atomic step.

## Upsert protocol

**Overview:** The graph follows the "per-file full-replace upsert, never merge" invariant declared in the Architectural Invariants section. Every source file that contributes nodes or edges to the graph is re-indexed as a full unit: all prior rows owned by that file are DELETEd, then the current file is re-parsed and INSERTed from scratch. The one documented exception is File UPDATE-in-place within the `ast-grep-walk` source, covered in the Node schema's File section and reiterated verbatim below. No other exception exists, no other exception will be added silently, and any future proposal to add a second exception is a v2 schema change, not a v1 patch.

### Per-file algorithm

```
function index_file(file_path):
    observed_hash = hash_current_file(file_path)
    stored = _source.find(file_path)

    if stored exists AND observed_hash == stored.content_hash
       AND stored.indexer_version == current_indexer_version:
        return SKIPPED  # up to date

    # Transaction boundary: everything below is atomic
    BEGIN TRANSACTION

    if stored exists:
        # Full replace: drop everything this file owns
        DELETE nodes WHERE source_file = file_path
        # (cascading: edges whose endpoints are deleted go with them)

    parsed = parse_source(file_path)  # returns list of node+edge records
    for record in parsed:
        if record.kind == NODE:
            CREATE node
        else if record.kind == EDGE:
            CREATE edge
        record.source_file = file_path  # stamp every record

    _source.upsert(file_path, {
        content_hash: observed_hash,
        last_indexed_at: now(),
        node_count: parsed.node_count,
        edge_count: parsed.edge_count,
        indexer_version: current_indexer_version,
    })

    COMMIT TRANSACTION
    return UPDATED
```

### Failure mode

If the transaction fails mid-way (parse error, disk error, Kuzu crash), the `BEGIN TRANSACTION` / `COMMIT TRANSACTION` pair MUST NOT leave the graph in a partial state. Kuzu's single-writer atomicity guarantees this at the DB level: an in-flight transaction that does not reach `COMMIT TRANSACTION` is rolled back on the next open of the database, and the prior hash in `_source` remains authoritative. If the parse fails BEFORE the transaction begins, no changes are made — the stale data remains and the next index pass retries. Never half-apply. The indexer MUST NOT catch a mid-transaction exception and proceed with partial results; it rolls back, logs, and moves to the next file.

### Batching across multiple files

When `cc-master:index` runs without `--touch`, it iterates all tracked files (from `_source`) and discovers new files (not yet in `_source`). It processes one file per transaction — NOT all files in a single transaction. Rationale: a single bad parse should not invalidate an otherwise successful batch. The indexer reports per-file success/failure in its final summary, with counts of `UPDATED`, `SKIPPED`, and `FAILED` plus the list of failed `file_path` values and the exception each one raised.

### The File UPDATE-in-place exception

> For File nodes whose `source_file = 'ast-grep-walk'`, the indexer does NOT full-replace on `content_hash` change. Instead, it UPDATEs the changed File node in place. This is an exception to the full-replace invariant because File granularity is fine enough to make targeted UPDATE safe (each File is a self-contained unit of information with no internal relationships that could become inconsistent), and module-level full-replace would re-scan thousands of files per single-file edit — blowing the `--touch` ≤200ms scaling target. All OTHER invalidations — JSON artifacts, Module nodes, Spec nodes — use full-replace without exception.

## Canonical queries

**Overview:** The v1 schema is justified by the queries it must serve. This section enumerates the seven canonical Cypher queries that graph-backed skills run — the full working set for v1. Every query uses only the six node types (`Task`, `Subtask`, `Spec`, `Feature`, `Module`, `File`) and six edge types (`HAS_SUBTASK`, `HAS_SPEC`, `BLOCKED_BY`, `IMPLEMENTS`, `TOUCHES`, `CONTAINS`) defined above — no query invents schema. Each query is paired with the skill(s) that run it, the exact parameterization, the result shape a caller should expect, and the fallback path per `prompts/graph-read-protocol.md` when the graph is absent, stale, or erroring. A query that requires a property or relationship the v1 schema does not expose is called out as a limitation and deferred to v0.22+; none of the seven below cross that line.

### Query 1: Kanban board render

**Purpose:** Fetch all parent tasks for the text kanban board — status, priority, owner, source badge, blocked-by list, and subtask progress counts for the board's progress indicator.

**Consuming skill(s):** `cc-master:kanban`

**Cypher:**

```cypher
MATCH (t:Task)
OPTIONAL MATCH (t)-[:BLOCKED_BY]->(b:Task)
WITH t, collect(b.id) AS blocked_by
OPTIONAL MATCH (t)-[:HAS_SUBTASK]->(st:Subtask)
WITH t, blocked_by, count(st) AS subtask_total,
     count(CASE WHEN st.status = 'completed' THEN 1 END) AS subtask_done
RETURN t.id        AS id,
       t.subject   AS subject,
       t.status    AS status,
       t.priority  AS priority,
       t.source    AS source,
       t.owner     AS owner,
       blocked_by,
       subtask_total,
       subtask_done
ORDER BY t.priority, t.id
```

**Parameters:** No parameters.

**Result shape:**

```json
{
  "id": 3,
  "subject": "Add user authentication",
  "status": "pending",
  "priority": "high",
  "source": "roadmap",
  "owner": null,
  "blocked_by": [1, 2],
  "subtask_total": 5,
  "subtask_done": 2
}
```

**When absent:** The kanban skill falls back to reading `.cc-master/kanban.json` in full, filtering `tasks` to entries where `metadata.parent_id` is `null` to derive the Task set, walking each task's `blocked_by` array to compute the `blocked_by` field, and iterating the full `tasks` array a second pass to compute `subtask_total` and `subtask_done` per parent in Python. The skill prints `"Graph absent — falling back to JSON"` on the first fallback per session to surface the degradation.

### Query 2: Kanban-add dedup lookup

**Purpose:** Before appending a new task from roadmap, insights, or manual input, check whether a task with a sufficiently similar subject and the same source already exists — the dedup gate that prevents duplicate cards from piling up on the board.

**Consuming skill(s):** `cc-master:kanban-add`

**Cypher:**

```cypher
MATCH (t:Task)
WHERE t.source = $source
  AND toLower(t.subject) CONTAINS toLower($subject_fragment)
RETURN t.id AS id, t.subject AS subject, t.status AS status
LIMIT 10
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| source | STRING | The task source the new entry would be stamped with — e.g., `roadmap`, `insights`, `qa-ui-review` |
| subject_fragment | STRING | A substring to search for, lowercased by the caller; typically the normalized subject of the candidate task |

**Result shape:**

```json
[
  {"id": 12, "subject": "Fix login redirect bug", "status": "completed"},
  {"id": 47, "subject": "Login redirect regression test", "status": "pending"}
]
```

**When absent:** `cc-master:kanban-add` falls back to reading `.cc-master/kanban.json`, filtering `tasks` in Python to entries where `metadata.source == source` and `subject_fragment.lower() in subject.lower()`, then truncating the result list to 10 — identical semantics, identical cap, just slower on boards with hundreds of tasks.

### Query 3: Spec-by-module proximity

**Purpose:** Given the set of modules a proposed new spec will touch, return existing specs that touch overlapping modules — the dedup signal ("is there already a spec for this?") and the pattern-reference signal ("what prior specs in this area should I mirror?") in a single query.

**Consuming skill(s):** `cc-master:spec` (Step 2 context loading; Step 3 pattern reference)

**Cypher:**

```cypher
MATCH (m:Module) WHERE m.name IN $module_names
MATCH (s:Spec)-[:TOUCHES]->(m)
WITH s, collect(DISTINCT m.name) AS shared_modules
MATCH (t:Task)-[:HAS_SPEC]->(s)
RETURN t.id AS task_id,
       t.subject AS task_subject,
       s.file_path AS spec_file,
       shared_modules
ORDER BY size(shared_modules) DESC
LIMIT 10
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| module_names | STRING[] | The names of the modules the new spec will touch, derived by the spec skill from the task's candidate files via longest-prefix match against `Module.path` — same resolution used by the TOUCHES upsert |

**Result shape:**

```json
[
  {
    "task_id": 14,
    "task_subject": "Add rate limiting to auth endpoints",
    "spec_file": ".cc-master/specs/14.md",
    "shared_modules": ["auth", "middleware"]
  }
]
```

**When absent:** The spec skill falls back to globbing `.cc-master/specs/*.md`, reading each file, grepping the "Files to Modify" and "Files to Create" subsections for the module-prefix paths, and ranking specs by the count of matched prefixes in Python. Slower and less precise because spec text parsing happens inline rather than being pre-derived, but functional on any size board.

### Query 4: Task blast radius (downstream impact)

**Purpose:** Given a starting Task, return every Task transitively blocked by it — the downstream impact set that a PR touching this task will unblock when it lands. Used for PR context annotations and for reasoning about the cost/benefit of deferring a task.

**Consuming skill(s):** `cc-master:impact`, `cc-master:pr-review` (for PR context annotations)

**Cypher:**

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

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| task_id | INT64 | The task whose downstream impact to compute — typically the task being reviewed or deferred |

**Result shape:**

```json
[
  {"id": 18, "subject": "Login endpoint", "status": "pending", "priority": "high"},
  {"id": 22, "subject": "Registration endpoint", "status": "pending", "priority": "high"}
]
```

**When absent:** The consuming skill falls back to reading `.cc-master/kanban.json` and running a Python BFS bounded to depth 5 over the `blocked_by` field (inverted: for each node, the frontier expands to tasks whose `blocked_by` contains the current node's id). The same 50-task cap is applied after dedup.

**Depth limit note:** v1 caps transitive traversal at 5 hops. Beyond 5 hops the assumption that dependencies carry real meaning weakens — human-declared `blocked_by` is usually a nearest-neighbor signal, not a full dependency graph — and unbounded traversal is a footgun on large boards. The cap is explicit rather than defaulted to infinity so the cost is predictable. Callers that need deeper traversal should paginate by re-querying from the frontier, not by raising the depth.

### Query 5: Blocked chain traversal (upstream blockers)

**Purpose:** For a given Task, return the full chain of things that must complete before it can start — the upstream blocker set. Used by the kanban detail view for the "why can't this start?" panel and by the build skill for wave-scheduling verification (a Task whose chain contains a non-completed node cannot be dispatched in the current wave).

**Consuming skill(s):** `cc-master:kanban` (detail view), `cc-master:build` (wave-scheduling verification)

**Cypher:**

```cypher
MATCH (start:Task {id: $task_id})-[:BLOCKED_BY*1..10]->(blocker:Task)
WITH DISTINCT blocker
RETURN blocker.id AS id,
       blocker.subject AS subject,
       blocker.status AS status
ORDER BY blocker.status, blocker.id
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| task_id | INT64 | The task whose upstream blockers to list |

**Result shape:**

```json
[
  {"id": 4, "subject": "Create index skill", "status": "completed"},
  {"id": 7, "subject": "Create graph-read-protocol.md", "status": "pending"}
]
```

**When absent:** Fallback is a Python BFS over `.cc-master/kanban.json`'s `blocked_by` arrays starting from the target task and walking forward, bounded to the same 10-hop cap. The 10-hop bound is looser than Query 4's 5-hop because upstream chains are typically shorter in practice (they terminate at the root of a feature) and the build skill's scheduler needs a complete chain, not a near-neighbor approximation.

### Query 6: Files authorized to modify (qa-review gate)

**Purpose:** Given a Task, list the files its spec authorizes agents to modify — the authorization set that `cc-master:qa-review` uses to detect out-of-scope changes. A file touched by the build but not in this set is a spec violation and a qa-review finding.

**Consuming skill(s):** `cc-master:qa-review`

**Cypher:**

```cypher
MATCH (t:Task {id: $task_id})-[:HAS_SPEC]->(s:Spec)-[tc:TOUCHES]->(m:Module)
MATCH (m)-[:CONTAINS]->(f:File)
RETURN DISTINCT f.path AS file_path,
                m.name AS module_name,
                tc.intent AS intent
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| task_id | INT64 | The task being QA'd |

**Result shape:**

```json
[
  {"file_path": "src/auth/login.ts", "module_name": "auth", "intent": "modify"},
  {"file_path": "src/auth/register.ts", "module_name": "auth", "intent": "create"}
]
```

**When absent:** qa-review falls back to parsing the spec file's "Files to Modify" and "Files to Create" subsections directly from markdown and using those paths verbatim as the authorization set. Precision degrades because the Module-level TOUCHES → File expansion is skipped: an agent that modifies a file within an authorized module but not explicitly listed in the spec will pass JSON-fallback qa-review where it would have failed graph-backed qa-review. qa-review stamps the report's `mode` field as `"json-fallback"` when running in this path so reviewers can see the degraded precision on the output itself.

### Query 7: Tasks missing specs (`spec --all`)

**Purpose:** Return all pending parent Tasks that do not yet have a Spec attached — the default selection set for `cc-master:spec --all`. This is the skill's entry-point when invoked without explicit task IDs: "spec everything that needs spec'ing."

**Consuming skill(s):** `cc-master:spec --all`

**Cypher:**

```cypher
MATCH (t:Task)
WHERE t.status = 'pending'
  AND NOT (t)-[:HAS_SPEC]->(:Spec)
RETURN t.id       AS id,
       t.subject  AS subject,
       t.priority AS priority
ORDER BY t.priority, t.id
LIMIT 20
```

**Parameters:** No parameters.

**Result shape:**

```json
[
  {"id": 11, "subject": "Refactor cc-master:spec --all", "priority": "normal"},
  {"id": 19, "subject": "First-run migration prompt", "priority": "normal"}
]
```

**When absent:** The spec skill falls back to globbing `.cc-master/specs/*.md`, extracting the task id from each filename stem into a "has-spec" set, reading `.cc-master/kanban.json`, filtering to parent tasks where `status == 'pending'`, and excluding any task whose id appears in the has-spec set. The same 20-task cap is applied after sorting by priority then id. Semantics are identical; the overhead is the extra JSON read and directory listing.

## NOT in v1

The v1 graph engine deliberately excludes these capabilities. Each is tracked for a future version with a specific trigger for reconsideration.

### Deferred to v0.22

- **Symbol nodes with dynamic-dispatch resolution** — v1 uses ast-grep, which handles structural patterns but not runtime polymorphism (interface dispatch, reflection, DI container lookups). This is a known accuracy gap. Trigger for v0.22: a real project shows ast-grep-missed call edges that materially affect `cc-master:impact` correctness. Solution path: SCIP indexer swap-in per language (same graph schema, different indexer).
- **Test-symbol REFERENCES edges** — v1 classifies files as `is_test = true` based on path/filename rules, and edges between Test files and Symbols they exercise are NOT materialized. This means `cc-master:qa-review` cannot answer "which tests cover this symbol?" via graph query — it falls back to string-based test-file greps. Trigger for v0.22: user demand for `cc-master:impact --tests` or `cc-master:qa-review --uncovered-symbols`.
- **CompetitorInsight nodes** — `.cc-master/competitor_analysis.json` pain points and market gaps are not yet indexed. `cc-master:spec` resolves them via direct JSON read. Trigger for v0.22: roadmap feature cross-referencing becomes expensive enough to justify graph materialization.

### Deferred to v0.23

- **PR nodes** — linking Tasks to GitHub PRs via `metadata.pr_url`. Useful for post-merge impact queries ("what PRs touched this module?") but not on any skill's critical path today.
- **Vector / embedding layer** — semantic search over spec content and insights sessions. A separate discussion (see Open questions); adds a second dependency (sqlite-vec or similar) for arguable token-saving benefit until spec volume grows large enough.

### Deferred indefinitely

- **Cross-module call-graph transitive closure with runtime dispatch** — the full "who could ever call this at runtime" query. ast-grep can't compute this; SCIP gives a better approximation but still not complete. This is a research problem, not a shipping feature. The graph supports 2-3 hop transitive closure today (Query 4 / Query 5); deeper dispatch-aware analysis stays out-of-scope until a compelling use case appears.
- **Mutation via skills other than cc-master:index** — a hard architectural invariant, not a deferral. Other skills will always be read-only on the graph.

## Open questions for v0.22+

Decisions intentionally left open. Each has a revisit trigger — a specific signal that warrants re-opening the question.

### 1. ast-grep vs SCIP for the code-graph indexer

v1 uses ast-grep because it's a single binary with zero per-language setup. The tradeoff is accuracy on dynamic dispatch. Revisit when: (a) a real project's `cc-master:impact` output demonstrably misses call edges that matter, OR (b) ast-grep's output format breaks in a way that makes parsing fragile, OR (c) SCIP indexer install tooling improves to the point where "one command per language" becomes acceptable UX.

### 2. Vector / embedding layer: yes, no, when?

The argument for: semantic search over specs, insights, and roadmap entries could replace fragment-match queries with "find similar-in-meaning" queries. The argument against: adds a dependency (sqlite-vec or equivalent), embedding cost per write, and most current skills care about structural relationships the graph already provides.

Revisit when: (a) spec count on a real project exceeds 200 AND Query 3 (spec-by-module proximity) returns too many false positives for human triage, OR (b) insights session history grows large enough that full-text search becomes the bottleneck.

### 3. Graph-read cache invalidation across skill invocations

Kuzu's file-backed DB is accessed per-skill-invocation. Each invocation incurs open/close overhead. Revisit when: measured overhead exceeds 100ms per skill on a representative project. Possible solution: a long-lived background process (cc-master daemon) — but this conflicts with the "plugin is just files" invariant and is non-trivial UX.

### 4. Incremental discovery + incremental graph

`cc-master:discover --update` supports module-level incremental re-trace. The graph should mirror this: when only module X changed, re-index only module X's Module + File + Symbol nodes without touching others. v1 already supports this via `cc-master:index --module <name>`, but the automatic wiring from discover to index is not yet built. Revisit when: discover + index chained invocation shows up as a pain point in user reports.

### 5. Multi-repo graph

Can one graph index multiple repos? Useful for monorepo-across-git-repos organizations. Revisit when: a real use case from a user, not speculatively.

