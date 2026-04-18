# Graph Read Protocol — Fallback Contract

This document is cited by cc-master skills that read the Kuzu graph at `.cc-master/graph.kuzu/`. It defines the contract for safe graph reads and the fallback path to JSON when the graph is absent, stale, or erroring. Every graph-backed skill MUST cite this file and MUST follow every check below in order. This is not guidance — it is the contract. A skill that skips a check to save time is wrong, even if it appears to work.

The graph is a derived index over the JSON and markdown artifacts in `.cc-master/`. JSON is the source of truth; the graph is an acceleration. When the graph cannot be trusted, read-side skills MUST fall back to the JSON artifact and compute the same result in memory. Correctness first, speed second. See `docs/plans/2026-04-graph-engine-v1.md`, section "Architectural Invariants", for the governing rules this protocol implements.

## Pre-Query Checks

Every graph-backed skill MUST execute these three checks, in this order, before trusting any Cypher result.

1. **Check 1 — Graph path exists and is readable.** Before any Cypher query, verify `.cc-master/graph.kuzu` exists on disk as a file or directory (Kuzu's on-disk representation varies by version) and the process can read it. On failure → fall back to JSON read.

2. **Check 2 — Source hashes match.** For every JSON/markdown artifact the query depends on (`kanban.json`, `roadmap.json`, `discovery.json`, relevant `specs/*.md`), compute the file's current canonical hash and compare against `_source.content_hash`. On any mismatch → fall back to JSON read for that artifact.

3. **Check 3 — Query executes cleanly.** Run the Cypher query via `scripts/graph/kuzu_client.py`. If exit code is non-zero or stderr contains an error → fall back to JSON read.

A skill that passes Check 1 and 2 but fails Check 3 MUST NOT retry the query against the graph in the same session. Retrying masks real corruption and wastes tokens on the same failure. Fall back and proceed.

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
Before any graph query, this skill MUST follow the three pre-query checks in prompts/graph-read-protocol.md (directory exists, _source hash matches, query executes cleanly). On any check failure, fall back to JSON and emit one warning per session.
Check 1 — `.cc-master/graph.kuzu` exists on disk (file or directory, readable).
Check 2 — `_source.content_hash` matches the current on-disk hash for every dependent JSON/markdown artifact.
Check 3 — the Cypher query executes cleanly via `scripts/graph/kuzu_client.py` (exit code 0, empty stderr).
Emit at most one fallback warning per session; do NOT retry the graph query after fallback has started.
If any pre-query check above fails for this query, fall back to reading
.cc-master/<artifact>.json directly and computing the same result in memory.
Print one warning line per session on first fallback:
  "Graph absent/stale — falling back to JSON read for <artifact>"
Do NOT retry the graph query during the same session once fallback has
started — retries mask real corruption and waste tokens.
```

The citation line is the single-line summary an operator or reviewer sees first; the three check restatements make the contract auditable inside the skill itself; the one-warning rule prevents terminal spam; the JSON-fallback fragment (copied verbatim from `## JSON Fallback Template`) is the exact behavior downstream consumers depend on. All four elements MUST appear together — a partial paste is a contract violation.
