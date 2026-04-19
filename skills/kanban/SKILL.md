---
name: kanban
description: Render current tasks as a text-based kanban board. Reads from .cc-master/kanban.json and displays compact column view with box-drawing characters. Use anytime to see project status at a glance.
---

# cc-master:kanban — Text Kanban Board

Render the current task list as a visual kanban board in the terminal using box-drawing characters. Reads from `.cc-master/kanban.json`.

## Task Persistence Protocol

Tasks are persisted to `.cc-master/kanban.json` — the sole source of truth.
Never use CC's TaskCreate, TaskGet, TaskList, or TaskUpdate tools.

**Initialize:** If `.cc-master/kanban.json` does not exist, create the `.cc-master/` directory if it does not exist, then create the file with `{"version":1,"next_id":1,"tasks":[]}` before proceeding.

**Read:** Use the Read tool on `.cc-master/kanban.json` and parse the JSON.

**Find subtasks:** Filter `tasks` where `metadata.parent_id == <parent id>`.

## Process

### Step 1: Read Task State

Read `.cc-master/kanban.json` using the Read tool and parse the JSON. If the file does not exist or `tasks` array is empty, print:

```
No tasks found. Use /cc-master:kanban-add to create tasks.
```

And stop.

### Step 1b: Pre-Query Checks

This skill is graph-backed with a strict JSON fallback. Paste the following contract block verbatim before executing any Cypher query — the text is the required citation of `prompts/graph-read-protocol.md` and propagates the three pre-query checks, the one-warning-per-session rule, and the JSON-fallback fragment downstream.

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

Execute the checks in order:

1. **Check 1 — Graph path exists and is readable.** Test that `.cc-master/graph.kuzu` exists and is readable (Kuzu may store the DB as a directory or a single file depending on version — `test -e` works for both, e.g. `test -e .cc-master/graph.kuzu`). If absent or unreadable → set `render_source = "JSON fallback"`, emit the one-warning line `Graph absent/stale — falling back to JSON read for kanban.json` if not already emitted this session, skip directly to Step 2 using the `tasks[]` array from Step 1's JSON read.

2. **Check 2 — Source hash matches.** Run the `_source` lookup via the Kuzu client:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu "MATCH (s:_source {file_path: '.cc-master/kanban.json'}) RETURN s.content_hash AS stored"
   ```

   Compute the on-disk canonical-JSON hash of `.cc-master/kanban.json` using the JSON-artifact algorithm specified in `prompts/graph-read-protocol.md` (`## Hash Comparison Rule`):

   ```
   python3 -c "import json,hashlib,sys; o=json.load(open(sys.argv[1])); print(hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':')).encode()).hexdigest())" .cc-master/kanban.json
   ```

   If no `_source` row is returned, or the stored hash differs from the current on-disk hash → set `render_source = "JSON fallback"`, emit the one-warning line if not already emitted, skip to Step 2 using the JSON `tasks[]` array.

3. **Check 3 — Query executes cleanly.** Guard every Cypher shell-out in Step 1c with exit-code inspection. If `kuzu_client.py query` exits non-zero (codes 2, 3, 4, or any other) or writes to stderr → set `render_source = "JSON fallback"`, emit the one-warning line if not already emitted, abandon the graph rowset, and fall through to Step 2 using the JSON `tasks[]` array.

Once fallback has been taken for this invocation, do NOT retry the graph query for any later step. The protocol forbids retry. Continue through Steps 2–5 using the JSON data.

If all three checks pass, set `render_source = "graph"` and proceed to Step 1c.

### Step 1c: Graph Query

With `render_source = "graph"`, shell out to `${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query` against `.cc-master/graph.kuzu/` to fetch the task and subtask rowsets. Each invocation runs one Cypher statement and returns JSON rows on stdout.

**Query A — Tasks:**

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu "MATCH (t:Task) RETURN t.id AS id, t.subject AS subject, t.status AS status, t.priority AS priority, t.source AS source, t.owner AS owner, t.competitor_insight_ids AS competitor_insight_ids, t.phase AS phase"
```

**Query B — Subtasks:**

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py query .cc-master/graph.kuzu "MATCH (s:Subtask) RETURN s.id AS id, s.parent_id AS parent_id, s.subject AS subject, s.status AS status, s.blocked_by AS blocked_by, s.wave AS wave"
```

Inspect each invocation's exit code. On exit code 4 (Cypher parse/runtime error), or exit codes 2 or 3, or any non-zero exit, or non-empty stderr → this is Check 3 failing mid-query: set `render_source = "JSON fallback"`, emit the one-warning line `Graph absent/stale — falling back to JSON read for kanban.json` if not already emitted this session, discard any partial rowset, and fall through to Step 2 using the JSON `tasks[]` array.

Query B's `blocked_by` array is the authoritative source of blocked-status markers for Subtasks; Task-level blocked relations come from `Task.blocked_by` in Query A if extended, otherwise from Query B for subtasks — no separate `BLOCKED_BY` edge traversal is needed for the board render at v1 scope.

