---
name: roadmap
description: Generate a strategic feature roadmap from project understanding. Reads discovery.json if available, analyzes codebase, produces prioritized features organized into phases. Writes roadmap.json. Optionally integrates competitor analysis for market-informed prioritization.
---

# cc-master:roadmap — Strategic Feature Generation

Generate a prioritized feature roadmap for this project. Analyze what exists, identify what's missing, and organize features into dependency-ordered phases with MoSCoW prioritization.

When competitor analysis is available, features are enriched with user stories, linked to competitor insights, and given priority boosts based on market pain points.

## Process

### Step 1: Load Context

**If `--auto`, `--competitors`, or `--bugs` is present in arguments**, strip them before parsing any other arguments. Remember which flags were present — `--auto` controls chaining, `--competitors` triggers inline competitor analysis, `--bugs` enables maintenance roadmap mode.

**If `--bugs` is present:**
- Reject if `--competitors` was also present: print `"--bugs and --competitors are mutually exclusive. Maintenance roadmap does not use competitor analysis."` and stop.
- Require `.cc-master/discovery.json` to exist: if it does not exist, print `"No discovery.json found — run /cc-master:discover first. The maintenance roadmap requires a full discovery baseline."` and stop. Do NOT run lightweight inline discovery for bugs mode.
- Skip all of Steps 2, 3, and 4. Instead, execute Bugs Mode (see section below). After Bugs Mode completes, stop.

1. Check if `.cc-master/discovery.json` exists using Glob. If it does, read it — this is your primary context. Discovery has already traced the codebase deeply.

2. If no discovery.json exists, do a lightweight inline discovery:
   - Scan project structure, identify languages/frameworks/entry points
   - Read a few key files (README, main entry point, route definitions)
   - Build enough understanding to generate meaningful features
   - Print: `No discovery.json found — running lightweight analysis. For deeper results, run /cc-master:discover first.`

3. Check if `.cc-master/roadmap.json` already exists. If it does, read it to preserve features that have status `planned`, `in_progress`, or `done` — these must not be overwritten or removed.

4. **Competitor context (optional):**

   a. If `--competitors` flag was present: Invoke the Skill tool with `skill: "cc-master:competitors"` now. Wait for it to complete, then read the resulting `.cc-master/competitor_analysis.json`. Continue with step 2 below using the competitor data.

   b. Otherwise, check if `.cc-master/competitor_analysis.json` exists using Glob. If it does, read it — a previous competitor analysis run produced this data. **Validate that `pain_points` and `market_gaps` are arrays.** If the file is malformed, print `Competitor analysis file is malformed — proceeding without competitor data.` and continue as if no competitor data exists. Otherwise print: `Found competitor analysis — incorporating market insights into roadmap.`

   c. If neither flag nor file exists, proceed without competitor data. The roadmap works fine without it — competitor integration is purely additive.

   **Note:** When chaining from `/cc-master:competitors`, the competitor_analysis.json file is already written before roadmap starts, so path (b) detects it automatically — no `--competitors` flag needed.

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

**Competitor-derived gaps** (only when competitor_analysis.json is loaded):
- **Pain points to solve:** Critical and high-severity pain points from competitors that this project could address. These represent known user frustrations.
- **Market gaps as differentiators:** Gaps with `strong` or `moderate` differentiator potential. Features addressing these set the project apart from competitors.
- **Table stakes:** Features that all analyzed competitors have. The project needs these to be competitive — they don't differentiate but their absence is a dealbreaker.

**Do not fabricate gaps.** If the project is complete and well-built, say so. A roadmap with 3 real features is better than one with 20 invented ones.

**Verify before trusting.** If discovery.json, CLAUDE.md, README, or any documentation mentions bugs, errors, technical debt, or broken features — **do not accept these as fact**. Read the actual source code to confirm the issue still exists before creating a feature to fix it. Documentation rots: a "known bug" may have been fixed, a "missing feature" may have been added, a TODO may be stale. Only create roadmap features for issues you can verify in the current codebase.

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

**Additional fields when competitor data is available:**

