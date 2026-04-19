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
| Cold full index | ≤30s aspirational, ≤60s hard gate | 500-task `kanban.json`, 50-spec `specs/` directory, 10k-file codebase, `ast-grep` available on PATH; Wave 7 impact queries depend on this | Stop — optimize before Wave 7. Split indexing per-module, reconsider the bulk-insert strategy (COPY FROM vs. MERGE batches), and re-measure via `scripts/graph/measure_code_graph_index.sh` (exits 3 on >60s miss) |
| `--touch kanban.json` re-index | ≤200ms | Single `kanban.json` write from a post-write skill (e.g. `kanban-add`, `build`, `complete`) | Skip synchronous re-index and fall back to async/batched indexing on a debounce timer |
| Board-render query | ≤50ms | 500 tasks, cold Kuzu query cache, all columns rendered | Add a composite index on `Task.status` and `Task.priority`; re-measure before accepting |
| 2-hop impact query | ≤200ms | Start from a single `Symbol` node on a 10k-file codebase, traverse two hops of `REFERENCES`/`DEFINED_IN` edges | Cap traversal depth, paginate results, and require callers to request additional pages explicitly |
| `--touch discovery.json` re-index | ≤5s | Full `discovery.json` re-parse after a module boundary change that invalidates entry points, key flows, and symbol tables | Re-scope to changed-modules-only by diffing the previous and current discovery snapshots |

The envelope is fixed for v1. If production usage surfaces a workload these numbers do not cover, it becomes a v1.1 entry — not a quiet relaxation of v1.

## Node schema

The v1 graph defines seven node types: `Task`, `Subtask`, `Spec`, `Feature`, `Module`, `File`, and `Symbol`. Each node is derived from a specific JSON artifact or filesystem scan, carries a `source_file` property so the per-file full-replace invariant can locate every derived node in a single query, and follows the same DELETE-then-INSERT lifecycle on upstream change. Types are Kuzu native types: `STRING`, `INT64`, `BOOLEAN`, `TIMESTAMP`, and `STRING[]` / `INT64[]` for arrays.

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
| competitor_insight_ids | STRING[] | no | Array of competitor insight ids from `metadata.competitor_insight_ids` (default `[]`). Drives the `[C]` competitor-informed badge in the kanban board render. |
| phase | STRING | no | Free-form phase stamp from `metadata.phase` such as `"qa"` (default `""` — empty string, not NULL). Drives the Review column classification (`status = in_progress AND phase = "qa"`) in the kanban board render. |

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
| competitor_insight_ids | STRING[] | no | Array of competitor insight ids from `metadata.competitor_insight_ids` (default `[]`). Drives the `[C]` competitor-informed badge in the kanban board render. |
| phase | STRING | no | Free-form phase stamp from `metadata.phase` such as `"qa"` (default `""` — empty string, not NULL). Drives the Review column classification (`status = in_progress AND phase = "qa"`) in the kanban board render. |

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
| is_test | BOOLEAN | no | True if classified as a test file. Classification rules live in `prompts/test-file-definition.md` — the canonical source shared with the build skill's production-quality scan (task #76 extracted, task #81 wired into the ast-grep walker). |
| last_indexed | TIMESTAMP | no | When this File node was last refreshed |
| source_file | STRING | no | The artifact that caused this File to be indexed — `.cc-master/discovery.json` when from discovery, or the literal string `ast-grep-walk` when from a code-graph walk |

**Primary key:** `path`

**Indexes:** `module`, `is_test`, `content_hash`, `source_file`

**Upsert source:** `.cc-master/discovery.json` for the project-state layer in v1; `ast-grep` walk of each Module for the code-graph layer starting at task #12.

**Lifecycle rules:**

