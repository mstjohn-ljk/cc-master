# Quality Skills

Skills for validating, reviewing, and verifying implementations.

---

## `/cc-master:qa-review`

Scored validation against spec and acceptance criteria. Uses **deep trace verification** to follow each criterion to an actual leaf before marking it met. Checks functional correctness, code quality, security, test coverage, and production readiness.

```
Usage:  /cc-master:qa-review <task-id>
Output: .cc-master/specs/<task-id>-review.json
```

Pass threshold: score ≥ 90 AND zero unmet acceptance criteria AND zero critical/high findings.

See [deep trace verification](../deep-trace-verification.md) for the methodology used in Step 2 (Functional Correctness).

---

## `/cc-master:qa-fix`

Triages review findings (real issue / false positive / pre-existing) and applies targeted fixes. Reads the review report produced by qa-review.

```
Usage:  /cc-master:qa-fix <task-id>
Input:  .cc-master/specs/<task-id>-review.json (must exist — run qa-review first)
```

---

## `/cc-master:qa-loop`

Orchestrates review → fix → re-review, looping until all gates pass or max 5 iterations. Tracks score progression, detects regressions.

```
Usage:  /cc-master:qa-loop <id> [--auto] [--no-chain]
        /cc-master:qa-loop 3,5,7
Chains: → complete (prompted or --auto, unless --no-chain)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain prompt, continue to complete |
| `--no-chain` | Do not chain to complete. Used by build's batch pipeline. |
| `3,5,7` | Comma-separated IDs — processes each task sequentially |

---

## `/cc-master:qa-ui-review`

End-to-end UI testing via Playwright. Goes beyond rendering checks to verify that every interactive element actually works. Creates kanban tasks for every finding with `[Q]` badges. Requires Playwright MCP server.

```
Usage:  /cc-master:qa-ui-review <url> [<task-id>] [--spec <id>] [--auth-env <file>] [--flows <list>]
Output: .cc-master/ui-reviews/<review-id>-review.json
        .cc-master/ui-reviews/<review-id>/screenshots/
```

Available flows: `navigation`, `forms`, `auth`, `crud`, `responsive`, `error-handling`. Pass threshold: score ≥ 80 and zero critical findings.

**Testing layers (in execution order):**

| Step | Layer | What it catches |
|------|-------|-----------------|
| 3b | API Health Gate | 4xx/5xx responses, timeouts, empty responses on every page load |
| 4 | User Flow Testing | Navigation, form submission, auth, CRUD, error handling |
| 4b | Action Testing | Forms/modals that render but fail on submit; API success with stale UI |
| 4c | Cross-Page Consistency | Same endpoint returning different results on different pages |
| 4d | Runtime Config | `"undefined"`, `"CHANGE_ME"`, `"TODO"` in rendered output; missing env vars |
| 5 | Look & Feel / UX | Accessibility, responsive breakpoints, visual consistency |
| 5b | Error Path Testing | Missing empty states, broken CTAs, infinite loading on zero data |

**Finding categories:** `e2e`, `api`, `security`, `config`, `empty-state`, `accessibility`, `responsive`, `ux`, `performance`

---

## `/cc-master:align-check`

Three-way alignment verification: original task → spec → code. Catches the drift that qa-review misses — when a spec accurately describes code that does the wrong thing.

```
Usage:  /cc-master:align-check <task-id> [--auto]
        /cc-master:align-check 3,5,7
Output: .cc-master/specs/<task-id>-align.json
```

Three checks:
1. **Spec captures task intent** — every requirement in the task appears in the spec
2. **Code delivers spec** — uses existing qa-review report when available
3. **Code delivers task (end-to-end)** — the requester perspective test

Pass threshold: score ≥ 85 AND zero `not_satisfied` requirements AND zero critical Check 1 misalignments.

---

## `/cc-master:gap-check`

Pipeline gap detector. Checks what was forgotten between plan and code across all pipeline layers.

```
Usage:  /cc-master:gap-check <task-id>
        /cc-master:gap-check --all
        /cc-master:gap-check --roadmap
Output: .cc-master/gap-check-<timestamp>.json
```

Four layers inspected:
1. Roadmap → Spec (planned features without specs)
2. Spec → Subtasks (acceptance criteria without subtasks)
3. Subtasks → Implementation (marked complete but no git evidence)
4. Implementation → Tests (criteria implying tests that have none)

---

## `/cc-master:api-contract`

Frontend/backend API contract verification derived from actual source code — no OpenAPI spec required. Cross-references every frontend call against every backend route through proxy layers.

```
Usage:  /cc-master:api-contract [--scope frontend|backend|both] [--fix] [--live <url>] [--output <dir>]
Output: .cc-master/api-contracts/<timestamp>-contract-report.json
```

| Flag | Effect |
|------|--------|
| `--scope` | Limit analysis to one side (default: both) |
| `--fix` | Auto-fix simple mismatches (path corrections, method corrections, field name casing) |
| `--live <url>` | Runtime verification via curl/agent-browser |

Pass threshold: score ≥ 70 AND zero CRITICAL findings.

Supports: Dropwizard/Jersey, Vert.x, Express/Node, Spring Boot, FastAPI, Flask, Go. Traces through nginx proxy layers.

---

## `/cc-master:doc-review`

Documentation accuracy validation. Cross-references documented APIs, CLI flags, config options, env vars, and workflows against actual code. Produces a scored report and creates kanban tasks for findings with `[D]` badges.

```
Usage:  /cc-master:doc-review [<doc-file>] [--scope <area>]
Output: .cc-master/doc-reviews/<timestamp>-report.json
```

---

## `/cc-master:perf-audit`

Performance analysis — static detection of N+1 queries, unbounded list queries, synchronous-blocking operations in async paths, and hot path identification. Optional Playwright frontend metrics.

```
Usage:  /cc-master:perf-audit [--focus backend|frontend|db|all] [--target <rps>]
```

Creates kanban tasks for CRITICAL and HIGH findings. Playwright is optional — backend analysis works without it.
