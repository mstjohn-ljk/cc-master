---
name: insights
description: Codebase Q&A with structured task extraction. Explore and understand the project with context from discovery and roadmap. Surfaces actionable tasks from analysis.
---

# cc-master:insights — Codebase Q&A with Task Extraction

Answer questions about the codebase with deep understanding. When you identify actionable work during analysis, surface it as structured task suggestions that can be added to the kanban.

## Process

### Step 1: Load Context

**Graph-backed read contract.** Before any graph query this skill may issue during this step or any later step, the following contract block from `prompts/graph-read-protocol.md` applies verbatim:

```
First-run check — if .cc-master/graph.kuzu is absent, follow the ## First-Run Prompt section of this protocol before Check 1.
Before any graph query, this skill MUST follow the three pre-query checks in prompts/graph-read-protocol.md (directory exists, _source hash matches, query executes cleanly). On any check failure, fall back to JSON and emit one warning per session.
Check 1 — `.cc-master/graph.kuzu` exists on disk (file or directory, readable).
Check 2 — `_source.content_hash` matches the current on-disk hash for every dependent JSON/markdown artifact.
Check 3 — the Cypher query executes cleanly via `scripts/graph/kuzu_client.py` (exit code 0, empty stderr).
Emit at most one fallback warning per session; do NOT retry the graph query after fallback has started.
Emit the Graph: <state> output indicator per the ## Output Indicator section as the last line of the primary summary.
If any pre-query check above fails for this query, fall back to reading
.cc-master/<artifact>.json directly and computing the same result in memory.
Print one warning line per session on first fallback:
  "Graph absent/stale — falling back to JSON read for <artifact>"
Do NOT retry the graph query during the same session once fallback has
started — retries mask real corruption and waste tokens.
```

Load available cc-master context to inform your answers:

1. Check for `.cc-master/discovery.json` — if it exists, read it. This gives you deep project understanding without re-analyzing.
2. Check for `.cc-master/roadmap.json` — if it exists, read it. This tells you what's already planned so you don't suggest duplicates.
3. If neither exists, that's fine — you'll explore the codebase directly.

### Step 2: Answer the Question

The user's question (or topic) is provided as the skill arguments. If no arguments, ask:
```
What would you like to know about this codebase?
```

Use Read, Glob, and Grep to explore the codebase and answer thoroughly. Follow the same depth principles as discover:
- Read actual implementations, not just file names
- Trace execution paths when relevant
- Cite specific files and line ranges as evidence

### Step 3: Extract Task Suggestions

As you analyze the codebase to answer the question, watch for actionable work:

- Bugs or broken logic you encounter while reading code
- Missing error handling on paths you're tracing
- Security issues (unvalidated input, missing auth checks, SQL injection)
- Test gaps for critical functionality
- Performance issues (N+1 queries, missing indexes, unbounded loops)
- Dead code or unused dependencies
- Inconsistent patterns that should be unified

**Only suggest tasks for real issues you've verified.** Do not invent issues.

When you find something actionable, note it. After answering the main question, present suggestions:

```
Task Suggestions:

  1. [security/high] Add rate limiting to login endpoint
     src/routes/auth/login.ts has no rate limiting. Brute force attacks possible.

  2. [quality/medium] Unify error response format
     Auth routes return {error: string}, team routes return {message: string, code: number}.
     See src/routes/auth/login.ts:45 vs src/routes/teams/create.ts:32

  3. [coverage/medium] Add tests for HMAC middleware
     src/middleware/hmac.ts has zero test coverage. Critical auth path.

Add these to kanban? Run /cc-master:kanban-add --from-insights
```

### Step 4: Persist Session

After answering, append to `.cc-master/insights/sessions.json`:

Create the directory `.cc-master/insights/` if it doesn't exist. The file is a JSON array of session entries — read the existing array first (or start with `[]` if the file doesn't exist), append the new entry, then write back.

```json
[
  {
    "id": "session-<timestamp_ms>",
    "timestamp": "ISO-8601",
    "question": "The user's question",
    "answer_summary": "2-3 sentence summary of what was found",
    "files_explored": ["path/to/file1.ts", "path/to/file2.ts"],
    "suggested_tasks": [
      {
        "title": "Add rate limiting to login endpoint",
        "description": "src/routes/auth/login.ts has no rate limiting...",
        "priority": "high",
        "category": "security",
        "complexity": "low"
      }
    ]
  }
]
```

### Step 5: Write Pending Suggestions — Mandatory

**This step is mandatory whenever Step 3 produced task suggestions. Do not skip it. Do not proceed to Step 6 without completing it.**

If Step 3 produced zero task suggestions, skip this step.

If Step 3 produced one or more task suggestions:

