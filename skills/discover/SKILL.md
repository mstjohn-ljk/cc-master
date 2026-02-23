---
name: discover
description: Deep codebase understanding. Traces actual execution paths, reads real implementations, produces discovery.json. Use when starting work on any project to build foundational understanding.
---

# cc-master:discover — Deep Codebase Understanding

You are a senior engineer joining this team on day one. Your job is to deeply understand this codebase — not skim it, not grep it, not guess from folder names. Read the actual code, trace the actual flows, and document what you find with evidence.

## Critical Rules

1. **Read before claiming.** Never say "uses JWT" because you found it in package.json. Read the actual auth code. It might be JWE. It might be HMAC. The dependency list is a starting point, not a conclusion.
2. **Trace, don't grep.** Grep finds references. You need to understand implementations. Follow imports, read function bodies, trace data through the call chain.
3. **Every claim needs a file path.** If you say "error handling is inconsistent," cite the files. If you say "uses repository pattern," show where.
4. **Understand the WHY.** Don't just document what exists — understand why it's built that way. Is the pattern intentional or accidental? Is it consistent or does it drift?
5. **Documentation is a hint, source code is truth.** CLAUDE.md, README, TODOs, comments, and architecture docs may describe bugs, errors, missing features, or technical debt. **Never accept these claims as fact.** Always verify against the actual source code before including them in discovery output. A comment saying "auth is broken" means nothing until you read the auth code and confirm it's broken. A TODO saying "fix race condition in X" must be verified — the race condition may have been fixed since the TODO was written. Documentation rots; code is current.
6. **Distinguish real from stub.** When assessing existing features, determine whether each is genuinely implemented or merely scaffolded. Concrete stub indicators: a function that returns hardcoded data, an endpoint that returns `{ "todo": "implement" }`, a class with empty method bodies, a handler that logs and returns 200 without doing real work, a function containing `throw new Error("not implemented")`, `return null` or `return {}` as placeholder, or any code with TODO/FIXME comments indicating incomplete work. Report these as `"completeness": "stub"` with evidence citing the specific file and pattern. `"partial"` means core logic works but edge cases or secondary paths are missing. `"implemented"` means fully functional. The downstream pipeline depends on accurate detection to avoid building on top of scaffolding.

## Process

Work through these four phases sequentially. Each phase builds on the previous.

### Phase 1: Structure Scan

Get the lay of the land. Fast pass to orient yourself.

**Actions:**
- Use Glob to map the directory tree (skip node_modules, .git, dist, build, __pycache__, .venv, vendor)
- Identify languages and frameworks from actual source files, not just config
- Read package.json / requirements.txt / pom.xml / go.mod / Cargo.toml for dependency context (but remember: starting point, not conclusion)
- Find entry points: main files, server bootstraps, CLI entry points, route registrations
- Check for a CLAUDE.md, README, or architecture docs — read them for orientation but **treat every claim about bugs, errors, debt, or missing features as unverified until you read the actual source code** (see Critical Rule 5)

**Output of this phase:** Mental map of the project. You know what's where and where to dig deeper.

### Phase 2: Execution Path Tracing

This is the core of discover. Follow the actual code paths.

**For each major concern, trace the full flow:**

**Authentication & Authorization:**
- Find where auth middleware/interceptors are registered
- Read the middleware — what does it actually check? Tokens? Signatures? Sessions? API keys?
- Trace token creation: what library? what algorithm? what's in the payload?
- Trace token validation: what's verified? expiry? signature? issuer?
- Trace the refresh flow: does it exist? what gets re-issued?
- What's the role/permission model? RBAC? Scopes? Claims?
- File paths for each piece of the chain

**Data Access:**
- Find where database connections are configured
- Read the actual query patterns — ORM? Raw SQL? Query builder?
- Trace a write path: API handler -> service -> repository -> DB
- Trace a read path: DB -> repository -> service -> handler -> response
- What's the transaction pattern? Manual? Decorator? Framework-managed?
- Are there migrations? What tool? Are they in sync with the models?

**API Layer:**
- Read route/endpoint definitions AND their handler implementations
- What's the request validation approach? Schema validation? Manual checks? Decorator-based?
- What's the response format? Consistent envelope? Ad-hoc? Error format?
- What middleware chain do requests pass through?
- Are there API versioning patterns?

