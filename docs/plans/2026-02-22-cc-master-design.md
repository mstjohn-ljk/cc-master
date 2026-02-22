# CC-Master: Claude Code Global Skills/Hooks Framework

**Date:** 2026-02-22
**Status:** Approved design

## Overview

CC-Master is a standalone Claude Code plugin (namespace `cc-master:`) that provides autonomous project management capabilities — roadmap generation, codebase insights, kanban task tracking, implementation, and QA validation — as TUI/CLI-native experiences.

Inspired by Auto-Claude's roadmap, insights, and kanban features, CC-Master reimplements them as composable Claude Code skills that share state through a **pipeline pattern**. No GUI — everything runs in the terminal via slash commands and renders as formatted text.

## Architecture

```
State Layer:     .cc-master/          <- JSON artifacts (roadmap.json, discovery.json)
Task Layer:      CC TaskCreate/List   <- kanban backing store (native CC tasks)
Skill Layer:     cc-master:*          <- composable slash commands
Hook Layer:      hooks/               <- automatic triggers (post-task QA gates)
MCP Layer:       Context7, Puppeteer  <- optional enhanced capabilities
```

### Data Flow

```
/cc-master:discover  ->  discovery.json
                              |
/cc-master:roadmap   ->  roadmap.json
                              |
/cc-master:kanban-add -> CC TaskCreate (from roadmap features OR manual)
                              |
/cc-master:kanban    ->  reads TaskList -> renders text columns
                              |
/cc-master:spec      ->  breaks task into subtasks with acceptance criteria
                              |
/cc-master:build     ->  implements in worktree, agent teams for parallel subtasks
                              |
/cc-master:qa-loop   ->  orchestrates qa-review <-> qa-fix until clean
                              |
/cc-master:complete  ->  merges worktree, updates kanban, optionally creates PR
```

### Pipeline Pattern

Skills produce JSON artifacts that other skills consume. Each skill is standalone — you can run `/cc-master:discover` without ever running `/cc-master:roadmap`. You can `/cc-master:kanban-add` a manual task without any roadmap. But when chained, each skill enriches the next.

### State Directory

```
.cc-master/
├── discovery.json        # Deep project understanding
├── roadmap.json          # Strategic feature roadmap with phases
├── project-index.json    # Codebase structure index (lightweight, auto-generated)
├── specs/
│   └── <task-id>.md      # Per-task spec documents
└── insights/
    ├── sessions.json     # Q&A session log
    └── pending-suggestions.json  # Unactioned task suggestions
```

---

## Skill Inventory (11 Skills)

### Skill 1: `cc-master:discover` — Deep Codebase Understanding

**Phase:** Understanding
**Purpose:** Analyze the codebase deeply — trace actual execution paths, not surface-level keyword scanning.

#### Methodology

The skill instructs Claude to work like a senior engineer joining the team on day one — read the code, trace the flows, understand what's real.

**Phase 1: Structure scan** (fast, sets up the map)
- Directory layout, languages, frameworks
- Entry points (main files, route definitions, CLI commands)
- Dependency files — as a starting point, not a conclusion

**Phase 2: Execution path tracing** (the deep part)
- Start at entry points, follow actual code paths
- Auth: read the middleware chain, trace token creation -> validation -> refresh. What crypto? What headers? What's the actual flow?
- Data: read models/migrations, trace how data flows from API -> service -> DB. What ORM? What patterns?
- API: read route definitions AND their handlers. What do they actually do?

**Phase 3: Pattern identification** (understanding, not listing)
- Error handling: global handler? per-route? both?
- Test suite: unit? integration? what runner? what mocking approach?
- Config: env vars? config files? secrets manager? what resolves what?
- Architectural patterns: traced from actual code, not inferred from folder names

**Phase 4: Gap and debt analysis** (informed by real understanding)
- Dead code / unused dependencies (verified, not guessed)
- Missing error handling on real code paths
- Security patterns inconsistent across the codebase
- Test coverage gaps based on what's actually tested vs what exists