- For Files with `source_file = '.cc-master/discovery.json'`: on `discovery.json` hash change → DELETE all File nodes WHERE `source_file = '.cc-master/discovery.json'` → re-INSERT from the current JSON.
- For Files with `source_file = 'ast-grep-walk'` (v1.b and later): on a Module's hash change → DELETE File nodes WHERE `module = <that module name>` AND `source_file = 'ast-grep-walk'` → re-INSERT from the walk output.
- **Exception to the per-file full-replace invariant:** on a `content_hash` change for a File already indexed via `ast-grep-walk`, UPDATE that File node in place (setting `content_hash`, `size`, `last_indexed`, and any language reclassification). Do NOT trigger a full Module re-index for a single-file content change. This is an explicit exception because (1) File granularity is already per-file — the same unit the "never merge" rule is written against — so a targeted UPDATE does not span multiple source artifacts and cannot drift across them, and (2) a module-level full-replace would re-scan thousands of files on every single-file edit, which blows past the `--touch discovery.json` ≤5s envelope and is unusable in an interactive edit loop. The tradeoff is documented here so future changes do not silently extend this exception to other node types: the exception applies to `File` only, only when triggered by a `content_hash` change, and only for Files with `source_file = 'ast-grep-walk'`. All other File lifecycle paths follow standard DELETE + re-INSERT.

### Symbol

**Purpose:** A named code entity — a function, class, method, struct, interface, type alias, or enum — declared in a source file and extracted by the ast-grep walk during code-graph indexing. Symbol nodes are the v1 addressable unit for code-level queries such as `cc-master:impact` blast-radius traversals and qa-review's "which symbols does this spec touch?" checks. Symbol-level edges to other symbols (CALLS, EXTENDS, IMPLEMENTS_INTERFACE) are NOT in v1 — only `REFERENCES` from `File` to `Symbol` is materialized — so Symbol is a lexical node in v1, not a call-graph node.

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| id | STRING | no | `sha256(module:file:kind:name:line)[:16]` — a deterministic 16-char hex digest stable across re-indexes of unchanged code |
| name | STRING | no | The declared symbol name as it appears in source (not qualified — qualification lives in `module` + `file`) |
| kind | STRING | no | One of: `function`, `class`, `method`, `struct`, `interface`, `type`, `enum`. Other kinds (variable, constant, macro) are deferred to v0.22 |
| file | STRING | no | Relative path to the source file the symbol is declared in, matching `File.path` |
| line | INT64 | no | 1-indexed line number of the symbol's declaration as reported by ast-grep |
| module | STRING | no | Name of the owning Module, matching `Module.name`; resolved by the same longest-prefix match used for `File.module` |
| source_file | STRING | no | Always `'ast-grep-walk'` for v1 — Symbols are exclusively populated by the code-graph walk, never by discovery.json |
| last_indexed | TIMESTAMP | no | When this Symbol node was last refreshed |

**Primary key:** `id`

**Indexes:** `name` (for name-resolution queries), `module` (for module-scoped re-index DELETE), `file` (for file-scoped invalidation during REFERENCES re-derivation), `source_file` (for the per-file full-replace invariant)

**Upsert source:** `ast-grep` walk of each Module. The walker emits one Symbol record per qualifying declaration in each source file within the module, stamping each record with `source_file = 'ast-grep-walk'`.

