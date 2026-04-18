# scripts/graph/

Helper scripts for the cc-master v2 graph engine. All scripts are optional — the plugin functions without them, with graph-backed skills falling back to JSON reads.

## check_kuzu.sh

Verifies the Kuzu Python binding is installed.

**Usage:**

    bash scripts/graph/check_kuzu.sh

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0    | Installed — stdout: `kuzu <version>` |
| 2    | Not installed or python3 missing — stderr: install command |

**Example (success):**

    $ bash scripts/graph/check_kuzu.sh
    kuzu 0.11.2

**Example (absent):**

    $ bash scripts/graph/check_kuzu.sh
    kuzu Python binding is required for the v2 graph engine.
    Install:
      pip install kuzu==0.11.2     # pin the version from plugin.json
      pipx install kuzu            # isolated environment alternative
    # exit 2

## kuzu_client.py

Thin Python CLI wrapper around the Kuzu bindings. All stdout is JSON. All errors go to stderr as `{"error": "<msg>"}` with a non-zero exit code.

**Subcommands:**

    python3 scripts/graph/kuzu_client.py init <db_path>
    python3 scripts/graph/kuzu_client.py query <db_path> <cypher> [--params-json <json>]
    python3 scripts/graph/kuzu_client.py close <db_path>

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0    | Success — stdout: JSON result |
| 1    | Argument parsing error or unexpected exception |
| 2    | Kuzu Python binding not installed |
| 3    | Database path not found (query/close against non-existent db) |
| 4    | Cypher parse or runtime error |

**Example — init:**

    $ python3 scripts/graph/kuzu_client.py init /tmp/cc-test.kuzu
    {"status": "ok", "db_path": "/tmp/cc-test.kuzu", "kuzu_version": "0.11.2"}

**Example — simple query:**

    $ python3 scripts/graph/kuzu_client.py query /tmp/cc-test.kuzu "RETURN 1 AS one"
    [{"one": 1}]

**Example — parameterized query:**

    $ python3 scripts/graph/kuzu_client.py query /tmp/cc-test.kuzu \
        "MATCH (t:Task {id: $tid}) RETURN t.subject" \
        --params-json '{"tid": 42}'
    [{"t.subject": "Add user authentication"}]

**Example — Cypher error:**

    $ python3 scripts/graph/kuzu_client.py query /tmp/cc-test.kuzu "INVALID CYPHER"
    {"error": "..."}
    # exit 4

**Invariant:** Only `cc-master:index` executes write Cypher (CREATE / MERGE / DELETE). All other skills use MATCH / RETURN only. See [`docs/plans/2026-04-graph-engine-v1.md`](../../docs/plans/2026-04-graph-engine-v1.md).

## Prerequisite checks

Summary of the check scripts for the v2 graph engine's optional dependencies.

| Script | Checks for | Exit 0 | Exit 2 | Exit 3 |
|--------|-----------|--------|--------|--------|
| `check_kuzu.sh` | Python `kuzu` binding | `kuzu X.Y.Z` on stdout | not installed (stderr: install command) | unused |
| `check_astgrep.sh` | `ast-grep` binary >= 0.25.0 | `ast-grep X.Y.Z` on stdout | not installed (stderr: three install commands) | installed but below minimum (stderr: upgrade command) |

Exit 1 is reserved for argument-parsing errors in scripts that accept arguments (currently only `kuzu_client.py`). The check scripts take no arguments.

## Degradation contract

Both Kuzu and ast-grep are OPTIONAL at the plugin level. cc-master works without either — graph-backed skills fall back to reading JSON directly.

**Without Kuzu (Python binding absent):**
- `cc-master:index` cannot write a graph — prints `"Graph not built — run /cc-master:index after installing kuzu"` and exits.
- Every graph-backed skill falls back to JSON reads automatically via `prompts/graph-read-protocol.md`.
- Project-state queries (board render, spec dedup, blocked chain) work as they did in v0.20 and earlier.
- No skill crashes.

**Without ast-grep (binary absent or below minimum):**
- `cc-master:index` populates Task, Subtask, Spec, Feature, Module nodes from JSON only.
- Symbol, File (via `ast-grep-walk` source), and REFERENCES edges are not created.
- `cc-master:impact` prints `"Code graph requires ast-grep — run bash scripts/graph/check_astgrep.sh for install instructions"` and exits without running code-graph queries.
- Project-state queries still work.

**Without both:** The plugin runs exactly as it did in v0.20 — every skill uses JSON reads. The v2 graph engine is purely additive; removing it removes nothing from the baseline.

## Alternatives considered

Three alternatives to ast-grep were evaluated for the v1 code-graph indexer:

- **tree-sitter bindings directly** — requires per-language grammar compilation and Python/Node bindings per language. ast-grep gives tree-sitter's multi-language coverage via a single prebuilt binary, which makes the "single install command" UX possible.
- **SCIP + scip-* indexers** (scip-java, scip-typescript, scip-python) — higher accuracy on dynamic dispatch and generics, but requires a per-language indexer install per target project. Targeted for v0.22+ when dispatch accuracy matters enough to justify the install cost. Same graph schema — ast-grep and SCIP are drop-in swappable at the indexer layer.
- **Universal-ctags** — too coarse. Emits symbol definitions but not structural references or type-aware queries. Fast and battle-tested, but insufficient for the "who references this symbol?" queries that drive `cc-master:impact`.
