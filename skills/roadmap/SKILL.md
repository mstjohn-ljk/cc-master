---
name: roadmap
description: Generate a strategic feature roadmap from project understanding. Reads discovery.json if available, analyzes codebase, produces prioritized features organized into phases. Writes roadmap.json.
---

# cc-master:roadmap — Strategic Feature Generation

Generate a prioritized feature roadmap for this project. Analyze what exists, identify what's missing, and organize features into dependency-ordered phases with MoSCoW prioritization.

## Process

### Step 1: Load Context

1. Check if `.cc-master/discovery.json` exists using Glob. If it does, read it — this is your primary context. Discovery has already traced the codebase deeply.

2. If no discovery.json exists, do a lightweight inline discovery:
   - Scan project structure, identify languages/frameworks/entry points
   - Read a few key files (README, main entry point, route definitions)
   - Build enough understanding to generate meaningful features
   - Print: `No discovery.json found — running lightweight analysis. For deeper results, run /cc-master:discover first.`

3. Check if `.cc-master/roadmap.json` already exists. If it does, read it to preserve features that have status `planned`, `in_progress`, or `done` — these must not be overwritten or removed.

### Step 2: Analyze Gaps and Opportunities

Based on your understanding of the project, identify:

**Functional gaps:**
- What does a user of this type of project expect that's missing?
- What existing features are incomplete?
- What workflows are broken or half-built?

**Technical gaps:**
- Missing test coverage for critical paths
- No CI/CD when the project needs it
- Missing error handling, logging, monitoring
- Security gaps (auth, validation, rate limiting)

**Quality of life:**
- Developer experience improvements
- Documentation gaps
- Performance optimizations

**Do not fabricate gaps.** If the project is complete and well-built, say so. A roadmap with 3 real features is better than one with 20 invented ones.

### Step 3: Generate Features

For each identified gap/opportunity, create a feature entry:

- **title**: Short, actionable name (imperative: "Add X", "Implement Y", "Fix Z")
- **description**: 2-3 sentences explaining what this feature does and why
- **rationale**: Why this matters — what problem does it solve?
- **priority**: MoSCoW classification
  - `must` — project is broken or unusable without this
  - `should` — significant value, expected by users, but workarounds exist
  - `could` — nice to have, improves experience but not critical
  - `wont` — explicitly out of scope (document why)
- **complexity**: `low` (hours), `medium` (days), `high` (week+)
- **impact**: `low`, `medium`, `high` — how much does this improve the project?
- **acceptance_criteria**: 3-5 specific, testable criteria
- **dependencies**: IDs of features that must be done first

### Step 4: Organize into Phases

Group features into sequential phases based on dependencies and priority:

- **Phase 1** should contain foundational must-haves with no dependencies
- Later phases build on earlier ones
- Each phase should be independently shippable — completing phase N leaves the project in a working state
- Name phases descriptively ("Foundation", "Core Experience", "Polish & Scale")

### Step 5: Write roadmap.json

Create `.cc-master/` directory if needed. Write `.cc-master/roadmap.json`:

```json
{
  "vision": "One-line product vision inferred from the codebase",
  "phases": [
    {
      "id": "phase-1",
      "name": "Foundation",
      "description": "Core infrastructure and critical fixes",
      "order": 1,
      "features": ["feat-1", "feat-2"]
    }
  ],
  "features": [
    {
      "id": "feat-1",
      "title": "Add user authentication",
      "description": "Full auth flow with registration, login, token refresh",
      "rationale": "Blocking requirement for all user-facing features",
      "priority": "must",
      "complexity": "high",
      "impact": "high",
      "phase_id": "phase-1",
      "dependencies": [],
      "acceptance_criteria": [
        "User can register with email and password",
        "Login returns encrypted tokens",
        "Token refresh works without re-login",
        "Invalid credentials return 401"
      ],
      "status": "idea"
    }
  ],
  "metadata": {
    "created_at": "",
    "updated_at": "",
    "prioritization_framework": "moscow",
    "feature_count": 0,
    "phase_count": 0
  }
}
```

**Preserving existing features:** If a previous `roadmap.json` existed with features that had status `planned`, `in_progress`, or `done`, merge them back into the new roadmap. Match by `id` first, then by title. Never discard user-managed features.

### Step 6: Print Summary

```
Roadmap: <project_name> — "<vision>"

Phase 1: <name> (<count> features)
  MUST   [high] <feature title>
  MUST   [med]  <feature title>
  SHOULD [low]  <feature title>

Phase 2: <name> (<count> features)
  MUST   [high] <feature title>
  SHOULD [med]  <feature title>
  COULD  [low]  <feature title>

Phase 3: <name> (<count> features)
  ...

Total: <n> features across <m> phases
  <must_count> must | <should_count> should | <could_count> could | <wont_count> won't

Written to .cc-master/roadmap.json
Next: /cc-master:kanban-add --from-roadmap to convert features to tasks.
```

## What NOT To Do

- Do not create tasks — that's kanban-add's job
- Do not implement anything — this is planning only
- Do not fabricate features for a codebase you haven't analyzed
- Do not generate more than 20 features — focus on the highest-value items
- Do not remove features with status planned/in_progress/done from an existing roadmap
- Do not modify any project files besides .cc-master/roadmap.json
