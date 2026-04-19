# Kanban Write Protocol — Write-and-Invalidate Contract

This document is the canonical write-and-invalidate contract for any cc-master skill that writes `.cc-master/kanban.json`. It is the write-side counterpart to `prompts/graph-read-protocol.md` (the read-side fallback contract). Together the two fragments define the full graph-integration contract for kanban: read through the graph with a JSON fallback when the graph is absent or stale, and stamp the graph after every write so the next graph-backed skill sees a fresh `_source.content_hash`. Every cc-master skill that mutates `.cc-master/kanban.json` — whether through initial task insertion, status flips, owner assignments, `blocked_by` rewrites, `metadata.gh_issue_number` / `metadata.gh_issue_url` link-backs, or any other field-level edit — MUST cite this file and MUST follow the four-step protocol below in order. This is not guidance; it is the contract. A skill that skips invalidation to save time is wrong, even if it appears to work — the failure surfaces later, on a downstream graph-backed read, as data silently drifting between the JSON artifact and the Kuzu graph.

## The Four-Step Protocol

Every kanban-writing cc-master skill MUST execute the following four steps, in this order, exactly once per invocation. Steps 1–3 are the JSON-write half of the contract and apply to every individual mutation; Step 4 is the graph-invalidation half and fires exactly ONCE at the end of the invocation regardless of how many mutations Steps 1–3 produced (see `## Batch Coalescing — One --touch Per Invocation` below).

1. **Step 1 — Read `.cc-master/kanban.json` and parse JSON.** Use the Read tool to load the file. If the file does not exist, treat it as the empty document `{"version": 1, "next_id": 1, "tasks": []}`. Parse the JSON into an in-memory object before applying any mutation. Do not stream-edit the file on disk; do not append-write fragments; do not use a JSON-patch tool. The whole file is read, the whole file is rewritten.

2. **Step 2 — Apply mutations in memory.** Apply every kanban mutation this invocation needs to the in-memory object. For new tasks: assign `id = next_id`, increment `next_id`, append the task to `tasks[]`. For existing tasks: find by `id` and modify the named fields in place. For every mutation (create or update), set `updated_at` on the affected task to the current ISO-8601 UTC timestamp. Multiple mutations against the same kanban load (e.g., a multi-task batch, a status flip plus a `metadata` link-back on the same task) MUST all be applied to the same in-memory object before Step 3 writes back. Do not loop Read → mutate → Write per task; that pattern produces the wasted `--touch` outcomes documented in `## Batch Coalescing` below.

3. **Step 3 — Write the JSON back to disk.** Use the Write tool to serialize the mutated in-memory object back to `.cc-master/kanban.json`. The file content is the entire updated document, not a diff or a patch. After Step 3 returns successfully, the JSON artifact is the new source of truth — Step 4's invalidation call is what brings the derived graph back into agreement with that source of truth.

4. **Step 4 — Invoke the Skill tool EXACTLY ONCE per invocation.** After all kanban writes for this invocation have completed successfully, invoke the Skill tool with the LITERAL strings:

   - `skill: "cc-master:index"`
   - `args: "--touch .cc-master/kanban.json"`

   These are literal string constants — never placeholders, never variables, never user-supplied values. The path argument is always exactly `.cc-master/kanban.json`. This makes argument-validation failures (exit code `2`) impossible under normal operation; if exit code `2` is observed, it signals a skill-author code mistake (typo in the path or an unknown flag combination) and must be surfaced loudly per `## Fail-Open Recovery`.

## Exit-Code Contract

Inspect the exit code returned by the `cc-master:index` Skill invocation. The touch path uses the exit-code contract documented in `skills/index/SKILL.md` under `## --touch Single-File Refresh` → Substep T.6. The codes below mirror that table verbatim — do not invent additional codes, and do not collapse codes together. Each row is a distinct outcome with a distinct meaning.