**Critical rule:** Every claim in discovery.json must be backed by actual file paths and traced execution. "Auth: JWE + HMAC" because we read `src/middleware/auth.ts` and traced the chain, not because grep found a keyword.

#### Output Schema

```json
{
  "project_name": "my-app",
  "project_type": "web-api",
  "tech_stack": {
    "languages": ["TypeScript", "Python"],
    "frameworks": ["Express", "FastAPI"],
    "verified_by": "read actual source, not just package files"
  },
  "architecture": {
    "pattern": "modular monolith with service layer",
    "entry_points": [
      {"path": "src/server.ts", "purpose": "HTTP server bootstrap, mounts routers"}
    ],
    "key_flows": {
      "authentication": {
        "summary": "JWE encrypted tokens + HMAC request signing",
        "implementation": "src/middleware/auth.ts -> src/services/crypto.ts",
        "details": "Tokens are JWE (A256GCM) not JWT. Every request also carries X-Signature header with HMAC-SHA256 of request body using per-user secret key.",
        "token_lifecycle": "Login returns JWE access + refresh. Refresh endpoint re-issues both."
      },
      "data_access": {
        "summary": "Repository pattern with raw SQL via pg driver",
        "implementation": "src/repositories/*.ts",
        "details": "No ORM. Parameterized queries. Connection pool via pg.Pool."
      }
    }
  },
  "current_state": {
    "maturity": "production-mvp",
    "existing_features": [
      {"name": "User auth", "completeness": "full", "location": "src/routes/auth/"}
    ],
    "technical_debt": [
      {"issue": "Error handling inconsistent", "evidence": "src/routes/auth/ uses global handler, src/routes/teams/ has inline try/catch", "severity": "medium"}
    ],
    "test_coverage": {
      "approach": "Vitest + supertest for integration",
      "gaps": ["No tests for HMAC signing middleware"]
    }
  },
  "target_audience": {
    "primary": "Developer teams needing X",
    "pain_points": [],
    "goals": []
  },
  "product_vision": {
    "one_liner": "",
    "problem_statement": "",
    "value_proposition": ""
  },
  "constraints": {"technical": [], "dependencies": []},
  "created_at": "ISO-8601"
}
```

#### Pipeline I/O
- **Reads:** codebase (via Read, Glob, Grep + Explore agent for deep tracing)
- **Writes:** `.cc-master/discovery.json`
- **Consumed by:** `cc-master:roadmap`, `cc-master:insights`, `cc-master:spec`

#### MCP Servers
- **Recommended:** Context7 (for framework documentation lookup during analysis)

---

### Skill 2: `cc-master:roadmap` — Strategic Feature Generation

**Phase:** Planning
**Purpose:** Generate a prioritized feature roadmap from project understanding and codebase analysis.

#### Methodology

