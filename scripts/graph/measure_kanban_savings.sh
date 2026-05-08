#!/usr/bin/env bash
# measure_kanban_savings.sh — measure JSON-vs-graph byte savings for the
# cc-master:kanban refactor (v0.21.0 / v2-graph-engine).
#
# What this script proves (per task #8's STOP gate in the spec):
#   JSON read of a realistic 500-task kanban.json returns N bytes.
#   The three Cypher queries the graph-backed kanban skill issues return M bytes.
#   Ratio = N / M. A ratio >= 5.0 is the pass threshold; lower ratios are still
#   reported honestly — the STOP-gate decision lives in subtask #60.
#
# Design notes:
#   - Uses the real `scripts/graph/kuzu_client.py` CLI for init + every Cypher
#     query. No inline `import kuzu` shortcuts — we measure the same surface
#     the kanban skill uses.
#   - The node populate step DOES use an embedded Python helper that imports
#     kuzu directly. That is explicitly permitted by the subtask spec ("small
#     Python helper embedded inline is fine … bypass cc-master:index and do a
#     direct populate since the goal is to measure query-time bytes").
#   - Schema DDL is hardcoded below; authoritative source is
#     skills/index/SKILL.md Step 3.2. Keep in sync with that section.

set -eu

# ---------------------------------------------------------------------------
# Resolve paths before mktemp so traps see stable values.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KUZU_CLIENT="$SCRIPT_DIR/kuzu_client.py"
FIXTURE="$REPO_ROOT/tests/fixtures/kanban-500.json"

if [ ! -f "$FIXTURE" ]; then
  echo "error: fixture not found at $FIXTURE" >&2
  exit 1
fi
if [ ! -f "$KUZU_CLIENT" ]; then
  echo "error: kuzu_client.py not found at $KUZU_CLIENT" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Select a Python interpreter with the `kuzu` module importable. System
# `python3` may point at a version without the binding (e.g. homebrew 3.14
# while kuzu lives on 3.13). Probe 3.13 and 3.12 before falling back to
# `python3`.
# ---------------------------------------------------------------------------
pick_python() {
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import kuzu' >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  echo "error: no python3 interpreter with 'kuzu' module importable" >&2
  echo "hint:  pip install kuzu==0.11.2" >&2
  exit 2
}
PY="$(pick_python)"

# ---------------------------------------------------------------------------
# Scratch directory with trap cleanup.
# ---------------------------------------------------------------------------
SCRATCH="$(mktemp -d -t cc-master-kanban-measure.XXXXXX)"
cleanup() {
  rm -rf "$SCRATCH" || true
}
trap cleanup EXIT INT TERM

mkdir -p "$SCRATCH/.cc-master"
cp "$FIXTURE" "$SCRATCH/.cc-master/kanban.json"

DB_PATH="$SCRATCH/.cc-master/graph.kuzu"

