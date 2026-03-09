# Completion & Documentation Skills

Skills for completing work and generating project documentation.

---

## `/cc-master:complete`

Creates a pull request (default) or merges to main after QA passes. Updates kanban status and roadmap feature status. Never merges directly to main without explicit approval.

```
Usage:  /cc-master:complete <id> [--pr] [--merge] [--target <branch>] [--auto]
        /cc-master:complete 3,5,7      # comma-separated batch
```

| Flag | Effect |
|------|--------|
| `--pr` | Create a pull request (default) |
| `--merge` | Merge directly to main (explicit override required) |
| `--target <branch>` | PR target branch (default: main) |
| `--auto` | Skip prompts. Defaults to PR. Honors `--merge` if passed alongside. |

`--auto` never merges without explicit `--merge`. `--pr` and `--merge` together are rejected as conflicting.

---

## `/cc-master:pr-review`

Review incoming pull requests from other developers or agents. Works on any branch, no spec required. Applies quality gates and produces GitHub-formatted review output.

```
Usage:  /cc-master:pr-review [--branch <name>] [--post]
```

| Flag | Effect |
|------|--------|
| `--branch <name>` | Review a specific branch (default: current branch) |
| `--post` | Post review via `gh` CLI |

---

## `/cc-master:release-docs`

Generate structured release notes and CHANGELOG entries from completed kanban tasks, QA reports, and git history.

```
Usage:  /cc-master:release-docs [--version <tag>] [--since <tag>] [--format changelog|notes|both]
Output: .cc-master/reports/release-<version>.md
```

---

## `/cc-master:dev-guide`

Generate developer-facing documentation for contributors and maintainers. Context-aware — only documents what exists in the project (build system, tests, CI, extension points). No empty stub sections.

```
Usage:  /cc-master:dev-guide [--output <path>]
Output: CONTRIBUTING.md or specified path
```

---

## `/cc-master:user-guide`

User-facing documentation generation adapted to the project type. Reads `discovery.json` and the codebase to produce relevant documentation sections. Skips sections that don't apply.

```
Usage:  /cc-master:user-guide [--format md|docsite] [--output <path>]
```

---

## `/cc-master:openapi-docs`

OpenAPI 3.1 specification generation from codebase analysis. Detects HTTP API endpoints, traces routes and schemas across multiple frameworks, and produces or updates valid OpenAPI YAML or JSON. Exits cleanly if the project has no HTTP API.

```
Usage:  /cc-master:openapi-docs [--format yaml|json] [--output <path>] [--update]
```

| Flag | Effect |
|------|--------|
| `--update` | Merge new routes into an existing spec rather than overwriting |
| `--format` | Output format (default: yaml) |
