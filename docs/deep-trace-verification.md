# Deep Trace Verification

CC-Master's build and QA agents are required to trace every acceptance criterion to a **leaf** — the point where data is actually read, written, sent, or received — before reporting it complete.

This methodology is defined in [`prompts/deep-trace-verification.md`](../prompts/deep-trace-verification.md) and manually duplicated verbatim into two skills:

- **`/cc-master:build`** — agent self-review during implementation. Each subtask must pass before being marked complete.
- **`/cc-master:qa-review`** — Step 2 (Functional Correctness). Each acceptance criterion is traced to a leaf during review.

## What is a leaf?

A leaf is the final side effect in an execution chain. What counts as a leaf depends on the project:

| Project type | Example leaves |
|-------------|----------------|
| Web API | Database query, outbound HTTP call, message queue publish |
| CLI tool | Filesystem write, subprocess exec, stdout output |
| UI component | Rendered DOM element, event emission |
| Worker / pipeline | Message ack, file write, downstream service call |

## The Five Checks

The operative checklist lives in [`prompts/deep-trace-verification.md`](../prompts/deep-trace-verification.md) — that file is the source of truth. What follows is a human-readable summary; if it diverges from the prompts file, the prompts file wins.

At each node in the call chain, verify:

1. **Entry point is reachable** — the trigger actually invokes this code path. Route registered? Command wired? Event handler bound?

2. **Each layer calls the next correctly** — callee exists, accepts the arguments being passed, returns what the caller expects. Don't stop at `someService.doThing(...)` — read `doThing`.

3. **Referenced resources exist** — config keys, templates, queue names, env vars, file paths, translation keys. A function calling `loadTemplate("welcome_email")` is broken if that template was never created.

4. **Data shape is consistent end-to-end** — name, type, and unit at every boundary. A field set in seconds but read as milliseconds ships broken behavior silently.

5. **Error and absence paths are handled** — what happens if a call fails, returns null, or throws? Is failure surfaced or swallowed?

## Why this matters

Without deep trace verification, agents commonly report criteria as complete when:

- A handler calls a service that calls a method that... is a stub returning hardcoded data
- A route is registered but the middleware chain never reaches the handler
- A config key is read but was never set in any environment
- A field is set in the request body but the backend reads a different field name

The checklist forces agents to follow the data, not the assumption.

## Generalization

The checklist is intentionally language- and framework-agnostic. It applies equally to:

- Java/Dropwizard backends
- TypeScript/Express APIs
- Python/FastAPI services
- CLI tools in any language
- React frontends
- Workers and data pipelines

Agents adapt the "entry point" concept to the project type: HTTP route, CLI command, event listener, scheduled job, or queue consumer.

## History

- Added in commit `756facb` (2026-03-08): initial implementation, checklist duplicated into build and qa-review
- Generalized in commit `f006742` (2026-03-08): removed web-backend-specific assumptions (nginx rewrites, HTTP auth bypass lists, Java-flavored examples)