Merge Queries A and B into a unified list matching the shape the existing render logic already consumes:

```
{
  id,
  subject,
  status,
  owner,
  description: "",
  blocked_by,
  metadata: {
    source,
    priority,
    parent_id,
    wave,
    phase,
    competitor_insight_ids,
  }
}
```

Task rows from Query A have `parent_id = null`; Subtask rows from Query B have their parent id populated — this is how downstream classification and subtask-rollup logic already distinguishes parents from children. Populate `description` as an empty string at this stage; it is only needed for `--detail` view and is merged in during Step 4.

### Step 2: Classify Tasks Into Columns

Map each task (from the graph rowset produced by Step 1c OR the JSON fallback `tasks[]` list — both are normalized into the same shape before this step runs) into one of four columns based on status and metadata:

| Column | Condition |
|--------|-----------|
| **Backlog** | status = `pending` AND no `blocked_by` AND no owner |
| **In Progress** | status = `in_progress` |
| **Review** | status = `in_progress` AND metadata.phase = `qa` (or task subject contains "review"/"QA") |
| **Done** | status = `completed` |

Tasks with `blocked_by` that are still pending go into **Backlog** but are marked as blocked.

### Step 3: Read Metadata

Each task (from the graph rowset produced by Step 1c OR the JSON fallback `tasks[]` list) already carries the fields the render needs — in graph mode they come from Task/Subtask node properties, in JSON mode they come from the `task` record and its `metadata` subobject. After the Step 1c normalization, both sources expose the same shape to this step. Required fields:
- `subject` — the display title (truncate to column width)
- `owner` — show as `@owner-name` if assigned
- `description` — human-readable text. Populated directly in JSON-fallback mode; populated via the hybrid JSON merge described in Step 4's Detail View when running in graph mode. Empty string at Step 3 for default/compact/filter views in graph mode — these views never render `description` and do not need it.
- `blocked_by` — array of blocking task IDs; mark blocked tasks with a lock indicator
- `metadata.source` — for source badge display
- `metadata.priority` — for priority prefix display
- `metadata.competitor_insight_ids` — if present and non-empty, show `[C]` badge

### Step 4: Render the Board

**Default view — compact columns:**

Use box-drawing characters. Four columns. Tasks listed vertically within each column.

```
┌──────────────────┬──────────────────┬──────────────────┬──────────────────┐
│   Backlog (3)    │ In Progress (2)  │   Review (1)     │    Done (4)      │
├──────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ * Add dark mode  │ ! Fix auth bug   │ * Update API [R] │ * Setup CI       │
│   [R]            │   @agent-1       │   @qa            │ - Add tests      │
│ - Add i18n [R]   │ * Refactor DB    │                  │ . Fix typos      │
│ . Mobile [M]     │   @agent-2       │                  │ - Add logging    │
└──────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

**Rendering rules:**

Priority prefix (first character of task line):
- `!` = critical
- `*` = high
- `-` = normal (default when no priority set)
- `.` = low

Source badge (shown on next line or after title if space permits):
- `[R]` = from roadmap
- `[M]` = manual
- `[I]` = from insights
- `[C]` = competitor-informed (shown alongside source badge, not replacing it)
- `[Q]` = from qa-ui-review
- `[D]` = from doc-review
- `[G]` = from gap-check
- `[T]` = from trace
- `[A]` = from align-check
- `[P]` = from perf-audit
- `[B]` = from debug
- No badge if source unknown

A task can have multiple badges — e.g., `[R][C]` means "from roadmap, competitor-informed". The `[C]` badge is shown whenever `competitor_insight_ids` is present and non-empty in the task metadata.

Owner (shown below task title when assigned):
- `@agent-name` — truncate name to fit column

Blocked indicator:
- Prepend `🔒` (or `[B]` if no emoji) before blocked task titles

**Column width calculation:**
- Each column gets equal share of available width
- Minimum column width: 16 characters
- Task titles truncate with `...` if they exceed column width minus 2 (for padding)
- If a column is empty, still show the header with count (0)

**Building the board string:**

1. Calculate column width: `floor(available_width / 4)` — use 18 as default if you can't detect terminal width
2. Build the top border: `┌` + `─` repeated + `┬` between columns + `┐`
3. Build header row: column names centered with counts
4. Build separator: `├` + `─` + `┼` between columns + `┤`
5. Build task rows: pad each column to the height of the tallest column (empty cells get spaces)
6. Build bottom border: `└` + `─` + `┴` between columns + `┘`

Output the complete board as a single formatted text block.

### Step 5: Summary Line

After the board, print a one-line summary:

```
Total: <n> tasks | <backlog> backlog | <active> active | <review> review | <done> done
```

On the next line, print a render-source indicator reflecting the value of `render_source` set in Steps 1b/1c. Exactly one of:

```
Rendered from: graph
```

or:

```
Rendered from: JSON fallback
```

If arguments were provided, print next-action hints:

```
Hint: /cc-master:kanban-add to add tasks | /cc-master:spec <id> to spec a backlog task
```

### Step 6: Emit Graph Output Indicator

As the last line of the primary summary (before any chain-point prompt), print exactly ONE of these three strings based on the pre-query check outcomes from Step 1b:

- `Graph: fresh` — all three pre-query checks passed and the Cypher result was consumed.
- `Graph: stale — fell back to JSON` — Check 2 hash mismatch for at least one dependent artifact (worst-state-wins per `prompts/graph-read-protocol.md § Output Indicator`).
- `Graph: absent — fell back to JSON` — Check 1 failed (directory missing or unreadable).

If the skill errored during pre-query checks before classification, default to `Graph: absent — fell back to JSON`. Do NOT omit the indicator. Do NOT duplicate it per artifact — one line at the bottom of the primary summary block.

## Argument Handling

The skill may be invoked with arguments. Parse them from the ARGUMENTS string:

- **No arguments** — render the full board (default)
- **`--detail`** — render expanded list view instead of columns (see below)
- **`--compact`** — render single-line summary only
- **`--filter backlog|progress|review|done`** — show only one column

### Detail View (`--detail`)

**Hybrid data-source model for `--detail`:** when the render source is `graph`, the detail view runs a hybrid merge — Query A and Query B from Step 1c supply the task list, statuses, priorities, sources, owners, phases, and `competitor_insight_ids`; `.cc-master/kanban.json` is then read ONCE and its `tasks[]` array is keyed by `id` to merge in `description` text (and, for competitor-informed tasks, the `Market Evidence` block parsed out of the description). This is NOT a fallback — descriptions are intentionally not stored in the v1 graph schema — so the one-warning-per-session line is NOT emitted for this case. The `render_source` value stays `graph`. If the render source is already `JSON fallback`, the description is already present on each task record and no second read is required.

When `--detail` is passed, render as a grouped list with full descriptions:

```
## Backlog (3)

  #1 Add dark mode                          P:high     [R][C]
     Implement dark/light theme toggle with system preference detection
     Evidence: [critical] "Eye strain complaints across competitors" — G2 reviews (widespread)
     Evidence: [high] "No dark mode despite modern UI" — Reddit r/saas (common)
     Blocked by: #5 Setup CI

  #2 Add i18n support                       P:normal   [R]
     Internationalization with react-i18next

  #3 Mobile responsive                      P:low      [M]
     Responsive breakpoints for tablet and phone

