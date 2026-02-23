---
name: kanban
description: Render current tasks as a text-based kanban board. Reads from native TaskList and displays compact column view with box-drawing characters. Use anytime to see project status at a glance.
---

# cc-master:kanban — Text Kanban Board

Render the current task list as a visual kanban board in the terminal using box-drawing characters.

## Process

### Step 1: Read Task State

Call `TaskList` to get all current tasks. If no tasks exist, print:

```
No tasks found. Use /cc-master:kanban-add to create tasks.
```

And stop.

### Step 2: Classify Tasks Into Columns

Map each task into one of four columns based on status and metadata:

| Column | Condition |
|--------|-----------|
| **Backlog** | status = `pending` AND no `blockedBy` AND no owner |
| **In Progress** | status = `in_progress` |
| **Review** | status = `in_progress` AND metadata.phase = `qa` (or task subject contains "review"/"QA") |
| **Done** | status = `completed` |

Tasks with `blockedBy` that are still pending go into **Backlog** but are marked as blocked.

### Step 3: Read Metadata

For each task, use `TaskGet` to read full details including:
- `subject` — the display title (truncate to column width)
- `owner` — show as `@owner-name` if assigned
- `description` — parse for metadata JSON block if present
- `blockedBy` — mark blocked tasks with a lock indicator

Look for a metadata block in the task description (set by `cc-master:kanban-add`):
```
<!-- cc-master
{"source":"roadmap","priority":"high","feature_id":"feat-1"}
-->
```

If present, extract `source`, `priority`, and `competitor_insight_ids` for display badges. If `competitor_insight_ids` is present and non-empty, the task is competitor-informed.

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

If arguments were provided, print next-action hints:

```
Hint: /cc-master:kanban-add to add tasks | /cc-master:spec <id> to spec a backlog task
```

## Argument Handling

The skill may be invoked with arguments. Parse them from the ARGUMENTS string:

- **No arguments** — render the full board (default)
- **`--detail`** — render expanded list view instead of columns (see below)
- **`--compact`** — render single-line summary only
- **`--filter backlog|progress|review|done`** — show only one column

### Detail View (`--detail`)

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
- Show task ID (from TaskList), full subject, priority, source badge(s), and owner
- Show first line of description below the title
- For competitor-informed tasks (`[C]` badge), show evidence lines below the description:
  - Parse the task description for text between `Market Evidence:` and `Acceptance Criteria:` headers
  - Display each evidence line prefixed with `Evidence:` and indented to align with the description
  - Show up to 3 evidence lines; if more exist, append `+ N more`
  - **Defensive parsing:** If the delimiters are missing, malformed, or yield zero parseable lines, skip the evidence display for that task rather than rendering corrupt content
- For in-progress tasks, show subtask completion if subtasks exist (count completed vs total from blockedBy relationships)
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
- Do not read .cc-master/ files — kanban reads exclusively from CC's native TaskList
- Do not suggest actions unless printing the hint line
- Do not render more than 20 tasks per column — truncate with "+ N more" if exceeded
