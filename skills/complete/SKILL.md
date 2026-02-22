---
name: complete
description: Close a task after QA passes. Merges worktree back, updates kanban status to done, updates roadmap feature status, optionally creates a PR. The last mile.
---

# cc-master:complete — Task Completion

Merge the implementation back, close the task on the kanban, and optionally create a PR. This skill only runs after QA has passed.

## Process

### Step 1: Verify QA Status

Arguments should provide a task ID: `complete 3` or `complete #3`

**If `--auto` is present in arguments**, strip it before parsing the task ID and `--pr`/`--target` flags. Complete is the terminal pipeline skill so `--auto` is simply ignored.

1. Call `TaskGet` to load the task
2. Read the review report from `.cc-master/specs/<task-id>-review.json`
3. Verify the latest review status is `pass` (score >= 90, no critical/high findings)

If QA hasn't passed:
```
Task #3 has not passed QA (latest score: 78/100).
Run /cc-master:qa-loop first.
```
And stop.

### Step 2: Check for PR Flag

Parse arguments for `--pr` flag:
- `complete 3` — merge directly to current branch
- `complete 3 --pr` — create a pull request instead of merging
- `complete 3 --pr --target develop` — PR against specific branch

### Step 3: Merge or PR

**Direct merge (default):**

```bash
# From the main working tree
cd <project-root>

# Merge the worktree branch
git merge cc-master/<task-slug> --no-ff -m "Implement: <task title>"
```

If merge conflicts occur:
1. List the conflicting files
2. Attempt automatic resolution for simple conflicts
3. If auto-resolution fails, print the conflicts and ask the user to resolve:
   ```
   Merge conflict in 2 files:
     src/server.ts — both branches modified route registration
     src/config.ts — both branches added new config keys

   Resolve manually, then run /cc-master:complete 3 again.
   ```
   And stop.

**Pull request (`--pr`):**

```bash
# Push the worktree branch
cd .cc-master/worktrees/<task-slug>
git push -u origin cc-master/<task-slug>

# Create PR
gh pr create \
  --title "<task title>" \
  --base <target-branch> \
  --body "## Summary
<task description summary>

## Changes
<list of files modified/created>

## QA Report
Score: <score>/100
Iterations: <count>
All acceptance criteria met.

## Spec
See .cc-master/specs/<task-id>.md"
```

Print the PR URL when done.

### Step 4: Clean Up Worktree

After successful merge or PR creation:

```bash
git worktree remove .cc-master/worktrees/<task-slug>
```

If `--pr` was used, keep the worktree until the PR is merged (the branch needs to exist). Print:
```
Worktree kept at .cc-master/worktrees/<task-slug> (branch needed for PR).
Remove after PR merges: git worktree remove .cc-master/worktrees/<task-slug>
```

### Step 5: Update Task Status

1. Call `TaskUpdate` to mark the parent task as `completed`
2. Mark any remaining subtasks as `completed` via `TaskUpdate`

### Step 6: Update Roadmap (if applicable)

1. Read the task metadata for a `feature_id` reference
2. If it links to a roadmap feature, read `.cc-master/roadmap.json`
3. Update the feature's status to `done`
4. Write the updated roadmap back

### Step 7: Print Summary

```
Task Complete: Add user authentication

  Status:    done
  Method:    merged to main (or: PR #42 created)
  Branch:    cc-master/add-auth (merged and cleaned up)
  QA Score:  95/100 (2 iterations)
  Files:     6 modified, 5 new

  Roadmap:   feat-1 "Add user authentication" -> done

Run /cc-master:kanban to see the updated board.
```

If this was the last task in a roadmap phase:
```
Phase 1 "Foundation" is now complete! (3/3 features done)
```

## What NOT To Do

- Do not complete a task that hasn't passed QA — always verify the review report
- Do not force-push or force-merge — if there are conflicts, stop and ask
- Do not delete the worktree if it's needed for an open PR
- Do not modify any implementation files — this skill only merges and updates status
- Do not skip the roadmap update — if the task came from a roadmap feature, close the loop
