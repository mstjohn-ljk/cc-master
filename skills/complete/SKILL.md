---
name: complete
description: Close tasks after QA passes. Creates a PR (default) or merges to main with explicit --merge flag. Updates kanban status and roadmap feature status. Supports single task or comma-separated IDs for batch completion. The last mile.
---

# cc-master:complete — Task Completion

Create a PR (default) or merge to main (with explicit `--merge`), close tasks on the kanban, and update the roadmap. This skill only runs after QA has passed. Supports single-task and multi-task (batch) modes.

## Input Validation Rules

- **Task IDs must be positive integers only** — matching `^[0-9]+$`. Reject any argument containing path separators (`/`, `\`, `..`), shell metacharacters, or non-numeric characters (except commas for multi-task).
- **Branch names (from `--target`) must be safe** — matching `^[a-zA-Z0-9._/-]+$`. Reject values containing spaces, semicolons, backticks, dollar signs, or other shell metacharacters.
- **Range syntax (`3-7`) and `--all` are NOT supported by complete.** If a range is detected, print: `"Range syntax is only supported by /cc-master:build. Use comma-separated IDs: complete 3,4,5,6,7"` and stop.

## Process

### Step 1: Identify the Task(s)

Arguments provide one or more task IDs:
- Single: `complete 3` or `complete #3`
- Multiple: `complete 3,5,7` — comma-separated task IDs

**If `--auto` is present in arguments**, strip it before parsing the task ID and `--pr`/`--merge`/`--target` flags. Complete is the terminal pipeline skill so `--auto` controls the default completion method (PR) rather than being discarded.

**Validate all IDs** against the Input Validation Rules above.

**Single-task mode:** Proceed with the single task through Steps 2-8 as before.

**Multi-task mode:** Parse the comma-separated IDs. For each ID:
1. Call `TaskGet` to load the task
2. Read the review report from `.cc-master/specs/<task-id>-review.json`
3. Verify the latest review status is `pass` (score >= 90, no critical/high findings)

If any task hasn't passed QA, report which ones and stop:
```
Cannot complete batch — these tasks have not passed QA:
  #7 Add structured logging (latest score: 78/100)
Run /cc-master:qa-loop for failing tasks first.
```

**`--pr` in batch mode:** Supported. A single PR is created for the shared batch branch containing all tasks. The PR title summarizes the batch (e.g., `"Implement: auth, CI/CD, logging"`) and the body includes per-task details.

**Worktree resolution:** Determine the worktree path for the batch:
1. Check for a batch manifest: glob `.cc-master/worktrees/batch-*/.batch-manifest.json` and read each. If any manifest's `task_ids` array contains ALL of the provided task IDs (or a superset), use that manifest's `worktree_path` and `branch`.
2. If no batch manifest matches and this is a single-task invocation, look for `.cc-master/worktrees/<task-slug>`.
3. If neither exists, the work may already be on the current branch (previously merged). Skip worktree-specific steps.

For multi-task, print the target list:
```
Completing 3 tasks:
  #3 Add user authentication    QA score: 95/100
  #5 Setup CI/CD pipeline       QA score: 97/100
  #7 Add structured logging     QA score: 92/100

Worktree: .cc-master/worktrees/batch-3-5-7 (resolved from batch manifest)
```

**Batch index tracking:** When processing multiple tasks, maintain a 0-based `batch_index` counter:
- `batch_index == 0` → this is the **first** task: run commit in Step 2
- `batch_index == len(task_ids) - 1` → this is the **last** task: run merge/PR in Step 4, cleanup in Step 5
- All other indices → skip commit (Step 2) and merge (Step 4); only update task status (Step 6) and roadmap (Step 7)

### Step 2: Commit All Changes in Worktree

**This step is mandatory and must complete before any merge or PR operation.**

Build and QA agents frequently leave uncommitted changes in the worktree. If these are not committed first, the merge will either fail or silently lose work.

1. Navigate to the worktree directory (resolved in Step 1)
2. Run `git status` to check for uncommitted changes (staged, unstaged, and untracked files)
3. **If there are ANY uncommitted changes:**
   a. Stage all relevant files (`git add` — exclude `.cc-master/` state files, `.env`, and other non-source files)
   b. **Commit message safety:** Strip or escape any characters that are special in shell contexts (double quotes, backticks, dollar signs, backslashes, newlines) from task titles before using in commit messages. Alternatively, write the message to a temp file and use `git commit -F <file>`.
   c. **Single-task:** Commit with message: `"Implement: <sanitized-task-title>"`
   d. **Multi-task:** Commit with message: `"Implement batch: <sanitized-task-1-title>, <sanitized-task-2-title>, ..."`
   e. Run `git status` again to confirm the working tree is clean
4. **If the working tree is already clean:** proceed to Step 3
5. **If the commit fails for any reason:** stop and report the error. Do not proceed to merge with uncommitted changes.

**Do NOT skip this step.** Even if you believe all changes were committed during build/qa-fix, verify it. Uncommitted changes in a worktree are silently lost on merge.

**Shared worktree handling (multi-task batch):** When processing multiple tasks that share a batch worktree:
- Run the commit step only **once** (on the first task processed). All tasks share the same worktree, so one commit captures everything.
- For subsequent tasks in the batch, skip this step (the worktree is already clean from the first task's commit).

### Step 3: Determine Completion Method (Merge vs PR)

**Completed tasks must NEVER be merged directly to main without explicit user approval.** The default behavior is to create a pull request.

Parse arguments for `--pr` and `--merge` flags:
- `complete 3 --pr` — create a pull request (explicit)
- `complete 3 --pr --target develop` — PR against specific branch (validate branch name against Input Validation Rules)
- `complete 3 --merge` — merge directly to main (explicit user override)
- `complete 3 --pr --merge` — INVALID. Print: `"Conflicting flags: --pr and --merge cannot be used together."` and stop.

**If neither `--pr` nor `--merge` is specified:**

- **If `--auto` is active:** Default to `--pr`. Print: `"Auto mode: creating pull request (direct merge requires explicit --merge flag)."`
- **Otherwise, ask the user:**
  ```
  How should this be completed?
  1. Pull request (recommended) — push branch and create PR
  2. Merge to main — merge directly to the current branch
  ```
  Wait for the user's response:
  - "1", "pr", "pull request": proceed as `--pr`
  - "2", "merge": proceed as `--merge`

**If `--merge` is explicitly passed alongside `--auto`:** Honor `--merge`. The auto-mode default to PR is a fallback when no explicit method is specified. Print: `"Auto mode with explicit --merge: merging directly to main."`

This applies to both single-task and multi-task modes.

**If no worktree was found in Step 1** (work already on main): Skip this step entirely. Print: `"Work appears to already be on the current branch. Marking tasks as done."` and proceed directly to Step 6 (Update Task Status).

Sanitize task titles and descriptions before interpolating into `gh pr create` arguments using the same rules as commit message safety (Step 2). If using a HEREDOC for the body, ensure the delimiter (`EOF`) does not appear in the task description content.

### Step 4: Merge or PR

**Direct merge (only when explicitly chosen via `--merge` or user prompt):**

```bash
# From the main working tree
cd <project-root>

# Merge the worktree branch (use branch name resolved in Step 1)
git merge <branch-name> --no-ff -m "<sanitized-commit-message>"
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

**Pull request (default, or when explicitly chosen via `--pr`):**

```bash
# Push the worktree branch
cd <worktree-path>
git push -u origin <branch-name>

# Create PR
gh pr create \
  --title "<sanitized-task-title>" \
  --base <validated-target-branch> \
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

**Shared worktree handling (multi-task batch):**
- **Merge (if `--merge`):** Perform the merge only on the **last task** being processed. The shared branch contains all tasks' changes, so one merge brings everything in.
  - Merge message: `"Implement batch: <sanitized-task-1-title>, <sanitized-task-2-title>, ..."`
  - For earlier tasks in the batch, skip merge (it happens on the last one).
- **PR (default or `--pr`):** Push the shared branch and create a single PR on the **last task** being processed. The PR title lists all task titles. The PR body includes a summary section for each task with its QA score and acceptance criteria status.

### Step 5: Clean Up Worktree

After successful merge or PR creation:

```bash
git worktree remove <worktree-path>
```

If a PR was created (default behavior or explicit `--pr`), keep the worktree until the PR is merged (the branch needs to exist). Print:
```
Worktree kept at <worktree-path> (branch needed for PR).
Remove after PR merges: git worktree remove <worktree-path>
```

**Shared worktree handling (multi-task batch):** Clean up only after the **last task** has been processed (after the merge in Step 4). Also remove the batch manifest file.

### Step 6: Update Task Status

1. Call `TaskUpdate` to mark the parent task as `completed`
2. Mark any remaining subtasks as `completed` via `TaskUpdate`

**Multi-task:** Do this for each task as it is processed (not just at the end). Each task gets marked complete individually even though the merge happens once at the end.

### Step 7: Update Roadmap (if applicable)

1. Read the task metadata for a `feature_id` reference
2. If it links to a roadmap feature, read `.cc-master/roadmap.json`
3. Update the feature's status to `done`
4. Write the updated roadmap back

**Multi-task:** Batch all roadmap updates into a single read-modify-write cycle to avoid repeated file I/O. Read roadmap once, update all features, write once.

### Step 8: Print Summary

**Single-task (unchanged):**
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

**Multi-task batch summary:**
```
Batch Complete: batch-3-5-7

  #3 Add user authentication    done  QA 95/100 (2 rounds)
  #5 Setup CI/CD pipeline       done  QA 97/100 (1 round)
  #7 Add structured logging     done  QA 92/100 (3 rounds)

3/3 tasks completed.
Method: PR #42 created (or: merged to main with --merge)
Branch: cc-master/batch-3-5-7

Roadmap updates:
  feat-1 "Add user authentication" -> done
  feat-3 "Setup CI/CD pipeline" -> done
  feat-5 "Add structured logging" -> done

Run /cc-master:kanban to see the updated board.
```

## What NOT To Do

- Do not complete a task that hasn't passed QA — always verify the review report
- Do not merge or create a PR with uncommitted changes in the worktree — always commit first (Step 2)
- Do not force-push or force-merge — if there are conflicts, stop and ask
- Do not delete the worktree if it's needed for an open PR
- Do not modify any implementation files — this skill only merges and updates status
- Do not skip the roadmap update — if the task came from a roadmap feature, close the loop
- Do not merge multiple times for a batch — commit once (first task), merge once (last task)
- Do not pass unsanitized task IDs, titles, or branch names to shell commands — validate first
- Do not merge directly to main without explicit user approval — always default to PR or ask the user
- Do not assume `--auto` means merge — auto mode defaults to PR
