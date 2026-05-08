# v0.21.0 Validation — Scratch Notes

Scratch notes for task #22 (v2 graph engine integration smoke test). Consumed by subtasks #115 (pipeline run), #116 (measurements), and #117 (validation-section writeup into `docs/plans/2026-04-graph-engine-v1.md`). Produced by subtask #114.

## Target Project

- Path: `/Users/mstjohn/Documents/SRC/LJK/cc-master`
- Kanban tasks: 117 (counted from `.cc-master/kanban.json` tasks array)
- Specs: 22 active (`.cc-master/specs/*.md`, top level only; 12 additional specs live under `.cc-master/specs/archive-*/` and were excluded per the spec's "excluding archive directories" rule)
- Dogfooding: yes (cc-master repo itself is the validation target)

### Target project selection rationale

Probed `/Users/mstjohn/Documents/SRC/LJK/*/` and `/Users/mstjohn/Documents/SRC/*/` for sibling projects with `.cc-master/kanban.json`:

| Candidate | Path | Tasks |
|-----------|------|-------|
| cc-master (self) | `/Users/mstjohn/Documents/SRC/LJK/cc-master` | 117 |
| SF | `/Users/mstjohn/Documents/SRC/LJK/SF` | 67 |
| escrow-domains-ui | `/Users/mstjohn/Documents/SRC/LJK/escrow-domains-ui` | 4 (below AC threshold) |

cc-master itself was selected because (a) it has the largest kanban and the richest spec corpus (22 active specs vs. SF's unknown spec count — probe kept to <2 min per instructions), (b) spec #22 acceptance criteria explicitly permit cc-master as a "large real project" with ≥20 kanban tasks, and (c) the v2 graph engine under test is developed in this same repo, so end-to-end wiring (kuzu_client.py, astgrep_walker.py, `.cc-master/graph.kuzu/` location, `prompts/graph-read-protocol.md`, `prompts/kanban-write-protocol.md`) is guaranteed to be the exact commit being released. The dogfooding caveat is that the graph engine is validating itself; subtask #117 must disclose this in the release doc's validation section.

## Environment

- **OS:** macOS 26.0.1 (build 25A362), Darwin kernel 25.0.0 (arm64, `mikes-MacBook-Pro.local`)
- **Hardware:** Apple `Mac16,7` (arm64), 14 CPU cores, 25,769,803,776 bytes RAM (24 GiB)
- **cc-master commit:** `cff23024549942c8abd30beaaa3a2fc3fb042de2` (branch `v2-graph-engine`; latest merge is "Merge wave 8 (task 18) into v2-graph-engine")
- **cc-master plugin version:** `0.21.0-dev.5` (from `.claude-plugin/plugin.json` `version` field; will finalize to `0.21.0` in wave 9)
- **Kuzu:** pinned to `0.11.2` in `.claude-plugin/plugin.json` `dependencies.kuzu` block (optional dependency, `interface: python3`). NOT currently installed in the system Python 3.14 interpreter — `python3 -c "import kuzu"` raises `ModuleNotFoundError`, and `bash scripts/graph/check_kuzu.sh` exits 2 with the install-instruction message. **Subtask #115 MUST install `kuzu==0.11.2` into the interpreter used by `scripts/graph/kuzu_client.py` before running the pipeline, and #116 MUST record the actually-installed version (from `python3 -c "import kuzu; print(kuzu.__version__)"`) in the final release doc.**
- **ast-grep:** `0.42.1` (from `ast-grep --version`; also accessible as `sg 0.42.1`). No version pin found in `plugin.json`.
- **Python:** `3.14.3` (main, Feb 3 2026, 15:32:20) at `/opt/homebrew/bin/python3` → `/opt/homebrew/opt/python@3.14/bin/python3.14`, Clang 17.0.0 (clang-1700.6.3.2)
- **Run date:** `2026-04-19T07:38:07Z` (ISO-8601 UTC; captured with `date -u +"%Y-%m-%dT%H:%M:%SZ"`)

## Pipeline Plan (for subtask #115)

#115 will exercise the full graph-backed pipeline against the cc-master target by (1) installing `kuzu==0.11.2` into the Python interpreter the scripts resolve to, (2) wiping `.cc-master/graph.kuzu/` (if present) and invoking `cc-master:index` to run the ast-grep v1 indexer end-to-end, (3) running one representative read skill (`cc-master:impact` on a high-traffic file such as `scripts/graph/kuzu_client.py`) to exercise the graph-only path, and (4) running one representative write skill (`cc-master:kanban-add` manual mode to append a sentinel task, then verifying the `--touch` invalidation marker was written per `prompts/kanban-write-protocol.md`). No PRs, no merges, no deletions — strictly read/write within the worktree's `.cc-master/` (which is gitignored and therefore disposable).

## Measurement Plan (for subtask #116)

Five measurements map to concrete scripts already checked into `scripts/graph/`:

- **Kanban token savings** — run `bash scripts/graph/measure_kanban_savings.sh` from the target project root. This is the same script that verified the 6.7× reduction in wave 3 and should emit a JSON or stdout table with baseline vs. graph-backed token counts. Record the ratio.
- **Spec-context token savings** — run `bash scripts/graph/measure_spec_context_savings.sh` on a representative spec (e.g., the generated spec for task #19, #20, #21, or #22). Wave 5 recorded 6.7× reduction; confirm the figure is stable on current commit.
- **Code-graph indexing throughput** — run `bash scripts/graph/measure_code_graph_index.sh`. This should emit files/sec and total-seconds for the full cc-master walk. Record both; subtask #117 will cite files-per-second in the release doc.
- **Graph read latency for impact** — wrap the `cc-master:impact` invocation from the pipeline plan in `time` (or `/usr/bin/time -p` for portable real/user/sys) and capture wall-clock. Median of 3 runs with `.cc-master/graph.kuzu/` warm. Record ms.
- **Fallback correctness sanity** — run `bash scripts/graph/verify_fallback.sh` (temporarily renaming `.cc-master/graph.kuzu/` to simulate absent graph) and confirm the JSON-fallback path in `prompts/graph-read-protocol.md` still returns a non-empty result. This is a correctness check, not a timing measurement — pass/fail only.

All five measurements MUST be captured into the release doc's validation section by #117 along with the environment metadata above so the run is reproducible.

## Pipeline Run Results

All operations executed from `/Users/mstjohn/Documents/SRC/LJK/cc-master` (branch `v2-graph-engine`, commit `cff23024549942c8abd30beaaa3a2fc3fb042de2`) on 2026-04-19. Wall-clock captures use `/usr/bin/time -p` or the built-in timing emitted by `measure_code_graph_index.sh`.

### Operation 1 — Install Kuzu

Command: `pip3 install kuzu==0.11.2` (system Python 3.14, Homebrew).

Outcome: **blocked on Python 3.14**. Two attempts:

1. `pip3 install kuzu==0.11.2 2>&1 | tail -5` → rejected by PEP 668 (`error: externally-managed-environment`) — Homebrew's system Python is marked externally managed and refuses installs without `--break-system-packages`.
2. `pip3 install --user --break-system-packages kuzu==0.11.2 2>&1 | tail -15` → source build invoked because no prebuilt wheel exists for Python 3.14 / arm64; the build failed inside `setup.py build_extension` with `subprocess.CalledProcessError: Command '['make', 'clean']' returned non-zero exit status 2` followed by `ERROR: Failed building wheel for kuzu`. The kuzu 0.11.2 sdist on PyPI does not include the prebuilt vendor binaries the installer expects to find.

Fallback: Python 3.13 via Homebrew (`/opt/homebrew/bin/python3.13`). Commands:

```
python3.13 -m venv /tmp/kuzu-venv
/tmp/kuzu-venv/bin/pip install kuzu==0.11.2 2>&1 | tail -5
```

Result: `Successfully installed kuzu-0.11.2`. Verification:

```
$ /tmp/kuzu-venv/bin/python3 -c "import kuzu; print(kuzu.__version__)"
0.11.2
```

The system `python3` (3.14.3) still cannot import kuzu — confirmed by `python3 -c "import kuzu"` returning `ModuleNotFoundError: No module named 'kuzu'`. All subsequent operations therefore prepend `/tmp/kuzu-venv/bin` to `PATH` so that `python3` (as invoked by the scripts) resolves to the venv interpreter. `bash scripts/graph/check_kuzu.sh` under this PATH prints `kuzu 0.11.2` and exits 0 (run under `PATH="/tmp/kuzu-venv/bin:$PATH" bash scripts/graph/check_kuzu.sh`).

**Narrative.** kuzu 0.11.2 is incompatible with Python 3.14 on macOS arm64 at PyPI. A Python 3.13 venv is required today. Subtask #117 MUST document this prerequisite in the release doc's validation section; subtask #116 MUST record the venv path or interpreter version used for every measurement.

### Operation 2 — Cold full index

Because `cc-master:index` is a Claude Code slash command (not a shell binary), no purely-shell invocation can drive the full indexer. For this operation, a minimal driver script (`/tmp/cc-master-index-driver.py`, 108 lines) was written that (a) runs `scripts/graph/astgrep_walker.py` across the repo, (b) creates `File`, `Symbol`, and `REFERENCES` tables in a fresh Kuzu database at `.cc-master/graph.kuzu`, and (c) upserts the walker's output. This exercises the code-graph write path end-to-end but omits `Task`/`Subtask`/`Spec`/`Feature`/`Module`/`_source` node families that `cc-master:index` also writes. The limitation is documented explicitly here so #117 does not over-claim full-pipeline coverage.

Command:

```
CC_BENCH_REPO="$(pwd)" PATH="/tmp/kuzu-venv/bin:$PATH" \
  bash scripts/graph/measure_code_graph_index.sh \
  --invoke "/tmp/kuzu-venv/bin/python3 /tmp/cc-master-index-driver.py"
```

Driver JSON (stdout from the driver, emitted inside the measured region):

```
{"walk_seconds": 0.541, "upsert_seconds": 6.375, "total_seconds": 6.917, "files_walked": 568, "symbols_walked": 90, "refs_walked": 804, "edges_emitted": 153}
```

`measure_code_graph_index.sh` summary (post-run Kuzu counts queried directly from the graph):

```
Target repo:    /Users/mstjohn/Documents/SRC/ljk/cc-master
Mode:           cold
Elapsed:        7s
Files indexed:  568
Symbols:        90
References:     153
Artifact:       .cc-master/graph-perf/2026-04-19T07-43-04Z.json
SCALING PASS: 7s <= 60s.
```

Exit code: `0`. Stderr (first 20 lines):

```
CC_BENCH_REPO not set — measuring current repo
Running: /cc-master:index --code-graph
Driver:  /tmp/kuzu-venv/bin/python3 /tmp/cc-master-index-driver.py
Mode:    cold
```

(The `CC_BENCH_REPO not set` line is emitted when `CC_BENCH_REPO` is unset; in the recorded run it WAS set to the repo root, so the line may not appear in the operator's rerun — the measure script only logs it when the variable is unset.)

Graph directory size after cold build:

```
$ du -sh .cc-master/graph.kuzu
 10M	.cc-master/graph.kuzu
$ ls -la .cc-master/graph.kuzu
-rw-r--r--@ 1 mstjohn  staff  10330112 Apr 19 03:43 .cc-master/graph.kuzu
```

Kuzu 0.11.2 on this machine stores the DB as a **single file** (10.3 MB) rather than a directory — see `scripts/graph/verify_fallback.sh` comments for why `-e` (not `-d`) is the correct presence check.

**Narrative.** Cold index of the 568-file cc-master repo takes **6.9 s** total (0.54 s ast-grep walk + 6.4 s Kuzu MERGE upsert). The 60 s scaling gate passes with a 53 s margin. Only 153 REFERENCES edges were created from 804 walker references — the other 651 have `symbol_id: null` because the walker's v1 resolution does not follow cross-module imports (documented limitation; SCIP swap in v0.22 will reduce the null rate).

### Operation 3 — --touch round trip (warm re-index proxy)

`kuzu_client.py` has no `--touch` subcommand — the `--touch <file>` flag is a skill-level argument on `cc-master:index`. The closest shell-reproducible analog is a warm re-run after editing `.cc-master/kanban.json`.

Edit command:

```
python3 -c "import json, pathlib; p=pathlib.Path('.cc-master/kanban.json'); d=json.loads(p.read_text()); d['tasks'][0]['updated_at']='2026-04-19T07:44:00Z'; p.write_text(json.dumps(d, indent=2))"
```

This changed `tasks[0].updated_at` from `2026-04-18T00:00:00Z` to `2026-04-19T07:44:00Z`. Warm re-run:

```
CC_BENCH_REPO="$(pwd)" PATH="/tmp/kuzu-venv/bin:$PATH" \
  bash scripts/graph/measure_code_graph_index.sh --warm \
  --invoke "/tmp/kuzu-venv/bin/python3 /tmp/cc-master-index-driver.py"
```

Driver JSON:

```
{"walk_seconds": 0.535, "upsert_seconds": 6.362, "total_seconds": 6.897, "files_walked": 569, "symbols_walked": 90, "refs_walked": 804, "edges_emitted": 153}
```

Measure summary:

```
Target repo:    /Users/mstjohn/Documents/SRC/ljk/cc-master
Mode:           warm
Elapsed:        7s
Files indexed:  569
Symbols:        90
References:     306
```

Exit code `0`, artifact `.cc-master/graph-perf/2026-04-19T07-43-28Z.json`. `Files indexed` rose from 568 → 569 because the cold run's own artifact (`.cc-master/graph-perf/2026-04-19T07-43-04Z.json`) became a new JSON file inside the walk scope. `References` rose from 153 → 306 because the minimal driver does not DELETE prior REFERENCES rows before re-inserting (this is a known limitation of the validation driver — the real `cc-master:index` per-module DELETE-then-INSERT semantics described in `scripts/graph/README.md` lines 79-82 are not implemented in the 108-line driver). The true incremental upsert cost of `cc-master:index --touch .cc-master/kanban.json` will be materially lower than 6.9 s, because the slash-command path parses only the single touched file rather than walking the whole repo; that measurement requires a non-interactive driver for the skill, which #116 should construct if the number is load-bearing.

Revert command:

```
python3 -c "import json, pathlib; p=pathlib.Path('.cc-master/kanban.json'); d=json.loads(p.read_text()); d['tasks'][0]['updated_at']='2026-04-18T00:00:00Z'; p.write_text(json.dumps(d, indent=2))"
```

Post-revert check: `python3 -c "import json; d=json.load(open('.cc-master/kanban.json')); print(d['tasks'][0]['updated_at'], len(d['tasks']))"` prints `2026-04-18T00:00:00Z 117`. Kanban state restored.

**Narrative.** Warm re-run wall-time is effectively identical to cold (6.9 s) because the minimal driver re-upserts everything; it is NOT a faithful measurement of `cc-master:index --touch` single-file latency. The round-trip proved the driver is idempotent on file/symbol MERGE (counts unchanged) but not on REFERENCES (counts doubled — documented).

### Operation 4 — Graceful degradation (graph absent → exit 3)

Commands (executed as a single shell sequence):

```
mv .cc-master/graph.kuzu .cc-master/graph.kuzu.offline
PATH="/tmp/kuzu-venv/bin:$PATH" python3 scripts/graph/kuzu_client.py \
  query .cc-master/graph.kuzu "MATCH (f:File) RETURN count(f) AS n"
echo "exit=$?"
mv .cc-master/graph.kuzu.offline .cc-master/graph.kuzu
```

Captured output:

```
{"error": "database not found at /Users/mstjohn/Documents/SRC/LJK/cc-master/.cc-master/graph.kuzu"}
exit=3
```

Post-restore size:

```
$ ls -la .cc-master/graph.kuzu
-rw-r--r--@ 1 mstjohn  staff  14712832 Apr 19 03:43 .cc-master/graph.kuzu
```

**Narrative.** `kuzu_client.py query` against an absent graph path returns a single-line JSON error on stderr and exits with code **3**, matching the declared contract in `scripts/graph/README.md` (Exit codes table, row "3 — Database path not found"). The read-protocol's Check 1 therefore triggers deterministically when the graph is missing. Graph was moved aside and moved back — no data loss. (The size grew to 14.7 MB because Operation 3's warm re-run doubled the REFERENCES rows; the graph is otherwise intact.)

### Operation 5 — Impact accuracy (`_load_kuzu`)

Ground truth via `grep -rn "_load_kuzu" scripts/ .cc-master/worktrees/ 2>/dev/null`:

```
scripts/graph/kuzu_client.py:38:def _load_kuzu():
scripts/graph/kuzu_client.py:72:    kuzu = _load_kuzu()
scripts/graph/kuzu_client.py:96:    kuzu = _load_kuzu()
scripts/graph/kuzu_client.py:146:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py:38:def _load_kuzu():
.cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py:72:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py:96:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py:146:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py:38:def _load_kuzu():
.cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py:72:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py:96:    kuzu = _load_kuzu()
.cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py:146:    kuzu = _load_kuzu()
```

12 total lines — 3 definitions (one per file, line 38) and 9 calls (three files × lines 72/96/146).

Graph symbol query:

```
$ PATH="/tmp/kuzu-venv/bin:$PATH" python3 scripts/graph/kuzu_client.py query \
    .cc-master/graph.kuzu \
    "MATCH (sym:Symbol {name: '_load_kuzu'}) RETURN sym.id AS id, sym.kind AS kind, sym.file AS file, sym.line AS line"
[{"id": "037d6b2c1991f7ee", "kind": "function", "file": "scripts/graph/kuzu_client.py", "line": 38},
 {"id": "b7307057a0908cb6", "kind": "function", "file": ".cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py", "line": 38},
 {"id": "e9da52f354f306ea", "kind": "function", "file": ".cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py", "line": 38}]
```

3 Symbol nodes, one per walked copy. All three hashes are deterministic per the 16-char sha256 rule in `scripts/graph/README.md` line 147.

Graph reference query (DISTINCT because Operation 3 left duplicate edges):

```
$ PATH="/tmp/kuzu-venv/bin:$PATH" python3 scripts/graph/kuzu_client.py query \
    .cc-master/graph.kuzu \
    "MATCH (f:File)-[r:REFERENCES]->(sym:Symbol {name: '_load_kuzu'}) RETURN DISTINCT f.path AS file, r.line AS line ORDER BY file, line"
[{"file": ".cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py", "line": 72},
 {"file": ".cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py", "line": 96},
 {"file": ".cc-master/worktrees/batch-1-2-3/scripts/graph/kuzu_client.py", "line": 146},
 {"file": ".cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py", "line": 72},
 {"file": ".cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py", "line": 96},
 {"file": ".cc-master/worktrees/batch-19-22/scripts/graph/kuzu_client.py", "line": 146},
 {"file": "scripts/graph/kuzu_client.py", "line": 72},
 {"file": "scripts/graph/kuzu_client.py", "line": 96},
 {"file": "scripts/graph/kuzu_client.py", "line": 146}]
```

9 distinct (file, line) call sites — matches the 9 call lines in the grep ground truth exactly.

Combined: graph returned 3 definitions + 9 distinct calls = **12 results**; grep ground truth = **12 hits**.

- **Precision:** 12 / 12 = **100%** — every result returned by the graph query appears in the grep ground truth.
- **Recall:** 12 / 12 = **100%** — every grep hit appears in the graph output.

**Narrative.** For an intra-file function like `_load_kuzu` (definition and calls within the same Python file), the ast-grep v1 walker resolves all three call sites correctly and Kuzu round-trips them without loss. The three-way duplication across `scripts/graph/kuzu_client.py` and its two worktree copies surfaces because the cold-index walker did not exclude `.cc-master/worktrees/` — all three copies are real files the walker legitimately saw. This is an accuracy-positive result but also a hint that subtask #117 should document the walker's default ignore list (per `scripts/graph/README.md` line 158) and recommend adding `.cc-master/worktrees/` to it for dogfooded runs. Cross-module / dynamic-dispatch recall cannot be evaluated on this target because the chosen symbol is purely local — the MEMORY.md note about ast-grep v1's dynamic-dispatch blindspot (~80% accuracy) is the better framing for the next impact-accuracy test.