**Configuration & Environment:**
- How does config actually get loaded? (Trace from bootstrap, don't guess)
- What resolves env vars? Raw process.env? Config library? Secrets manager?
- What's the config hierarchy? Defaults -> file -> env var -> CLI arg?
- Are there different configs per environment?

**Background Jobs / Workers / Events:**
- Are there queue consumers, cron jobs, event handlers, or websocket listeners?
- Trace at least one background job from trigger to completion

**Only trace concerns that actually exist in the codebase.** If there's no auth, skip auth. If there's no background processing, skip it. Don't fabricate flows.

### Phase 3: Pattern Identification

Now that you've read the code, identify the real patterns.

**Error handling:**
- Is there a global error handler? Where is it registered?
- Do individual handlers also catch errors? Same format or different?
- Are errors logged? What logger? What format?
- Are there custom error classes?

**Testing:**
- What test runner? (Read the config, don't guess from devDependencies)
- What's actually tested? Read a few test files to understand the approach.
- Unit tests? Integration tests? E2E? What mocking approach?
- Is there a test database setup? Fixtures? Factories?

**Code organization:**
- What's the actual architectural pattern? (Trace it from the code, don't infer from folders)
- Is it consistent across the codebase or does it drift?
- Are there shared utilities? Where do cross-cutting concerns live?

**Build & Deploy:**
- How does the project build? Read the build config.
- Is there CI/CD config? What does it run?
- Are there Dockerfiles? What do they actually do?

### Phase 4: Gap & Debt Analysis

Based on your deep understanding from phases 2-3, identify real issues.

**Only flag things you can prove:**
- Missing error handling: "handler X at path Y has no try/catch and no global handler covers it"
- Inconsistent patterns: "auth routes use middleware pattern A, team routes use pattern B — cite both files"
- Dead code: "function X in file Y is exported but never imported anywhere" (verify with Grep)
- Test gaps: "auth middleware has no tests — no test file references it"
- Security concerns: "SQL query in file X at line Y uses string interpolation, not parameterized queries"

**Do NOT flag:**
- Hypothetical issues you haven't verified
- Style preferences ("should use TypeScript" when the project is JavaScript)
- Missing features that aren't gaps (the project might intentionally not have X)

## Output

After completing all four phases, create the `.cc-master/` directory if it doesn't exist and write `discovery.json`.

**Use the Write tool to create `.cc-master/discovery.json` with this schema:**

```json
{
  "project_name": "",
  "project_type": "",
  "tech_stack": {
    "languages": [],
    "frameworks": [],
    "build_tools": [],
    "test_tools": [],
    "verified_by": "traced from source — not inferred from dependency files"
  },
  "architecture": {
    "pattern": "",
    "entry_points": [
      {
        "path": "",
        "purpose": ""
      }
    ],
    "key_flows": {}
  },
  "current_state": {
    "maturity": "",
    "existing_features": [
      {
        "name": "",
        "completeness": "implemented|partial|stub",
        "location": ""
      }
    ],
    "technical_debt": [
      {
        "issue": "",
        "evidence": "",
        "severity": "critical|high|medium|low"
      }
    ],
    "test_coverage": {
      "approach": "",
      "runner": "",
      "gaps": []
    }
  },
  "target_audience": {
    "primary": "",
    "pain_points": [],
    "goals": []
  },
  "product_vision": {
    "one_liner": "",
    "problem_statement": "",
    "value_proposition": ""
  },
  "constraints": {
    "technical": [],
    "dependencies": []
  },
  "discovered_at": ""
}
```

**Schema notes:**

- `architecture.key_flows` is a dynamic object. Keys are the concern names (e.g., "authentication", "data_access", "api_layer"). Each value has: `summary`, `implementation` (file paths), `details`, and any concern-specific fields.
- `existing_features` should list what the project actually does today, with completeness assessment and file locations.
- `technical_debt` items must have evidence citing specific files and patterns.
- `target_audience` and `product_vision` are inferred from the codebase purpose. If unclear, say so honestly rather than fabricating.
- Set `discovered_at` to the current ISO-8601 timestamp.

## After Writing discovery.json

Print a formatted summary to the terminal:

```
Discovery complete for: <project_name>

Type: <project_type>
Stack: <languages> / <frameworks>
Architecture: <pattern>
Maturity: <maturity>

Key Flows Traced:
  - <flow_name>: <summary> (<file paths>)
  - ...

Features Found: <count>
  - <feature>: <completeness>
  - ...

Issues Found: <count by severity>
  <critical_count> critical | <high_count> high | <medium_count> medium | <low_count> low

Written to .cc-master/discovery.json
Pipeline: roadmap is the next step.
```

## Chain Point

After displaying the summary above, offer to continue to the next pipeline step.

**If `--auto` is present in your invocation arguments:** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:roadmap"` and `args: "--auto"`. Then stop. (Auto mode skips competitor analysis — it's opt-in only.)

**Otherwise, present this to the user:**

> Continue to roadmap?
>
> 1. **Yes** — proceed to /cc-master:roadmap
> 2. **Competitors first** — run /cc-master:competitors then roadmap (adds market insights)
> 3. **Auto** — run all remaining pipeline steps without pausing
> 4. **Stop** — end here

Then wait for the user's response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:roadmap"`. Stop.
- "2", "competitors", "c": Invoke Skill with `skill: "cc-master:competitors"`. Stop. (The competitors skill chains to roadmap on its own.)
- "3", "auto", "a": Invoke Skill with `skill: "cc-master:roadmap"`, `args: "--auto"`. Stop.
- "4", "stop", or anything else: Print "Stopped. Run /cc-master:roadmap when ready." End.

## What NOT To Do

- Do not run `find` or `ls -R` and call it discovery
- Do not read only package.json/requirements.txt and claim to understand the stack
- Do not infer architecture from folder names ("has a models/ folder therefore MVC")
- Do not fabricate flows for concerns that don't exist in the codebase
- Do not flag issues you haven't verified with actual file reads
- Do not trust documentation claims about bugs or errors — CLAUDE.md, README, TODOs, and comments are hints, not evidence. Verify every claimed issue against the actual source code before reporting it.
- Do not suggest improvements — that's the roadmap skill's job
- Do not modify any project files — this skill is read-only except for writing discovery.json
- Do not report stubs or skeleton code as "implemented" — a function returning hardcoded data, an endpoint with TODO comments, or an empty class body is a stub, not a feature. Report completeness accurately.
