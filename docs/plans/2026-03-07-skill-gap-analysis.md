# CC-Master Skill Gap Analysis — 2026-03-07

Developer-perspective analysis of missing workflows. Covers small-to-large projects, greenfield-to-existing codebases. No changes implemented yet — this document captures proposals for review and prioritization.

---

## Research Foundation

**Developer time allocation (IDC 2024, Rollbar, Cortex 2024 — 65K+ respondents):**

- Writing new code: **16% of dev time**
- Debugging / bug-fixing: **20–40% of dev time** (one study: 75% when including investigation + verification)
- Code review: **10–15% of dev time** (accelerating as AI-generated PRs increase)
- Security work: grew **8% → 13%** in a single year (IDC 2024, now #3 activity)
- Managing technical debt: **~33% of time** in existing codebases (Stripe/Codacy research)

**Greenfield challenges (Nimble, Naturaily, TheLinuxCode research):**
- High developer interdependency in initial sprints without existing patterns to follow
- Lengthy rework from lack of conventions — establish them early or pay later

**Brownfield challenges:**
- Lack of documentation / reverse-engineering overhead
- Low test coverage — every change risks silent regression
- Technical debt management consumes a third of dev time

**Key insight:** The current cc-master pipeline serves the 16% of time spent on feature development very well. The 84% remainder — debugging, reviews, maintenance, onboarding — is largely uncovered.

---

## Current Coverage Map

| Workflow phase | Skills | Status |
|---|---|---|
| Codebase onboarding | `discover`, `insights` | Strong |
| Feature planning | `roadmap`, `competitors`, `kanban*` | Strong |
| Specification | `spec` | Strong |
| Implementation | `build` | Strong |
| Feature QA | `qa-review`, `qa-fix`, `qa-loop`, `qa-ui-review` | Strong |
| Completion / PR | `complete` | Strong |
| Documentation | `dev-guide`, `user-guide`, `openapi-docs`, `doc-review`, `release-docs` | Strong |
| **Bug investigation & fix** | **Nothing** | **Total gap** |
| **Production hotfix** | **Nothing** | **Total gap** |
| **Greenfield bootstrap** | **Nothing** | **Total gap** |
| **Incoming PR review** | **Nothing** | **Total gap** |
| **Test generation for existing code** | **Nothing** | **Major gap** |
| Performance analysis | Partial — `qa-ui-review` touches Lighthouse incidentally | Gap |
| Security/dependency audit | Partial — `qa-review` catches issues reactively | Gap |

---

## Proposed New Skills

### 1. `debug` — Bug Investigation & Fix

**Priority: High**

**Gap filled:** 20–40% of dev time, zero current coverage.

The pipeline is entirely feature-oriented. Bugs have a fundamentally different workflow:
- The "spec" is the reported behavior vs actual behavior
- Investigation IS the planning phase — no roadmap step, no separate spec step
- Change surface is typically small; speed matters more than ceremony
- No worktree overhead warranted for single-file fixes

**Proposed workflow:**
1. Accept: bug description, error message, stack trace, or symptom
2. Reproduce: identify minimal reproduction steps from the description
3. Trace: follow the execution path from symptom to root cause (same depth as `discover`)
4. Assess blast radius: what else might be broken by the same issue?
5. Plan minimal targeted fix — explicitly NOT using a worktree unless complexity demands it
6. Implement the fix inline or in a lightweight branch
7. Write a regression test following the project's existing test patterns
8. Run targeted qa-review on changed files only
9. Chain to `complete` (PR) or optionally to `hotfix` for production issues

**Distinct from `build`:**
- No pre-existing spec required
- Investigation phase replaces spec/roadmap phases
- Works on current branch by default (no worktree)
- Regression test is the primary QA artifact

**Arguments:** `debug [--reproduce <steps>] [--file <path>] [--trace <entry-point>]`

---

### 2. `hotfix` — Production Emergency Response

**Priority: High**

**Gap filled:** Production emergencies need immediate action incompatible with the full pipeline ceremony.

Gitflow hotfix branching is a well-established industry pattern (Atlassian docs it explicitly). The workflow: branch from main, minimal targeted change, fast review, merge back to both main and develop/release.

**Proposed workflow:**
1. Accept: problem description + optional version tag
2. Validate: confirm this is truly production (warn if working on non-main branch)
3. Branch: create `hotfix/<slug>` from `main` directly (not a worktree — faster)
4. Investigate: trace root cause (abbreviated discover on affected modules only)
5. Fix: minimal change — reject scope creep explicitly
6. Fast QA: security + correctness only, skip coverage gap checks (time-sensitive)
7. PR: create PR tagged `[HOTFIX]`, include backport note to `develop`/release branch
8. Optionally bump patch version and tag

**Distinct from `debug`:**
- Specifically for production
- Carries version/release semantics
- Time-pressure constraint is explicit
- Always branches from main, never from a feature branch

**Arguments:** `hotfix [--version <patch|minor>] [--backport <branch>]`

---

### 3. `scaffold` — Greenfield Project Bootstrap

**Priority: High**

**Gap filled:** The entire cc-master pipeline assumes a project exists. Greenfield devs get zero value until they've manually set up enough structure for `discover` to read.

**Proposed workflow:**
1. Detect if the current directory is an empty/near-empty repo
2. Ask: project type (REST API, CLI tool, React SPA, Next.js app, library, microservice, monorepo)
3. Ask: stack (TypeScript/Node, Python/FastAPI, Go, Java/Spring, Rust — or detect from existing files)
4. Generate: idiomatic project structure for that stack following 2025 conventions
5. Wire: testing framework with at least one passing sample test
6. Wire: CI/CD scaffold (GitHub Actions — detect CI from existing config if any)
7. Write: `CLAUDE.md` with project-specific conventions (so all future cc-master skills work correctly)
8. Run: `discover` on the result to produce `discovery.json`
9. Chain: optionally to `roadmap`

**Why it matters:**
- Makes cc-master useful on day 0 for greenfield devs
- The conventions established here (test runner, error format, auth pattern) flow into all downstream skills

**Arguments:** `scaffold [--type <api|cli|spa|nextjs|library|monorepo>] [--stack <node|python|go|java|rust>] [--ci <github|gitlab|circleci>]`

---

### 4. `test-gen` — Test Generation for Existing Code

**Priority: Medium-High**

**Gap filled:** Brownfield projects have low test coverage — the primary driver of technical debt in existing codebases. `discover` surfaces test gaps but there's no way to close them without going through the full build pipeline (overkill for "write tests for this existing module").

**Proposed workflow:**
1. Accept: file paths, module names, or a directory
2. Read the implementation deeply (same depth as `discover` — trace actual logic, not just signatures)
3. Read existing tests to understand the project's testing patterns, mocking approach, test runner, assertion style
4. Generate: comprehensive tests covering happy paths, error paths, edge cases, boundary conditions
5. Verify: the generated tests actually pass before presenting them
6. Report: coverage delta — what percentage moved from the starting point

**Key constraint:** Must follow existing test patterns exactly. No new testing frameworks, no new mocking libraries. If the project uses Jest + supertest, the generated tests use Jest + supertest.

**Arguments:** `test-gen <path|pattern> [--runner <jest|pytest|go-test|junit>] [--coverage]`

---

### 5. `pr-review` — Incoming PR Review

**Priority: Medium-High**

**Gap filled:** Code review is 10–15% of dev time. cc-master currently only reviews your own implementations (`qa-review` is tightly coupled to worktrees and specs). No way to run cc-master against an incoming PR from another developer or agent.

**Proposed workflow:**
1. Accept: PR number (via `gh` CLI) or branch name
2. Diff: branch against base (usually main)
3. Load: any linked spec or GitHub issue if resolvable from PR description
4. Run: same quality gates as `qa-review` — correctness, security, pattern consistency, stub detection
5. Check: against spec acceptance criteria if available
6. Produce: review formatted as GitHub review comments (APPROVE / REQUEST_CHANGES / COMMENT)
7. Optionally: post directly via `gh pr review --body "..." --request-changes`

**Distinct from `qa-review`:**
- Works on any branch, no spec required
- Produces GitHub-formatted output
- No worktree assumption
- Designed for reviewing others' work, not your own

**Arguments:** `pr-review <pr-number|branch> [--post] [--spec <id>]`

---

### 6. `perf-audit` — Performance Analysis

**Priority: Medium**

**Gap filled:** "Application performance monitoring" is one of the top KTLO activities per IDC 2024. As projects scale, performance bottlenecks become critical. Currently there's no systematic performance analysis.

**Proposed workflow:**
1. Static analysis: detect N+1 queries, unbounded loops, synchronous blocking in async code, missing DB indexes
2. For web apps: Lighthouse via Playwright (Core Web Vitals — FCP, LCP, CLS, TTI)
3. For backend: identify hot paths from route definitions + DB query patterns
4. Optionally: accept a load profile (expected requests/sec) to contextualize findings
5. Produce: prioritized findings with estimated impact and fix suggestions
6. Create: kanban tasks for found issues (same pattern as `qa-ui-review`)

**Arguments:** `perf-audit [<url>] [--target <rps>] [--focus <backend|frontend|db>]`

---

## Proposed Enhancements to Existing Skills

### A. `spec` — Accept GitHub/Jira issue as input

**Rationale:** The most common real-world `spec` trigger is a ticket. Devs currently copy-paste issue descriptions manually.

**Enhancement:** `spec --from-issue <url>` — fetch the issue, extract title + body + labels, use as the requirement input. Strip to plain text before processing (no HTML). Support GitHub Issues natively; Jira via URL fetch.

---

### B. `build` — Lightweight `--inline` mode

**Rationale:** Full worktree + parallel agents is right for multi-file features. For 1–3 file changes (typical brownfield incremental fix), the overhead is disproportionate.

**Enhancement:** `build <id> --inline` skips worktree creation and works directly on the current branch. Subtask parallelism is also disabled in inline mode (single-agent execution). Suitable for small targeted changes where isolation overhead isn't justified.

---

### C. `discover` — `--update` flag for post-sprint refresh

**Rationale:** In long-running projects, `discover` runs from scratch and overwrites `discovery.json`. Devs in a sprint want to refresh understanding after a week of work without losing the baseline.

**Enhancement:** `discover --update` diffs current codebase state against the timestamp in `discovery.json` and only re-traces modules whose files have changed since the last run. Merges updated sections into the existing JSON, preserving unchanged sections.

---

### D. `roadmap` — `--bugs` mode for maintenance sprints

**Rationale:** The current roadmap generates feature roadmaps. Existing projects with technical debt need a "maintenance sprint" roadmap: what to fix, not what to build.

**Enhancement:** `roadmap --bugs` analyzes discovered issues, test gaps, TODOs/FIXMEs in the codebase, and security findings to generate a prioritized maintenance roadmap. Uses same MoSCoW framework but scoped to debt reduction rather than feature delivery.

---

### E. `complete` — Deploy hook integration

**Rationale:** After merging, most devs want to trigger a deployment. Currently `complete` stops at the PR. Adding an optional step closes the loop.

**Enhancement:** If `.cc-master/deploy.sh` exists (or `--deploy <script>` is passed), `complete` executes it after merge/PR creation and optionally polls a health check URL to verify the deploy succeeded. No-op if no deploy config present.

---

## Priority Matrix

| Proposal | Target dev | Research backing | Dev time covered | Priority |
|---|---|---|---|---|
| `debug` | All developers | 20–40% of dev time, zero coverage | Highest | ★★★ |
| `scaffold` | Small/greenfield | Unlocks cc-master for new projects entirely | Day 0 value | ★★★ |
| `hotfix` | All developers | Gitflow hotfix is industry standard | Production incidents | ★★★ |
| `spec --from-issue` | All developers | Removes #1 friction point for spec creation | QoL, high frequency | ★★ |
| `test-gen` | Brownfield/existing | 33% of brownfield time is tech debt | Debt reduction | ★★ |
| `pr-review` | Team/large projects | 10–15% of dev time | Code review | ★★ |
| `build --inline` | Small/brownfield | Reduces ceremony for small fixes | QoL, medium frequency | ★★ |
| `roadmap --bugs` | Brownfield | Maintenance sprints are real workflow | Planning | ★★ |
| `perf-audit` | Medium/large | #3 KTLO activity (IDC 2024) | Scaling bottlenecks | ★ |
| `discover --update` | Long-running projects | Keeps discovery fresh across sprints | Context freshness | ★ |
| `complete --deploy` | DevOps-oriented | Closes the deploy loop | Release workflow | ★ |

---

## The Three Biggest Gaps

Research most strongly supports these three as the highest ROI additions:

**1. `debug`** — The pipeline covers feature development beautifully but ignores the single activity consuming the most developer time. Every developer, every day, every project type.

**2. `scaffold`** — The pipeline is currently inaccessible to greenfield devs until they've done significant manual setup. Fixes cc-master's day-0 value problem for new projects.

**3. `hotfix`** — Production emergencies need a low-ceremony path with version semantics. The full `spec → build → qa-loop → complete` chain is incompatible with incident response urgency.

---

## Open Questions for Implementation

1. **`debug` vs `hotfix` boundary:** Should these be one skill with a `--production` flag, or two separate skills with different default behaviors? One skill is simpler; two skills are clearer in intent.

2. **`scaffold` stack coverage:** Which stacks to support at launch vs later? Suggest: TypeScript/Node and Python as tier 1 (highest usage), Go and Java as tier 2, others as tier 3.

3. **`pr-review` GitHub dependency:** Should this require `gh` CLI or work via raw git? Requiring `gh` is simpler but adds a dependency. Raw git diff works everywhere but loses issue/PR metadata.

4. **`test-gen` scope per invocation:** Should it process a single file or walk an entire directory? Single file is safer and easier to review; directory scan is more powerful but produces a lot of output.

5. **`build --inline` safety:** Inline mode skips worktree isolation. Should it require explicit confirmation ("This will modify files on your current branch directly. Continue?") to prevent accidents?
