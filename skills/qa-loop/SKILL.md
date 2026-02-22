---
name: qa-loop
description: Orchestrate the QA cycle. Runs qa-review, then qa-fix if needed, then re-review, looping until all gates pass or max iterations reached. Supports single task or comma-separated IDs for batch processing. The quality gate orchestrator.
---

# cc-master:qa-loop — QA Orchestration

Run the full quality gate cycle: review -> fix -> re-review, looping until the implementation passes all gates or max iterations is reached. Supports single-task and multi-task (batch) modes.

## Input Validation Rules

- **Task IDs must be positive integers only** — matching `^[0-9]+$`. Reject any argument containing path separators (`/`, `\`, `..`), shell metacharacters, or non-numeric characters (except commas for multi-task).
- **Range syntax (`3-7`) and `--all` are NOT supported by qa-loop.** If a range is detected, print: `"Range syntax is only supported by /cc-master:build. Use comma-separated IDs: qa-loop 3,4,5,6,7"` and stop.

## Process

### Step 1: Identify the Task(s)

Arguments provide one or more task IDs:
- Single: `qa-loop 3` or `qa-loop #3`
- Multiple: `qa-loop 3,5,7` — comma-separated task IDs

**If `--auto` is present in arguments**, strip it before parsing (it controls chaining behavior at the end, not task identification). Remember that `--auto` was present for the Chain Point step.

**If `--no-chain` is present in arguments**, strip it before parsing. When `--no-chain` is set, the Chain Point in Step 3 is skipped entirely — do not invoke complete, just print the QA result and stop. This flag is used by build's autonomous pipeline to prevent qa-loop from chaining to complete individually (build invokes complete as a batch after all QA runs finish).

**Validate all IDs** against the Input Validation Rules above.

**Single-task mode:** Call `TaskGet` to load the task. Verify:
- A spec exists at `.cc-master/specs/<task-id>.md`
- Implementation has been done (files exist, subtasks completed)

If not ready: `Task #3 has no spec or implementation. Run /cc-master:spec then /cc-master:build first.` and stop.

**Worktree resolution:** To find the implementation files, determine the worktree path:
1. Check for a batch manifest: glob `.cc-master/worktrees/batch-*/.batch-manifest.json` and read each. If any manifest's `task_ids` array contains this task ID, use that manifest's `worktree_path`.
2. If no batch manifest matches, look for a single-task worktree: `.cc-master/worktrees/<task-slug>` (derive slug from task title).
3. If neither exists, the implementation may have already been merged to the current branch. Proceed with files in the main working tree.

**Multi-task mode:** Parse the comma-separated IDs. For each ID:
1. Call `TaskGet` to load the task
2. Verify spec and implementation exist (same checks as single-task)
3. Resolve worktree path (same logic as above — all tasks in a batch will resolve to the same batch worktree)
4. If any task is not ready, report which ones and stop

For multi-task, print the target list:
```
QA Loop targets (3 tasks):
  #3 Add user authentication
  #5 Setup CI/CD pipeline
  #7 Add structured logging

Processing sequentially...
```

Then process each task through Steps 2-4 sequentially. Each task gets its own iteration counter and independent pass/fail status.

### Step 2: Run the Loop

```
MAX_ITERATIONS = 5
iteration = 0

print "Starting QA loop for: <task title>"
print "Max iterations: 5"
print ""

while iteration < MAX_ITERATIONS:
    iteration++

    # === REVIEW PHASE ===
    print "--- Iteration {iteration}/5: Review ---"

    Run the qa-review process inline:
      - Load spec and changed files
      - Check acceptance criteria
      - Review code quality
      - Review security
      - Check test coverage
      - Score and produce report

    Write report to .cc-master/specs/<task-id>-review.json

    if score >= 90 AND zero unmet criteria AND zero critical/high findings:
        print "QA PASSED (score: {score}/100) on iteration {iteration}"
        break  # -> Step 3

    print "QA FAILED (score: {score}/100)"
    print "Findings: {critical} critical, {high} high, {medium} medium, {low} low"

    if iteration == MAX_ITERATIONS:
        print "Max iterations reached. Escalating to human review."
        break  # -> Step 4

    # === FIX PHASE ===
    print "--- Iteration {iteration}/5: Fix ---"

    Run the qa-fix process inline:
      - Triage findings
      - Fix real issues (critical -> high -> medium)
      - Address test gaps
      - Re-run verification

    print "Fixes applied. Re-running review..."
    print ""
```

**Important:** Run qa-review and qa-fix inline (in the current session), not as subagents. The loop needs continuous context to understand what was already tried and avoid repeating failed fixes.

### Step 3: QA Passed

When the review passes:

1. Update the parent task via `TaskUpdate`:
   - Add "QA passed" to the description
   - Set metadata.phase = "review-complete"

2. Print the final summary:
```
QA Loop Complete: PASSED

Task: Add user authentication
Iterations: 2/5
Final Score: 95/100

Iteration History:
  Round 1: 72/100 — 4 findings (1 crit, 2 high, 1 med)
  Round 2: 95/100 — 1 finding (1 low, accepted)

Accepted Limitations:
  - [LOW] Unused import in auth.ts — logger used in error path, false positive

Pipeline: complete is the next step.
```

#### Chain Point

**Only execute this on QA PASS (Step 3). Never on escalation (Step 4).**

After displaying the QA passed summary, offer to continue to the next pipeline step. The task ID from Step 1 is forwarded.

**If `--no-chain` is present in your invocation arguments:** Skip the chain point entirely. Do not invoke complete. Just print the QA passed summary and stop. Build manages the complete invocation.

**If `--auto` is present (and `--no-chain` is NOT):** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:complete"` and `args: "<task-id> --auto"`. Then stop.

**Otherwise, present this to the user:**

> Continue to complete?
>
> 1. **Yes** — proceed to /cc-master:complete <task-id>
> 2. **Auto** — run all remaining pipeline steps without pausing
> 3. **Stop** — end here

Then wait for the user's response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:complete"`, `args: "<task-id>"`. Stop.
- "2", "auto", "a": Invoke Skill with `skill: "cc-master:complete"`, `args: "<task-id> --auto"`. Stop.
- "3", "stop", or anything else: Print "Stopped. Run /cc-master:complete <task-id> when ready." End.

**Note on multi-task batch from build:** When qa-loop is invoked per-task from build's autonomous pipeline, build passes `--no-chain` to prevent auto-chaining to complete. The build skill collects results from all qa-loop runs and invokes complete as a single batch call. The `--no-chain` mechanism makes this explicit — qa-loop does not need to guess whether it was invoked from build or directly by the user.

### Step 4: QA Failed — Escalation

When max iterations reached without passing:

1. Update the parent task via `TaskUpdate`:
   - Add "QA escalated — needs human review" to description
   - Keep status as `in_progress`

2. Print the escalation report:
```
QA Loop Complete: ESCALATED TO HUMAN

Task: Add user authentication
Iterations: 5/5 (max reached)
Final Score: 78/100

Recurring Issues (not resolved after multiple attempts):
  - Token refresh still returns 500 in edge case when both tokens expired
    Attempted fixes: try/catch wrapper (round 2), token state check (round 3),
    refresh token revalidation (round 4)
    Possible root cause: race condition in concurrent refresh requests

Remaining Findings:
  [HIGH] Concurrent refresh race condition (src/routes/auth/refresh.ts)
  [MED]  Missing test for concurrent refresh scenario

Recommendation: This may need architectural review of the token refresh design.
Review the implementation and provide guidance, then re-run /cc-master:qa-loop.
```

**Multi-task escalation:** When processing multiple tasks and one escalates, print the escalation report for that task, then continue to the next task. Do not stop the entire batch.

After all tasks in a multi-task batch have been processed (when invoked directly with comma-separated IDs), print a summary:
```
QA Batch Summary:
  #3 Add user authentication    PASSED  (2 iterations, score 95)
  #5 Setup CI/CD pipeline       PASSED  (1 iteration, score 97)
  #7 Add structured logging     ESCALATED (5 iterations, score 78)

2/3 passed, 1 escalated.
```

**Note:** When qa-loop is invoked per-task from build's autonomous pipeline, this batch summary is not printed — build provides its own end-to-end batch summary instead.

### Scoring Between Iterations

Track scores across iterations to detect if fixes are actually improving things:

- If score decreases between iterations: a fix introduced a regression. Flag it.
- If the same finding persists after 2 fix attempts: it's likely an architectural issue. Escalate earlier.
- If score plateaus (same score for 2 iterations): fixes aren't addressing the real issues. Escalate.

```
Iteration History:
  Round 1: 72/100
  Round 2: 85/100  (+13, improving)
  Round 3: 83/100  (-2, REGRESSION detected)
```

## Accepted Limitations

Not every finding needs to reach zero. The pass threshold is:
- Score >= 90
- Zero unmet acceptance criteria
- Zero critical or high findings

Low and medium findings can be accepted if:
- They're false positives (with explanation)
- They're pre-existing and outside the changeset scope
- They're genuine low-severity issues that don't affect functionality

Document all accepted limitations in the final report.

## What NOT To Do

- Do not skip the loop and mark as passed — every review must produce evidence
- Do not run more than MAX_ITERATIONS — escalate instead of infinite looping
- Do not count dismissed findings against the score
- Do not ignore regression between iterations — flag it prominently
- Do not modify the spec during QA — if the spec is wrong, that's a separate fix
- Do not stop the entire multi-task batch when one task escalates — continue to the next task
- Do not pass unsanitized task IDs to file paths — validate against Input Validation Rules first
- Do not auto-chain to complete when `--no-chain` is set — build uses this flag to manage the complete invocation as a batch
