---
name: qa-review
description: Review implementation against spec and acceptance criteria. Runs tests, checks code quality, security, and coverage. Produces structured pass/fail report. Does not fix — that's qa-fix's job.
---

# cc-master:qa-review — Quality Validation

Review the implementation of a task against its spec and acceptance criteria. Produce a structured report with pass/fail status, scored findings, and specific file/line references.

## Process

### Step 1: Load Review Context

1. **Identify the task.** Arguments should provide a task ID or spec reference.
   - Call `TaskGet` to load the task
   - Read the spec from `.cc-master/specs/<task-id>.md`

2. **Load project understanding.** Read `.cc-master/discovery.json` if available — this tells you the project's conventions, patterns, and existing quality standards.

3. **Identify what changed.** If work was done in a worktree, diff against the base:
   ```bash
   cd .cc-master/worktrees/<task-slug> && git diff main --name-only
   ```
   If not in a worktree, check recent unstaged changes or ask what to review.

### Step 2: Review — Functional Correctness

For each acceptance criterion in the spec:

1. Read the implementation file(s) that address this criterion
2. Trace the logic: does the code actually satisfy the criterion?
3. Check edge cases: what happens with empty input, null values, errors, concurrent access?
4. Mark as: `met`, `partially_met` (with explanation), or `not_met` (with explanation)

**Be rigorous but fair.** A criterion is `met` if the implementation handles the expected case correctly. It's `partially_met` if it works for the happy path but misses edge cases. It's `not_met` only if the core functionality is missing or broken.

### Step 3: Review — Code Quality

Read every changed file and evaluate:

**Pattern consistency:**
- Does this code follow the project's existing patterns? (reference discovery.json)
- If the project uses repository pattern, does the new code use it too?
- Are naming conventions consistent with the rest of the codebase?

**Error handling:**
- Are errors caught and handled appropriately?
- Do error messages help with debugging?
- Is the error handling consistent with the project's existing approach?

**Code clarity:**
- Can you understand what the code does by reading it?
- Are there unnecessarily complex constructions?
- Is there dead code or unused variables?

### Step 4: Review — Security

Check for common vulnerabilities in the changed code:

- **Injection:** SQL injection, command injection, XSS, template injection
- **Authentication/Authorization:** missing auth checks, broken access control
- **Data exposure:** sensitive data in logs, overly verbose error responses, secrets in code
- **Input validation:** missing validation on user input, unbounded inputs
- **SSRF/path traversal:** user-controlled URLs or file paths without validation

**Only flag security issues you can demonstrate in the actual code.** "This endpoint should have rate limiting" is an enhancement suggestion, not a security finding, unless the endpoint handles authentication.

### Step 5: Review — Test Coverage

1. Identify what test files exist for the changed code
2. Read the tests — do they actually test the new functionality?
3. Evaluate coverage:
   - Are the happy paths tested?
   - Are error paths tested?
   - Are edge cases tested?
4. Run the test command if specified in the spec:
   ```bash
   <test command from spec>
   ```

### Step 6: Produce Report

Print the review report and write it to `.cc-master/specs/<task-id>-review.json`:

**Terminal output:**

```
QA Review: <task title>
Iteration: <n>

Acceptance Criteria:
  [PASS] User can register with email and password
  [PASS] Login returns encrypted tokens
  [FAIL] Token refresh works without re-login
         -> Refresh endpoint returns 500 when token is expired (src/routes/auth/refresh.ts:28)
  [PASS] Invalid credentials return 401

Code Quality: 3 findings
  [HIGH] Inconsistent error format in registration handler
         src/routes/auth/register.ts:45 returns {error: string}
         but project convention is {message: string, code: number}
         (see src/routes/users/create.ts:38 for correct pattern)

  [MED]  Missing input validation on registration
         src/routes/auth/register.ts:12 — email and password not validated
         before database insert

  [LOW]  Unused import
         src/middleware/auth.ts:3 — 'logger' imported but never used

Security: 1 finding
  [HIGH] No rate limiting on login endpoint
         src/routes/auth/login.ts — brute force attack possible

Test Coverage: partial
  [PASS] Registration happy path tested
  [PASS] Login happy path tested
  [MISS] No tests for token refresh
  [MISS] No tests for invalid input handling

Tests: 8 passed, 0 failed, 2 missing

Score: 72/100
Status: FAIL

Findings: 1 critical, 2 high, 1 medium, 1 low
```

**JSON report** (written to `.cc-master/specs/<task-id>-review.json`):

```json
{
  "task_id": "",
  "status": "pass|fail",
  "score": 72,
  "iteration": 1,
  "timestamp": "ISO-8601",
  "acceptance_criteria": [
    {
      "criterion": "User can register with email and password",
      "status": "met",
      "evidence": "src/routes/auth/register.ts implements POST /register"
    },
    {
      "criterion": "Token refresh works without re-login",
      "status": "not_met",
      "evidence": "Refresh endpoint returns 500 on expired tokens",
      "file": "src/routes/auth/refresh.ts",
      "line": 28
    }
  ],
  "findings": [
    {
      "severity": "high",
      "category": "quality",
      "title": "Inconsistent error format",
      "file": "src/routes/auth/register.ts",
      "line": 45,
      "description": "Returns {error: string} but convention is {message, code}",
      "suggestion": "Use the same ResponseError class as src/routes/users/create.ts"
    }
  ],
  "tests": {
    "command": "npm test",
    "passed": 8,
    "failed": 0,
    "missing": ["token refresh tests", "invalid input tests"]
  }
}
```

**Scoring guide:**
- Start at 100
- Each unmet acceptance criterion: -15
- Each partially met criterion: -5
- Each critical finding: -20
- Each high finding: -10
- Each medium finding: -5
- Each low finding: -2
- Missing test coverage for critical path: -5 per gap
- Floor at 0

**Pass threshold:** Score >= 90 AND zero unmet acceptance criteria AND zero critical/high findings.

## What NOT To Do

- Do not fix issues — that's qa-fix's job. Report only.
- Do not modify any files (except writing the review JSON)
- Do not flag pre-existing issues as new findings unless they're in changed files
- Do not flag style preferences as findings (tabs vs spaces, semicolons, etc.)
- Do not hallucinate findings — every finding must reference a real file and line
- Do not inflate severity — rate limiting on a health check endpoint is LOW, not HIGH
