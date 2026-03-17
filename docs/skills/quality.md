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

## `/cc-master:smoke-test`

Post-deploy browser smoke test. Visits every discoverable route, intercepts all API calls, flags failures. Completes in 2-3 minutes — not a full QA review. Uses agent-browser CLI (not Playwright MCP). Creates kanban tasks with `[SMOKE]` badges.

```
Usage:  /cc-master:smoke-test <url> [--user <name> --pass <pw>] [--cookie <name=value>]
Output: .cc-master/smoke-tests/<run-id>-report.json
```

Checks per page: API 4xx/5xx responses, console errors, stub text indicators (`DEMO`, `TODO`, `undefined`, `[object Object]`), blank content areas. Pass threshold: score ≥ 80 and zero critical findings.

---

## `/cc-master:stub-hunt`

Live runtime stub and mock data detection. Opens the running app, navigates every page (including modals and tabs), and detects placeholder content visible to real users. Uses agent-browser CLI. Creates kanban tasks with `[STUB]` badges.

```
Usage:  /cc-master:stub-hunt <url> [--user <name> --pass <pw>] [--cookie <name=value>]
Output: .cc-master/stub-hunt/<run-id>-report.json
```

Detects: demo user data (`John Doe`, `test@example.com`), leaked placeholders (`CHANGE_ME`, `Lorem ipsum`), developer artifacts (stack traces, `[object Object]`, `undefined`), broken images, fake security data, unconfigured feature indicators.

Different from substance-audit (static code) — this checks the **live deployed app** at runtime.

---

## `/cc-master:api-payload-audit`

Statically verify that every frontend API call sends all fields the backend requires. Catches "missing required parameter" bugs before deploy. No OpenAPI spec or running app needed. Creates kanban tasks with `[PAYLOAD]` badges.

```
Usage:  /cc-master:api-payload-audit [--scope frontend|backend|both]
Output: .cc-master/payload-audit/<timestamp>-report.json
```

Checks: missing required fields (CRITICAL), type mismatches (HIGH), naming mismatches like `userId` vs `user_id` (HIGH), inconsistent call sites for the same endpoint (HIGH), extra fields / mass assignment risk (MEDIUM).

Different from api-contract (route/method matching) — this verifies **payload field contents** match.

---

## `/cc-master:config-audit`

Verify that every env var, secret, build-time constant, and config value referenced in code exists in target environment configuration. Detect config drift between dev and prod. Creates kanban tasks with `[CONFIG]` badges.

```
Usage:  /cc-master:config-audit [--env prod|dev|staging|all]
Output: .cc-master/config-audit/<timestamp>-report.json
```

Scans: `process.env.*`, `System.getenv()`, `os.environ`, `import.meta.env`, secret manager references. Cross-references against `.env` files, Docker Compose, Terraform, CI/CD configs, systemd units. Produces side-by-side drift table.

---

## `/cc-master:config-sync`

Compare infrastructure configs across environments (dev vs prod). Flags dangerous divergences in reverse proxy routes, security headers, CORS, TLS, and rate limiting. Creates kanban tasks with `[INFRA]` badges.

```
Usage:  /cc-master:config-sync
Output: .cc-master/config-sync/<timestamp>-report.json
```

Parses nginx, Apache, Caddy, Traefik, Docker Compose, Kubernetes, and Terraform configs. Also cross-references frontend API paths against prod proxy routes to catch missing routes. Parses heredocs in deploy scripts as the config format they generate.

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

Frontend/backend API contract verification with full data shape tracing. Verifies routes + proxy layers, then traces field shapes across all layers: database schema → backend model/serialization → HTTP response → frontend field access. Catches the silent bugs that route-level checks miss.

```
Usage:  /cc-master:api-contract [--scope frontend|backend|both] [--fix] [--live <url>] [--output <dir>]
Output: .cc-master/api-contracts/<timestamp>-contract-report.json
```

| Flag | Effect |
|------|--------|
| `--scope` | Limit analysis to one side (default: both) |
| `--fix` | Auto-fix simple mismatches (path corrections, method corrections, field name casing, missing annotations) |
| `--live <url>` | Runtime verification via curl/agent-browser |

Pass threshold: score ≥ 70 AND zero CRITICAL findings.

**Verification layers:**

| Layer | What it checks |
|-------|----------------|
| Route matching | Frontend URLs ↔ backend routes through proxy layers |
| Response shape | Backend serialized field names ↔ frontend field access (accounting for `@JsonProperty`, naming strategies, global transformers) |
| Inter-service DTOs | Server-side response DTO wire names ↔ client-side request DTO wire names |
| DB → Model | Migration column names/types/constraints ↔ ORM model fields ↔ INSERT code paths |

Supports: Dropwizard/Jersey, Vert.x, Express/Node, Spring Boot, FastAPI, Flask, Go, Django, Rails. Traces through nginx proxy layers. Parses migrations from SQL, Liquibase, Flyway, Alembic, Knex, Prisma, TypeORM, Django.

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
