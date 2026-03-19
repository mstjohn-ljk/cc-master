# Implementation Skills

Skills for specifying, building, and bootstrapping code.

---

## `/cc-master:spec`

Structured specification with files to modify, acceptance criteria, and subtask breakdown with dependency ordering. Auto-runs discover if `discovery.json` is missing.

```
Usage:  /cc-master:spec <id> [--auto]
        /cc-master:spec 3,5,7          # comma-separated
        /cc-master:spec 3-7            # range (max 20)
        /cc-master:spec --all          # all unspec'd tasks (max 10)
        /cc-master:spec "description"  # unlinked spec
Output: .cc-master/specs/<task-id>.md
Chains: → build (prompted or --auto)
```

---

## `/cc-master:contract-first`

Pre-build API contract verification. Reads the server's actual source code, traces routing/proxy layers, and documents exact parameters and response shapes before any client code is written. Prevents the #1 cause of integration bugs: guessing the API shape instead of reading the server source.

```
Usage:  /cc-master:contract-first
```

**5-step trace per endpoint:**

| Step | Action |
|------|--------|
| 1 | Find the server handler (`@Path`, `router.get()`, `@app.route()`, etc.) |
| 2 | Trace the routing/proxy layer (nginx rewrites, context paths, sub-router mounts) |
| 3 | Document parameters (`@QueryParam`, `@RequestParam` — exact names, types, defaults, constraints) |
| 4 | Trace the response shape (return type → serializer behavior → exact wire JSON field names) |
| 5 | Write verified contract types (TypeScript interface / Python dataclass / Go struct with backend source file:line reference) |

**Pipeline integration:**
- `spec` runs the 5-step trace when tasks cross service boundaries and embeds verified contracts in the spec
- `build` agents import verified contract types instead of guessing
- `build` Step 7c re-runs `api-contract` after implementation to catch any drift

---

## `/cc-master:build`

Implements in an isolated git worktree. Groups subtasks into dependency waves and dispatches parallel agents for independent work. Enforces production quality — no TODOs, no stubs, no mock data.

Uses **deep trace verification** during agent self-review: before marking a subtask complete, the agent must trace the implementation to an actual leaf.

On successful build, automatically:
- **Updates `discovery.json`** with new routes, services, middleware, models, and integrations added by the build
- **Marks linked roadmap features as delivered** when the task has a `feature_id` in its metadata
- **Closes linked GitHub Issues** with a completion comment (if created via `kanban-add --add-gh-issues`)
- **Runs `api-contract` verification** if the build touched client code that makes HTTP calls (Step 7c)

```
Usage:  /cc-master:build <id> [--auto]
        /cc-master:build 3,5,7         # comma-separated (shared worktree)
        /cc-master:build 3-7           # range (max 20)
        /cc-master:build --all         # all spec'd tasks (max 10)
Output: Code in .cc-master/worktrees/<task-slug>/
Chains: → qa-loop (prompted or --auto)
```

See [deep trace verification](../deep-trace-verification.md) for details.

---

## `/cc-master:scaffold`

Bootstrap a new project from scratch. Generates idiomatic project structure for the detected stack, wires a working test suite, sets up CI/CD, writes a CLAUDE.md, then chains to discover and optionally roadmap.

```
Usage:  /cc-master:scaffold [--stack <name>] [--auto]
Chains: → discover → roadmap (prompted or --auto)
```

---

## `/cc-master:debug`

Bug investigation and fix workflow. Accepts a bug description, stack trace, or `file:function` pinpoint. Traces root cause depth-first, assesses blast radius, implements a minimal fix, writes a regression test, runs targeted QA.

Works on the current branch — no worktree overhead for typical bugs.

```
Usage:  /cc-master:debug "<bug description>"
        /cc-master:debug "<stack trace>"
        /cc-master:debug src/services/payment.ts:chargeCard
```

---

## `/cc-master:hotfix`

Production emergency response. Creates `hotfix/<slug>` branch from main, runs abbreviated investigation (depth 5), applies a minimal fix, fast QA (security + correctness only), tagged `[HOTFIX]` PR.

```
Usage:  /cc-master:hotfix "<description>" [--version patch|minor] [--backport <branch>]
```

| Flag | Effect |
|------|--------|
| `--version patch\|minor` | Tag the hotfix PR with a version bump label |
| `--backport <branch>` | Create a backport PR to the specified branch |

---

## `/cc-master:test-gen`

Generate comprehensive tests for existing code, following the project's existing test patterns exactly. Reads implementation deeply, learns the test framework and patterns in use, generates a test plan, writes verified tests. Does not introduce new test frameworks.

```
Usage:  /cc-master:test-gen <file-path>
        /cc-master:test-gen <glob-pattern>
        /cc-master:test-gen <directory>
        /cc-master:test-gen <path> [--runner <framework>] [--coverage]
```