- **user_stories** (optional): 1-3 user stories in "As a [role], I want [capability] so that [benefit]" format. Derived from pain points and market gaps — these ground the feature in real user needs.
- **competitor_insight_ids** (optional): Array of pain point and/or gap IDs from competitor_analysis.json that this feature addresses (e.g., `["pp-3", "pp-7", "gap-2"]`). Links the feature back to market evidence.
- **priority_rationale** (optional): One sentence explaining why this priority was chosen. Especially useful when competitor data influenced the decision (e.g., "Elevated to must: addresses critical pain point across 3 competitors").

**Priority boost rules when competitor data is available:**
- Pain points with severity `critical` + frequency `widespread`/`common` → boost the addressing feature to `must` (unless it's already `must`)
- Pain points with severity `high` + frequency `widespread` → boost to `should` minimum
- Market gaps with `high` opportunity + `strong` differentiator → boost to `should` minimum
- Table stakes features → boost to `must` (competitive baseline)
- Document any boost in `priority_rationale`

### Step 4: Organize into Phases

Group features into sequential phases based on dependencies and priority:

- **Phase 1** should contain foundational must-haves with no dependencies
- Later phases build on earlier ones
- Each phase should be independently shippable — completing phase N leaves the project in a working state
- Name phases descriptively ("Foundation", "Core Experience", "Polish & Scale")

**When competitor data is available**, each phase may include an optional `milestones` array — 1-3 milestone descriptions that frame what the phase achieves in market terms (e.g., "Reach feature parity with Competitor X on core workflows", "Address top 3 user pain points from competitor reviews").

### Step 5: Write roadmap.json

Create `.cc-master/` directory if needed. Write `.cc-master/roadmap.json`:

```json
{
  "vision": "One-line product vision inferred from the codebase",
  "competitor_context": {
    "analysis_available": true,
    "competitors_analyzed": 4,
    "pain_points_addressed": 8,
    "gaps_targeted": 3,
    "source_file": ".cc-master/competitor_analysis.json"
  },
  "phases": [
    {
      "id": "phase-1",
      "name": "Foundation",
      "description": "Core infrastructure and critical fixes",
      "order": 1,
      "features": ["feat-1", "feat-2"],
      "milestones": ["Achieve table-stakes parity with competitors"]
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
      "status": "idea",
      "user_stories": [
        "As a user, I want to create an account so that my data persists across sessions"
      ],
      "competitor_insight_ids": ["pp-3", "gap-1"],
      "priority_rationale": "Table stakes: all competitors provide authentication"
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

**Schema notes:**

- `competitor_context` is a **top-level optional object**. Include it only when competitor analysis was used. Omit it entirely when no competitor data was available. It summarizes the competitor influence without duplicating the full analysis. Calculate `pain_points_addressed` as the count of distinct pain point IDs from competitor_analysis.json that appear in any feature's `competitor_insight_ids`. Calculate `gaps_targeted` similarly for gap IDs.
- `milestones` on phases is an **optional array**. Include only when competitor data was used. Omit the field entirely otherwise.
- `user_stories`, `competitor_insight_ids`, and `priority_rationale` on features are **optional fields**. Include only on features that were informed by competitor analysis. Omit them entirely on features without competitor linkage.
- kanban-add reads: `id`, `title`, `description`, `rationale`, `priority`, `complexity`, `acceptance_criteria`, `dependencies`, `status`, plus optionally `user_stories`, `competitor_insight_ids`, and `priority_rationale` when present. kanban-add resolves `competitor_insight_ids` against `competitor_analysis.json` to embed evidence text into task descriptions.

**Preserving existing features:** If a previous `roadmap.json` existed with features that had status `planned`, `in_progress`, or `done`, merge them back into the new roadmap. Match by `id` first (preferred). Only fall back to title matching if no ID match exists, and when matching by title, only merge if the existing feature's `phase_id` also aligns with the new feature's intended phase — if ambiguous, treat as a new feature. Never discard user-managed features.

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
```

**When competitor data was used**, enhance feature lines with per-feature evidence. For each feature that has `competitor_insight_ids`, resolve the IDs against `competitor_analysis.json` (already loaded in Step 1) and show up to 3 evidence lines below the feature title:

```
Phase 1: Foundation (3 features)
  MUST   [high] Add dark mode
                 ↳ "Eye strain complaints across competitors" — G2 reviews
                 ↳ "No dark mode despite modern UI" — Reddit r/saas
  MUST   [med]  Fix auth flow
  SHOULD [low]  Add i18n (table stakes)
                 ↳ "All competitors support 5+ languages" — cross-competitor gap
```

**Evidence line rendering rules:**
- For pain points (`pp-*` IDs): `↳ "<description>" — <source>`
- For market gaps (`gap-*` IDs): `↳ "<description>" — cross-competitor gap`
- Cap at 3 evidence lines per feature. If more exist, show `↳ + N more insights`
- Only show evidence for features that have `competitor_insight_ids` — features without them display normally with no extra lines
- Indent evidence lines to align with the feature title (after the priority/complexity prefix)


**When competitor data was used, add this section before the totals:**

```
Competitor-Informed Features:
  <count> features linked to competitor insights
  <count> features boosted by pain point severity
  <count> table-stakes features added
  Top addressed gaps: <gap descriptions>
```

Then print:
```
Written to .cc-master/roadmap.json
Pipeline: kanban-add --from-roadmap is the next step.
```

## Bugs Mode (`--bugs` flag)

Bugs Mode generates a prioritized maintenance roadmap from existing codebase artifacts. Execute this section when `--bugs` was detected in Step 1, then stop.

### Bugs Step 1: Collect Data from 4 Sources

Read all sources before generating any roadmap items. Do not generate until all 4 sources have been read.

**Source 1 — discovery.json technical debt:**
Read the `technical_debt` array from `.cc-master/discovery.json`. For each item extract: `description`, `severity` (use "medium" if absent), `file`.

**Source 2 — QA review and align-check reports:**
Use Glob to find `.cc-master/specs/*-review.json` and `.cc-master/specs/*-align.json`.
For each file found: read it, parse as JSON. If malformed, skip and continue.
Extract findings with severity HIGH or CRITICAL only. Record: finding description, severity, file path, source filename.

**Source 3 — TODO/FIXME grep:**
Search source files (excluding `node_modules/`, `.git/`, `dist/`, `build/`, `__pycache__/`, `.venv/`, `vendor/`, `*.lock`) for the following patterns (word-boundary, case-insensitive): `\bTODO\b`, `\bFIXME\b`, `\bHACK\b`, `\bXXX\b`.

For each match: read the surrounding 3 lines of context. Include the item ONLY IF:
- The context suggests real unfixed work (not a done comment or a note about intentional behavior)
- The file is NOT a test file (path does NOT contain `__tests__/`, `test/`, `tests/`, `spec/`, `specs/`; filename does NOT match `*.test.*`, `*.spec.*`, `*_test.*`, `test_*.*`)
- The file is NOT a documentation-only file (`*.md` files)

If the grep produces more than 50 items after filtering, cap at 50 and note: "Limited to 50 TODO/FIXME items."

**Source 4 — Gap-check reports:**
Use Glob to find `.cc-master/gap-check-*.json`.
For each file found: read it, parse as JSON. If malformed, skip.
Extract uncovered code path descriptions and missing functionality items.

### Bugs Step 2: Deduplicate

Before generating roadmap items, deduplicate across all 4 sources. Merge items where:
- Same source file path AND
- Same issue type (e.g., two TODO comments about auth validation in `src/auth.ts` → one item)

When merging: keep the higher severity. Record all source files the merged item came from.

### Bugs Step 3: MoSCoW Prioritization

Map deduplicated items to MoSCoW priorities:
- **Must (Critical Fixes):** Severity CRITICAL, security vulnerabilities, data loss risks, authentication/authorization gaps
- **Should (Stability):** Severity HIGH, test coverage gaps that block QA confidence, crash-causing bugs, data corruption risks
- **Could (Quality Improvement):** Severity MEDIUM, code quality improvements, performance hints, refactoring opportunities
- **Won't (this sprint):** Severity LOW, style preferences, minor naming inconsistencies, documentation nits

### Bugs Step 4: Write Maintenance Roadmap

Format output using the same roadmap.json schema as the feature roadmap, with these differences:
- Top-level `"mode": "maintenance"`
- Phase names: `"Critical Fixes"`, `"Stability"`, `"Quality Improvement"`, `"Won't Fix"`
- Each feature entry: `"type": "bug"` or `"type": "debt"` (use "bug" for crashes/security issues, "debt" for tech debt/quality items)
- Each feature entry: `"source": "<source>"` where source is one of `"discovery.json"`, `"qa-review"`, `"grep-TODO"`, `"gap-check"`
- Keep all other schema fields: `id`, `title`, `description`, `priority`, `phase`, `status` (default: `"idea"`)

**Output path routing:**
Check if `.cc-master/roadmap.json` exists:
- If it exists AND has `"mode": "feature"` (or has no `"mode"` field at all, which implies feature mode): write maintenance roadmap to `.cc-master/roadmap-bugs.json`. Print: `"Feature roadmap preserved at roadmap.json. Maintenance roadmap written to roadmap-bugs.json."`
- If `.cc-master/roadmap.json` does not exist OR has `"mode": "maintenance"`: write to `.cc-master/roadmap.json`. Print: `"Maintenance roadmap written to roadmap.json."`

Print a summary table:
```
Phase                  | Items
-----------------------|-------
Critical Fixes         | N
Stability              | N
Quality Improvement    | N
Won't Fix              | N
Total                  | N
```

### Bugs Mode — Chain Point

After writing the roadmap file, determine the correct file path (either `roadmap.json` or `roadmap-bugs.json` as determined above).

If `--auto` was present: Immediately invoke Skill tool with `skill: "cc-master:kanban-add"` and `args: "--from-roadmap"`. Note: kanban-add may need the file path — include it if the skill supports a `--file` argument, otherwise print the path for the user. Stop.

Otherwise, present:

> Maintenance roadmap written. Continue to kanban-add?
>
> 1. **Yes** — proceed to /cc-master:kanban-add --from-roadmap (using <roadmap file path>)
> 2. **Stop** — end here

Wait for response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:kanban-add"`, `args: "--from-roadmap"`. Stop.
- "2", "stop", or anything else: Print "Stopped. Run /cc-master:kanban-add --from-roadmap when ready." End.

## Chain Point

After displaying the summary above, offer to continue to the next pipeline step.

**If `--auto` is present in your invocation arguments:** Skip the prompt below. Immediately invoke the Skill tool with `skill: "cc-master:kanban-add"` and `args: "--from-roadmap --auto"`. Then stop.

**Note:** When using `--auto` with competitor-enriched roadmaps, web-scraped evidence text flows into task descriptions without manual review. Users should review competitor-informed task descriptions (marked `[C]`) before acting on them.


**Otherwise, present this to the user:**

> Continue to kanban-add?
>
> 1. **Yes** — proceed to /cc-master:kanban-add --from-roadmap
> 2. **Auto** — run all remaining pipeline steps without pausing
> 3. **Stop** — end here

Then wait for the user's response:
- "1", "yes", "y": Invoke Skill with `skill: "cc-master:kanban-add"`, `args: "--from-roadmap"`. Stop.
- "2", "auto", "a": Invoke Skill with `skill: "cc-master:kanban-add"`, `args: "--from-roadmap --auto"`. Stop.
- "3", "stop", or anything else: Print "Stopped. Run /cc-master:kanban-add --from-roadmap when ready." End.

## What NOT To Do

- Do not create tasks — that's kanban-add's job
- Do not implement anything — this is planning only
- Do not fabricate features for a codebase you haven't analyzed
- Do not trust documentation claims about bugs or errors without verifying against actual source code — CLAUDE.md, README, TODOs, and discovery.json may contain stale or incorrect information
- Do not generate more than 20 features — focus on the highest-value items
- Do not remove features with status planned/in_progress/done from an existing roadmap
- Do not modify any project files besides .cc-master/roadmap.json
- Do not fabricate competitor insights — only use data from competitor_analysis.json