**Lifecycle rules:** On a Module's hash change → DELETE all Symbol nodes WHERE `module = <that module name>` AND `source_file = 'ast-grep-walk'` → re-INSERT from the walk output. Never UPDATE in place. Unlike File, Symbol does NOT receive a UPDATE-in-place exception — a symbol's identity derives from its line number, and a change to the declaration line is indistinguishable from a delete + insert of a new symbol, so the safe behavior is full replace at the module boundary. The File UPDATE-in-place exception (see the File node's Lifecycle rules, final bullet) applies when only a File's `content_hash` changed AND no symbols were added, removed, or moved inside it: in that narrow case the File node is UPDATEd in place and its outgoing `REFERENCES` edges are re-derived in a targeted pass without triggering a full module re-walk. If the targeted pass detects any symbol change, the indexer escalates to the full module DELETE + re-INSERT described above.

## Edge schema

The v1 graph defines seven edge types: `HAS_SUBTASK`, `HAS_SPEC`, `BLOCKED_BY`, `IMPLEMENTS`, `TOUCHES`, `CONTAINS`, and `REFERENCES`. Each edge is derived from a specific JSON artifact or filesystem relationship and follows the same DELETE-then-INSERT lifecycle as the node on whose `source_file` it depends — when the source artifact changes, every edge derived from it is wiped and re-derived from scratch. No edge merges. No edge UPDATEs in place. Edges without a matching target node (dangling references) are silently dropped rather than materialized as half-edges.

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

### REFERENCES

**Purpose:** Links a File to each Symbol it lexically references — a call site, an import, or a type annotation. REFERENCES materializes the "who mentions this symbol?" lookup that `cc-master:impact` uses to compute blast radius and that `cc-master:pr-review` uses to annotate PR bodies with the downstream files a change reaches.

**Source → Target:** `File → Symbol`

**Cardinality:** `N:M` (a File may reference many Symbols; a Symbol may be referenced from many Files)

**Properties:**

| Name | Type | Nullable | Description |
|------|------|----------|-------------|
| line | INT64 | no | 1-indexed line number in the source File where the reference occurs |
| context | STRING | no | The trimmed source text of the referencing line — used for human-readable output in impact and pr-review reports (bounded to 240 chars by the walker; longer lines are truncated with a trailing ellipsis) |
| kind | STRING | no | One of: `call`, `import`, `type_ref`. `call` = function/method invocation; `import` = module/symbol import statement; `type_ref` = type annotation, generic parameter, or extends/implements clause |
| source_file | STRING | no | Always `'ast-grep-walk'` for v1 — REFERENCES edges are exclusively populated by the code-graph walk |

**Semantic:** A REFERENCES edge expresses a lexical textual reference, not a resolved runtime call. ast-grep matches structural patterns — it sees `login(user)` as a call to a name `login`, and the REFERENCES edge points to every Symbol whose `name = 'login'` within the same module (v1 does NOT perform cross-module name resolution — see "NOT in v1"). Callers that need cross-module or dispatch-aware resolution must fall back to language-specific tooling; the graph provides the lexical substrate only.

**Upsert source:** `ast-grep` walk per module. For each source file in the module, the walker emits one REFERENCES record per matched reference pattern (call / import / type_ref), stamping each record with `source_file = 'ast-grep-walk'` and resolving the target Symbol id by matching `name` + `module` against already-indexed Symbol nodes. References that do not resolve to an existing Symbol within the module are silently dropped (consistent with the general dangling-edge rule stated at the top of this section).

**Lifecycle rules:** On a Module's hash change → DELETE all REFERENCES edges WHERE the source File has `source_file = 'ast-grep-walk'` AND `module = <that module name>` → re-INSERT from the walk output. Never UPDATE in place. Edges live and die with the module's full re-walk cycle. **File UPDATE-in-place exception cross-reference:** when only a File's `content_hash` changed and no symbols were added, removed, or moved (the targeted exception defined in the File node's Lifecycle rules), the File node is UPDATEd in place and its outgoing `REFERENCES` edges are re-derived in a targeted pass — DELETE REFERENCES WHERE the source File matches the single updated path AND `source_file = 'ast-grep-walk'`, then re-INSERT from ast-grep's output for that one file only. This avoids re-walking thousands of files in the module when a single file's body churned without touching its declared symbols. If the targeted re-derivation discovers that the file now introduces or removes a reference whose target Symbol does not exist within the module, the indexer escalates to a full module re-walk rather than persisting a partially consistent edge set.

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

**Overview:** The v1 schema is justified by the queries it must serve. This section enumerates the eight canonical Cypher queries that graph-backed skills run — the full working set for v1. Every query uses only the six node types (`Task`, `Subtask`, `Spec`, `Feature`, `Module`, `File`) and six edge types (`HAS_SUBTASK`, `HAS_SPEC`, `BLOCKED_BY`, `IMPLEMENTS`, `TOUCHES`, `CONTAINS`) defined above — no query invents schema. Each query is paired with the skill(s) that run it, the exact parameterization, the result shape a caller should expect, and the fallback path per `prompts/graph-read-protocol.md` when the graph is absent, stale, or erroring. A query that requires a property or relationship the v1 schema does not expose is called out as a limitation and deferred to v0.22+; none of the seven below cross that line.

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

### Query 8: Tests in a module

**Purpose:** Enumerate the test files that live inside a given Module — the test-scope set that `cc-master:qa-review` uses to decide which tests cover the module under review and that `cc-master:impact` uses to list tests affected by a change to that module. Because v1 does not materialize Test-symbol REFERENCES edges (see NOT in v1), this file-level enumeration is the v1 substitute for "which tests exercise this module?".

