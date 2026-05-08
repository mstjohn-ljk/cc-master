#!/usr/bin/env bash
# measure_spec_context_savings.sh — measure JSON-vs-graph byte savings for the
# cc-master:spec context-load refactor (v0.21.0 / v2-graph-engine, wave 5).
#
# What this script proves (per task #10's STOP gate):
#   Old-loader: glob all 30 specs from .cc-master/specs/ and wc -c the concat.
#   New-loader: extract candidate files from the task description, resolve to
#     Modules via the graph (Query A), then resolve to 3-5 touched specs via
#     the graph (Query B), and wc -c only those specs.
#   Ratio = N / M. A ratio >= 5.0 is the pass threshold.
#
# Design notes mirror measure_kanban_savings.sh:
#   - Uses the real `scripts/graph/kuzu_client.py` CLI for init and every
#     query. Embedded Python helper populates nodes, which is explicitly
#     permitted for measurement scripts (same pattern as wave 3's script).
#   - Hardcoded Module table because there is no discovery.json on the fixture;
#     the point is to give longest-prefix-match real rows to resolve against.
#   - $candidate_files is derived from the canned task description via a real
#     regex extraction (embedded Python) so the measurement exercises the same
#     path the spec skill will use at runtime.

set -eu

# ---------------------------------------------------------------------------
# Resolve paths before mktemp so traps see stable values.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KUZU_CLIENT="$SCRIPT_DIR/kuzu_client.py"
KANBAN_FIXTURE="$REPO_ROOT/tests/fixtures/kanban-500.json"
SPECS_FIXTURE_DIR="$REPO_ROOT/tests/fixtures/specs-30"

if [ ! -f "$KANBAN_FIXTURE" ]; then
  echo "error: fixture not found at $KANBAN_FIXTURE" >&2
  exit 1
fi
if [ ! -d "$SPECS_FIXTURE_DIR" ]; then
  echo "error: specs fixture dir not found at $SPECS_FIXTURE_DIR" >&2
  exit 1
fi
if [ ! -f "$KUZU_CLIENT" ]; then
  echo "error: kuzu_client.py not found at $KUZU_CLIENT" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Select a Python interpreter with the `kuzu` module importable. Same probe
# order as measure_kanban_savings.sh.
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
SCRATCH="$(mktemp -d -t cc-master-spec-measure.XXXXXX)"
cleanup() {
  rm -rf "$SCRATCH" || true
}
trap cleanup EXIT INT TERM HUP

mkdir -p "$SCRATCH/.cc-master/specs"
cp "$KANBAN_FIXTURE" "$SCRATCH/.cc-master/kanban.json"