# ---------------------------------------------------------------------------
# Step 1: init the graph DB via the real kuzu_client CLI.
# ---------------------------------------------------------------------------
(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" init ".cc-master/graph.kuzu") >/dev/null

# ---------------------------------------------------------------------------
# Step 2: apply v1 schema DDL. One statement per kuzu_client invocation
# (the wrapper is single-statement-per-call). Authoritative source:
# skills/index/SKILL.md Step 3.2 lines 420-432.
# ---------------------------------------------------------------------------
apply_ddl() {
  local stmt="$1"
  (cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$stmt") >/dev/null
}

apply_ddl "CREATE NODE TABLE IF NOT EXISTS Task(id INT64, subject STRING, status STRING, priority STRING, source STRING, owner STRING, created_at TIMESTAMP, updated_at TIMESTAMP, source_file STRING, competitor_insight_ids STRING[], phase STRING, PRIMARY KEY (id))"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS Subtask(id INT64, parent_id INT64, subject STRING, status STRING, blocked_by INT64[], spec_file STRING, wave INT64, created_at TIMESTAMP, updated_at TIMESTAMP, source_file STRING, competitor_insight_ids STRING[], phase STRING, PRIMARY KEY (id))"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS Spec(task_id INT64, file_path STRING, has_production_readiness BOOLEAN, has_verified_contracts BOOLEAN, touches_modules STRING[], updated_at TIMESTAMP, source_file STRING, PRIMARY KEY (task_id))"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS Feature(id STRING, title STRING, priority STRING, status STRING, phase STRING, complexity STRING, impact STRING, delivered_at TIMESTAMP, source_file STRING, PRIMARY KEY (id))"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS Module(name STRING, path STRING, language STRING, file_count INT64, source_file STRING, PRIMARY KEY (name))"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS File(path STRING, module STRING, language STRING, content_hash STRING, size INT64, is_test BOOLEAN, last_indexed TIMESTAMP, source_file STRING, PRIMARY KEY (path))"
apply_ddl "CREATE REL TABLE IF NOT EXISTS HAS_SUBTASK(FROM Task TO Subtask)"
apply_ddl "CREATE REL TABLE IF NOT EXISTS HAS_SPEC(FROM Task TO Spec)"
apply_ddl "CREATE REL TABLE IF NOT EXISTS BLOCKED_BY(FROM Task TO Task, FROM Task TO Subtask, FROM Subtask TO Task, FROM Subtask TO Subtask)"
apply_ddl "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS(FROM Task TO Feature)"
apply_ddl "CREATE REL TABLE IF NOT EXISTS TOUCHES(FROM Spec TO Module, intent STRING)"
apply_ddl "CREATE REL TABLE IF NOT EXISTS CONTAINS(FROM Module TO File)"
apply_ddl "CREATE NODE TABLE IF NOT EXISTS _source(file_path STRING, content_hash STRING, last_indexed_at TIMESTAMP, node_count INT64, edge_count INT64, indexer_version STRING, PRIMARY KEY (file_path))"

# ---------------------------------------------------------------------------
# Step 3: direct node populate. Embedded Python helper uses the kuzu binding
# directly — permitted per subtask spec since this is a measurement tool and
# we want to bypass the full cc-master:index pipeline. Production code goes
# through the indexer skill.
# ---------------------------------------------------------------------------
"$PY" - "$SCRATCH/.cc-master/kanban.json" "$DB_PATH" <<'PYEOF'
import json
import sys
import kuzu

kanban_path, db_path = sys.argv[1], sys.argv[2]
with open(kanban_path) as f:
    data = json.load(f)

db = kuzu.Database(db_path)
conn = kuzu.Connection(db)

task_ids = set()
subtask_recs = []

# Pass 1: Task nodes (parent_id is null/absent).
for t in data["tasks"]:
    md = t.get("metadata") or {}
    parent_id = md.get("parent_id")
    if parent_id is None:
        conn.execute(
            "CREATE (:Task {id: $id, subject: $subject, status: $status, "
            "priority: $priority, source: $source, owner: $owner, "
            "created_at: CAST($created_at AS TIMESTAMP), "
            "updated_at: CAST($updated_at AS TIMESTAMP), "
            "source_file: $source_file, "
            "competitor_insight_ids: $cii, phase: $phase})",
            parameters={
                "id": int(t["id"]),
                "subject": t.get("subject") or "",
                "status": t.get("status") or "",
                "priority": md.get("priority") or "",
                "source": md.get("source") or "",
                "owner": t.get("owner") or "",
                "created_at": t.get("created_at") or "1970-01-01T00:00:00Z",
                "updated_at": t.get("updated_at") or "1970-01-01T00:00:00Z",
                "source_file": ".cc-master/kanban.json",
                "cii": list(md.get("competitor_insight_ids") or []),
                "phase": md.get("phase") or "",
            },
        )
        task_ids.add(int(t["id"]))
    else:
        subtask_recs.append((t, md, int(parent_id)))

# Pass 2: Subtask nodes.
for t, md, parent_id in subtask_recs:
    conn.execute(
        "CREATE (:Subtask {id: $id, parent_id: $parent_id, subject: $subject, "
        "status: $status, blocked_by: $blocked_by, spec_file: $spec_file, "
        "wave: $wave, created_at: CAST($created_at AS TIMESTAMP), "
        "updated_at: CAST($updated_at AS TIMESTAMP), "
        "source_file: $source_file, competitor_insight_ids: $cii, phase: $phase})",
        parameters={
            "id": int(t["id"]),
            "parent_id": parent_id,
            "subject": t.get("subject") or "",
            "status": t.get("status") or "",
            "blocked_by": [int(b) for b in (t.get("blocked_by") or [])],
            "spec_file": md.get("spec_file") or "",
            "wave": int(md.get("wave")) if md.get("wave") is not None else 0,
            "created_at": t.get("created_at") or "1970-01-01T00:00:00Z",
            "updated_at": t.get("updated_at") or "1970-01-01T00:00:00Z",
            "source_file": ".cc-master/kanban.json",
            "cii": list(md.get("competitor_insight_ids") or []),
            "phase": md.get("phase") or "",
        },
    )

# Pass 3: BLOCKED_BY edges — only materialize the variants we will query.
# For the measurement we use Task→Task and Subtask→Task/Subtask edges whose
# target ids resolve to existing nodes.
subtask_ids = {int(t["id"]) for t, _, _ in subtask_recs}

def find_kind(nid):
    if nid in task_ids:
        return "Task"
    if nid in subtask_ids:
        return "Subtask"
    return None

edge_count = 0
for t in data["tasks"]:
    md = t.get("metadata") or {}
    src_kind = "Subtask" if md.get("parent_id") is not None else "Task"
    src_id = int(t["id"])
    for b in (t.get("blocked_by") or []):
        b = int(b)
        tgt_kind = find_kind(b)
        if tgt_kind is None:
            continue
        conn.execute(
            f"MATCH (a:{src_kind} {{id: $a}}), (b:{tgt_kind} {{id: $b}}) "
            f"CREATE (a)-[:BLOCKED_BY]->(b)",
            parameters={"a": src_id, "b": b},
        )
        edge_count += 1

print(f"populated tasks={len(task_ids)} subtasks={len(subtask_recs)} blocked_by_edges={edge_count}", file=sys.stderr)
PYEOF

# ---------------------------------------------------------------------------
# Step 4: run the three Cypher queries that kanban's graph path executes
# and capture their COMBINED stdout byte count.
# ---------------------------------------------------------------------------
QUERY_A='MATCH (t:Task) RETURN t.id AS id, t.subject AS subject, t.status AS status, t.priority AS priority, t.source AS source, t.owner AS owner, t.competitor_insight_ids AS competitor_insight_ids, t.phase AS phase'
QUERY_B='MATCH (s:Subtask) RETURN s.id AS id, s.parent_id AS parent_id, s.subject AS subject, s.status AS status, s.blocked_by AS blocked_by, s.wave AS wave'
QUERY_C='MATCH (a)-[:BLOCKED_BY]->(b) RETURN a.id AS from_id, b.id AS to_id'

GRAPH_OUT_FILE="$SCRATCH/graph-output.jsonl"
: >"$GRAPH_OUT_FILE"
(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$QUERY_A") >>"$GRAPH_OUT_FILE"
(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$QUERY_B") >>"$GRAPH_OUT_FILE"
(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$QUERY_C") >>"$GRAPH_OUT_FILE"

GRAPH_BYTES=$(wc -c <"$GRAPH_OUT_FILE" | tr -d ' ')
JSON_BYTES=$(wc -c <"$FIXTURE" | tr -d ' ')

if [ "$GRAPH_BYTES" -eq 0 ]; then
  echo "error: graph query produced 0 bytes" >&2
  exit 1
fi

RATIO=$("$PY" -c "import sys; j=int(sys.argv[1]); g=int(sys.argv[2]); print(f'{j/g:.1f}')" "$JSON_BYTES" "$GRAPH_BYTES")

# ---------------------------------------------------------------------------
# Step 5: emit the required final lines (last thing printed).
# ---------------------------------------------------------------------------
printf 'JSON bytes: %s\n' "$JSON_BYTES"
printf 'Graph bytes: %s\n' "$GRAPH_BYTES"
printf 'Ratio: %sx\n' "$RATIO"