## In Progress (2)

  #5 Fix auth bug                           P:critical @agent-1
     JWT token refresh failing on expired sessions
     Subtasks: 2/4 complete

  #7 Refactor DB layer                      P:high     @agent-2
     Migrate from raw SQL to query builder
     Subtasks: 0/3 complete

## Review (1)

  #8 Update REST API                        P:high     @qa
     Add pagination to list endpoints

## Done (4)

  #10 Setup CI pipeline                     completed
  #11 Add unit tests                        completed
  #12 Fix typos in docs                     completed
  #13 Add structured logging                completed
```

In detail view:
- Show task ID (from kanban.json), full subject, priority, source badge(s), and owner
- Show first line of description below the title
- For competitor-informed tasks (`[C]` badge), show evidence lines below the description:
  - Parse the task description for text between `Market Evidence:` and `Acceptance Criteria:` headers
  - Display each evidence line prefixed with `Evidence:` and indented to align with the description
  - Show up to 3 evidence lines; if more exist, append `+ N more`
  - **Defensive parsing:** If the delimiters are missing, malformed, or yield zero parseable lines, skip the evidence display for that task rather than rendering corrupt content
- For in-progress tasks, show subtask completion if subtasks exist (filter kanban.json tasks where `metadata.parent_id == task.id`, count completed vs total)
- For blocked tasks, show what blocks them
- For done tasks, just show "completed"

Example with competitor evidence:
```
## Backlog (3)

  #1 Add dark mode                          P:high     [R][C]
     Implement dark/light theme toggle with system preference detection
     Evidence: [critical] "Eye strain complaints across competitors" — G2 reviews (widespread)
     Evidence: [high] "No dark mode despite modern UI" — Reddit r/saas (common)
     Blocked by: #5 Setup CI

  #4 Add real-time sync                     P:high     [R][C]
     Real-time data synchronization using WebSockets
     Evidence: [critical] "Sync delays frustrating power users" — ProductHunt reviews (widespread)
     Evidence: [high] "Competitors sync instantly, ours lags 30s" — internal surveys (common)
     + 2 more
```

### Compact View (`--compact`)

Single line:

```
Kanban: 3 backlog | 2 active | 1 review | 4 done (10 total)
```

## What NOT To Do

- Do not modify any tasks — this skill is read-only
- Do not create tasks — that's kanban-add's job
- Do not use CC's TaskCreate, TaskGet, TaskList, or TaskUpdate tools — read exclusively from `.cc-master/kanban.json`
- Do not suggest actions unless printing the hint line
- Do not render more than 20 tasks per column — truncate with "+ N more" if exceeded
- Do not write to the graph — this skill is read-only. Only `cc-master:index` writes to the graph.
