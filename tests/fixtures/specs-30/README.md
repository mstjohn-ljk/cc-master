# specs-30/ — Spec-Context Measurement Fixture

Thirty realistic `.cc-master/specs/<N>.md` files used by
`scripts/graph/measure_spec_context_savings.sh` (subtask #69) to quantify the
token savings delivered by the `cc-master:spec` graph-backed context-load
refactor (tasks #10 and #11).

## Purpose

The spec skill's context-load phase is one of the heaviest read sites in the
cc-master pipeline — on large projects it ingests `.cc-master/kanban.json`,
`.cc-master/roadmap.json`, `.cc-master/discovery.json`, AND every existing
`.cc-master/specs/*.md` so the new spec writer can cross-reference prior work.
Without a graph backend, every spec invocation pays a full-file cost proportional
to the total spec corpus.

This fixture provides a reproducible, fixed-size spec corpus that the
measurement script can feed into both the old (whole-file) and new
(graph-backed) paths to compute a byte-reduction ratio. A stable corpus is
essential — measurements taken against the live `.cc-master/specs/` directory
drift as specs are added or rewritten, making longitudinal comparisons
meaningless.

## Why 30 specs

Real cc-master projects reach this count quickly. The v2-graph-engine branch
alone has 30+ specs after four waves of work. Token-savings measurements taken
below this size underestimate the savings ratio because the JSON whole-file
path dominates at small corpus sizes but scales worse than graph-backed reads
as the corpus grows. Thirty is the lower bound for a measurement that reflects
production-scale behavior.

## Contents

- `1.md`–`9.md`: verbatim copies of the real cc-master specs `#1`–`#9` from the
  Wave 1–4 graph-engine work. These are the ground truth — the measurement
  script treats them as a realistic sample of the live spec format (schema,
  length, section density).
- `10.md`–`30.md`: twenty-one synthetic specs authored for measurement
  headroom. Each follows the same format (Requirement, Acceptance Criteria,
  Production Readiness with 6 numbered items, Technical Approach, Verification,
  Risks, Subtasks) and references real cc-master module paths in
  `### Files to Modify` so that a graph indexer pass against this fixture
  produces realistic TOUCHES edges distributed across `skills/`, `scripts/graph/`,
  `prompts/`, `commands/`, `hooks/`, and `docs/plans/`.

## How the measurement script consumes this directory

`scripts/graph/measure_spec_context_savings.sh` does the following:

1. Copies the whole `specs-30/` directory into a scratch
   `.cc-master/specs/` inside a disposable project root.
2. Synthesizes matching `.cc-master/kanban.json`, `.cc-master/roadmap.json`,
   and `.cc-master/discovery.json` stubs so the indexer has complete input.
3. Runs `cc-master:index --full` against the scratch project.
4. Measures the JSON whole-file ingestion cost by reading every `<N>.md` file
   from disk and summing the byte count (the path the legacy spec skill
   takes on a graph-absent project).
5. Measures the graph-backed ingestion cost by running the three canonical
   Cypher queries the refactored spec skill uses (task/subtask lookup, related
   features via IMPLEMENTS, blocker chains via BLOCKED_BY) and summing the
   stdout byte count from `kuzu_client.py query`.
6. Prints `JSON bytes: X / Graph bytes: Y / Ratio: Z.Z×`.

The script then tears down the scratch project via `trap`.

## Fixture maintenance policy

`1.md`–`9.md` were copied from `.cc-master/specs/` at fixture-generation time
(this subtask #68). They are **static** going forward — the fixture is never
auto-regenerated from live specs, because regeneration would destroy the
stability that longitudinal measurements depend on.

If the spec skill's context schema changes materially (new mandatory section,
different subtask format, etc.), regenerate the fixture manually:

1. Ensure all 30 specs still parse under the new schema.
2. Add, remove, or replace synthetic specs as needed to exercise the new
   schema edges.
3. Commit the regenerated fixture alongside the schema change in a dedicated
   commit so the baseline in `tests/benchmarks/graph-engine-baseline.json`
   (subtask #21) can be refreshed in the same PR.

## Zero stub markers

Every file in this directory is a fully-realized spec or doc, not a template
or placeholder. The measurement script expects realistic content — empty or
skeleton specs would produce misleadingly low JSON byte counts and inflate
the savings ratio. If you add a synthetic spec, it must follow the same
format and length (60-150 lines) as the rest.
