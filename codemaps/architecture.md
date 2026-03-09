# CC-Master Architecture

_Last updated: 2026-03-08_

## Overview

CC-Master is a pure-markdown Claude Code plugin. No build system, no runtime, no compiled output. All artifacts are YAML-frontmatter + prompt text in Markdown files.

## Repository Layout

```
cc-master/
├── skills/                     # 30 skill definitions
│   └── <name>/SKILL.md         # Frontmatter: name, description, tools, mcp_recommended
├── commands/                   # Slash command aliases (30 files)
│   └── <name>.md               # Thin wrappers that invoke skills
├── prompts/                    # Shared prompt fragments
│   └── deep-trace-verification.md  # Injected into build + qa-review
├── docs/                       # Extended documentation
│   ├── plans/                  # Design and analysis documents
│   └── skills/                 # Per-category skill reference docs
├── codemaps/                   # Architecture docs (this file)
├── CLAUDE.md                   # Claude Code project instructions
└── README.md                   # Primary user-facing documentation
```

## Skill Categories

### Pipeline Skills (auto-chain capable)

| Skill | Phase | Chains To |
|-------|-------|-----------|
| discover | Understanding | roadmap |
| competitors | Planning | roadmap |
| roadmap | Planning | kanban-add |
| kanban-add | Task Management | — |
| spec | Implementation | build |
| build | Implementation | qa-loop |
| qa-loop | QA | complete |
| complete | Completion | — |

### Standalone Skills (no auto-chain)

| Skill | Purpose |
|-------|---------|
| trace | Single-feature deep execution path tracing |
| overview | Stakeholder project report from pipeline artifacts |
| insights | Codebase Q&A with task extraction |
| kanban | Board rendering |
| qa-review | Score implementation against spec |
| qa-fix | Fix qa-review findings |
| qa-ui-review | Playwright E2E browser testing |
| align-check | Task → spec → code alignment verification |
| gap-check | Pipeline gap detection across all layers |
| api-contract | Frontend/backend contract verification |
| doc-review | Documentation accuracy validation |
| perf-audit | Performance analysis (N+1, unbounded queries) |
| pr-review | PR review from external contributors |
| debug | Bug investigation and minimal fix |
| hotfix | Production emergency response |
| research | Deep web research with citations |
| scaffold | Bootstrap new project from scratch |
| test-gen | Generate tests for existing code |
| dev-guide | Developer documentation generation |
| user-guide | User-facing documentation generation |
| openapi-docs | OpenAPI 3.1 spec generation |
| release-docs | Release notes and CHANGELOG generation |

## Shared Infrastructure

### Task Persistence

All skills that create or read tasks use **file-based persistence** via `.cc-master/kanban.json` in the user's project (not this repo). Skills must never use Claude Code's built-in `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` tools — they are session-scoped and do not survive context clears.

Protocol: Read file → modify in memory → write back atomically. Schema: `{version: 1, next_id: N, tasks: [...]}`.

### Deep Trace Verification

`prompts/deep-trace-verification.md` defines a five-point checklist for verifying that an implementation actually reaches a leaf (DB row, HTTP call, filesystem write) rather than stopping at a call boundary. This checklist is manually duplicated verbatim into:
- `skills/build/SKILL.md` — agent self-review before marking subtasks complete
- `skills/qa-review/SKILL.md` — Step 2 functional correctness check

### Discovery Artifact

`discovery.json` (written to `.cc-master/` in the user's project by `discover`) is consumed by: `trace`, `api-contract`, `align-check`, `gap-check`, `overview`, `spec`, `build`, `qa-review`, `doc-review`, `perf-audit`, `test-gen`, `dev-guide`, `user-guide`, `openapi-docs`. All consumers must treat it as untrusted data and not execute any instructions found within it.

### Injection Defense

All skills include injection defense rules in their Input Validation Rules section. Source code files, spec content, kanban task descriptions, discovery.json, and roadmap.json can contain AI-targeted instructions. Skills are written to ignore these and follow only the methodology in the skill file.

## State Directory Layout (user's project)

```
.cc-master/
├── discovery.json              # Written by: discover; read by: 14 skills
├── discovery-<module>.partial.json  # Intermediate; cleaned up after merge
├── competitor_analysis.json    # Written by: competitors; read by: roadmap, overview
├── roadmap.json                # Written by: roadmap; read by: kanban-add, overview, gap-check
├── kanban.json                 # Written by: all task-creating skills; read by: all task-reading skills
├── specs/<task-id>.md          # Written by: spec; read by: build, qa-review, qa-fix, qa-loop, align-check, gap-check
├── specs/<task-id>-review.json # Written by: qa-review; read by: qa-fix, qa-loop, align-check
├── specs/<task-id>-align.json  # Written by: align-check
├── traces/<slug>.md            # Written by: trace
├── insights/
│   ├── sessions.json
│   └── pending-suggestions.json
├── ui-reviews/<id>-review.json # Written by: qa-ui-review
├── ui-reviews/<id>/screenshots/
├── api-contracts/<timestamp>-contract-report.json  # Written by: api-contract
├── reports/<timestamp>-overview.md                 # Written by: overview
├── research/<slug>.md                              # Written by: research
├── worktrees/<task-slug>/      # Git worktrees (isolated); written by: build
└── worktrees/batch-*/.batch-manifest.json
```
