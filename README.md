# CC-Master

Autonomous project management for Claude Code. Roadmap generation, kanban task tracking, codebase insights, implementation, and QA validation — all TUI/CLI-native.

CC-Master is a Claude Code plugin that adds 35 composable skills forming a complete development pipeline: understand your codebase, analyze competitors, plan features, track work on a text kanban board, implement in isolated worktrees, and validate with automated QA loops.

## Install

Run these inside a Claude Code session (not your shell):

```
/plugin marketplace add mstjohn-ljk/cc-master
/plugin install cc-master@mstjohn-ljk-cc-master
```

Or install from a local clone:

```bash
git clone git@github.com:mstjohn-ljk/cc-master.git
```

Then inside Claude Code:

```
/plugin marketplace add ./cc-master
/plugin install cc-master@cc-master
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
/cc-master:kanban-add   →  kanban.json (from roadmap, insights, or manual)
                                │
/cc-master:kanban       →  text kanban board
                                │
/cc-master:spec         →  subtasks with dependencies
                                │
/cc-master:build        →  implementation in isolated worktree
                                │
/cc-master:qa-loop      →  qa-review ↔ qa-fix until passing
                                │
/cc-master:qa-ui-review →  browser E2E testing, creates tasks for findings (optional)
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

### Skill Reference

Skills are organized by phase. See `docs/skills/` for full documentation on every skill.

| Phase | Skills |
|-------|--------|
| [Understanding](docs/skills/understanding.md) | `discover`, `trace`, `insights`, `overview` |
| [Planning](docs/skills/planning.md) | `competitors`, `roadmap`, `research` |
| Task Management | `kanban`, `kanban-add` |
| [Implementation](docs/skills/implementation.md) | `spec`, `build`, `scaffold`, `debug`, `hotfix`, `test-gen` |
| [Quality](docs/skills/quality.md) | `qa-review`, `qa-fix`, `qa-loop`, `qa-ui-review`, `smoke-test`, `stub-hunt`, `api-payload-audit`, `config-audit`, `config-sync`, `align-check`, `gap-check`, `api-contract`, `doc-review`, `perf-audit` |
| [Completion & Docs](docs/skills/completion.md) | `complete`, `pr-review`, `release-docs`, `dev-guide`, `user-guide`, `openapi-docs` |

---

### Understanding

**`/cc-master:discover`** — Deep codebase analysis. Traces actual execution paths, reads implementations, identifies patterns and gaps. Produces `.cc-master/discovery.json`.

Not a file scanner. Reads the actual auth middleware to tell you it's JWE + HMAC, not "uses JWT" because it found a keyword.

```
Usage:  /cc-master:discover [--auto] [--update]
Output: .cc-master/discovery.json
Chains: → roadmap (prompted or auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain point prompt, continue to roadmap automatically |
| `--update` | Incremental refresh — re-traces only modules changed since last run |

**`/cc-master:trace`** — Single-feature depth tracing. Follows the complete execution path for one feature from entry point to leaf, detects bugs and risks at each node, creates kanban tasks for findings.

Narrower and faster than discover — one feature at full depth.

```
Usage:  /cc-master:trace <task-id>
        /cc-master:trace "feature name"
        /cc-master:trace src/routes/checkout.ts:handleCheckout [--depth <1-20>]
Output: .cc-master/traces/<slug>.md
```

---

### Planning

**`/cc-master:competitors`** — Competitor analysis via web search. Identifies 3-5 competitors, extracts user pain points from reviews and forums, maps market gaps. Produces `.cc-master/competitor_analysis.json`. Optional — the pipeline works without it.

```
Usage:  /cc-master:competitors [--auto]
Output: .cc-master/competitor_analysis.json
Chains: → roadmap (prompted or auto)
```

**`/cc-master:roadmap`** — Strategic feature generation from project understanding. MoSCoW prioritization, complexity/impact assessment, dependency-ordered phases. When competitor data is available, features are enriched with user stories, linked to market evidence, and given priority boosts based on pain point severity.

```
Usage:  /cc-master:roadmap [--auto] [--competitors]
Output: .cc-master/roadmap.json
Chains: → kanban-add (prompted or auto)
```

**`/cc-master:insights`** — Codebase Q&A with task extraction. Ask questions, get deep answers, and actionable task suggestions are surfaced automatically.

```
Usage:  /cc-master:insights <question>
Output: .cc-master/insights/sessions.json, .cc-master/insights/pending-suggestions.json
```

**`/cc-master:overview`** — Stakeholder-ready project report synthesized from pipeline artifacts. Three-act narrative: What We Have / What The Market Expects / What We're Building.

```
Usage:  /cc-master:overview [--technical] [--output <dir>] [--title <string>]
Output: .cc-master/reports/overview-<timestamp>.md
```

**`/cc-master:research`** — Deep web research for software development topics. Decomposes questions into parallel search angles, synthesizes sources with citations.

```
Usage:  /cc-master:research <question>
Output: .cc-master/research/<slug>.md
```

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

**`/cc-master:kanban-add`** — Add tasks from roadmap features, insights suggestions, or manually.

```
Usage:  /cc-master:kanban-add [--from-roadmap | --from-insights | <title>]
```

---

### Implementation

**`/cc-master:spec`** — Structured specification with files to modify, acceptance criteria, and subtask breakdown with dependency ordering.

```
Usage:  /cc-master:spec <id> [--auto]
        /cc-master:spec 3,5,7 | /cc-master:spec 3-7 | /cc-master:spec --all
Output: .cc-master/specs/<task-id>.md
Chains: → build (prompted or auto)
```

**`/cc-master:build`** — Implements in an isolated git worktree. Groups subtasks into dependency waves, dispatches parallel agents. Enforces production quality — no TODOs, no stubs, no mock data. Agents apply [deep trace verification](docs/deep-trace-verification.md) before marking subtasks complete. On success, automatically updates `discovery.json` with new routes/services/models and marks linked roadmap features as delivered.

```
Usage:  /cc-master:build <id> [--auto]
        /cc-master:build 3,5,7 | /cc-master:build 3-7 | /cc-master:build --all
Output: .cc-master/worktrees/<task-slug>/
Chains: → qa-loop (prompted or auto)
```

**`/cc-master:scaffold`** — Bootstrap a new project from scratch with structure, tests, and CI.

```
Usage:  /cc-master:scaffold [--stack <name>] [--auto]
Chains: → discover → roadmap (prompted or auto)
```

**`/cc-master:debug`** — Bug investigation and fix. Traces root cause, implements minimal fix, writes regression test, runs targeted QA. Works on current branch.

```
Usage:  /cc-master:debug "<bug description>" | "<stack trace>" | file:function
```

**`/cc-master:hotfix`** — Production emergency response. Hotfix branch, abbreviated investigation, minimal fix, fast QA, tagged PR.

```
Usage:  /cc-master:hotfix "<description>" [--version patch|minor] [--backport <branch>]
```

**`/cc-master:test-gen`** — Generate comprehensive tests for existing code following the project's exact test patterns. No new frameworks introduced.

```
Usage:  /cc-master:test-gen <file|glob|directory> [--runner <framework>] [--coverage]
```

---

### Quality Assurance

**`/cc-master:qa-review`** — Scored validation against spec and acceptance criteria. Applies [deep trace verification](docs/deep-trace-verification.md) to follow each criterion to an actual leaf. Checks functional correctness, code quality, security, test coverage, and production readiness.

```
Usage:  /cc-master:qa-review <task-id>
Output: .cc-master/specs/<task-id>-review.json
```

Pass threshold: score ≥ 90, zero unmet criteria, zero critical/high findings.

**`/cc-master:qa-fix`** — Triages review findings and applies targeted fixes.

```
Usage:  /cc-master:qa-fix <task-id>
Input:  .cc-master/specs/<task-id>-review.json (must exist)
```

**`/cc-master:qa-loop`** — Orchestrates review → fix → re-review until passing or max 5 iterations.

```
Usage:  /cc-master:qa-loop <id> [--auto] [--no-chain]
        /cc-master:qa-loop 3,5,7
Chains: → complete (prompted or auto, unless --no-chain)
```

**`/cc-master:qa-ui-review`** — End-to-end UI testing via Playwright. Goes beyond "does it render" to verify that every form, modal, and action actually works end-to-end. Includes API health monitoring, cross-page consistency checks, runtime config validation, and empty-state testing. Requires Playwright MCP server.

```
Usage:  /cc-master:qa-ui-review <url> [<task-id>] [--spec <id>] [--auth-env <file>] [--flows <list>]
Output: .cc-master/ui-reviews/<review-id>-review.json + screenshots/
```

Testing layers:
- **API Health Gate** — intercepts all fetch/XHR calls, flags 4xx/5xx responses, timeouts, and empty responses
- **Action Testing** — submits every form and modal with test data, verifies both API response and UI state update
- **Cross-Page Consistency** — detects when the same API endpoint returns different results on different pages
- **Runtime Config** — catches `"undefined"`, `"CHANGE_ME"`, `"TODO"`, and other stub phrases rendered in the UI
- **Error Path Testing** — verifies empty states exist with working CTAs (not just blank pages)
- Plus: accessibility, responsive design, security headers, and UX pattern checks

Pass threshold: score ≥ 80, zero critical findings.

**`/cc-master:smoke-test`** — Post-deploy browser smoke test. Visits every discoverable route, intercepts all API calls, flags failures. Fast pass (2-3 minutes), not a full QA review.

```
Usage:  /cc-master:smoke-test <url> [--user <name> --pass <pw>] [--cookie <name=value>]
Output: .cc-master/smoke-tests/<run-id>-report.json
```

**`/cc-master:stub-hunt`** — Live runtime stub and mock data detection. Opens the running app in a browser, navigates every page, detects placeholder content and developer artifacts visible to real users.

```
Usage:  /cc-master:stub-hunt <url> [--user <name> --pass <pw>] [--cookie <name=value>]
Output: .cc-master/stub-hunt/<run-id>-report.json
```

**`/cc-master:api-payload-audit`** — Statically verify that every frontend API call sends all fields the backend requires. Catches "missing required parameter" bugs before deploy. No OpenAPI spec or running app needed.

```
Usage:  /cc-master:api-payload-audit [--scope frontend|backend|both]
Output: .cc-master/payload-audit/<timestamp>-report.json
```

**`/cc-master:config-audit`** — Verify that every env var, secret, and config value referenced in code exists in the target environment configuration. Detect config drift between dev and prod.

```
Usage:  /cc-master:config-audit [--env prod|dev|staging|all]
Output: .cc-master/config-audit/<timestamp>-report.json
```

**`/cc-master:config-sync`** — Compare infrastructure configs across environments. Flags divergences in reverse proxy routes, security headers, CORS, TLS, and rate limiting.

```
Usage:  /cc-master:config-sync
Output: .cc-master/config-sync/<timestamp>-report.json
```

**`/cc-master:align-check`** — Three-way alignment: original task → spec → code. Catches when a spec accurately describes code that does the wrong thing.

```
Usage:  /cc-master:align-check <task-id> [--auto]
Output: .cc-master/specs/<task-id>-align.json
```

**`/cc-master:gap-check`** — Pipeline gap detector. Finds everything forgotten between planning and code: unspec'd features, uncovered criteria, incomplete subtasks, missing tests.

```
Usage:  /cc-master:gap-check <task-id> | --all | --roadmap
Output: .cc-master/gap-check-<timestamp>.json
```

**`/cc-master:api-contract`** — Frontend/backend contract verification from source code. No OpenAPI spec required. Traces through proxy layers. Optional auto-fix and live runtime verification.

```
Usage:  /cc-master:api-contract [--scope frontend|backend|both] [--fix] [--live <url>]
Output: .cc-master/api-contracts/<timestamp>-contract-report.json
```

**`/cc-master:doc-review`** — Documentation accuracy validation. Cross-references docs against actual code.

**`/cc-master:perf-audit`** — N+1 detection, unbounded query analysis, hot path identification.

---

### Completion & Documentation

**`/cc-master:complete`** — Creates a pull request (default) or merges to main after QA passes. Never merges without explicit `--merge`.

```
Usage:  /cc-master:complete <id> [--pr] [--merge] [--target <branch>] [--auto]
        /cc-master:complete 3,5,7
```

**`/cc-master:pr-review`** — Review incoming pull requests. Applies quality gates, produces GitHub-formatted output, optionally posts via `gh` CLI.

**`/cc-master:release-docs`** — Generate release notes and CHANGELOG entries from completed tasks and git history.

**`/cc-master:dev-guide`** — Developer documentation for contributors: build system, tests, CI, extension points.

**`/cc-master:user-guide`** — User-facing documentation adapted to the project type.

**`/cc-master:openapi-docs`** — Generate OpenAPI 3.1 specs from codebase analysis. Multi-framework support.

---

## Deep Trace Verification

Build and QA agents are required to trace every acceptance criterion to a **leaf** — the actual point where data is read, written, sent, or received — before reporting it complete.

The five-point checklist:
1. Entry point is reachable (route registered, command wired, handler bound)
2. Each layer calls the next correctly (read the callee — don't assume it works)
3. Referenced resources exist (config keys, templates, env vars, file paths)
4. Data shape is consistent end-to-end (name, type, unit at every boundary)
5. Error and absence paths are handled (not silently swallowed)

See [docs/deep-trace-verification.md](docs/deep-trace-verification.md) for the full methodology.

---

## State Directory

CC-Master stores project-level state in `.cc-master/` at the project root:

```
.cc-master/
├── discovery.json              # Deep project understanding
├── competitor_analysis.json    # Competitor pain points and market gaps
├── roadmap.json                # Strategic feature roadmap
├── kanban.json                 # Persisted task board (survives context clears)
├── specs/                      # Per-task specs and review reports
│   ├── <task-id>.md
│   ├── <task-id>-review.json
│   └── <task-id>-align.json
├── traces/                     # Single-feature trace outputs
│   └── <slug>.md
├── insights/
│   ├── sessions.json
│   └── pending-suggestions.json
├── reports/                    # Overview and release reports
├── api-contracts/              # API contract reports
├── research/                   # Research outputs
├── ui-reviews/                 # UI testing reports and screenshots
└── worktrees/                  # Isolated git worktrees for builds
    └── batch-*/.batch-manifest.json
```

Add `.cc-master/` to your `.gitignore`.

## Pipeline Pattern

Skills compose through JSON artifacts:

- `discover` writes `discovery.json` → `roadmap` reads it
- `competitors` writes `competitor_analysis.json` → `roadmap` reads it (optional)
- `roadmap` writes `roadmap.json` → `kanban-add` reads it
- `kanban-add` resolves competitor evidence, creates tasks → `kanban` renders them
- `spec` writes spec files → `build` reads them
- `build` produces code in worktrees, updates `discovery.json` and marks roadmap features delivered → `qa-review` validates it with deep trace verification
- `qa-fix` fixes findings → `qa-review` re-validates
- `complete` creates a PR (or merges with explicit `--merge`) after QA passes

Each skill works standalone.

## MCP Server Integration

| MCP Server | Used By | Type | Purpose |
|------------|---------|------|---------|
| Playwright | qa-ui-review | required | Browser-based E2E UI testing |
| Context7 | competitors | recommended | Live documentation for market research |
| Sequential Thinking | qa-ui-review | recommended | Structured multi-step reasoning |

## Full Pipeline Examples

### Single task (interactive)

```bash
/cc-master:discover
/cc-master:competitors        # optional
/cc-master:roadmap
/cc-master:kanban-add --from-roadmap
/cc-master:kanban
/cc-master:spec 3
/cc-master:build 3
/cc-master:qa-loop 3
/cc-master:complete 3
```

### Single task (fully autonomous)

```bash
/cc-master:discover --auto
# After selecting a task:
/cc-master:spec 3 --auto
# chains: spec → build → qa-loop → complete (creates PR)
```

### Batch (multiple tasks, autonomous)

```bash
/cc-master:spec 3,5,7
/cc-master:build 3,5,7
# chains: build all → qa-loop each → complete batch (single PR)
```

### Verification only

```bash
# Check alignment between task, spec, and code
/cc-master:align-check 3

# Find everything forgotten in the pipeline
/cc-master:gap-check --all

# Verify frontend/backend contract
/cc-master:api-contract --fix

# Audit for N+1 queries and performance issues
/cc-master:perf-audit --focus db
```

## License

MIT