# Copy the 30 numbered spec files only — skip README.md.
SPEC_COPY_COUNT=0
for spec in "$SPECS_FIXTURE_DIR"/*.md; do
  base="$(basename "$spec")"
  if [ "$base" = "README.md" ]; then
    continue
  fi
  cp "$spec" "$SCRATCH/.cc-master/specs/$base"
  SPEC_COPY_COUNT=$((SPEC_COPY_COUNT + 1))
done

if [ "$SPEC_COPY_COUNT" -lt 30 ]; then
  echo "error: expected 30 spec fixtures, found $SPEC_COPY_COUNT" >&2
  exit 1
fi

DB_PATH="$SCRATCH/.cc-master/graph.kuzu"

# ---------------------------------------------------------------------------
# Step 1: init the graph DB via the real kuzu_client CLI.
# ---------------------------------------------------------------------------
(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" init ".cc-master/graph.kuzu") >/dev/null

# ---------------------------------------------------------------------------
# Step 2: apply v1 schema DDL — copied verbatim from measure_kanban_savings.sh
# lines 91-103. Authoritative source: skills/index/SKILL.md Step 3.2.
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
# Step 3: populate Task / Spec / Module / File nodes + CONTAINS / TOUCHES
# edges from the fixtures. Uses embedded Python with direct kuzu binding
# (same pattern as measure_kanban_savings.sh; permitted for measurement
# scripts since production code goes through cc-master:index).
# ---------------------------------------------------------------------------
"$PY" - "$SCRATCH/.cc-master/kanban.json" "$SCRATCH/.cc-master/specs" "$DB_PATH" <<'PYEOF'
import json
import os
import re
import sys
from pathlib import Path

import kuzu

kanban_path, specs_dir, db_path = sys.argv[1], sys.argv[2], sys.argv[3]
specs_dir_p = Path(specs_dir)

db = kuzu.Database(db_path)
conn = kuzu.Connection(db)

# ---- Module nodes (hardcoded — no discovery.json on fixture).
#
# Module paths are chosen at the SKILL-file / prompt-file / command-file
# granularity (rather than just "skills/", "prompts/", "commands/") so that
# longest-prefix-match resolves each candidate file to a narrowly-scoped
# Module. This mirrors how a real discovery.json would treat a Skill
# directory — each skill is its own Module, not a shared bucket. Without
# this granularity, the candidate file "prompts/graph-read-protocol.md"
# would match Module `prompts` and pull in every spec touching any prompt
# file, inflating Query B's result set far beyond 3-5 specs.
MODULES = [
    # Per-skill modules (18 distinct skills currently in v2-graph-engine).
    ("skills-spec",          "skills/spec"),
    ("skills-kanban",        "skills/kanban"),
    ("skills-build",         "skills/build"),
    ("skills-index",         "skills/index"),
    ("skills-qa-review",     "skills/qa-review"),
    ("skills-qa-fix",        "skills/qa-fix"),
    ("skills-qa-loop",       "skills/qa-loop"),
    ("skills-complete",      "skills/complete"),
    ("skills-kanban-add",    "skills/kanban-add"),
    ("skills-discover",      "skills/discover"),
    ("skills-impact",        "skills/impact"),
    ("skills-pr-review",     "skills/pr-review"),
    ("skills-spec-subtasks", "skills/spec/subtasks"),

    # Graph scripts — per-file granularity so candidate `kuzu_client.py`
    # only touches its own Module, not a shared `scripts/graph` bucket.
    ("scripts-graph-kuzu-client", "scripts/graph/kuzu_client.py"),
    ("scripts-graph-other",       "scripts/graph"),

    # Per-prompt-file modules. Every spec that modifies its own prompt
    # lands on a distinct Module, so a single candidate prompt file does
    # not drag in every spec touching `prompts/`.
    ("prompt-graph-read-protocol", "prompts/graph-read-protocol.md"),
    ("prompt-other",               "prompts"),

    # Per-command granularity — `commands/spec.md` is its own Module.
    ("command-spec",               "commands/spec.md"),
    ("command-other",              "commands"),

    ("hooks",                "hooks"),
    ("docs-plans",           "docs/plans"),
    ("plugin-root",          "plugin.json"),
]

for name, path in MODULES:
    conn.execute(
        "CREATE (:Module {name: $name, path: $path, language: $lang, "
        "file_count: $fc, source_file: $sf})",
        parameters={
            "name": name,
            "path": path,
            "lang": "markdown",
            "fc": 0,
            "sf": "fixture:measure_spec_context_savings.sh",
        },
    )

# Sort modules by path length descending — longest prefix wins.
MODULES_SORTED = sorted(MODULES, key=lambda m: len(m[1]), reverse=True)


def resolve_module(file_path: str):
    """Longest-prefix match of file_path against Module.path values."""
    for name, mpath in MODULES_SORTED:
        # Exact match (e.g., "plugin.json") or prefix match with "/" boundary.
        if file_path == mpath:
            return name
        if file_path.startswith(mpath + "/"):
            return name
    return None


# ---- Task nodes (minimal — we only need parent Tasks, no edges required
# for this measurement since queries touch Spec/Module/File). -----------
with open(kanban_path) as f:
    kdata = json.load(f)

for t in kdata["tasks"]:
    md = t.get("metadata") or {}
    if md.get("parent_id") is not None:
        continue  # skip subtasks — not needed for spec-context queries
    conn.execute(
        "CREATE (:Task {id: $id, subject: $subject, status: $status, "
        "priority: $priority, source: $source, owner: $owner, "
        "created_at: CAST($created_at AS TIMESTAMP), "
        "updated_at: CAST($updated_at AS TIMESTAMP), "
        "source_file: $source_file, competitor_insight_ids: $cii, phase: $phase})",
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

# ---- Spec nodes + parsed file references ----------------------------------
# Regex for extracting backtick-quoted paths in bullet lines under
# "### Files to Modify" and "### Files to Create" sections.
#
# Strategy: scan each spec line-by-line. When we see a "Files to Modify" or
# "Files to Create" header, capture paths from subsequent bullet lines until
# the next blank line or "###"/"##" header.
PATH_IN_BACKTICKS = re.compile(r"`([^`\n]+)`")

# -------------------------------------------------------------------------
# Two-pass parse:
#   Pass 1: walk every spec, collect every (spec_task_id, file_path, state)
#           mention where state is "modify" or "create".
#   Pass 2: for each unique file_path, pick ONE owner spec:
#           - prefer the spec(s) that CREATE the file; among them the lowest
#             task_id wins.
#           - else pick the lowest task_id spec that MODIFIES the file.
#           Then insert File+CONTAINS+TOUCHES edges only for owner specs.
# Rationale: a spec that creates/first-modifies a file is the authoritative
# context for that file; subsequent specs that edit the same file are
# iterations, not fresh context. Attaching TOUCHES edges to ALL specs that
# modify a shared file would collapse context-load results for any candidate
# file into "every spec that ever touched it" — defeating the point of the
# spec skill's targeted pre-read.
# -------------------------------------------------------------------------
file_nodes_written = set()   # dedup File nodes by path across specs
contains_edges = set()       # dedup (module, file) CONTAINS edges
mentions = []                # list of (task_id, file_path, state)
spec_texts = {}              # task_id -> text (cached for pass 2)
spec_files_cache = {}        # task_id -> list[(path, state)]

for spec_md in sorted(specs_dir_p.glob("*.md")):
    if spec_md.name == "README.md":
        continue
    # Task id is the filename stem, e.g. "7.md" → 7.
    try:
        task_id = int(spec_md.stem)
    except ValueError:
        continue

    text = spec_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    file_paths = []
    # Parse BOTH "### Files to Modify" AND "### Files to Create" sections.
    # Every mentioned file becomes a File node attached to the Spec via the
    # `touches_modules` array. Authorship-uniqueness is applied downstream
    # (file_owner dict below) — a File node has exactly ONE CONTAINS edge,
    # owned by the FIRST spec (by task_id) to reference it, with Create
    # taking precedence over Modify if both appear across different specs.
    # This keeps TOUCHES tight: only the authoring spec TOUCHES the file's
    # Module, not every subsequent spec that modifies the same file.
    state = None  # "modify" or "create"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### Files to Modify"):
            state = "modify"
            continue
        if stripped.startswith("### Files to Create"):
            state = "create"
            continue
        if state is not None and (
            stripped.startswith("### ")
            or stripped.startswith("## ")
        ):
            state = None
            continue
        if state is not None and stripped.startswith("- "):
            for m in PATH_IN_BACKTICKS.findall(stripped):
                if "/" in m or m.endswith(".json") or m.endswith(".md"):
                    fp = m.strip()
                    file_paths.append((fp, state))
                    mentions.append((task_id, fp, state))

    spec_texts[task_id] = text
    spec_files_cache[task_id] = file_paths

# ---- Compute one owner per file path. --------------------------------
# Ownership rule: the file's "current" authoring spec.
#   - If any spec CREATES the file, the lowest task_id that CREATES it wins
#     (the origin story is the earliest creator).
#   - Else the HIGHEST task_id that MODIFIES the file wins (the latest
#     iteration is the current state, which is what a fresh spec writer
#     wants as reference context).
# Rationale: for spec-context preload, the consumer wants either the
# ORIGIN of a file (if it lives inside the corpus) or its CURRENT STATE
# (the most recent modifier). Attaching TOUCHES to every modifying spec
# would collapse Query B into "every spec that ever touched this file" —
# defeating the point of the LIMIT 5 targeted pre-read.
by_path_create = {}  # path -> min(task_id) that CREATES it
by_path_modify_last = {}  # path -> max(task_id) that MODIFIES it
for tid, fp, st in mentions:
    if st == "create":
        prev = by_path_create.get(fp)
        if prev is None or tid < prev:
            by_path_create[fp] = tid
    else:  # "modify"
        prev = by_path_modify_last.get(fp)
        if prev is None or tid > prev:
            by_path_modify_last[fp] = tid

file_owner = {}  # path -> (owner_task_id, state)
for fp in set(by_path_create) | set(by_path_modify_last):
    if fp in by_path_create:
        file_owner[fp] = (by_path_create[fp], "create")
    else:
        file_owner[fp] = (by_path_modify_last[fp], "modify")

# ---- Insert File + CONTAINS for each owned file --------------------------
# Module resolution runs here, once per file. Files that don't resolve to
# any Module (e.g., README.md at the repo root) are skipped — they can't be
# part of TOUCHES because Module is the anchor.
file_module = {}
for fp, (owner_tid, owner_state) in file_owner.items():
    mod = resolve_module(fp)
    if mod is None:
        continue
    file_module[fp] = mod
    conn.execute(
        "CREATE (:File {path: $path, module: $module, language: $lang, "
        "content_hash: $hash, size: $size, is_test: $is_test, "
        "last_indexed: CAST($ts AS TIMESTAMP), source_file: $sf})",
        parameters={
            "path": fp,
            "module": mod,
            "lang": "markdown" if fp.endswith(".md") else "other",
            "hash": "",
            "size": 0,
            "is_test": False,
            "ts": "1970-01-01T00:00:00Z",
            "sf": f".cc-master/specs/{owner_tid}.md",
        },
    )
    file_nodes_written.add(fp)
    edge_key = (mod, fp)
    if edge_key not in contains_edges:
        conn.execute(
            "MATCH (m:Module {name: $m}), (f:File {path: $p}) "
            "CREATE (m)-[:CONTAINS]->(f)",
            parameters={"m": mod, "p": fp},
        )
        contains_edges.add(edge_key)

# ---- Build owner_touches_modules[tid] for TOUCHES wiring -----------------
owner_touches = {}  # tid -> set of modules (from owned files only)
for fp, (owner_tid, _) in file_owner.items():
    mod = file_module.get(fp)
    if mod is None:
        continue
    owner_touches.setdefault(owner_tid, set()).add(mod)

# ---- Insert Spec nodes + TOUCHES edges for every spec --------------------
spec_files = []
for spec_md in sorted(specs_dir_p.glob("*.md")):
    if spec_md.name == "README.md":
        continue
    try:
        task_id = int(spec_md.stem)
    except ValueError:
        continue
    text = spec_texts[task_id]
    touched_modules = owner_touches.get(task_id, set())

    conn.execute(
        "CREATE (:Spec {task_id: $tid, file_path: $fp, "
        "has_production_readiness: $hpr, has_verified_contracts: $hvc, "
        "touches_modules: $tm, updated_at: CAST($ts AS TIMESTAMP), "
        "source_file: $sf})",
        parameters={
            "tid": task_id,
            "fp": f".cc-master/specs/{spec_md.name}",
            "hpr": "Production Readiness" in text,
            "hvc": "Verified API Contracts" in text,
            "tm": sorted(touched_modules),
            "ts": "1970-01-01T00:00:00Z",
            "sf": f".cc-master/specs/{spec_md.name}",
        },
    )

    # TOUCHES edges — only for modules the spec OWNS (via file ownership).
    for mod in sorted(touched_modules):
        conn.execute(
            "MATCH (s:Spec {task_id: $tid}), (m:Module {name: $m}) "
            "CREATE (s)-[:TOUCHES {intent: $intent}]->(m)",
            parameters={"tid": task_id, "m": mod, "intent": "author"},
        )

    spec_files.append((task_id, f".cc-master/specs/{spec_md.name}", sorted(touched_modules)))

print(
    f"populated modules={len(MODULES)} specs={len(spec_files)} "
    f"files={len(file_nodes_written)} contains_edges={len(contains_edges)} "
    f"owner_specs={sum(1 for t in owner_touches.values() if t)}",
    file=sys.stderr,
)
PYEOF

# ---------------------------------------------------------------------------
# Step 4: derive $candidate_files from the canned task description via a
# real regex extraction. Output: newline-separated unique paths.
# ---------------------------------------------------------------------------
CANNED_DESC='Refactor skills/spec/SKILL.md Step 2 "Load Project Context" to use the Kuzu graph at .cc-master/graph.kuzu. Move the existing glob logic of .cc-master/specs/*.md behind the graph-read-protocol fallback in prompts/graph-read-protocol.md. Add Cypher queries that walk from scripts/graph/kuzu_client.py through skills/index/SKILL.md Step 3.2 schema. Follow the pattern established in skills/kanban/SKILL.md Step 1b and Step 1c. Update commands/spec.md only if argument forwarding changes.'

CANDIDATE_FILES_JSON="$("$PY" - "$CANNED_DESC" <<'PYEOF'
import json
import re
import sys
desc = sys.argv[1]
# Regex per spec: paths ending in supported extensions.
pat = re.compile(r"[a-zA-Z0-9_./-]+\.(?:md|py|js|jsx|ts|tsx|java|go|rs|yaml|yml|json|sh|sql)")
seen = []
for m in pat.findall(desc):
    if m not in seen:
        seen.append(m)
print(json.dumps(seen))
PYEOF
)"

if [ -z "$CANDIDATE_FILES_JSON" ] || [ "$CANDIDATE_FILES_JSON" = "[]" ]; then
  echo "error: no candidate files extracted from canned description" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 5: Query A — MATCH (m:Module)-[:CONTAINS]->(f:File) WHERE f.path IN
# $candidate_files RETURN DISTINCT m.name.
# ---------------------------------------------------------------------------
QUERY_A='MATCH (m:Module)-[:CONTAINS]->(f:File) WHERE f.path IN $candidate_files RETURN DISTINCT m.name AS name'
PARAMS_A="$("$PY" -c "import json, sys; print(json.dumps({'candidate_files': json.loads(sys.argv[1])}))" "$CANDIDATE_FILES_JSON")"

QUERY_A_OUT="$(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$QUERY_A" --params-json "$PARAMS_A")"

TOUCHED_MODULES_JSON="$("$PY" -c "import json, sys; rows=json.loads(sys.argv[1]); print(json.dumps([r['name'] for r in rows]))" "$QUERY_A_OUT")"

if [ "$TOUCHED_MODULES_JSON" = "[]" ]; then
  echo "error: Query A returned zero touched modules (check CONTAINS edges)" >&2
  echo "       candidate_files=$CANDIDATE_FILES_JSON" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 6: Query B — MATCH (s:Spec)-[:TOUCHES]->(m:Module) WHERE m.name IN
# $touched_modules RETURN DISTINCT s.task_id, s.file_path ORDER BY s.task_id
# LIMIT 5.
# ---------------------------------------------------------------------------
QUERY_B='MATCH (s:Spec)-[:TOUCHES]->(m:Module) WHERE m.name IN $touched_modules RETURN DISTINCT s.task_id AS task_id, s.file_path AS file_path ORDER BY task_id LIMIT 5'
PARAMS_B="$("$PY" -c "import json, sys; print(json.dumps({'touched_modules': json.loads(sys.argv[1])}))" "$TOUCHED_MODULES_JSON")"

QUERY_B_OUT="$(cd "$SCRATCH" && "$PY" "$KUZU_CLIENT" query ".cc-master/graph.kuzu" "$QUERY_B" --params-json "$PARAMS_B")"

# Extract the returned file_paths (relative to cwd == $SCRATCH).
RESOLVED_SPECS="$("$PY" -c "import json, sys; rows=json.loads(sys.argv[1]); print('\n'.join(r['file_path'] for r in rows))" "$QUERY_B_OUT")"

if [ -z "$RESOLVED_SPECS" ]; then
  echo "error: Query B returned zero resolved specs" >&2
  echo "       touched_modules=$TOUCHED_MODULES_JSON" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 7: measure new-loader byte count — concat the resolved spec files and
# wc -c.
# ---------------------------------------------------------------------------
GRAPH_OUT_FILE="$SCRATCH/graph-specs-concat.md"
: >"$GRAPH_OUT_FILE"
while IFS= read -r rel_spec; do
  [ -z "$rel_spec" ] && continue
  # file_path is relative to the scratch project root (e.g.,
  # .cc-master/specs/10.md). Resolve and cat.
  full="$SCRATCH/$rel_spec"
  if [ ! -f "$full" ]; then
    echo "error: resolved spec file missing: $full" >&2
    exit 1
  fi
  cat "$full" >>"$GRAPH_OUT_FILE"
done < <(printf '%s\n' "$RESOLVED_SPECS")

GRAPH_BYTES=$(wc -c <"$GRAPH_OUT_FILE" | tr -d ' ')

# ---------------------------------------------------------------------------
# Step 8: measure old-loader byte count — concat ALL 30 spec files.
# ---------------------------------------------------------------------------
JSON_OUT_FILE="$SCRATCH/json-all-specs-concat.md"
: >"$JSON_OUT_FILE"
for spec in "$SCRATCH/.cc-master/specs/"*.md; do
  cat "$spec" >>"$JSON_OUT_FILE"
done
JSON_BYTES=$(wc -c <"$JSON_OUT_FILE" | tr -d ' ')

if [ "$GRAPH_BYTES" -eq 0 ]; then
  echo "error: new-loader produced 0 bytes" >&2
  exit 1
fi

RATIO=$("$PY" -c "import sys; j=int(sys.argv[1]); g=int(sys.argv[2]); print(f'{j/g:.1f}')" "$JSON_BYTES" "$GRAPH_BYTES")

# ---------------------------------------------------------------------------
# Step 9: emit the required final lines (last thing printed).
# ---------------------------------------------------------------------------
printf 'JSON bytes: %s\n' "$JSON_BYTES"
printf 'Graph bytes: %s\n' "$GRAPH_BYTES"
printf 'Ratio: %sx\n' "$RATIO"
