---
name: qa-fix
description: Fix issues identified by qa-review. Reads the review report, triages findings, applies fixes, and re-runs verification. Does not re-review — that's qa-review's job.
---

# cc-master:qa-fix — QA Remediation

Read the QA review report, triage each finding, and fix the real issues. Then re-run verification to confirm fixes work.

## Process

### Step 1: Load Review Report

1. Read the review report from `.cc-master/specs/<task-id>-review.json`
2. Read the spec from `.cc-master/specs/<task-id>.md` for context
3. If no review report exists, print: `No review report found. Run /cc-master:qa-review first.` and stop.

### Step 2: Triage Findings

Go through each finding and classify it before fixing anything:

**Categories:**

| Classification | Action | Example |
|---------------|--------|---------|
| **Real issue in changed code** | Fix | Missing validation on new endpoint |
| **False positive** | Dismiss with explanation | Flagging `return;` after `System.exit()` as unreachable |
| **Pre-existing, small** (< 10 lines to fix) | Fix in-band | Existing file missing error handler, easy to add |
| **Pre-existing, widespread** | Note for follow-up | 30+ files with inconsistent error format |
| **Design decision** | Dismiss with explanation | "Should use TypeScript" when project is JavaScript |

Print the triage:
```
Triage:

  [FIX]     HIGH: Inconsistent error format in register handler
  [FIX]     HIGH: No rate limiting on login endpoint
  [FIX]     MED:  Missing input validation on registration
  [DISMISS] LOW:  Unused import — false positive, logger is used in error path on line 47
  [FIX]     CRIT: Token refresh returns 500 on expired tokens

  Fixing 4 findings, dismissing 1.
```

### Step 3: Fix Unmet Acceptance Criteria First

These are the highest priority — the feature doesn't work without them.

For each `not_met` or `partially_met` criterion:
1. Read the file and line referenced in the review
2. Understand what's wrong
3. Implement the fix
4. Verify the fix addresses the criterion

### Step 4: Fix Findings by Severity

Work through findings in order: critical -> high -> medium -> low.

For each finding classified as "fix":
1. Read the file at the referenced line
2. Read the suggestion from the review report if provided
3. Read the pattern reference (e.g., "use the same pattern as file X") if provided
4. Implement the fix
5. Verify it doesn't break anything else

**Fixing approach:**
- Match existing project patterns — read similar code for reference
- Minimal changes — fix the issue, don't refactor surrounding code
- If a fix requires a new dependency, note it but still apply the fix
- If a fix requires changes outside the current task's scope, note it as a follow-up instead of fixing

### Step 5: Address Test Gaps

For each missing test noted in the review:
1. Read existing test files to understand the testing pattern
2. Add the missing test following the same structure
3. Run the test to verify it passes

### Step 6: Re-run Verification

Run the verification commands from the spec:
```bash
<test command>
```

Print results:
```
Verification after fixes:
  [PASS] npm test — 12 passed, 0 failed
  [PASS] All acceptance criteria addressed

Fixes applied:
  1. Fixed token refresh error handling (src/routes/auth/refresh.ts:28-35)
  2. Added rate limiting to login endpoint (src/routes/auth/login.ts:5-8)
  3. Added input validation to registration (src/routes/auth/register.ts:12-22)
  4. Added tests for refresh and validation (tests/auth.test.ts:45-89)

Dismissed:
  1. Unused import — logger IS used in error path (line 47)

Ready for re-review: /cc-master:qa-review
```

### Step 7: Update Review Report

Read the existing review JSON, update it with fix notes:

Add a `fixes_applied` array to the review JSON:
```json
{
  "fixes_applied": [
    {
      "finding_index": 0,
      "action": "fixed",
      "description": "Added ResponseError class usage",
      "files_modified": ["src/routes/auth/register.ts"]
    },
    {
      "finding_index": 3,
      "action": "dismissed",
      "reason": "Logger is used in error catch block at line 47"
    }
  ],
  "fixes_iteration": 1,
  "fixes_timestamp": "ISO-8601"
}
```

## What NOT To Do

- Do not re-review — fix only. The qa-loop orchestrator will trigger a re-review.
- Do not fix issues classified as "dismiss" or "follow-up"
- Do not refactor code beyond what's needed to fix the finding
- Do not add features while fixing — scope creep breaks the QA cycle
- Do not skip verification after fixes — always re-run tests
- Do not fix pre-existing widespread issues — note them for a follow-up task
