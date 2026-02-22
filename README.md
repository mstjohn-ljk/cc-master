# CC-Master

Autonomous project management for Claude Code. Roadmap generation, kanban task tracking, codebase insights, implementation, and QA validation — all TUI/CLI-native.

CC-Master is a Claude Code plugin that adds 11 composable skills forming a complete development pipeline: understand your codebase, plan features, track work on a text kanban board, implement in isolated worktrees, and validate with automated QA loops.

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
/cc-master:discover  →  discovery.json
                              │
/cc-master:roadmap   →  roadmap.json
                              │
/cc-master:kanban-add → TaskCreate (from roadmap, insights, or manual)
                              │
/cc-master:kanban    →  text kanban board
                              │
/cc-master:spec      →  subtasks with dependencies
                              │
/cc-master:build     →  implementation in isolated worktree
                              │
/cc-master:qa-loop   →  qa-review ↔ qa-fix until passing
                              │
/cc-master:complete  →  merge, update kanban, optional PR
```

Each skill is standalone — run any skill independently or chain them for the full pipeline.

### Understanding

**`/cc-master:discover`** — Deep codebase analysis. Traces actual execution paths, reads implementations, identifies patterns and gaps. Produces `.cc-master/discovery.json`.

Not a file scanner. Reads the actual auth middleware to tell you it's JWE + HMAC, not "uses JWT" because it found a keyword.

### Planning

**`/cc-master:roadmap`** — Strategic feature generation from project understanding. MoSCoW prioritization, complexity/impact assessment, dependency-ordered phases. Produces `.cc-master/roadmap.json`.

**`/cc-master:insights`** — Codebase Q&A with task extraction. Ask questions, get deep answers, and actionable task suggestions are surfaced automatically.

### Task Management

**`/cc-master:kanban`** — Text kanban board rendered with box-drawing characters.

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

Supports `--detail` (expanded list), `--compact` (one-line summary), and `--filter <column>`.

**`/cc-master:kanban-add`** — Add tasks from roadmap features (`--from-roadmap`), insights suggestions (`--from-insights`), or manually.

### Implementation

**`/cc-master:spec`** — Structured specification with files to modify, acceptance criteria, and subtask breakdown with dependency ordering.

**`/cc-master:build`** — Implements in an isolated git worktree. Groups subtasks into dependency waves and dispatches parallel agents for independent work.

### Quality Assurance

**`/cc-master:qa-review`** — Scored validation against spec and acceptance criteria. Checks functional correctness, code quality, security, and test coverage. Produces a structured pass/fail report.

**`/cc-master:qa-fix`** — Triages review findings (real issue / false positive / pre-existing) and applies targeted fixes.

**`/cc-master:qa-loop`** — Orchestrates review → fix → re-review, looping until all gates pass (score >= 90, zero critical/high findings) or max 5 iterations.

### Completion

**`/cc-master:complete`** — Merges worktree back after QA passes, updates kanban status, updates roadmap feature status, optionally creates a PR with `--pr`.

## State Directory

CC-Master stores project-level state in `.cc-master/` at the project root:

```
.cc-master/
├── discovery.json           # Deep project understanding
├── roadmap.json             # Strategic feature roadmap
├── specs/                   # Per-task implementation specs
│   ├── <task-id>.md
│   └── <task-id>-review.json
├── insights/
│   ├── sessions.json        # Q&A session log
│   └── pending-suggestions.json
└── worktrees/               # Isolated git worktrees for builds
```

Add `.cc-master/` to your `.gitignore`.

## Pipeline Pattern

Skills compose through JSON artifacts:

- `discover` writes `discovery.json` → `roadmap` reads it
- `roadmap` writes `roadmap.json` → `kanban-add` reads it
- `kanban-add` creates CC tasks → `kanban` renders them
- `spec` writes spec files → `build` reads them
- `build` produces code → `qa-review` validates it
- `qa-fix` fixes findings → `qa-review` re-validates
- `complete` merges after QA passes

Each skill works standalone. You can `kanban-add` manual tasks without a roadmap, or run `qa-review` on any code without the full pipeline.

## MCP Server Integration

Skills optionally leverage MCP servers for enhanced capabilities:

| MCP Server | Used By | Purpose |
|------------|---------|---------|
| Context7 | discover, insights, spec, qa-review | Live framework documentation |
| Puppeteer | qa-review, qa-loop | Browser-based E2E validation |
| Linear / GitHub | roadmap | Import existing issues as features |
| Sequential Thinking | spec, qa-review | Structured multi-step reasoning |

All MCP integrations are optional — skills degrade gracefully without them.

## Full Pipeline Example

```bash
# 1. Understand the codebase
/cc-master:discover

# 2. Generate a feature roadmap
/cc-master:roadmap

# 3. Add features to the kanban
/cc-master:kanban-add --from-roadmap

# 4. See the board
/cc-master:kanban

# 5. Spec out a task
/cc-master:spec 3

# 6. Build it
/cc-master:build 3

# 7. Run QA until clean
/cc-master:qa-loop 3

# 8. Merge and close
/cc-master:complete 3 --pr
```

## License

MIT
