---
name: insights
description: Codebase Q&A with structured task extraction. Explore and understand the project with context from discovery and roadmap. Surfaces actionable tasks from analysis.
---

# cc-master:insights — Codebase Q&A with Task Extraction

Answer questions about the codebase with deep understanding. When you identify actionable work during analysis, surface it as structured task suggestions that can be added to the kanban.

## Process

### Step 1: Load Context

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

Create the directory and file if they don't exist. The file is a JSON array of session entries.

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

If there are task suggestions, also write/update `.cc-master/insights/pending-suggestions.json` — same format as the `suggested_tasks` array but accumulated across sessions. This is what `kanban-add --from-insights` reads.

When writing to an existing file, read the current content first, append the new entry, then write back.

### Step 5: Print Footer

After your answer and any task suggestions:

```
Session logged to .cc-master/insights/sessions.json
```

## What NOT To Do

- Do not modify project files — insights is read-only (except .cc-master/insights/)
- Do not create CC tasks directly — suggestions go to pending-suggestions.json for kanban-add
- Do not make shallow claims — if you say something about the code, you've read it
- Do not suggest tasks that duplicate existing roadmap features (check roadmap.json)
- Do not re-suggest tasks that are already in pending-suggestions.json
