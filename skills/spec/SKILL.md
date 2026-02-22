---
name: spec
description: Create a structured implementation specification for a task. Analyzes the codebase, writes a detailed spec with acceptance criteria, and breaks the task into ordered subtasks with dependencies.
---

# cc-master:spec — Structured Specification Creation

Take a task and produce a detailed implementation spec — requirements, files to modify, acceptance criteria, verification steps — then break it into ordered subtasks.

## Process

### Step 1: Identify the Task

The task is specified via arguments. Accept any of:
- A task ID from the kanban: `spec 3` or `spec #3`
- A task title or description: `spec "Add user authentication"`

**If `--auto` is present in arguments**, strip it before parsing (it controls chaining behavior at the end, not task identification). Remember that `--auto` was present for the Chain Point step.

**If a task ID is provided:**
1. Call `TaskGet` with the ID to load the full task
2. Read its subject and description for the requirement

**If a description is provided:**
1. Use it directly as the requirement
2. Note: this creates a spec without a linked kanban task — suggest running `kanban-add` first

### Step 2: Load Project Context

1. Read `.cc-master/discovery.json` if it exists — this gives you architecture understanding, patterns, and conventions to follow
2. If no discovery exists, do a quick scan of the project to understand:
   - What language/framework
   - What patterns are used (read 2-3 existing implementations as examples)
   - Where new code should go based on existing structure
3. **Competitor enrichment (optional):** If the feature being spec'd has `competitor_insight_ids` in roadmap.json, check if `.cc-master/competitor_analysis.json` exists. If it does, read it and look up the referenced pain point and gap IDs. Use these to:
   - Add more specific acceptance criteria grounded in real user pain points (e.g., if a pain point says "slow import takes 5+ minutes", add a criterion like "Import completes within 30 seconds for typical datasets")
   - Include the pain point context in the spec's Requirement section so the implementer understands the market motivation
   - Do NOT let competitor data override the feature's core requirements — it enriches, not replaces

### Step 3: Analyze What Needs to Change

Based on the task requirement and your project understanding:

1. **Identify all files that need modification or creation.** For each file:
   - Does it exist? Read it to understand current state.
   - What specific changes are needed?
   - Are there related files that might need updates? (tests, configs, types, migrations)

2. **Identify the pattern to follow.** Read an existing similar implementation in the codebase:
   - If adding a new API endpoint, read an existing endpoint to match the pattern
   - If adding a new component, read an existing component
   - If adding a new service, read an existing service
   - Document the pattern: "Follow the pattern in src/routes/users.ts"

3. **Identify risks and unknowns:**
   - Are there dependencies that need to be installed?
   - Are there database migrations needed?
   - Could this break existing functionality?
   - Are there edge cases that need handling?

### Step 4: Write the Spec

Write to `.cc-master/specs/<task-id>.md` (or `.cc-master/specs/<slugified-title>.md` if no task ID).

Create the `.cc-master/specs/` directory if it doesn't exist.

**Spec format:**

```markdown
# Spec: <Task Title>

## Requirement
<2-3 sentence description of what needs to be built and why>

## Acceptance Criteria
1. <Specific, testable criterion>
2. <Specific, testable criterion>
3. <Specific, testable criterion>

## Technical Approach

### Pattern Reference
Follow the pattern established in: <path to existing similar implementation>

### Files to Modify
- `<path>` — <what changes and why>
- `<path>` — <what changes and why>

### Files to Create
- `<path>` — <purpose>
- `<path>` — <purpose>

### Dependencies
- <any new packages/dependencies needed>

### Database Changes
- <migrations, schema changes, or "none">

## Verification
- [ ] `<test command>` passes
- [ ] <manual verification step>
- [ ] <manual verification step>

## Risks
- <risk and mitigation>

## Subtasks
1. <subtask title> — <brief description>
   Files: <paths>
   Depends on: none
2. <subtask title> — <brief description>
   Files: <paths>
   Depends on: 1
3. <subtask title> — <brief description>
   Files: <paths>
   Depends on: 1, 2
```

### Step 5: Create Subtasks

Break the spec into 3-7 subtasks. Each subtask should be:
- **Independently implementable** — an agent can do it with just the subtask description + spec context
- **Small enough to complete in one session** — if a subtask feels like it needs sub-subtasks, it's too big
- **Ordered by dependency** — later subtasks can depend on earlier ones

For each subtask, create a CC task via `TaskCreate`:
- `subject`: subtask title
- `description`: subtask details including files to modify, the pattern to follow, and acceptance criteria for this specific subtask + a reference to the spec file + metadata block
- `activeForm`: "Implementing <subtask title>"

Set `addBlockedBy` relationships based on the dependency chain.

If the spec was created for an existing kanban task (by ID), make all subtasks block that parent task — or link them by including the parent task ID in each subtask's metadata.

### Step 6: Update Parent Task

If the spec was created for an existing kanban task:
1. Call `TaskUpdate` to update the parent task's description with a link to the spec file
2. The parent task stays in its current status — subtasks drive the progress

### Step 7: Print Summary

```
Spec written: .cc-master/specs/<name>.md

Subtasks created:
  #14 Create crypto service utilities         (no deps)
  #15 Create auth middleware chain             (no deps)
  #16 Implement registration endpoint          blocked by #14, #15
  #17 Implement login endpoint                 blocked by #14, #15
  #18 Add integration tests                    blocked by #16, #17

Wave 1 (parallel): #14, #15
Wave 2 (parallel): #16, #17
Wave 3: #18

Pipeline: build is the next step.
```

## Chain Point

After displaying the summary above, offer to continue to the next pipeline step. The task ID from Step 1 is forwarded to the next skill.

**If `--auto` is present in your invocation arguments:** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:build"` and `args: "<task-id> --auto"`. Then stop.

**Otherwise, present this to the user:**

> Continue to build?
>
> 1. **Yes** — proceed to /cc-master:build <task-id>
> 2. **Auto** — run all remaining pipeline steps without pausing
> 3. **Stop** — end here

Then wait for the user's response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:build"`, `args: "<task-id>"`. Stop.
- "2", "auto", "a": Invoke Skill with `skill: "cc-master:build"`, `args: "<task-id> --auto"`. Stop.
- "3", "stop", or anything else: Print "Stopped. Run /cc-master:build <task-id> when ready." End.

## What NOT To Do

- Do not implement any code — spec is planning only
- Do not create more than 7 subtasks — if the task needs more, it should be broken into multiple specs
- Do not write vague subtasks — each must have specific files and clear acceptance criteria
- Do not skip reading existing code patterns — the spec must match project conventions
- Do not modify project files besides .cc-master/specs/
