---
name: kanban-add
description: Add tasks to the kanban board. Supports three modes — import from roadmap, import from insights suggestions, or manual creation. Creates native CC tasks with metadata for display.
---

# cc-master:kanban-add — Task Injection

Add tasks to the kanban board by creating native CC tasks. Three modes: from roadmap, from insights, or manual.

## Metadata Convention

Every task created by this skill embeds a metadata block in the task description. This is how `cc-master:kanban` reads priority, source, and feature linkage.

**Format** (HTML comment so it's invisible in normal rendering):

```
<!-- cc-master
{"source":"roadmap","priority":"high","feature_id":"feat-1","complexity":"medium","acceptance_criteria":["Criterion 1","Criterion 2"]}
-->
```

The metadata block is always the LAST thing in the task description, separated by a blank line from the human-readable description text.

## Mode 1: From Roadmap

**Trigger:** Arguments contain `--from-roadmap` or `--roadmap`

**Process:**

1. Read `.cc-master/roadmap.json` using the Read tool. If it doesn't exist, print:
   ```
   No roadmap found. Run /cc-master:roadmap first.
   ```
   And stop.

2. List all features with status `idea` or `under_review` (skip already-planned/done features). Present them as a numbered list:
   ```
   Roadmap features available to add:

     1. [MUST/high]  Add user authentication
     2. [MUST/med]   Setup CI/CD pipeline
     3. [SHOULD/low] Add structured logging
     4. [COULD/med]  Dark mode support

   Which features? (e.g., "1,2,3" or "all" or "must" for all MUST priority)
   ```

3. Use AskUserQuestion to let the user select which features to add. Offer options:
   - "All features" — adds everything
   - "MUST priority only" — adds only must-have features
   - "Let me pick" — user specifies by number

4. For each selected feature, create a CC task via `TaskCreate`:
   - `subject`: feature title
   - `description`: feature description + rationale + acceptance criteria (human-readable) + metadata block
   - `activeForm`: "Working on <feature title>"

5. If features have dependencies in the roadmap, set `addBlockedBy` relationships between the created tasks.

6. Update `.cc-master/roadmap.json` — change each added feature's status from `idea` to `planned`. Use the Read tool to get current content, then Write tool to save updated version.

7. Print summary:
   ```
   Added 3 tasks from roadmap:
     #1 Add user authentication        P:high   [R]
     #2 Setup CI/CD pipeline           P:high   [R]
     #3 Add structured logging         P:low    [R]

   Run /cc-master:kanban to see the board.
   ```

## Mode 2: From Insights

**Trigger:** Arguments contain `--from-insights` or `--insights`

**Process:**

1. Read `.cc-master/insights/pending-suggestions.json` using Read tool. If it doesn't exist or is empty, print:
   ```
   No pending suggestions. Run /cc-master:insights to explore the codebase first.
   ```
   And stop.

2. Present suggestions as a numbered list with category and priority.

3. Use AskUserQuestion to let the user select which to add.

4. Create CC tasks for each selected suggestion with `source: "insights"` in metadata.

5. Remove added suggestions from `pending-suggestions.json`.

6. Print summary.

## Mode 3: Manual

**Trigger:** No `--from-roadmap` or `--from-insights` flag. Arguments are treated as the task title.

**Process:**

1. Parse arguments as the task title. If no arguments provided, use AskUserQuestion to ask:
   ```
   What's the task? (short title)
   ```

2. Use AskUserQuestion to gather:
   - Priority: critical / high / normal / low
   - Brief description (or skip for title-only task)

3. Create CC task via `TaskCreate`:
   - `subject`: the title
   - `description`: user-provided description + metadata block with `source: "manual"` and selected priority
   - `activeForm`: "Working on <title>"

4. Print confirmation:
   ```
   Added task:
     #4 Fix login redirect              P:high   [M]

   Run /cc-master:kanban to see the board.
   ```

## What NOT To Do

- Do not start work on tasks — that's the spec/build skills' job
- Do not modify existing tasks — only create new ones
- Do not read TaskList — kanban-add creates, kanban reads
- Do not create duplicate tasks — if importing from roadmap, check that feature_id isn't already linked to an existing task (search task descriptions for the feature_id)