| Code | Meaning | When |
|------|---------|------|
| `0`  | Success | The stamped `_source` row outcome was `changed`, `unchanged`, or `deleted`, AND the close call inside the touch path succeeded. All three sub-outcomes are valid; the kanban-writing skill continues silently. |
| `1`  | Unexpected error | Any failure not covered by `2`, `3`, or `4` (defensive default — should not occur on a well-formed input). |
| `2`  | Argument validation failure | Rejected by `cc-master:index`'s argument parser (missing value, unknown flag, `--touch` combined with `--full`). This MUST NOT happen here because the path is the literal constant `.cc-master/kanban.json` and the only flag is `--touch`. If exit code `2` is observed, the skill author has made a code mistake — surface the failure loudly with the warning wording in `## Fail-Open Recovery` and treat it as a bug to fix rather than a transient error. |
| `3`  | Kuzu database-path issue | `.cc-master/graph.kuzu/` is missing, unreadable, or cannot be opened; or the `close` call inside the touch path fails. |
| `4`  | Cypher error during touch execution | Any non-zero exit from `kuzu_client.py query` during the touch path's DELETE statements or `_source` MERGE statements. This is the most common failure mode in practice. |

Any other non-zero exit code is treated the same way as `3` and `4`: emit the warning and continue. Per the read-side contract (`prompts/graph-read-protocol.md`), the next graph-backed skill's hash-check picks up the staleness and falls back to JSON, preserving correctness.

## Batch Coalescing — One --touch Per Invocation

When a single skill invocation produces multiple `kanban.json` writes — a multi-task batch (e.g., `build 3,5,7` flipping three tasks `in_progress` → `done`), a multi-step write (e.g., a task create followed by a `metadata.gh_issue_number` link-back), a `blocked_by` rewrite that touches several blocking edges, or any other pattern where Step 3 fires more than once before the skill exits — the skill MUST invoke `/cc-master:index --touch .cc-master/kanban.json` **EXACTLY ONCE at the end of the invocation, after the LAST kanban write**. Never once per write, never once per task, never inside a per-task loop.

Rationale: `--touch` is a hash-keyed single-file refresh — it compares the on-disk content hash to the stored `_source.content_hash` and only re-indexes when they differ. N per-write calls against a file that is still being mutated would produce N-1 `unchanged` outcomes (the file hash moves between mutations but the stored hash only updates on the call that wins the race) plus one final `changed` outcome that actually does the useful work, wasting the subprocess-spawn latency of the other N-1. A single coalesced call after the last write ensures exactly one `changed` outcome per session and one cheap round-trip to Kuzu.

If zero writes happened (e.g., the user selected a no-op path, every dedup candidate was skipped, the invocation was cancelled before any mutation landed), the skill MAY skip the `--touch` call entirely — there is nothing to invalidate. In every other case, fire it once at the end.

## Fail-Open Recovery

If `cc-master:index --touch` returns ANY non-zero exit code (`1`, `2`, `3`, `4`, or anything else), the kanban.json write **STANDS**. The skill MUST NOT roll back, delete, or undo any mutation that Step 3 wrote to disk. The order of operations is strict: write `kanban.json` first, fire the one-shot `--touch` second; if the touch fails, the JSON write is already final, the task is created, the status flip is recorded, the `metadata` link-back is in place, and the skill exits with a zero status on the kanban side.

On any non-zero exit, emit EXACTLY ONE warning line per session, substituting the observed exit code for `<N>`:

```
Warning: graph invalidation failed (exit code <N>) — next graph-backed skill will fall back to JSON. Run /cc-master:index --full to rebuild.
```

Do not emit additional diagnostic lines. Do not retry the touch. Do not prompt the user. The single warning line is the entire recovery protocol on the write side. Operators who see the warning can run `/cc-master:index --full` out-of-band to re-stamp every source file and bring the graph back into agreement with the JSON artifacts.

This is the write-side counterpart to `prompts/graph-read-protocol.md`'s **fail-closed** read-side rule: read-side skills, when they detect a stale or absent graph, fall back to reading JSON and emit one fallback warning per session; write-side skills, when they detect a failed invalidation, accept the write and emit one invalidation-failure warning per session. The asymmetry is deliberate — the write has already happened and is correct; the read can refuse to trust the graph. Both sides converge on the same invariant: JSON is authoritative, the graph is a derived index, correctness is preserved unconditionally.

## JSON Is Authoritative

`.cc-master/kanban.json` is the source of truth for every kanban task in the project. The Kuzu graph at `.cc-master/graph.kuzu/` is a derived index over that JSON — it exists to accelerate graph-backed reads (kanban render, dedup, blocked-by traversal, spec context-load), not to be a parallel source of truth. The four-step protocol above codifies this asymmetry: the write goes to JSON, then the graph is told the JSON has changed.

