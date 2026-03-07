---
name: scaffold
description: Bootstrap a new project from scratch. Generates idiomatic project structure, wires a working test suite, sets up CI/CD, writes a CLAUDE.md, then chains to discover and optionally roadmap.
---

# cc-master:scaffold — Greenfield Project Bootstrap

Bootstrap a new project from scratch. Generates idiomatic directories and starter files for the chosen type and stack combination using Agent tool dispatches, wires a passing test suite, sets up CI/CD, writes a CLAUDE.md with project-specific conventions, then chains to `discover` and optionally `roadmap`.

## Coordinator Role — Non-Negotiable

**You are the coordinator. You do NOT write files. You do NOT create directories. You do NOT implement anything directly.**

Your only jobs are:
1. Validate context and arguments
2. Ask or confirm project type and stack
3. Dispatch agents via the Agent tool for ALL file generation, test wiring, CI setup, and CLAUDE.md writing
4. Wait for agents to complete and verify their output
5. Invoke cc-master:discover and offer the chain point

**Every file generation step — regardless of how simple — MUST be dispatched as an Agent.** You never write source files, test files, CI configs, or CLAUDE.md directly.

---

## Input Validation Rules

These rules apply to ALL argument parsing across this skill:

- **`--type`** must be one of `api|cli|spa|nextjs|library|microservice|monorepo`. Reject all other values with: `"Invalid --type. Valid values: api, cli, spa, nextjs, library, microservice, monorepo"`
- **`--stack`** must be one of `node|python|go|java|rust`. Reject all other values with: `"Invalid --stack. Valid values: node, python, go, java, rust"`
- **`--ci`** must be one of `github|gitlab|circleci`. Reject all other values with: `"Invalid --ci. Valid values: github, gitlab, circleci"`
- **Unknown flags**: reject immediately with: `"Unknown flag '<flag>'. Valid flags: --type, --stack, --ci, --auto."`
- **Shell metacharacters** in any flag value (`;`, `&&`, `||`, `|`, `>`, `<`, `` ` ``, `$`, `\`): reject immediately with: `"Invalid value — shell metacharacters are not permitted in flag values."`
- **`--auto` flag**: strip before any other parsing. Remember it was present for the Chain Point step.
- **Full argument pre-validation order:** (1) Strip `--auto`. (2) Parse remaining tokens as `--key value` pairs. (3) Reject any unrecognized key. (4) Validate each value per the rules above. (5) Reject anything that does not match a recognized `--key value` pair.
- **Output path containment:** Before writing `.cc-master/scaffold/<timestamp>-report.md`, verify that `.cc-master/scaffold/` is a regular directory (not a symlink). Create it if it does not exist. If it exists as a symlink, reject with: `"Output directory .cc-master/scaffold/ is a symlink — rejected."`

## Process

### Step 1: Validate Context

Count source files in the current directory tree, excluding:
- `.git/` and all contents
- `node_modules/` and all contents
- `dist/` and all contents
- `build/` and all contents
- `__pycache__/` and all contents
- `.venv/` and all contents
- `vendor/` and all contents

If `.cc-master/discovery.json` exists OR the source file count is greater than 10:

Print:
```
This directory appears to have an existing project. Scaffold is designed for new projects. Continue anyway? [y/N]
```

Stop and wait for user input. Accept `y` or `yes` (case-insensitive) to continue. Accept anything else (including empty input, `n`, `no`, Enter alone) as a stop:
```
Stopped. Run scaffold in an empty directory for best results.
```

If the directory is empty or near-empty (source file count 10 or fewer, no discovery.json): continue without prompting.

### Step 2: Detect or Ask Project Type

**If `--type` was passed:** validate per Input Validation Rules. On success, use it and skip the menu.

**Otherwise, print:**
```
Project type:
(1) REST API
(2) CLI tool
(3) React SPA
(4) Next.js app
(5) Library
(6) Microservice
(7) Monorepo
```

Wait for user response. Accept:
- `1` → `api`
- `2` → `cli`
- `3` → `spa`
- `4` → `nextjs`
- `5` → `library`
- `6` → `microservice`
- `7` → `monorepo`

Reject anything else with: `"Please enter a number 1-7."` and re-prompt.

### Step 3: Detect or Ask Stack

**If `--stack` was passed:** validate per Input Validation Rules. On success, use it and skip detection and the menu.

**Otherwise, check for stack hint files in the current directory:**
- `package.json` → `node`
- `requirements.txt` or `pyproject.toml` → `python`
- `go.mod` → `go`
- `pom.xml` or `build.gradle` → `java`
- `Cargo.toml` → `rust`

If a hint file is found, print:
```
Detected stack: <stack>. Continue with this stack? [Y/n]
```
Accept `Y`, `y`, or Enter as yes. Accept `n` or `no` as no — proceed to the menu.

**If no hint found or user declined:** print:
```
Stack:
(1) TypeScript/Node
(2) Python
(3) Go
(4) Java/Spring
(5) Rust
```

Wait for user response. Accept:
- `1` → `node`
- `2` → `python`
- `3` → `go`
- `4` → `java`
- `5` → `rust`

Reject anything else with: `"Please enter a number 1-5."` and re-prompt.

**After stack is confirmed, print the support tier notice:**
```
Tier 1 (TypeScript/Node, Python): fully supported.
Tier 2 (Go, Java): supported.
Tier 3 (Rust): best-effort structure.
```

### Step 4: Generate Project Structure

**IMPORTANT: The coordinator (this skill) NEVER writes files directly. ALL file generation goes through Agent tool dispatches.**

Print:
```
Generating project structure for <type> / <stack>...
```

Dispatch one Agent to generate the full project structure for the chosen type+stack combination. The agent prompt MUST include:
- The project type and stack
- The absolute working directory path
- The complete list of files to create with their content requirements
- The production-quality mandate: no TODO placeholders, no empty stubs, every file must be runnable

**File generation requirements by combination:**

**REST API + TypeScript/Node:**
- `src/index.ts` — Express server that binds to port 3000 (reads `PORT` env var with fallback), mounts routes, and starts listening. Must log "Server listening on port 3000" on startup.
- `src/routes/health.ts` — Router exporting `GET /healthz` returning HTTP 200 with `{"status":"ok","timestamp":<ISO string>}`.
- `package.json` — name, version, scripts (`start`, `build`, `dev`), dependencies (express, @types/express, typescript, ts-node, ts-node-dev), devDependencies.
- `tsconfig.json` — strict mode, `esModuleInterop: true`, `outDir: dist`, `rootDir: src`.
- `.gitignore` — node_modules, dist, .env, *.js.map.

**REST API + Python:**
- `src/main.py` — FastAPI app with `GET /healthz` returning `{"status":"ok","timestamp":<ISO string>}`. Runnable with `uvicorn src.main:app --reload`.
- `requirements.txt` — `fastapi`, `uvicorn[standard]`.
- `.gitignore` — __pycache__, .venv, dist, *.pyc, .env.

**CLI tool + TypeScript/Node:**
- `src/index.ts` — commander-based CLI with `--help`, `--version` (reads from package.json), and at least one sample subcommand that performs real work (e.g., `hello <name>` prints a greeting).
- `package.json` — bin field pointing to compiled output, scripts (`build`, `start`, `dev`), dependencies (commander).
- `tsconfig.json` — strict mode, `outDir: dist`.
- `.gitignore` — node_modules, dist, .env.

**React SPA + TypeScript/Node:**
- `src/App.tsx` — Root component rendering a heading and a placeholder content div. Uses React hooks. No hardcoded Lorem Ipsum — renders real structural content.
- `src/main.tsx` — Entry point mounting App to `#root`.
- `index.html` — Standard Vite HTML template with `<div id="root">`.
- `package.json` — scripts (`dev`, `build`, `preview`), dependencies (react, react-dom), devDependencies (vite, @vitejs/plugin-react, typescript, @types/react, @types/react-dom).
- `tsconfig.json` — JSX support, strict mode.
- `vite.config.ts` — Vite config with React plugin.
- `.gitignore` — node_modules, dist, .env.

**Next.js app + TypeScript/Node:**
- `app/page.tsx` — Root page component using the App Router.
- `app/layout.tsx` — Root layout with `<html>`, `<body>`.
- `app/api/health/route.ts` — API route returning `{"status":"ok"}`.
- `package.json` — scripts (`dev`, `build`, `start`), dependencies (next, react, react-dom), devDependencies (typescript, @types/react, @types/node).
- `tsconfig.json` — Next.js-compatible strict config.
- `next.config.ts` — Minimal Next.js config.
- `.gitignore` — node_modules, .next, out, .env.

**Library + TypeScript/Node:**
- `src/index.ts` — Exports at least one working public function with a real implementation (not a stub). Document the function with JSDoc.
- `src/types.ts` — Shared type definitions used by the exported function.
- `package.json` — `main` and `types` fields, scripts (`build`), devDependencies (typescript).
- `tsconfig.json` — `declaration: true`, `outDir: dist`.
- `.gitignore` — node_modules, dist.

**Microservice + TypeScript/Node:**
- Same as REST API + TypeScript/Node, with additions:
- `src/config.ts` — Reads all config from environment variables with validation (fail-fast if required vars are missing).
- `src/middleware/requestId.ts` — Middleware that attaches a UUID request ID to every request and response header.

**Monorepo + TypeScript/Node:**
- `package.json` — Workspace root with `"workspaces": ["packages/*"]`, scripts (`build`, `test`) that run across all packages.
- `packages/core/package.json` — Core library package.
- `packages/core/src/index.ts` — Exports one real utility function.
- `packages/api/package.json` — API service package depending on `@scope/core`.
- `packages/api/src/index.ts` — Express server importing from core.
- `tsconfig.json` — Base tsconfig with path aliases for workspace packages.
- `.gitignore` — node_modules at all levels, dist.

**For Go, Java, Rust, and Python variants not explicitly listed above:** generate the idiomatic equivalent structure for the chosen type. Use 2025 idiomatic patterns (e.g., Go modules with `go.mod`, Java with Spring Boot starter structure, Rust with `cargo new` structure).

**Note at end of Step 4:** "Generated project targets 2025 idiomatic patterns. Check for framework updates if using scaffold output after 2026."

### Step 5: Wire Testing Framework

Print:
```
Wiring testing framework for <stack>...
```

Dispatch one Agent to add the testing framework and a passing sample test. The agent MUST:
1. Add all necessary test dependencies and configuration
2. Write a sample test that covers the health endpoint or primary entry point
3. Actually run the test and confirm it passes before reporting complete
4. Report the test output (pass/fail counts) in its completion message

**Testing framework by stack:**

**TypeScript/Node:**
- Install: `jest`, `ts-jest`, `@types/jest`
- Add: `jest.config.ts` — configures ts-jest preset, testMatch `**/__tests__/**/*.test.ts`
- Add: `src/__tests__/health.test.ts` — imports the health route handler, makes a request using `supertest`, asserts HTTP 200 and `{"status":"ok"}` in body. Uses a real Express app instance — not a mock.
- Update `package.json` scripts: add `"test": "jest"` and `"test:watch": "jest --watch"`

**Python:**
- Add to `requirements.txt`: `pytest`, `httpx`
- Add: `tests/__init__.py` (empty)
- Add: `tests/test_health.py` — imports FastAPI app, uses `TestClient` from `starlette.testclient`, calls `GET /healthz`, asserts status 200 and `{"status":"ok"}` in response JSON.

**Go:**
- Add: `<package>_test.go` (adjacent to `main.go` or primary file) — uses standard `testing` package, contains one function `TestHealthEndpoint` that calls the health handler and checks the response.

**Java:**
- Add: `src/test/java/<package>/HealthControllerTest.java` — JUnit 5 test using `@SpringBootTest` and `MockMvc` (or `WebTestClient` for reactive), asserts `/healthz` returns 200.

**Rust:**
- Add `#[cfg(test)]` module in the primary source file — contains one `#[test]` function that calls the health handler function and asserts the expected response. Use Axum or Actix-web test utilities as appropriate.

**Requirement:** The sample test must actually pass when run. The agent must run the test and confirm it passes before reporting complete. If the test fails, the agent must fix the issue before reporting.

### Step 6: Wire CI/CD

**Check for existing CI configuration:**
- GitHub Actions: `.github/workflows/` directory containing any `.yml` or `.yaml` file
- GitLab CI: `.gitlab-ci.yml` at project root
- CircleCI: `.circleci/config.yml`

If any CI config is detected, print:
```
CI config detected at <path> — skipping CI generation.
```
Skip the rest of this step.

**Determine CI target:**
- Default: GitHub Actions
- Override with `--ci gitlab` → GitLab CI
- Override with `--ci circleci` → CircleCI

Print:
```
Generating <target> CI configuration...
```

Dispatch one Agent to generate the CI configuration. The generated config MUST be complete and syntactically valid — not a stub. The agent must verify the YAML is syntactically valid before reporting complete.

**GitHub Actions (`.github/workflows/ci.yml`):**
```yaml
# Generated by cc-master:scaffold
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup <runtime>
        uses: actions/setup-<runtime>@v<version>
        with:
          <version-spec>
      - name: Install dependencies
        run: <install command>
      - name: Run tests
        run: <test command>
      - name: Build          # REST API types only
        run: <build command> # REST API types only
```

Fill in all placeholders with real values for the chosen stack. `actions/setup-node@v4` for Node (node-version: '20'), `actions/setup-python@v5` for Python (python-version: '3.12'), `actions/setup-go@v5` for Go (go-version: '1.22'), no setup action needed for Java (use `mvn` directly after checkout), `actions/setup-rust@v1` for Rust.

**GitLab CI (`.gitlab-ci.yml`):** Equivalent stages — `install`, `test`, `build` (REST API only). Use the appropriate image for the stack.

**CircleCI (`.circleci/config.yml`):** Equivalent orbs and steps. Use the appropriate executor for the stack.

### Step 7: Write CLAUDE.md

Print:
```
Writing CLAUDE.md with project conventions...
```

Dispatch one Agent to write `CLAUDE.md` at the project root. The file MUST contain all five of the following sections with content specific to the detected type and stack — not generic boilerplate:

1. **Stack**: "This project uses <stack> with <framework> (e.g., TypeScript/Node with Express 4.x)"
2. **Test runner**: "Run tests with: <exact command>" (e.g., `npm test`, `pytest`, `go test ./...`, `mvn test`, `cargo test`)
3. **File naming convention**: Stack-specific convention (e.g., "TypeScript files use camelCase for functions, PascalCase for classes and React components. File names match their default export.")
4. **Module/import style**: Stack-specific convention (e.g., "Use ES modules with named exports. Import order: Node built-ins, third-party packages, local modules. No default exports except React components and Next.js pages.")
5. **Error handling pattern**: Stack-specific convention (e.g., "Throw typed errors extending `AppError` from `src/errors.ts`. Never swallow errors silently. Express error handler in `src/middleware/errorHandler.ts` formats all errors consistently.")

The CLAUDE.md is what makes all downstream cc-master skills (discover, spec, build) understand this project's conventions correctly.

### Step 8: Run discover

Print:
```
Running cc-master:discover to build discovery.json...
```

Invoke the Skill tool with `skill: "cc-master:discover"` and `args: ""`.

**WARNING:** The `args` parameter MUST be an empty string `""`. NEVER pass `--auto` here — it triggers the full discover→roadmap→kanban-add chain, which is NOT intended at this step. The scaffold skill manages its own chain point.

Wait for discover to complete. If discover fails or exits without producing `discovery.json`, print:
```
Warning: discover did not produce discovery.json. Run /cc-master:discover manually when ready.
```
Continue to the output and chain point regardless — the scaffold itself succeeded.

## Output

After all steps complete, write a report to `.cc-master/scaffold/<timestamp>-report.md`.

**Before writing:**
1. Verify `.cc-master/scaffold/` is a regular directory (not a symlink). Create it if it doesn't exist. If it is a symlink, reject: `"Output directory .cc-master/scaffold/ is a symlink — rejected."`
2. Generate timestamp: ISO 8601 format (`YYYY-MM-DDTHH-MM-SS`), with `:` replaced by `-` for filename safety.

**Report format:**
```markdown
# Scaffold Report — <timestamp>

## Project Configuration
- Type: <type>
- Stack: <stack>
- CI: <ci-target>

## Generated Files
| File | Purpose |
|------|---------|
| src/index.ts | Application entry point — Express server on port 3000 |
| src/routes/health.ts | Health check endpoint GET /healthz |
| src/__tests__/health.test.ts | Sample test — asserts /healthz returns 200 |
| .github/workflows/ci.yml | GitHub Actions CI — install, test, build |
| CLAUDE.md | Project conventions for cc-master skills |
| ... | ... |

## Test Results
<test runner output — pass/fail counts>

## Next Steps
1. Run `<test command>` to verify the sample test passes
2. Run `/cc-master:roadmap` to generate a feature roadmap for your new project
3. Run `/cc-master:spec <task-id>` to spec out your first feature
```

Then display a summary to the terminal:

```
Scaffold complete.

  Type:  <type>
  Stack: <stack>
  CI:    <ci-target>

  Files generated: <count>
  Tests:           PASS (<n> tests)
  discover:        discovery.json written

  Report: .cc-master/scaffold/<timestamp>-report.md
```

## Chain Point

After the output report is written, offer to chain to roadmap:

> Project scaffolded successfully. Continue to roadmap?
>
> 1. **Yes** — proceed to /cc-master:roadmap
> 2. **Auto** — run roadmap without pausing
> 3. **Stop** — end here, you have a working project

**If `--auto` was present in your invocation arguments:** Skip the prompt. Immediately invoke the Skill tool with `skill: "cc-master:roadmap"` and `args: "--auto"`. Stop.

**Otherwise, wait for user response:**
- `1`, `yes`, `y`: Invoke Skill with `skill: "cc-master:roadmap"`, `args: ""`. Stop.
- `2`, `auto`, `a`: Invoke Skill with `skill: "cc-master:roadmap"`, `args: "--auto"`. Stop.
- `3`, `stop`, or anything else: Print `"Stopped. Run /cc-master:roadmap when ready to plan features."` End.

## What NOT To Do

- **Do not write files directly** — all file generation, test wiring, CI setup, and CLAUDE.md writing go through Agent tool dispatches. If you are writing file content, stop and dispatch an agent instead.
- **Do not pass `--auto` when invoking `cc-master:discover`** (Step 8) — it triggers unintended chaining. The `args` parameter must always be `""`.
- **Do not generate TODO placeholders, empty stubs, or skeleton functions** in any generated project file — every file must be complete and runnable.
- **Do not add non-standard testing frameworks** — use only the idiomatic framework for the stack (Jest for Node, pytest for Python, go test for Go, JUnit 5 for Java, cargo test for Rust).
- **Do not skip the context validation step** (Step 1) — always check source file count and warn for established projects.
- **Do not pass unsanitized flag values to shell commands** — validate all values against Input Validation Rules before any use.
- **Do not proceed past the "Continue anyway? [y/N]" prompt** without explicit user confirmation of `y` or `yes`.
- **Do not generate a monorepo with full nx/turborepo configuration** — scope to workspace root + 2 example packages for simplicity. Full monorepo tooling is out of scope.
- **Do not accept shell metacharacters in flag values** — reject immediately, no partial processing.
- **Do not silently ignore unknown flags** — reject with a message listing valid flags.
- **Do not write `.cc-master/scaffold/` as a relative path** — always verify it is a regular directory with a containment check before writing.

---

## Acceptance Criteria Checklist (verify before reporting complete)

1. `skills/scaffold/SKILL.md` exists with proper frontmatter (`name`, `description`)
2. Input Validation Rules cover `--type`, `--stack`, `--ci`, `--auto`, unknown flags, and shell metacharacter rejection
3. Step 1 checks source file count and `discovery.json` existence; warns and stops for established projects unless confirmed
4. Step 2 validates `--type` or shows numbered menu for all 7 types; re-prompts on invalid input
5. Step 3 validates `--stack`, detects from existing files with confirmation prompt, shows menu if needed; documents Tier 1/2/3
6. Step 4 dispatches one Agent for generation — coordinator never writes files directly; enumerates key type+stack combinations; includes 2025-patterns note
7. Step 5 dispatches one Agent for passing sample test; states test must actually pass requirement; agent must run and confirm
8. Step 6 generates GitHub Actions by default; detects and skips existing CI; dispatches one Agent; requires syntactically valid config
9. Step 7 dispatches one Agent for CLAUDE.md with all 5 required conventions
10. Step 8 invokes `cc-master:discover` with `args: ""` — explicitly warns against `--auto`
11. Chain Point offers roadmap with 3 options; `--auto` mode immediately chains to `roadmap --auto`
12. Output written to `.cc-master/scaffold/<timestamp>-report.md` with containment check for output directory
13. `--type`, `--stack`, `--ci` all validated; unknown flags rejected with message listing valid flags
14. "What NOT To Do" section is present and covers injection defense, direct file writing, and `--auto` on discover
