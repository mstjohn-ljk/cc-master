---
name: build
description: Implement a spec'd task. Creates git worktree for isolation, dispatches subtasks to agents in dependency waves, tracks progress on kanban. The coder skill.
---

# cc-master:build — Implementation

Implement a spec'd task by executing subtasks in dependency order. Uses git worktrees for isolation and dispatches parallel agents for independent subtasks.

## Process

### Step 1: Identify What to Build

The task is specified via arguments:
- A task ID: `build 3` or `build #3`
- A spec file: `build .cc-master/specs/add-auth.md`

**If `--auto` is present in arguments**, strip it before parsing (it controls chaining behavior at the end, not task identification). Remember that `--auto` was present for the Chain Point step.

**If task ID:** Call `TaskGet` to load the task. Look for a spec file reference in its description. If no spec exists, suggest running `/cc-master:spec <id>` first and stop.

**If spec file:** Read the spec directly.

### Step 2: Read the Spec and Subtasks

1. Read the spec file from `.cc-master/specs/`
2. Call `TaskList` to find all subtasks (tasks that reference this spec or parent task in their metadata)
3. Verify subtasks have clear assignments: files to modify, acceptance criteria, pattern references
4. If subtasks don't exist yet, suggest running `/cc-master:spec` first and stop

### Step 3: Create Worktree

Create an isolated git worktree for this work:

```bash
git worktree add .cc-master/worktrees/<task-slug> -b cc-master/<task-slug>
```

If `.cc-master/worktrees/` doesn't exist, create it. All implementation happens in the worktree — the main working tree stays clean.

**If the worktree already exists** (resumed build), use the existing one. Check `git worktree list` first.

### Step 4: Plan Execution Waves

Group subtasks into waves based on their `blockedBy` dependencies:

- **Wave 1:** Subtasks with no dependencies — can all run in parallel
- **Wave 2:** Subtasks that depend only on Wave 1 tasks
- **Wave 3:** Subtasks that depend on Wave 2 tasks
- etc.

Print the execution plan:
```
Build plan for: Add user authentication
Worktree: .cc-master/worktrees/add-auth (branch: cc-master/add-auth)

Wave 1 (parallel):
  #14 Create crypto service utilities
  #15 Create auth middleware chain

Wave 2 (parallel, after wave 1):
  #16 Implement registration endpoint
  #17 Implement login endpoint

Wave 3 (after wave 2):
  #18 Add integration tests

Starting wave 1...
```

### Step 5: Execute Waves

For each wave:

**If the wave has a single subtask:**
- Execute it directly in the current session
- Read the files specified in the subtask
- Implement the changes following the pattern reference from the spec
- Mark subtask as `completed` via `TaskUpdate`

**If the wave has multiple independent subtasks:**
- Dispatch each subtask as a parallel agent via the `Task` tool
- Each agent gets a self-contained prompt including:
  - The subtask description and acceptance criteria
  - The spec file content (or relevant section)
  - The project discovery context (if available)
  - The pattern reference to follow
  - The worktree path to work in
  - Explicit file paths to modify/create
- Wait for all agents in the wave to complete
- Verify their work: read the modified files, check for conflicts

**After each wave:**
- Mark completed subtasks via `TaskUpdate` (status: `completed`)
- Print progress: `Wave 1 complete (2/3 waves done)`
- If any subtask failed, attempt to fix it before moving to the next wave
- If fix fails, stop and report: `Wave 1 failed on subtask #14: <error>. Fix manually or re-run.`

### Step 6: Verify Implementation

After all waves complete:

1. Run any verification commands from the spec (test commands, build commands)
2. Check that all acceptance criteria from the spec are addressed
3. Do a quick review of all modified files for obvious issues

If verification passes:
```
Build complete for: Add user authentication
All 5 subtasks implemented in .cc-master/worktrees/add-auth

Files modified:
  + src/services/crypto.ts (new)
  + src/middleware/auth.ts (new)
  + src/routes/auth/register.ts (new)
  + src/routes/auth/login.ts (new)
  + tests/auth.test.ts (new)
  ~ src/server.ts (modified — mounted auth routes)

Verification:
  [PASS] npm test
  [PASS] All acceptance criteria addressed

Pipeline: qa-loop is the next step.
```

If verification fails:
```
Build complete but verification failed:
  [FAIL] npm test — 2 tests failing
  [PASS] 4/5 acceptance criteria met
  [MISS] Token refresh not implemented

Review the failures and either fix manually or re-run /cc-master:build.
```

### Step 7: Update Task Status

Update the parent task via `TaskUpdate`:
- If verification passed: set metadata.phase = "qa" (ready for QA)
- If verification failed: keep status as `in_progress` with failure notes

### Step 8: Chain Point

**Only execute this step if verification PASSED in Step 6.** If verification failed, skip this entirely.

After displaying the success summary and updating task status, offer to continue to the next pipeline step. The task ID from Step 1 is forwarded.

**If `--auto` is present in your invocation arguments:** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:qa-loop"` and `args: "<task-id> --auto"`. Then stop.

**Otherwise, present this to the user:**

> Continue to qa-loop?
>
> 1. **Yes** — proceed to /cc-master:qa-loop <task-id>
> 2. **Auto** — run all remaining pipeline steps without pausing
> 3. **Stop** — end here

Then wait for the user's response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:qa-loop"`, `args: "<task-id>"`. Stop.
- "2", "auto", "a": Invoke Skill with `skill: "cc-master:qa-loop"`, `args: "<task-id> --auto"`. Stop.
- "3", "stop", or anything else: Print "Stopped. Run /cc-master:qa-loop <task-id> when ready." End.

## Agent Prompts for Parallel Subtasks

When dispatching subtask agents, give each a complete, self-contained prompt:

```
You are implementing a single subtask for the cc-master build pipeline.

## Your Subtask
Title: <subtask title>
Description: <subtask description>

## Acceptance Criteria
<criteria from the subtask>

## Files to Modify/Create
<specific file paths>

## Pattern to Follow
Read <pattern reference path> and follow the same structure, naming, and conventions.

## Project Context
<relevant section from discovery.json if available>

## Working Directory
All work happens in: <worktree path>

## Rules
- Only modify the files listed above unless you discover a necessary related change
- Follow existing project conventions exactly
- Do not add comments explaining what you're doing — write self-documenting code
- Do not add features beyond what the subtask specifies
- Run the verification command if one is specified for this subtask
```

## What NOT To Do

- Do not implement without a spec — if no spec exists, direct to /cc-master:spec
- Do not work in the main working tree — always use a worktree
- Do not implement subtasks out of dependency order
- Do not modify files outside the scope of the current subtask
- Do not skip verification after implementation
- Do not mark the parent task as done — that's the complete skill's job after QA
