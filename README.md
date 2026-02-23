# CC-Master

Autonomous project management for Claude Code. Roadmap generation, kanban task tracking, codebase insights, implementation, and QA validation — all TUI/CLI-native.

CC-Master is a Claude Code plugin that adds 13 composable skills forming a complete development pipeline: understand your codebase, analyze competitors, plan features, track work on a text kanban board, implement in isolated worktrees, and validate with automated QA loops.

## Install

```bash
claude plugin add --marketplace https://github.com/mstjohn-ljk/cc-master
claude plugin install cc-master
```

Or install directly from a local clone:

```bash
git clone git@github.com:mstjohn-ljk/cc-master.git
claude plugin add /path/to/cc-master
```

## Skills

### Pipeline Overview

```
/cc-master:discover     →  discovery.json
                                │
/cc-master:competitors  →  competitor_analysis.json (optional)
                                │
/cc-master:roadmap      →  roadmap.json (with competitor evidence when available)
                                │
/cc-master:kanban-add   →  TaskCreate (from roadmap, insights, or manual)
                                │
/cc-master:kanban       →  text kanban board
                                │
/cc-master:spec         →  subtasks with dependencies
                                │
/cc-master:build        →  implementation in isolated worktree
                                │
/cc-master:qa-loop      →  qa-review ↔ qa-fix until passing
                                │
/cc-master:complete     →  PR (default) or merge with --merge, update kanban
```

Each skill is standalone — run any skill independently or chain them for the full pipeline.

### Auto-Chain

Skills chain automatically when `--auto` is passed. Two chain sequences exist:

**Planning chain** (stops for task selection):

```
discover --auto → roadmap --auto → kanban-add (imports features, then stops)
```

**Implementation chain** (runs to completion):

```
build --auto → qa-loop --auto → complete --auto (creates PR)
```

The planning chain ends at kanban-add — after features are imported, you select a task and start the implementation chain with `spec --auto` or `build --auto`. At each chain point without `--auto`, the user is prompted to continue, go auto, or stop.

**Safety:** `--auto` never merges directly to main. The complete skill defaults to creating a pull request in auto mode. Direct merge requires explicit `--merge`.

---

### Understanding

**`/cc-master:discover`** — Deep codebase analysis. Traces actual execution paths, reads implementations, identifies patterns and gaps. Produces `.cc-master/discovery.json`.

Not a file scanner. Reads the actual auth middleware to tell you it's JWE + HMAC, not "uses JWT" because it found a keyword.

