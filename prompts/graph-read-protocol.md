# Graph Read Protocol — Fallback Contract

This document is cited by cc-master skills that read the Kuzu graph at `.cc-master/graph.kuzu/`. It defines the contract for safe graph reads and the fallback path to JSON when the graph is absent, stale, or erroring. Every graph-backed skill MUST cite this file and MUST follow every check below in order. This is not guidance — it is the contract. A skill that skips a check to save time is wrong, even if it appears to work.

The graph is a derived index over the JSON and markdown artifacts in `.cc-master/`. JSON is the source of truth; the graph is an acceleration. When the graph cannot be trusted, read-side skills MUST fall back to the JSON artifact and compute the same result in memory. Correctness first, speed second. See `docs/plans/2026-04-graph-engine-v1.md`, section "Architectural Invariants", for the governing rules this protocol implements.

## Pre-Query Checks

Every graph-backed skill MUST execute these three checks, in this order, before trusting any Cypher result.

1. **Check 1 — Graph path exists and is readable.** Before any Cypher query, verify `.cc-master/graph.kuzu` exists on disk as a file or directory (Kuzu's on-disk representation varies by version) and the process can read it. On failure → fall back to JSON read.

2. **Check 2 — Source hashes match.** For every JSON/markdown artifact the query depends on (`kanban.json`, `roadmap.json`, `discovery.json`, relevant `specs/*.md`), compute the file's current canonical hash and compare against `_source.content_hash`. On any mismatch → fall back to JSON read for that artifact.

3. **Check 3 — Query executes cleanly.** Run the Cypher query via `${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py`. If exit code is non-zero or stderr contains an error → fall back to JSON read.

A skill that passes Check 1 and 2 but fails Check 3 MUST NOT retry the query against the graph in the same session. Retrying masks real corruption and wastes tokens on the same failure. Fall back and proceed.

## First-Run Prompt

When `.cc-master/` exists but `.cc-master/graph.kuzu` does not, graph-backed skills MUST print the prompt exactly once per session on the first graph-read attempt. This is the centralized migration prompt — every graph-backed skill shares identical wording and identical decline semantics so the operator sees one coherent behavior across the entire pipeline. The `cc-master:index` skill itself is EXEMPT — when it is invoked on a cold project it builds the graph directly; it does not prompt.

The prompt text is verbatim:

```
Graph index not found at .cc-master/graph.kuzu/. Build now? (~30s for a medium project) [y/N]
```

Followed by a single-line follow-up printed on the next line, verbatim:

```
Decline → fall back to JSON for the remainder of this session.
```

1. **Accept path (`y` or `yes`, case-insensitive).** Invoke the Skill tool with the LITERAL strings `skill: "cc-master:index"` and `args: "--full"`. Wait for the invocation to complete. On success, retry the graph query from Check 1 onward — Check 1 now passes because the graph exists, Check 2 computes fresh hashes against the newly stamped `_source` rows, Check 3 runs the Cypher query against the now-populated database. If `cc-master:index --full` itself returns a non-zero exit code (binding missing, build error, etc.), fall back to JSON and emit the standard one-warning-per-session line. MUST NOT retry `cc-master:index` and MUST NOT enter a build loop.

2. **Decline path (`n`, anything else, empty input).** Set an in-session flag `graph_first_run_declined = true`. The flag exists only for the lifetime of the current skill invocation chain — it is not persisted to disk. All subsequent graph-read attempts in the same session MUST skip the prompt entirely and fall straight through to JSON fallback with the standard one-warning-per-session line. A skill that re-prompts after a decline is wrong, even if the operator re-invokes the same skill — the flag answers the question for the rest of the session.

3. **`--auto` mode.** When the invoking skill is run with `--auto` in its arguments, the skill MUST NOT print the prompt under any circumstance. It silently falls back to JSON and emits the standard one-warning-per-session line. `--auto` mode is for non-interactive pipelines where blocking on operator input is unacceptable; the prompt would hang the pipeline forever. Treat an absent graph under `--auto` as an automatic decline.

4. **`cc-master:index` exemption.** `cc-master:index` is the skill that builds the graph. It MUST NOT print the first-run prompt — when invoked on a cold project it proceeds directly to indexing. Every other graph-backed skill in the cc-master pipeline (align-check, api-payload-audit, build, complete, config-audit, config-sync, debug, doc-review, gap-check, impact, insights, kanban, kanban-add, perf-audit, pr-review, qa-loop, qa-review, qa-ui-review, release-docs, research, smoke-test, spec, stub-hunt, trace) MUST follow this prompt contract.

The prompt fires at most once per session. Once fired — whether accepted, declined, or silenced by `--auto` — the outcome governs every subsequent graph-read attempt in the same session. A skill that fires the prompt a second time in the same session is wrong.

## Output Indicator

Every graph-backed cc-master skill MUST emit a single-line status indicator on its final output reporting whether the graph was consulted, whether it was fresh, and whether the skill fell back to JSON. The indicator gives the operator a one-glance verdict on which path ran. Wording is fixed across all 25 graph-backed skills so the operator reads the same three strings everywhere.

1. **Indicator strings — verbatim, no variants.** The three values are the complete permitted set. No prefix, no suffix, no emoji, no color marker, no trailing punctuation. Copy the literal characters — the em-dash is U+2014, not two hyphens.

   ```
   Graph: fresh
   Graph: stale — fell back to JSON
   Graph: absent — fell back to JSON
   ```

2. **Footer placement rule.** The indicator MUST be the last line of the skill's primary summary output, printed before any chain-point prompt. If the skill emits multiple artifacts (e.g., `build` produces kanban updates AND a summary), the indicator appears at the bottom of the single primary summary block — it MUST NOT be duplicated per artifact. A skill that prints the indicator twice in the same invocation is wrong.

3. **State-detection logic.** The state is derived from the pre-query check outcomes recorded during this invocation; it is NEVER a hardcoded string pasted as a literal footer.
   - `Graph: fresh` — all three Pre-Query Checks passed for every dependent artifact; the Cypher path served the result.
   - `Graph: stale — fell back to JSON` — Check 2 hash mismatch triggered fallback for at least one dependent artifact during this invocation. Any post-check Cypher failure that forced a fallback during the same invocation also maps to `stale`.
   - `Graph: absent — fell back to JSON` — Check 1 reported the `.cc-master/graph.kuzu` path missing, so no Cypher query was attempted.

4. **Worst-state-wins rule (priority: absent > stale > fresh).** When a single query depends on multiple artifacts and their per-artifact states differ, the skill MUST report the worst observed state. Example: `kanban.json` fresh, `discovery.json` hash mismatched → `Graph: stale — fell back to JSON`. Example: graph directory missing and a spec hash would also mismatch → `Graph: absent — fell back to JSON`. Do NOT average, do NOT report per-artifact lines — emit one indicator for the whole invocation using the worst state seen.

5. **`--auto` and chained modes still print the indicator.** Silence is reserved for the first-run prompt (see `## First-Run Prompt`); status reporting is not silenced. A skill running under `--auto` that fell back to JSON MUST still emit `Graph: absent — fell back to JSON` (or `stale`, as applicable) as its final line. Pipelines rely on the indicator to tell accepted-path runs from fallback runs.

6. **Non-graph-backed skills MUST NOT print the indicator.** The indicator is a truthful report about a graph-read attempt. A skill that never touches `.cc-master/graph.kuzu/` has no state to report and MUST NOT emit any of the three strings — emitting one would be a lie about what the skill did.

7. **Error-phase default.** If the pre-query check phase itself errors before a state can be determined (e.g., `.cc-master/` unreadable), the indicator defaults to `Graph: absent — fell back to JSON`. NEVER omit the indicator silently on an error path — the operator must see that the graph was not consulted.

## Failure Modes

The following failure conditions are the full enumerated set of pre-query failures a read-side skill can encounter. Each maps to exactly one fallback action.

- `.cc-master/graph.kuzu` path absent (neither file nor directory) — Fallback action: read the dependent JSON artifact(s) directly and compute the result in memory.
- `_source` content hash mismatch for a dependent file — Fallback action: read that specific JSON/markdown artifact directly and compute the result from the live file, not the graph.
- Cypher parse error (kuzu_client exit code 4) — Fallback action: surface the Cypher text in a one-line diagnostic and fall back to JSON read; do not silently discard the error.
- Kuzu Python binding not installed (kuzu_client exit code 2) — Fallback action: print a one-line "graph binding missing — falling back to JSON" warning and read JSON for the remainder of the session.
- Database path corrupted or unreadable (kuzu_client exit code 3) — Fallback action: fall back to JSON read and emit a one-line warning suggesting the user delete `.cc-master/graph.kuzu/` and run `cc-master:index --full` to rebuild.
- Query returns schema that does not match caller's expectation (runtime validation failure) — Fallback action: fall back to JSON read; do not attempt to coerce, reshape, or partially consume the mismatched result.

## JSON Fallback Template

Skills SHOULD inline the following fragment as their fallback instruction block. Cite it verbatim — downstream behavior depends on the exact wording.

```
If any pre-query check above fails for this query, fall back to reading
.cc-master/<artifact>.json directly and computing the same result in memory.
Print one warning line per session on first fallback:
  "Graph absent/stale — falling back to JSON read for <artifact>"
Do NOT retry the graph query during the same session once fallback has
started — retries mask real corruption and waste tokens.
```

The one-warning-per-session rule is deliberate: a skill that emits a warning on every query floods the operator's terminal and trains them to ignore it. One warning, clearly worded, once per session.

## Hash Comparison Rule

Read-side skills that verify `_source.content_hash` against the live file MUST use the same algorithm the indexer (`cc-master:index`) uses. The algorithm varies by file type. Any other hashing approach will produce false mismatches and force unnecessary JSON fallback.

### JSON artifacts (kanban.json, roadmap.json, discovery.json)

Canonical-json (sorted keys, minimal separators) → SHA-256 hex. The JSON bytes are parsed, re-serialized with `sort_keys=True` and `separators=(",", ":")`, then the UTF-8 bytes of that canonical string are hashed. This absorbs key-order and whitespace noise — a pretty-printer does not trigger a mismatch; a real data edit does.

Exact one-liner:

```
python3 -c "import json,hashlib,sys; o=json.load(open(sys.argv[1])); print(hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':')).encode()).hexdigest())" <path>
```

### Markdown spec files (.cc-master/specs/*.md)

Raw bytes → SHA-256 hex. No normalization. Every whitespace, heading-style, and trailing-newline choice in a human-authored spec is intentional and counts as a real change. Do NOT trim, re-encode, or canonicalize the bytes before hashing.

Exact one-liner:

```
python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>
```

### Code-graph module walks (ast-grep-walk:<module-name>)

Wave-6 scope — currently not invoked by any skill. Composite hash: SHA-256 of the sorted lines `<file_path>:<file_content_hash>\n...`, where each per-file hash is the raw-bytes SHA-256 of that file and the lines are sorted by `file_path` in ASCII order, joined with `\n`. Detects file additions, deletions, or content changes anywhere inside a module with a single digest.

Note that read-side skills do NOT consume this pseudo-path in v1 — only the indexer does. It is documented here so the hash function remains unified across v1 and v2.

**Read-side check protocol**

1. Query: `MATCH (s:_source {file_path: $fp}) RETURN s.content_hash AS stored` for every source file the query depends on.
2. If no row found for a required file path → the graph has never indexed this file (or it was deleted) → fall back to JSON.
3. Compute the current hash from disk using the algorithm matching the file type.
4. If `current_hash != stored_hash` → fall back to JSON. Do NOT re-index (read-side skills are forbidden from writing to the graph).

**Never silently skip a hash mismatch.** A mismatch is the single signal read-side skills have that the graph is stale. Falling through to "trust the graph anyway" ships wrong answers that look right. Always fall back to JSON for the mismatched file.

Cross-references:

- `skills/index/SKILL.md`, section `## Content Hashing` — the authoritative implementation source for these algorithms. Read-side behavior here MUST match what the indexer writes.
- `docs/plans/2026-04-graph-engine-v1.md`, section "_source metadata table" (lines ~306-360) — schema source for the `_source` row shape, column types, and the governing invalidation algorithm.

Read-side skills MUST NOT invent their own hashing scheme or compare partial byte ranges. If the `_source` row is missing, absent, or unreadable for any reason, treat it as a hard hash mismatch — do not attempt to "trust by default" and do not assume the graph is fresh because the directory exists.

## Invariants (Re-stated for Emphasis)

These invariants are repeated here because every graph-backed skill will read this file as its contract, and the cost of a violation is data silently drifting between the graph and JSON. They are not subject to local override.

- Read-side skills MUST NOT mutate the graph. Ever. Even to "fix" stale data. Only `cc-master:index` writes. If a read-side skill detects corruption, its response is to fall back to JSON and emit a warning — not to repair, delete, or re-insert anything.
- Fail-closed, never fail-open. A fast wrong answer is worse than a slow right one. When in doubt about any pre-query check, fall back to JSON. The graph earning back trust is `cc-master:index`'s job, not a read-side skill's job.
- Every fallback path MUST return the same semantic result as the graph query — just slower. If the JSON fallback returns different data than the graph query would have, the fallback is wrong and the skill is broken. Test fallback paths against the graph-backed path for equivalence before shipping.

When any of these invariants conflict with a performance target or a user-visible wait, the invariant wins. Graph speed is an optimization; correctness is a contract.

## Citation Pattern

Every graph-backed cc-master skill MUST paste the following block verbatim into its `## Process` section at the first step that consumes `.cc-master/graph.kuzu/`. The block cites this contract, restates the three pre-query checks, states the one-warning-per-session rule, and carries the verbatim JSON-fallback fragment downstream. Pasting the block is how the contract propagates — a skill that paraphrases the block is not citing the contract, it is inventing its own.

```
First-run check — if .cc-master/graph.kuzu is absent, follow the ## First-Run Prompt section of this protocol before Check 1.
Before any graph query, this skill MUST follow the three pre-query checks in prompts/graph-read-protocol.md (directory exists, _source hash matches, query executes cleanly). On any check failure, fall back to JSON and emit one warning per session.
Check 1 — `.cc-master/graph.kuzu` exists on disk (file or directory, readable).
Check 2 — `_source.content_hash` matches the current on-disk hash for every dependent JSON/markdown artifact.
Check 3 — the Cypher query executes cleanly via `${CLAUDE_PLUGIN_ROOT}/scripts/graph/kuzu_client.py` (exit code 0, empty stderr).
Emit at most one fallback warning per session; do NOT retry the graph query after fallback has started.
Emit the Graph: <state> output indicator per the ## Output Indicator section as the last line of the primary summary.
If any pre-query check above fails for this query, fall back to reading
.cc-master/<artifact>.json directly and computing the same result in memory.
Print one warning line per session on first fallback:
  "Graph absent/stale — falling back to JSON read for <artifact>"
Do NOT retry the graph query during the same session once fallback has
started — retries mask real corruption and waste tokens.
```

The first-run check line is the single-line pointer to the `## First-Run Prompt` section and runs before Check 1 on any invocation where `.cc-master/graph.kuzu` is absent; the citation line is the single-line summary an operator or reviewer sees first; the three check restatements make the contract auditable inside the skill itself; the one-warning rule prevents terminal spam; the indicator-emission line binds the skill to print the `Graph: <state>` output indicator per the `## Output Indicator` section as the last line of its primary summary; the JSON-fallback fragment (copied verbatim from `## JSON Fallback Template`) is the exact behavior downstream consumers depend on. All six elements MUST appear together — a partial paste is a contract violation.