1. Read `.cc-master/insights/pending-suggestions.json` using the Read tool. If the file doesn't exist, start with `[]`.
2. Append each new suggestion from Step 3 to the array. Each suggestion must include: `title`, `description`, `priority`, `category`, `complexity`.
3. Write the updated array back to `.cc-master/insights/pending-suggestions.json`.
4. **Verify the write:** Read the file back and confirm the suggestions you just added are present. If they are not, write again.
5. Print: `"<N> suggestion(s) written to .cc-master/insights/pending-suggestions.json"`

This file is what `kanban-add --from-insights` reads. If this step is skipped, the suggestions are lost and the kanban-add command will report "No pending suggestions."

### Step 6: Print Footer

After your answer, any task suggestions, and the pending-suggestions write:

```
Session logged to .cc-master/insights/sessions.json
Suggestions: <N> pending (run /cc-master:kanban-add --from-insights to add)
```

If there were no suggestions, print only:

```
Session logged to .cc-master/insights/sessions.json
```

### Step 7: Emit Graph Output Indicator

As the last line of the primary summary (before any chain-point prompt), print exactly ONE of these three strings based on the pre-query check outcomes from Step 1:

- `Graph: fresh` — all three pre-query checks passed and the Cypher result was consumed.
- `Graph: stale — fell back to JSON` — Check 2 hash mismatch for at least one dependent artifact (worst-state-wins per `prompts/graph-read-protocol.md § Output Indicator`).
- `Graph: absent — fell back to JSON` — Check 1 failed (directory missing or unreadable).

If the skill errored during pre-query checks before classification, default to `Graph: absent — fell back to JSON`. Do NOT omit the indicator. Do NOT duplicate it per artifact — one line at the bottom of the primary summary block.

## Post-Write Invalidation

Every write to `.cc-master/kanban.json` performed by this skill MUST be followed by a single graph-invalidation call at the end of the invocation, per the canonical contract in `prompts/kanban-write-protocol.md`.

> Note: this skill currently has no explicit kanban-write step in `## Process`; the section is present so any future kanban writes added to this skill inherit the contract by default.

```
This skill writes `.cc-master/kanban.json` and MUST follow the write-and-invalidate
contract in prompts/kanban-write-protocol.md. The four-step protocol is:
  1. Read `.cc-master/kanban.json` and parse JSON (treat missing file as
     {"version": 1, "next_id": 1, "tasks": []}).
  2. Apply all mutations in memory — assign new IDs from next_id, append new tasks,
     modify fields on existing tasks, set updated_at on every affected task.
  3. Write the entire updated JSON document back to `.cc-master/kanban.json`.
  4. After ALL kanban writes for this invocation have completed, invoke the Skill
     tool EXACTLY ONCE with:
       skill: "cc-master:index"
       args: "--touch .cc-master/kanban.json"
     These are LITERAL strings — never placeholders, never variables.

Batch coalescing — one --touch per invocation. When a single invocation produces
multiple kanban.json writes (multi-task batch, create + link-back, multi-edge
blocked_by rewrite), fire the --touch EXACTLY ONCE at the end after the LAST write,
never per write and never per task. If zero writes happened, skip the --touch
entirely.

Fail-open recovery. If cc-master:index --touch returns ANY non-zero exit code, the
kanban.json write STANDS — never roll back, never delete, never undo. Emit EXACTLY
ONE warning line per session:
  Warning: graph invalidation failed (exit code <N>) — next graph-backed skill will fall back to JSON. Run /cc-master:index --full to rebuild.
Substitute the observed exit code for <N>. Do NOT retry the touch. Do NOT prompt the
user. The single warning line is the entire write-side recovery protocol — the next
graph-backed read will hash-check, detect staleness, and fall back to JSON per
prompts/graph-read-protocol.md. Correctness is preserved unconditionally.
```

**Insights write scope.** This skill writes to two artifacts: `.cc-master/insights/pending-suggestions.json` (suggestions persisted for later review) AND `.cc-master/kanban.json` (only when a suggestion is promoted to a kanban task). The Post-Write Invalidation contract above applies ONLY to the `kanban.json` writes. The `pending-suggestions.json` write is NOT a kanban write and does NOT trigger `--touch .cc-master/kanban.json` — invalidation fires only when at least one kanban write happened during the invocation.

## What NOT To Do

- Do not modify project files — insights is read-only (except .cc-master/insights/)
- Do not create tasks directly in kanban.json — suggestions go to pending-suggestions.json for kanban-add
- Do not skip writing pending-suggestions.json when task suggestions exist — this is the only way suggestions reach the kanban board
- Do not print the footer before confirming pending-suggestions.json was written successfully
- Do not make shallow claims — if you say something about the code, you've read it
- Do not suggest tasks that duplicate existing roadmap features (check roadmap.json)
- Do not re-suggest tasks that are already in pending-suggestions.json
