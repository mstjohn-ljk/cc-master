# Understanding Skills

Skills for building and maintaining project knowledge.

---

## `/cc-master:discover`

Deep codebase analysis. Traces actual execution paths module by module, reads implementations, identifies patterns and gaps. Produces `.cc-master/discovery.json`.

```
Usage:  /cc-master:discover [--auto] [--update]
Output: .cc-master/discovery.json
Chains: → roadmap (prompted or --auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain prompt, continue to roadmap |
| `--update` | Incremental refresh — re-traces only modules with git changes since last run |

**Key behavior:** Traces modules one at a time, writing `.cc-master/discovery-<module>.partial.json` after each to survive context loss. Final merge into `discovery.json` deletes partials.

---

## `/cc-master:trace`

Single-feature depth tracing. Follows the actual call chain for one feature from entry point to leaf, detects bugs and risks at each node, creates kanban tasks for findings.

```
Usage:  /cc-master:trace <task-id>
        /cc-master:trace "feature name"
        /cc-master:trace src/routes/checkout.ts:handleCheckout
        /cc-master:trace <id> [--depth <1-20>]
Output: .cc-master/traces/<slug>.md
```

| Argument | Effect |
|----------|--------|
| `<task-id>` | Load task + spec, find entry point |
| `"feature name"` | Search for matching route/handler |
| `file:function` | Use as explicit entry point |
| `--depth <n>` | Max hops (default: 10, max: 20) |

Creates kanban tasks for critical, high, and medium findings. Low findings appear in output only.

---

## `/cc-master:insights`

Codebase Q&A with task extraction. Ask questions, get deep answers grounded in the actual codebase. Actionable task suggestions are surfaced automatically.

```
Usage:  /cc-master:insights <question>
Output: .cc-master/insights/sessions.json
        .cc-master/insights/pending-suggestions.json
```

---

## `/cc-master:overview`

Stakeholder-ready project report synthesized from discovery, competitor analysis, and roadmap artifacts. Three-act narrative: What We Have / What The Market Expects / What We're Building.

```
Usage:  /cc-master:overview [--technical] [--output <dir>] [--title <string>]
Output: .cc-master/reports/overview-<timestamp>.md
```

| Flag | Effect |
|------|--------|
| `--technical` | Add architecture, tech debt, dependency analysis, file references |
| `--output <dir>` | Write report to a different directory |
| `--title <string>` | Override report title |

Standalone — no auto-chain, no git operations.