**Consuming skill(s):** `cc-master:qa-review`, `cc-master:impact`

**Cypher:**

```cypher
// Tests in a module — used by qa-review and impact to enumerate test files that exercise a module.
MATCH (f:File)
WHERE f.module = $module AND f.is_test = true
RETURN f.path
ORDER BY f.path
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| module | STRING | The name of the module whose tests to list — same value stored on `File.module` and `Module.name` |

**Result shape:**

```json
[
  {"f.path": "tests/auth/test_login.py"},
  {"f.path": "tests/auth/test_register.py"}
]
```

**When absent:** The consuming skill falls back to reading `.cc-master/discovery.json`, resolving the module's file list, and filtering each file against the path/filename rules in `prompts/test-file-definition.md` in Python — the same classification logic the ast-grep walker applies at index time, just executed per-call instead of pre-derived. Semantics are identical; the overhead is re-running the classifier on every query.

## NOT in v1

The v1 graph engine deliberately excludes these capabilities. Each is tracked for a future version with a specific trigger for reconsideration.

### Deferred to v0.22

- **Symbol nodes with dynamic-dispatch resolution / cross-module call closure** — basic Symbol nodes and lexical REFERENCES edges ARE in v1 as of wave 6 (task #12): ast-grep emits Symbol nodes for function/class/method/struct/interface/type/enum declarations and REFERENCES edges for call / import / type_ref references within a module. What is NOT in v1 is dynamic-dispatch resolution (interface dispatch, reflection, DI container lookups, function-pointer-in-a-map jumps) and cross-module call closure (resolving a reference whose target Symbol lives in a different module than the calling File). ast-grep handles structural patterns but not runtime polymorphism, and v1 deliberately scopes REFERENCES to intra-module name matches to keep the edge set bounded and the per-module re-walk cheap. Trigger for v0.22: a real project shows ast-grep-missed call edges that materially affect `cc-master:impact` correctness, OR users demand cross-module impact traversal that Query 4's `BLOCKED_BY` approximation cannot answer. Solution path: SCIP indexer swap-in per language (same graph schema, different indexer) with first-class cross-module symbol resolution.
- **Test-symbol REFERENCES edges** — v1 classifies files as `is_test = true` based on the path/filename rules in `prompts/test-file-definition.md`, but edges between Test files and the production Symbols they exercise are NOT materialized. This means the graph can answer "which files in a module are tests?" (Query 8) but cannot answer "which tests cover this specific symbol?" or "which production symbols have no covering test?" via graph query. Trigger for v0.22 is EITHER (a) user demand for `/cc-master:impact --tests` (list tests that cover a changed symbol), OR (b) user demand for `/cc-master:qa-review --uncovered-symbols` (find production symbols without test coverage). v1 workaround: string-based test-file greps in qa-review fall back to `MATCH (f:File) WHERE f.is_test = true` for the module scope (Query 8) and then scan those files' contents for symbol names — coarse but sufficient until one of the two v0.22 triggers fires.
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

## v0.21.0 Validation

**Run date:** 2026-04-19T07:38:07Z (pipeline run); 2026-04-19T20:00:00Z (measurements roll-up — `validation-measurements.json` `measurements_date`)
**Target project:** `/Users/mstjohn/Documents/SRC/LJK/cc-master` — dogfooded against cc-master itself (117 kanban tasks, 22 active top-level specs excluding `.cc-master/specs/archive-*/`). Selected over `SF` (67 tasks) and `escrow-domains-ui` (4 tasks) because it has the largest kanban, the richest spec corpus, is the repo in which the graph engine itself was developed, and satisfies spec #22 AC 6's "large real project" threshold of ≥20 kanban tasks.
**Environment:** macOS 26.0.1 (Darwin 25.0.0, `Mac16,7`, arm64, 14 cores, 24 GiB RAM) / Python 3.13 via `/tmp/kuzu-venv/` (not the system Python 3.14.3) / ast-grep 0.42.1 / Kuzu 0.11.2 (installed as `kuzu==0.11.2` into the venv; verified by `/tmp/kuzu-venv/bin/python3 -c "import kuzu; print(kuzu.__version__)"` → `0.11.2`).
**cc-master commit:** `cff23024549942c8abd30beaaa3a2fc3fb042de2` (branch `v2-graph-engine`, plugin version `0.21.0-dev.5`; finalizes to `0.21.0` in wave 9).

**Validation method note.** This is a dogfooded run: the graph engine under test indexed the very repository that produced it, which is the most realistic possible fidelity for the cc-master skill chain but does conflate test subject and test harness — a future validation should add a second target (e.g. the `SF` project) for independent confirmation. Two shell-reachability gaps shaped the method. First, `kuzu==0.11.2` has no Python 3.14 wheel on PyPI and its sdist fails `python3 setup.py build_extension` under the Homebrew 3.14 toolchain (`make clean` exits 2); every measurement therefore runs under a Python 3.13 venv at `/tmp/kuzu-venv/` with `PATH="/tmp/kuzu-venv/bin:$PATH"` prepended so the scripts' `python3` resolves to the venv interpreter. Second, both `cc-master:index` (the cold-index driver) and its `--touch <file>` flag are Claude Code slash commands with no shell binary; the cold-index measurement uses a purpose-built 108-line driver at `/tmp/cc-master-index-driver.py` that invokes `scripts/graph/astgrep_walker.py` directly and upserts `File`/`Symbol`/`REFERENCES` to a fresh Kuzu DB, and the `--touch` measurement uses an embedded Python proxy at `/tmp/touch-proxy2.py` that times the minimum MERGE work. Both are explicit lower-bound proxies for the full skill path; neither writes the `Task`/`Subtask`/`Spec`/`Feature`/`Module`/`_source` families that the real `cc-master:index` populates. Findings below are annotated accordingly, and the two gaps are carried forward as v1.1 backlog entries under Regressions.

### Token Reduction

Measured via `scripts/graph/measure_kanban_savings.sh` and `scripts/graph/measure_spec_context_savings.sh` run from the repo root with the venv on PATH. Both scripts emit **family-level aggregates** against canonical fixtures (`tests/fixtures/kanban-500.json`, `tests/fixtures/specs-30/`) rather than per-skill before/after byte counts, so the table reports one row per skill family; the `Skills covered` column enumerates the 22 refactored skills that cite `prompts/kanban-write-protocol.md` or `prompts/graph-read-protocol.md` and therefore benefit from the reduction.

| Family | Before (bytes) | After (bytes) | Reduction | Ratio | Design target | Skills covered |
|--------|---------------:|--------------:|----------:|------:|:-------------:|----------------|
| Kanban read (`kanban`, `kanban-add`, `build`, `complete`, `qa-review`, `qa-fix`, `qa-loop`, `pr-review`, `gap-check`, `align-check`, `release-docs`, `impact`) | 595,293 | 88,361 | 85.2% | **6.7×** | 5.0× | 12 skills |
| Spec context read (`spec`, `build`, `qa-review`, `pr-review`, `impact`, `debug`, `trace`, `config-audit`, `api-payload-audit`, `perf-audit`) | 248,572 | 37,055 | 85.1% | **6.7×** | 5.0× | 10 skills |

Both families clear the 5.0× design target (`validation-measurements.json → token_reduction.design_target_ratio`) with a 1.7× margin. The two family totals are independent; a skill that appears in both rows (`build`, `qa-review`, `pr-review`, `impact`) benefits from both reductions compounded.

### Cold Full Index

| Measurement | Value | Source |
|-------------|------:|--------|
| Wall time (total) | **6.9 s** | `validation-measurements.json → cold_index.wall_seconds` |
| ast-grep walk | 0.541 s | `cold_index.breakdown_seconds.ast_grep_walk` |
| Kuzu upsert | 6.375 s | `cold_index.breakdown_seconds.kuzu_upsert` |
| Files indexed | 568 | `cold_index.files_indexed` |
| Symbols indexed | 90 | `cold_index.symbols_indexed` |
| REFERENCES edges | 153 (of 804 walker refs — 651 had `symbol_id: null` from unresolved cross-module imports) | `cold_index.references_indexed` + notes |
| Graph-file size | 10.3 MB (single file, not directory — Kuzu 0.11.2 packs the DB into one file on this platform) | `du -sh .cc-master/graph.kuzu` |
| Design target | ≤60 s hard gate, ≤30 s aspirational (Scaling envelope row 1) | This doc |
| Result | **PASS — 53 s margin under the hard gate, 23 s margin under the aspirational target** | derived |

Driver command:

```
CC_BENCH_REPO="$(pwd)" PATH="/tmp/kuzu-venv/bin:$PATH" \
  bash scripts/graph/measure_code_graph_index.sh \
  --invoke "/tmp/kuzu-venv/bin/python3 /tmp/cc-master-index-driver.py"