1. Reads `.cc-master/discovery.json` for project understanding
2. If no discovery exists, runs lightweight inline discovery first
3. Brainstorms features from pain points, gaps, goals, and technical debt
4. Applies MoSCoW prioritization (must/should/could/won't)
5. Assesses complexity and impact for each feature
6. Organizes features into dependency-ordered phases
7. Writes `roadmap.json` and prints formatted summary

#### Output Schema

```json
{
  "vision": "One-line product vision",
  "phases": [
    {
      "id": "phase-1",
      "name": "Foundation",
      "description": "Core infrastructure and auth",
      "order": 1,
      "features": ["feat-1", "feat-2"]
    }
  ],
  "features": [
    {
      "id": "feat-1",
      "title": "Add user authentication",
      "description": "Full auth flow with registration, login, token refresh",
      "rationale": "Blocking requirement for all user-facing features",
      "priority": "must",
      "complexity": "high",
      "impact": "high",
      "phase_id": "phase-1",
      "dependencies": [],
      "acceptance_criteria": [
        "User can register with email/password",
        "Login returns encrypted tokens",
        "Token refresh works without re-login"
      ],
      "status": "idea"
    }
  ],
  "metadata": {
    "created_at": "ISO-8601",
    "updated_at": "ISO-8601",
    "prioritization_framework": "moscow"
  }
}
```

#### Terminal Output

```
Roadmap: my-app - "Simplify team collaboration for distributed teams"

Phase 1: Foundation (3 features)
  MUST   [high] Add user authentication
  MUST   [med]  Setup CI/CD pipeline
  SHOULD [low]  Add structured logging

Phase 2: Core Experience (4 features)
  MUST   [high] Real-time collaboration
  SHOULD [med]  Notification system
  COULD  [low]  Dark mode support
  COULD  [low]  Mobile responsive layout

Use /cc-master:kanban-add --from-roadmap to convert features to tasks.
```

#### Pipeline I/O
- **Reads:** `.cc-master/discovery.json`, codebase
- **Writes:** `.cc-master/roadmap.json`
- **Consumed by:** `cc-master:kanban-add`, `cc-master:insights`

#### MCP Servers
- **Recommended:** Linear, GitHub (import existing issues as roadmap input)

---

### Skill 3: `cc-master:kanban` — Text Board Rendering

**Phase:** Visibility
**Purpose:** Render CC's native TaskList as a compact column-based text kanban board.

#### Column Mapping

```
CC Task Status    ->  Kanban Column
-----------------------------------------
pending            ->  Backlog
in_progress        ->  In Progress
completed          ->  Done
(metadata.phase    ->  Review (when phase=qa)
 = "qa")
```

#### Rendering

Default compact column view using box-drawing characters:

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

**Legend:**
- Priority prefix: `!` critical, `*` high, `-` normal, `.` low
- Source badge: `[R]` roadmap, `[M]` manual, `[I]` insights
- Owner: `@agent-name` when assigned

#### Flags

- `--detail` — expanded list view with descriptions and progress bars
- `--filter <status>` — show single column only
- `--compact` — minimal single-line summary: `Kanban: 3 backlog | 2 active | 1 review | 4 done`

#### Detail View

```
## In Progress (2)

  #5 Fix auth bug                        P:critical  @agent-1
     JWT token refresh failing on expired sessions
     Phase: coding [████████░░] 80%

  #7 Refactor DB layer                   P:high      @agent-2
     Migrate from raw SQL to query builder
     Phase: planning [███░░░░░░░] 30%
```

#### Pipeline I/O
- **Reads:** CC TaskList (native), task metadata for display enrichment
- **Writes:** terminal output only (read-only skill)

---

### Skill 4: `cc-master:kanban-add` — Task Injection

**Phase:** Task creation
**Purpose:** Bridge between roadmap features, insights suggestions, and manual tasks into the kanban.

#### Three Modes

**1. From roadmap:** `/cc-master:kanban-add --from-roadmap`
- Reads `.cc-master/roadmap.json`
- Presents features interactively: "Which features to add as tasks?"
- Creates CC tasks via TaskCreate with metadata linking back to feature_id
- Updates roadmap.json feature status from `idea` -> `planned`

**2. From insights:** automatic when `/cc-master:insights` generates task suggestions
- Insights skill outputs structured suggestions
- User confirms which to add
- Creates CC tasks with `source: "insights"` metadata

**3. Manual:** `/cc-master:kanban-add "Task title" --priority high`
- Direct task creation
- Prompts for description if not provided
- Sets `source: "manual"` metadata

#### Task Metadata Schema

Every task created through kanban-add carries consistent metadata:

```json
{
  "source": "roadmap|insights|manual",
  "priority": "critical|high|normal|low",
  "feature_id": "feat-1",
  "complexity": "low|medium|high",
  "acceptance_criteria": ["..."],
  "phase": "pending"
}
```

#### Pipeline I/O
- **Reads:** `.cc-master/roadmap.json`, insights suggestions, user input
- **Writes:** CC TaskCreate, updates `.cc-master/roadmap.json` feature status

---

### Skill 5: `cc-master:insights` — Codebase Q&A with Task Extraction

**Phase:** Research
**Purpose:** Structured codebase Q&A that surfaces actionable tasks from analysis.

#### What It Adds Over Native CC

CC already explores codebases. This skill adds:

1. **Project awareness** — loads discovery.json and roadmap.json as context so answers are informed by existing project understanding
2. **Structured task extraction** — when the AI identifies actionable work during Q&A, it outputs structured task suggestions with title, description, priority, complexity, and category
3. **Session logging** — persists Q&A pairs to `.cc-master/insights/sessions.json` as a project knowledge log

#### Task Suggestion Format

When the skill identifies actionable work, it outputs:
```
TASK SUGGESTION:
  Title: Add rate limiting to auth endpoints
  Description: Login and refresh endpoints have no rate limiting...
  Priority: high
  Complexity: medium
  Category: security
```

These can be piped to `/cc-master:kanban-add` for task creation.

#### Session Persistence

Lightweight log (not full conversation replay):
```json
{
  "sessions": [
    {
      "id": "session-1708617600000",
      "timestamp": "2026-02-22T...",
      "question": "How does authentication work?",
      "answer_summary": "JWE + HMAC request signing via middleware chain...",
      "suggested_tasks": [
        {"title": "Add rate limiting", "priority": "high", "category": "security"}
      ],
      "files_explored": ["src/middleware/auth.ts", "src/services/crypto.ts"]
    }
  ]
}
```

#### Invocation
- `/cc-master:insights "How does auth work?"` — single question
- `/cc-master:insights` — interactive mode

#### Pipeline I/O
- **Reads:** `.cc-master/discovery.json`, `.cc-master/roadmap.json`, codebase
- **Writes:** `.cc-master/insights/sessions.json`, `.cc-master/insights/pending-suggestions.json`
- **Consumed by:** `cc-master:kanban-add`

#### MCP Servers
- **Recommended:** Context7 (framework documentation during analysis)

---

### Skill 6: `cc-master:spec` — Structured Specification Creation

**Phase:** Specification
**Purpose:** Take a kanban task and produce a detailed implementation specification with subtasks.

#### Methodology

1. Reads the task from CC TaskList (by ID or selection)
2. Loads `.cc-master/discovery.json` for project context
3. Explores relevant code areas based on task description
4. Generates structured spec:
   - Requirements with acceptance criteria
   - Files to modify/create
   - Verification steps (commands to run, behavior to check)
   - Risk assessment
5. Breaks into ordered subtasks with dependencies
6. Writes spec to `.cc-master/specs/<task-id>.md`
7. Creates subtasks via TaskCreate with `addBlockedBy` dependencies
8. Updates parent task description via TaskUpdate

#### Spec Output Structure

Written to `.cc-master/specs/<task-id>.md`:
```markdown
# Spec: Add user authentication

## Requirements
- User registration with email/password
- Login returns JWE encrypted access + refresh tokens
- HMAC request signing on all authenticated endpoints

## Acceptance Criteria
1. POST /auth/register creates user, returns 201
2. POST /auth/login returns JWE tokens
3. Protected routes reject unsigned requests with 401

## Files to Modify
- src/routes/auth/register.ts (create)
- src/routes/auth/login.ts (create)
- src/middleware/auth.ts (create)
- src/services/crypto.ts (create)
- tests/auth.test.ts (create)

## Subtasks
1. Create crypto service (JWE + HMAC utilities)
2. Create auth middleware chain
3. Implement registration endpoint
4. Implement login endpoint
5. Add integration tests

## Verification
- `npm test` passes
- Manual: POST /auth/register with valid body -> 201
- Manual: POST /auth/login -> returns encrypted tokens
```

#### Pipeline I/O
- **Reads:** CC TaskList, `.cc-master/discovery.json`, codebase
- **Writes:** `.cc-master/specs/<task-id>.md`, CC TaskCreate (subtasks), CC TaskUpdate
- **Consumed by:** `cc-master:build`

#### MCP Servers
- **Recommended:** Context7 (API docs for frameworks being used), Sequential Thinking (complex spec decomposition)

---

### Skill 7: `cc-master:build` — Implementation

**Phase:** Coding
**Purpose:** Implement a spec'd task. Creates isolated worktree, iterates through subtasks, spawns agent teams for parallel work.

#### Methodology

1. Reads task spec from `.cc-master/specs/<task-id>.md` and subtasks from TaskList
2. Creates a git worktree for isolation (`git worktree add`)
3. Iterates through subtasks in dependency order:
   - For independent subtasks: spawn parallel agents via CC's Task tool
   - For dependent subtasks: execute sequentially
   - Each subtask agent gets: the subtask description, files to modify, project discovery context, and acceptance criteria
4. After each subtask completes, updates TaskUpdate status
5. After all subtasks complete, updates parent task phase to "qa"
6. Kanban reflects progress in real-time via TaskUpdate

#### Parallel Execution

When subtasks have no dependencies on each other, they are dispatched as parallel agents:
```
Subtask 1: Create crypto service     -> Agent A (no deps)
Subtask 2: Create auth middleware     -> Agent B (no deps)
Subtask 3: Implement registration    -> Agent C (blocked by 1, 2)
Subtask 4: Implement login           -> Agent D (blocked by 1, 2)
Subtask 5: Add integration tests     -> Agent E (blocked by 3, 4)

Wave 1: Agent A + Agent B (parallel)
Wave 2: Agent C + Agent D (parallel, after wave 1)
Wave 3: Agent E (after wave 2)
```

#### Pipeline I/O
- **Reads:** `.cc-master/specs/<task-id>.md`, CC TaskList (subtasks), `.cc-master/discovery.json`
- **Writes:** code changes in worktree, CC TaskUpdate (subtask status)
- **Consumed by:** `cc-master:qa-loop`

---

### Skill 8: `cc-master:qa-review` — Quality Validation

**Phase:** QA - Review
**Purpose:** Review implementation against spec and acceptance criteria. Produce structured pass/fail report.

#### Methodology

1. Reads the spec from `.cc-master/specs/<task-id>.md`
2. Reads acceptance criteria from the task
3. Reviews all changed files in the worktree (via `git diff`)
4. Runs verification commands defined in the spec
5. Checks for:
   - Functional correctness (does it meet acceptance criteria?)
   - Code quality (patterns consistent with project conventions from discovery.json?)
   - Security (OWASP top 10, injection, auth bypass)
   - Test coverage (are new paths tested?)
6. Produces structured review report

#### Review Report Schema

```json
{
  "task_id": "...",
  "status": "pass|fail",
  "score": 85,
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "category": "security|quality|correctness|coverage",
      "file": "src/middleware/auth.ts",
      "line": 42,
      "description": "Missing rate limiting on login endpoint",
      "suggestion": "Add express-rate-limit middleware before auth handler"
    }
  ],
  "tests_run": {"passed": 12, "failed": 1, "skipped": 0},
  "acceptance_criteria_met": [
    {"criterion": "POST /auth/register -> 201", "met": true},
    {"criterion": "Protected routes reject unsigned requests", "met": false, "reason": "Returns 500 instead of 401"}
  ],
  "iteration": 1,
  "timestamp": "ISO-8601"
}
```

#### Pipeline I/O
- **Reads:** `.cc-master/specs/<task-id>.md`, worktree changes, `.cc-master/discovery.json`
- **Writes:** review report (passed to qa-loop orchestrator)
- **Consumed by:** `cc-master:qa-loop`, `cc-master:qa-fix`

#### MCP Servers
- **Required for E2E:** Puppeteer (browser-based validation)
- **Recommended:** Context7 (verify implementations against current framework docs)

---

### Skill 9: `cc-master:qa-fix` — Remediation

**Phase:** QA - Fix
**Purpose:** Take QA review findings and apply fixes. Re-run verification to confirm.

#### Methodology

1. Reads the review report from `cc-master:qa-review`
2. Triages findings:
   - Real issue in changed code -> fix
   - False positive -> dismiss with explanation
   - Pre-existing issue < 10 lines -> fix in-band
   - Pre-existing issue widespread -> note for follow-up
3. Applies fixes to each real finding
4. Re-runs verification commands to confirm fixes
5. Returns updated code state for re-review

#### Pipeline I/O
- **Reads:** review report, spec, codebase
- **Writes:** code fixes in worktree
- **Consumed by:** `cc-master:qa-loop` (triggers re-review)

---

### Skill 10: `cc-master:qa-loop` — QA Orchestration

**Phase:** QA - Orchestration
**Purpose:** Chain qa-review and qa-fix in a loop until all gates pass 100%.

#### Methodology

```
iteration = 0
MAX_ITERATIONS = 5

loop:
  1. Run cc-master:qa-review
  2. If status == "pass" and score == 100:
     -> Update task status to "review" (human review)
     -> Break
  3. If status == "fail":
     -> Run cc-master:qa-fix with findings
     -> iteration++
     -> If iteration >= MAX_ITERATIONS:
        -> Escalate to human review with report
        -> Break
     -> Loop back to step 1
```

**Escalation:** After MAX_ITERATIONS, the task moves to human review with all accumulated findings attached. The human can approve, reject, or provide guidance for another round.

**Gate integration:** This skill also runs code-reviewer and security-auditor agents (from existing CC agent types) as additional gates. All gates must pass before moving to completion.

#### Pipeline I/O
- **Reads:** orchestrates qa-review and qa-fix
- **Writes:** CC TaskUpdate (status transitions), final QA report

#### MCP Servers
- Inherits from qa-review: Puppeteer, Context7, Sequential Thinking

---

### Skill 11: `cc-master:complete` — Task Completion

**Phase:** Completion
**Purpose:** Merge worktree, update kanban, optionally create PR.

#### Methodology

1. Verifies QA has passed (reads final QA report)
2. Merges worktree back to the working branch:
   - `git worktree` merge strategy
   - Conflict resolution if needed
3. Updates task status via TaskUpdate -> `completed`
4. Updates roadmap feature status if task was sourced from roadmap
5. Optionally creates PR via `gh pr create`
6. Cleans up worktree
7. Renders updated kanban board

#### Flags
- `--pr` — create a pull request instead of direct merge
- `--pr-target <branch>` — PR target branch (default: develop or main)

#### Pipeline I/O
- **Reads:** QA report, worktree state, `.cc-master/roadmap.json`
- **Writes:** git merge/PR, CC TaskUpdate, roadmap.json feature status update

---

## MCP Server Integration

Skills can leverage MCP servers for capabilities beyond CC's built-in tools. Skills degrade gracefully when MCP servers aren't configured.

### MCP-Enhanced Skills

| Skill | MCP Servers | Purpose |
|-------|-------------|---------|
| `cc-master:discover` | Context7 | Framework documentation during analysis |
| `cc-master:roadmap` | Linear, GitHub | Import existing issues as roadmap input |
| `cc-master:insights` | Context7 | Live docs for detected frameworks |
| `cc-master:spec` | Context7, Sequential Thinking | API docs + structured reasoning |
| `cc-master:qa-review` | Context7, Puppeteer | Docs verification + browser E2E testing |
| `cc-master:qa-loop` | (inherits from qa-review) | Full QA gate suite |

### Common MCP Server Profiles

- **Context7** — Live documentation for any framework/library. Skills use it to look up current API patterns rather than relying on training data.
- **Puppeteer** — Browser automation for E2E QA validation. Screenshots, interaction testing, visual regression.
- **Linear/GitHub** — Issue tracking integration. Import issues as roadmap features, create issues from kanban tasks, sync status.
- **Sequential Thinking** — Structured multi-step reasoning for complex analysis (QA review logic, spec decomposition).

### Graceful Degradation

Each skill's prompt documents required and optional MCP servers. When an MCP server isn't available:
- Context7 missing: skill uses its own knowledge (may be less current)
- Puppeteer missing: QA skips browser tests, relies on command-line test runners
- Linear/GitHub missing: roadmap operates standalone without issue import

---

## Hook Integration

### Post-Task Completion Hook

- **Trigger:** Agent marks a task `completed` via TaskUpdate
- **Action:** Automatically runs `cc-master:qa-loop` on the completed work
- **Outcome:** Updates kanban status based on gate results (-> review if issues, -> done if all pass)

### Session End Hook (Insight Extraction)

- **Trigger:** CC session ends
- **Action:** Extracts learnings from the conversation into CC persistent memory
- **Outcome:** If actionable tasks were discussed but not created, logs them to `.cc-master/insights/pending-suggestions.json`

---

## Full Pipeline Example

A complete end-to-end workflow:

```
1. /cc-master:discover
   -> Deeply analyzes codebase, produces discovery.json

2. /cc-master:roadmap
   -> Reads discovery, generates prioritized feature roadmap

3. /cc-master:kanban-add --from-roadmap
   -> User selects "Add user authentication" -> CC task created

4. /cc-master:kanban
   -> Shows task in Backlog column

5. /cc-master:spec (on the auth task)
   -> Generates detailed spec, creates 5 subtasks with dependencies

6. /cc-master:build (on the auth task)
   -> Creates worktree, dispatches agents in waves
   -> Wave 1: crypto service + auth middleware (parallel)
   -> Wave 2: register + login endpoints (parallel)
   -> Wave 3: integration tests

7. /cc-master:qa-loop
   -> Round 1: qa-review finds missing rate limiting (score: 78%)
   -> qa-fix applies rate limiting
   -> Round 2: qa-review finds test gap (score: 92%)
   -> qa-fix adds missing test
   -> Round 3: qa-review passes (score: 100%)

8. /cc-master:complete --pr
   -> Merges worktree, creates PR, updates kanban to Done
   -> Roadmap feature status: idea -> planned -> done
```

---

## Implementation Priority

Recommended build order (each skill is independently useful):

1. **`cc-master:discover`** — foundation, all other skills benefit from it
2. **`cc-master:kanban` + `cc-master:kanban-add`** — immediate visual value, manual task management works standalone
3. **`cc-master:roadmap`** — strategic planning, feeds kanban-add
4. **`cc-master:spec`** — turns tasks into implementable plans
5. **`cc-master:build`** — the coder, most complex skill
6. **`cc-master:qa-review` + `cc-master:qa-fix` + `cc-master:qa-loop`** — quality gates
7. **`cc-master:complete`** — closes the loop
8. **`cc-master:insights`** — research tool, lower priority since CC already does this natively

---

## Repository Structure

```
cc-master/
├── CLAUDE.md                 # Project instructions for CC
├── skills/                   # Skill source files
│   ├── discover/
│   │   └── skill.md
│   ├── roadmap/
│   │   └── skill.md
│   ├── kanban/
│   │   └── skill.md
│   ├── kanban-add/
│   │   └── skill.md
│   ├── insights/
│   │   └── skill.md
│   ├── spec/
│   │   └── skill.md
│   ├── build/
│   │   └── skill.md
│   ├── qa-review/
│   │   └── skill.md
│   ├── qa-fix/
│   │   └── skill.md
│   ├── qa-loop/
│   │   └── skill.md
│   └── complete/
│       └── skill.md
├── prompts/                  # Reusable prompt fragments
│   ├── discovery-system.md
│   ├── roadmap-features.md
│   ├── qa-reviewer.md
│   └── qa-fixer.md
├── hooks/                    # CC hooks
│   ├── post-task-qa/
│   └── session-insights/
├── docs/
│   └── plans/
│       └── 2026-02-22-cc-master-design.md  # This document
└── scripts/
    └── install.sh            # Symlinks skills + hooks to ~/.claude/
```