The next graph-backed skill's hash-check (per `prompts/graph-read-protocol.md` Check 2 — `_source.content_hash` compared against the live file's canonical-JSON SHA-256) catches any missed invalidation by falling back to JSON for the affected artifact. Correctness is preserved unconditionally — the only cost of a missed `--touch` is a one-time fallback to JSON until someone runs `/cc-master:index --full` and re-stamps every source. The graph never silently ships a wrong answer; the worst it does is degrade gracefully to the same answer the JSON read would have produced, just slower.

This invariant is the reason `## Fail-Open Recovery` is safe: a failed invalidation cannot corrupt the user's data, because the user's data lives in the JSON artifact, not in the graph. The graph is rebuildable from the JSON at any time with a single `cc-master:index --full` call.

## Graph-Absent Behavior

If `.cc-master/graph.kuzu` does not exist on disk (neither as a file nor as a directory — Kuzu's on-disk representation varies by version), the `--touch` invocation is a no-op from the user's perspective: `cc-master:index` itself handles the absent-graph case internally and returns the appropriate exit code (typically `3` per the table above, though the kanban-writing skill does not need to branch on this). The kanban-writing skill MUST still invoke `--touch` unconditionally — the skill does NOT pre-check graph presence before firing Step 4. This rule is load-bearing: it keeps the citation block in `## Citation Pattern` IDENTICAL across all 22 kanban-writing skills, eliminates a subtle pre-check race (graph appears between the check and the call, or vice versa), and centralizes graph-absent handling inside `cc-master:index` where it belongs.

If the graph is absent and the touch returns non-zero, `## Fail-Open Recovery` applies normally: the kanban write stands, one warning is emitted, the next graph-backed read falls back to JSON. The user's first `cc-master:index --full` invocation will materialize the graph and re-stamp every source from scratch — kanban included.

## Citation Pattern

Every kanban-writing cc-master skill MUST paste the following block verbatim into its `## Post-Write Invalidation` section. Pasting the block is how the contract propagates — a skill that paraphrases the block is not citing the contract, it is inventing its own. The block is self-contained: a downstream skill author who has never opened `prompts/kanban-write-protocol.md` can read the block in the citing skill and execute the contract correctly from the block alone.

```
This skill writes `.cc-master/kanban.json` and MUST follow the write-and-invalidate
contract in prompts/kanban-write-protocol.md. The four-step protocol is:
  1. Read `.cc-master/kanban.json` and parse JSON (treat missing file as
     {"version": 1, "next_id": 1, "tasks": []}).
  2. Apply all mutations in memory — assign new IDs from next_id, append new tasks,
     modify fields on existing tasks, set updated_at on every affected task.
  3. Write the entire updated JSON document back to `.cc-master/kanban.json`.
  4. After ALL kanban writes for this invocation have completed, invoke the Skill
     tool EXACTLY ONCE with:
       skill: "cc-master:index"
       args: "--touch .cc-master/kanban.json"
     These are LITERAL strings — never placeholders, never variables.

Batch coalescing — one --touch per invocation. When a single invocation produces
multiple kanban.json writes (multi-task batch, create + link-back, multi-edge
blocked_by rewrite), fire the --touch EXACTLY ONCE at the end after the LAST write,
never per write and never per task. If zero writes happened, skip the --touch
entirely.

Fail-open recovery. If cc-master:index --touch returns ANY non-zero exit code, the
kanban.json write STANDS — never roll back, never delete, never undo. Emit EXACTLY
ONE warning line per session:
  Warning: graph invalidation failed (exit code <N>) — next graph-backed skill will fall back to JSON. Run /cc-master:index --full to rebuild.
Substitute the observed exit code for <N>. Do NOT retry the touch. Do NOT prompt the
user. The single warning line is the entire write-side recovery protocol — the next
graph-backed read will hash-check, detect staleness, and fall back to JSON per
prompts/graph-read-protocol.md. Correctness is preserved unconditionally.
```

The literal strings `cc-master:index` and `--touch .cc-master/kanban.json` MUST appear in the pasted block exactly as shown — they are the contract surface. The four-step protocol restatement makes the contract auditable inside the citing skill itself. The batch-coalescing rule prevents the most common implementation bug (per-write touch in a loop). The fail-open paragraph closes the loop by stating what happens when the invalidation fails. All four elements MUST appear together — a partial paste is a contract violation.