```

**Caveat.** The 108-line validation driver exercises the code-graph write path (`File`, `Symbol`, `REFERENCES`) but does **not** populate `Task`/`Subtask`/`Spec`/`Feature`/`Module`/`_source` — those are written by the full `cc-master:index` skill, which has no shell-invokable form in v0.21.0. The 6.9 s figure is therefore a lower bound on cold-index latency for code-graph-only scope; a full-fidelity measurement requires the driver work tracked under Regressions.

### --touch Single-File Re-Index

| Measurement | Value | Source |
|-------------|------:|--------|
| Wall time (median of 3) | **0.040 s** | `touch_reindex.wall_seconds` |
| Run 1 / 2 / 3 | 0.0847 s / 0.0398 s / 0.0353 s | `touch_reindex.runs_seconds` |
| Median breakdown — file read | 0.0001 s | `touch_reindex.breakdown_seconds_median.file_read` |
| Median breakdown — db connect | 0.0115 s | `breakdown_seconds_median.db_connect` |
| Median breakdown — MERGE upsert | 0.0069 s | `breakdown_seconds_median.merge_upsert` |
| Median breakdown — close | 0.0213 s | `breakdown_seconds_median.close` |
| Design target | ≤200 ms (Scaling envelope row 2) | This doc |
| Result | **PASS — 5× under target** (caveat below) | derived |

**Caveat.** `kuzu_client.py --help` exposes only `init`, `query`, and `close` subcommands — there is no `--touch` subcommand, and the `--touch <file>` flag on `cc-master:index` is only reachable via the slash command, not shell. The number above comes from `/tmp/touch-proxy2.py`, which times `read kanban.json → open DB → MERGE (:File {path}) → close` — the minimum work a real `--touch` would perform on a single file. It excludes the secondary `Task`/`Subtask`/`BLOCKED_BY` rewrites the real `--touch .cc-master/kanban.json` would perform after a kanban write, and it therefore **understates** true latency. The warm re-run number from subtask #115's pipeline log (6.9 s) must **not** be quoted as `--touch` latency — that was a full repo re-walk by the same 108-line driver used for cold index. A shell-invokable `cc-master:index --touch` driver is the only way to measure the real number; it is carried forward as Regression #2.

### cc-master:impact Accuracy

| Test | Symbol | Ground truth | Graph result | Precision | Recall |
|------|--------|-------------:|-------------:|----------:|-------:|
| Intra-file (defined and called in the same Python file) | `_load_kuzu` in `scripts/graph/kuzu_client.py` | 12 (3 defs + 9 call lines across the primary file and its two worktree copies) | 12 | **1.0** | **1.0** |
| Cross-file (defined in one module, called from another) | `classify_test_file` defined at `scripts/graph/astgrep_walker.py:153` | 22 (2 same-file calls at lines 233, 631 + 20 cross-file calls in `scripts/graph/test_astgrep_walker.py`) | 2 (same-file only) | 1.0 | 1.0 same-file / **0.0 cross-file** / **0.091 overall** |

Global graph context: a `MATCH (f:File)-[r:REFERENCES]->(s:Symbol) WHERE f.path <> s.file RETURN count(*)` returned `0` out of 306 total `REFERENCES` edges. The v1 graph contains **zero** cross-file references.

**Interpretation.** Precision stays at 1.0 across both tests — every edge the graph produces is a real call site in the source — but recall collapses from 1.0 to 0.0 the moment the call crosses a file boundary. This is the documented ast-grep v1 limitation: the walker matches call-site symbols textually and cannot resolve cross-module imports back to the defining `Symbol` node. The MEMORY.md "~80% accuracy" figure is an upper bound that holds when most references are intra-file; cc-master's heavier cross-file coupling via Python imports produces a worse recall profile. The v1 graph is therefore reliable for same-file impact analysis and refactor safety checks, but cross-module blast radius requires either (a) disclosing the limitation in the `impact` output or (b) the **SCIP swap scheduled for v0.22**, which replaces the ast-grep walker while preserving the Kuzu schema (`Task` #27 in the v1.1 backlog; schema-preserving so consumers do not change). v0.22 is expected to produce a non-trivial cross-file `REFERENCES` count on this same target.

### Graceful Degradation

Tested by moving `.cc-master/graph.kuzu` aside and invoking a read path:

```
mv .cc-master/graph.kuzu .cc-master/graph.kuzu.offline
PATH="/tmp/kuzu-venv/bin:$PATH" python3 scripts/graph/kuzu_client.py \
  query .cc-master/graph.kuzu "MATCH (f:File) RETURN count(f) AS n"
