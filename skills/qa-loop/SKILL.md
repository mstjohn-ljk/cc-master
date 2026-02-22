---
name: qa-loop
description: Orchestrate the QA cycle. Runs qa-review, then qa-fix if needed, then re-review, looping until all gates pass or max iterations reached. The quality gate orchestrator.
---

# cc-master:qa-loop — QA Orchestration

Run the full quality gate cycle: review -> fix -> re-review, looping until the implementation passes all gates or max iterations is reached.

## Process

### Step 1: Identify the Task

Arguments should provide a task ID: `qa-loop 3` or `qa-loop #3`

**If `--auto` is present in arguments**, strip it before parsing (it controls chaining behavior at the end, not task identification). Remember that `--auto` was present for the Chain Point step.

Call `TaskGet` to load the task. Verify:
- A spec exists at `.cc-master/specs/<task-id>.md`
- Implementation has been done (files exist, subtasks completed)

If not ready: `Task #3 has no spec or implementation. Run /cc-master:spec then /cc-master:build first.` and stop.

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

**If `--auto` is present in your invocation arguments:** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:complete"` and `args: "<task-id> --auto"`. Then stop.

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