```
Usage:  /cc-master:discover [--auto]
Output: .cc-master/discovery.json
Chains: → roadmap (prompted or auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain point prompt, continue to roadmap automatically |

---

### Planning

**`/cc-master:competitors`** — Competitor analysis via web search. Identifies 3-5 competitors, extracts user pain points from reviews and forums, maps market gaps. Produces `.cc-master/competitor_analysis.json`. Optional — the pipeline works without it.

```
Usage:  /cc-master:competitors [--auto]
Output: .cc-master/competitor_analysis.json
Chains: → roadmap (prompted or auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain point prompt, continue to roadmap automatically |

**`/cc-master:roadmap`** — Strategic feature generation from project understanding. MoSCoW prioritization, complexity/impact assessment, dependency-ordered phases. When competitor data is available, features are enriched with user stories, linked to market evidence, and given priority boosts based on pain point severity. Produces `.cc-master/roadmap.json`.

```
Usage:  /cc-master:roadmap [--auto] [--competitors]
Output: .cc-master/roadmap.json
Chains: → kanban-add (prompted or auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain point prompt, continue to kanban-add automatically |
| `--competitors` | Run competitor analysis inline before generating the roadmap |

**`/cc-master:insights`** — Codebase Q&A with task extraction. Ask questions, get deep answers, and actionable task suggestions are surfaced automatically.

```
Usage:  /cc-master:insights <question>
Output: .cc-master/insights/sessions.json, .cc-master/insights/pending-suggestions.json
```

No flags. Interactive Q&A — just ask your question as the argument.

---

### Task Management

**`/cc-master:kanban`** — Text kanban board rendered with box-drawing characters. Tasks show source badges (`[R]` roadmap, `[M]` manual, `[I]` insights, `[Q]` qa-ui-review) and `[C]` for competitor-informed tasks.

```
┌──────────────────┬──────────────────┬──────────────────┬──────────────────┐
│   Backlog (3)    │ In Progress (2)  │   Review (1)     │    Done (4)      │
├──────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ * Add dark mode  │ ! Fix auth bug   │ * Update API [R] │ * Setup CI       │
│   [R][C]         │   @agent-1       │   @qa            │ - Add tests      │
│ - Add i18n [R]   │ * Refactor DB    │                  │ . Fix typos      │
│ . Mobile [M]     │   @agent-2       │                  │ - Add logging    │
└──────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

```
Usage:  /cc-master:kanban [--detail] [--compact] [--filter <column>]
```

| Flag | Effect |
|------|--------|
| `--detail` | Expanded list view with full descriptions and competitor evidence |
| `--compact` | Single-line summary: `Kanban: 3 backlog \| 2 active \| 1 review \| 4 done` |
| `--filter <column>` | Show only one column: `backlog`, `progress`, `review`, or `done` |

Source badges: `[R]` roadmap, `[M]` manual, `[I]` insights, `[Q]` qa-ui-review, `[C]` competitor-informed. Priority prefixes: `!` critical, `*` high, `-` normal, `.` low.

**`/cc-master:kanban-add`** — Add tasks from roadmap features, insights suggestions, or manually. When importing from a competitor-enriched roadmap, resolves pain points and market gaps into human-readable evidence embedded in task descriptions.

```
Usage:  /cc-master:kanban-add [--from-roadmap | --from-insights | <title>]
```

| Flag / Argument | Effect |
|-----------------|--------|
| `--from-roadmap` | Import features from roadmap.json. Prompts to select which features. |
| `--from-insights` | Import suggestions from insights sessions |
| `<title>` | Create a manual task with the given title |

When importing from a competitor-enriched roadmap, tasks get `[C]` badges and embedded market evidence.

---

### Implementation

**`/cc-master:spec`** — Structured specification with files to modify, acceptance criteria, and subtask breakdown with dependency ordering. Auto-runs discover if `discovery.json` is missing.

```
Usage:  /cc-master:spec <id> [--auto]
        /cc-master:spec 3,5,7          # comma-separated
        /cc-master:spec 3-7            # range (max 20)
        /cc-master:spec --all          # all unspec'd tasks (max 10)
        /cc-master:spec "description"  # unlinked spec
Output: .cc-master/specs/<task-id>.md
Chains: → build (prompted or auto)
```

| Flag / Format | Effect |
|---------------|--------|
| `--auto` | Skip chain point prompt, continue to build automatically |
| `--all` | Spec all kanban tasks that don't have specs yet (max 10) |
| `3,5,7` | Comma-separated task IDs for batch spec creation |
| `3-7` | Range of task IDs (max 20, must be ascending) |

**`/cc-master:build`** — Implements in an isolated git worktree. Groups subtasks into dependency waves and dispatches parallel agents for independent work. Enforces production quality — no TODOs, no stubs, no mock data.

```
Usage:  /cc-master:build <id> [--auto]
        /cc-master:build 3,5,7         # comma-separated (shared worktree)
        /cc-master:build 3-7           # range (max 20)
        /cc-master:build --all         # all spec'd tasks (max 10)
Output: Code in .cc-master/worktrees/<task-slug>/ or .cc-master/worktrees/batch-<ids>/
Chains: → qa-loop (prompted or auto)
```

| Flag / Format | Effect |
|---------------|--------|
| `--auto` | Skip chain point prompt, continue to qa-loop automatically |
| `--all` | Build all tasks that have specs (max 10) |
| `3,5,7` | Comma-separated IDs — shared worktree, autonomous execution |
| `3-7` | Range of IDs — shared worktree, autonomous execution (max 20) |

Multi-task mode is always autonomous: build all → qa-loop each → complete as batch.

---

### Quality Assurance

**`/cc-master:qa-review`** — Scored validation against spec and acceptance criteria. Checks functional correctness, code quality, security, test coverage, and production readiness (no stubs, no mock data). Produces a structured pass/fail report.

```
Usage:  /cc-master:qa-review <task-id>
Output: .cc-master/specs/<task-id>-review.json
```

No flags. Pass threshold: score >= 90, zero unmet acceptance criteria, zero critical/high findings. Automatically locates the worktree for the task (batch or single-task).

**`/cc-master:qa-fix`** — Triages review findings (real issue / false positive / pre-existing) and applies targeted fixes. Reads the review report produced by qa-review.

```
Usage:  /cc-master:qa-fix <task-id>
Input:  .cc-master/specs/<task-id>-review.json (must exist — run qa-review first)
```

No flags. Classifies each finding before fixing: real issue, false positive, pre-existing small (fix in-band), pre-existing widespread (note for follow-up), or design decision (dismiss).

**`/cc-master:qa-loop`** — Orchestrates review -> fix -> re-review, looping until all gates pass or max 5 iterations. Tracks score progression and detects regressions.

```
Usage:  /cc-master:qa-loop <id> [--auto] [--no-chain]
        /cc-master:qa-loop 3,5,7       # comma-separated batch
Chains: → complete (prompted or auto, unless --no-chain)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain point prompt, continue to complete automatically |
| `--no-chain` | Do not chain to complete on pass. Used by build's batch pipeline. |
| `3,5,7` | Comma-separated IDs — processes each task sequentially |

---

### Completion

**`/cc-master:complete`** — Creates a pull request (default) or merges to main after QA passes. Updates kanban status and roadmap feature status. Never merges directly to main without explicit approval.

```
Usage:  /cc-master:complete <id> [--pr] [--merge] [--target <branch>] [--auto]
        /cc-master:complete 3,5,7      # comma-separated batch
```

| Flag | Effect |
|------|--------|
| `--pr` | Create a pull request (this is the default — flag is optional) |
| `--merge` | Merge directly to main (explicit override required) |
| `--target <branch>` | PR target branch (default: main) |
| `--auto` | Skip prompts. Defaults to PR. Honors `--merge` if explicitly passed alongside. |
| `3,5,7` | Comma-separated IDs — single PR or merge for the shared batch branch |

**Default behavior:**
- Without flags: asks the user (PR recommended, or merge)
- With `--auto`: creates a PR (never merges without explicit `--merge`)
- With `--merge`: merges directly to main (explicit user override — bypasses PR review)
- `--pr` and `--merge` together: rejected as conflicting

**Batch mode:** When completing multiple tasks from a shared worktree, commits once (first task), creates one PR or merge (last task), and updates each task's kanban status individually.

---

### UI Testing

**`/cc-master:qa-ui-review`** — End-to-end UI testing via Playwright browser automation. Exercises user flows, reviews look & feel, accessibility, responsive design, and client-side security against a running application. Creates kanban tasks for every finding with `[Q]` badges. Standalone — not part of the auto-chain pipeline.

```
Usage:  /cc-master:qa-ui-review <url> [<task-id>] [--spec <id>] [--auth-env <file>] [--flows <list>]
Output: .cc-master/ui-reviews/<review-id>-review.json
        .cc-master/ui-reviews/<review-id>/screenshots/
```

| Flag | Effect |
|------|--------|
| `<url>` | Required. The live URL to test (http/https). |
| `<task-id>` | Optional. Links the review to a kanban task. |
| `--spec <id>` | Load spec's acceptance criteria for targeted validation. |
| `--auth-env <file>` | Env file with credentials for authenticated flows (KEY=VALUE format). |
| `--flows <list>` | Comma-separated flow names to run. Default: all applicable. |

Available flows: `navigation`, `forms`, `auth`, `crud`, `responsive`, `error-handling`.

**Security notes:** Add auth-env files to `.gitignore` — never commit credentials. Credential values are used only for browser session login and are not written to review reports. When testing non-local environments, always use `https://` URLs.

Scoring: CRITICAL (-20), HIGH (-10), MEDIUM (-5), LOW (-2). Pass threshold: score >= 80 and zero critical findings. Categories: e2e, security, accessibility, responsive, ux, performance.

Requires Playwright MCP server.

---

## State Directory

CC-Master stores project-level state in `.cc-master/` at the project root:

```
.cc-master/
├── discovery.json              # Deep project understanding
├── competitor_analysis.json    # Competitor pain points and market gaps
├── roadmap.json                # Strategic feature roadmap
├── specs/                      # Per-task implementation specs
│   ├── <task-id>.md
│   └── <task-id>-review.json
├── insights/
│   ├── sessions.json           # Q&A session log
│   └── pending-suggestions.json
├── ui-reviews/                 # UI testing reports and screenshots
│   ├── <review-id>-review.json
│   └── <review-id>/
│       └── screenshots/
└── worktrees/                  # Isolated git worktrees for builds
    └── batch-*/.batch-manifest.json
```

Add `.cc-master/` to your `.gitignore`.

## Pipeline Pattern

Skills compose through JSON artifacts:

- `discover` writes `discovery.json` → `roadmap` reads it
- `competitors` writes `competitor_analysis.json` → `roadmap` reads it (optional)
- `roadmap` writes `roadmap.json` → `kanban-add` reads it
- `kanban-add` resolves competitor evidence, creates CC tasks → `kanban` renders them
- `spec` writes spec files → `build` reads them
- `build` produces code in worktrees → `qa-review` validates it
- `qa-fix` fixes findings → `qa-review` re-validates
- `complete` creates a PR (or merges with explicit `--merge`) after QA passes

Each skill works standalone. You can `kanban-add` manual tasks without a roadmap, or run `qa-review` on any code without the full pipeline.

## MCP Server Integration

Skills optionally leverage MCP servers for enhanced capabilities:

| MCP Server | Used By | Type | Purpose |
|------------|---------|------|---------|
| Playwright | qa-ui-review | required | Browser-based E2E UI testing |
| Context7 | competitors | recommended | Live documentation for market research |
| Sequential Thinking | qa-ui-review | recommended | Structured multi-step reasoning |

Skills marked `recommended` degrade gracefully without the MCP server — they use built-in tools as fallback. Skills marked `required` will not function without the server and will print an error message.

## Full Pipeline Examples

### Single task (interactive)

```bash
# 1. Understand the codebase
/cc-master:discover

# 2. (Optional) Analyze competitors
/cc-master:competitors

# 3. Generate a feature roadmap
/cc-master:roadmap

# 4. Add features to the kanban
/cc-master:kanban-add --from-roadmap

# 5. See the board
/cc-master:kanban

# 6. Spec out a task
/cc-master:spec 3

# 7. Build it
/cc-master:build 3

# 8. Run QA until clean
/cc-master:qa-loop 3

# 9. Create a PR (default) or merge
/cc-master:complete 3
```

### Single task (fully autonomous)

```bash
# Discover, plan, and add tasks — then stop for task selection
/cc-master:discover --auto

# After selecting a task, spec through completion
/cc-master:spec 3 --auto
# chains: spec → build → qa-loop → complete (creates PR)
```

### Batch (multiple tasks, autonomous)

```bash
# Spec multiple tasks
/cc-master:spec 3,5,7

# Build all — autonomous pipeline handles QA and PR creation
/cc-master:build 3,5,7
# chains: build all → qa-loop each → complete batch (single PR)
```

### Competitor-informed roadmap

```bash
# Discover + competitors + roadmap in one command
/cc-master:roadmap --competitors

# Or run competitors separately first
/cc-master:competitors
/cc-master:roadmap
```

### UI testing (standalone)

```bash
# Test a running application
/cc-master:qa-ui-review http://localhost:3000

# With spec validation and auth
/cc-master:qa-ui-review http://localhost:3000 3 --spec 3 --auth-env .env.test

# Only specific flows
/cc-master:qa-ui-review http://localhost:3000 --flows navigation,responsive
```

## License

MIT