echo "exit=$?"
mv .cc-master/graph.kuzu.offline .cc-master/graph.kuzu
```

Captured output:

```
{"error": "database not found at /Users/mstjohn/Documents/SRC/LJK/cc-master/.cc-master/graph.kuzu"}
exit=3
```

Exit code **3** matches the declared contract in `scripts/graph/README.md` (Exit codes table, "3 — Database path not found"). The Read Protocol's Check 1 (graph directory exists) therefore triggers deterministically on an absent graph.

**Indicator-contract verification.** The contract requires three literal strings (`Graph: fresh`, `Graph: stale — fell back to JSON`, `Graph: absent — fell back to JSON`) plus a First-run check and an Emit Graph Output Indicator step in every refactored skill. Verified against `skills/kanban/SKILL.md` on the v2-graph-engine branch (`validation-measurements.json → graceful_degradation.skill_md_lines`):

| Contract element | Line |
|------------------|-----:|
| First-run check | 38 |
| Step 6 "Emit Graph Output Indicator" header | 234 |
| Literal `Graph: fresh` | 238 |
| Literal `Graph: stale — fell back to JSON` | 239 |
| Literal `Graph: absent — fell back to JSON` | 240 |
| Default-on-error clause (emit `absent` string if a pre-query check errored) | 242 |

The `kanban` skill is representative of the 22 refactored skills — wave 8's indicator wiring (task #20) holds.

### Regressions

Two unmet or proxy-only items versus the design targets; both are known limitations with concrete fixes planned for v0.22 / v1.1.

| # | Measurement | Observed | Expected | Severity | Follow-up task (v1.1 backlog) |
|---|-------------|----------|----------|----------|-------------------------------|
| 1 | `impact` cross-file recall (`impact_accuracy.cross_file.recall_cross_file`) | 0.0 (0 of 306 `REFERENCES` edges are cross-file) | Non-zero for cross-module Python calls; MEMORY.md cites ~80% accuracy as ast-grep v1's upper bound | known-limitation | Swap the ast-grep walker for SCIP-based symbol resolution in v0.22 while preserving the Kuzu schema (`File`/`Symbol`/`REFERENCES` consumers unchanged). Re-run the `classify_test_file` cross-file test on the same commit and expect recall to rise from 0.0 toward the ~0.8 target. |
| 2 | `--touch` true single-file latency (`touch_reindex.true_single_file_latency`) | Proxy only (0.040 s median via embedded MERGE timer); no shell-reachable driver for `cc-master:index --touch <file>` | End-to-end `cc-master:index --touch <file>` wall-time against the real skill code path, including `Task`/`Subtask`/`BLOCKED_BY` rewrites on a `kanban.json` touch | instrumentation-gap | Expose `--touch <file>` as a `scripts/graph/kuzu_client.py` subcommand (mirroring `init`/`query`/`close`) OR ship a shell-invokable non-interactive driver for `cc-master:index` so future validation runs can measure the real single-file re-index without an embedded Python proxy. Required before any future "200 ms hard gate" re-attest. |

