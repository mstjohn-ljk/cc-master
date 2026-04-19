#!/bin/sh
# measure_code_graph_index.sh — measure cold (or warm) wall-time for the
# v2 graph engine code-graph indexing pass (cc-master:index --code-graph)
# and emit a structured JSON artifact plus a stdout summary.
#
# Scaling gate: if elapsed_seconds > 60, exit code 3 ("SCALING MISS"). The
# 60s target is the Wave 7 prerequisite codified in
# docs/plans/2026-04-graph-engine-v1.md "Scaling envelope".
#
# Exit codes (follow scripts/graph/check_astgrep.sh conventions):
#   0  success OR gate pass  (prints "SCALING PASS: ..." to stdout)
#   1  usage / missing --invoke / internal error
#   2  target repo missing or not a directory
#   3  scaling gate FAIL  (elapsed > 60s)
#
# POSIX sh only — no bashisms. Dependencies: date, mkdir, rm, printf, wc.
# The Kuzu count queries shell out to python3 + scripts/graph/kuzu_client.py
# (same binding pattern as measure_kanban_savings.sh and
# measure_spec_context_savings.sh).

set -e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GATE_THRESHOLD_SECONDS=60
SCRIPT_NAME="measure_code_graph_index.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_err() {
  printf '%s\n' "$*" >&2
}

print_usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [--warm] [--invoke "<shell-command>"] [--help]

Measures wall-clock time for a cold (default) or warm code-graph index pass
against a target repository, writes a JSON artifact with timing and graph
node counts, and enforces a ${GATE_THRESHOLD_SECONDS}s scaling gate.

Environment:
  CC_BENCH_REPO   Absolute path to the target repo. If unset, the current
                  working directory is measured.

Flags:
  --warm          Skip the pre-run wipe of .cc-master/graph.kuzu (measures
                  the warm/incremental path instead of cold).
  --invoke CMD    Shell command representing the indexing operation. The
                  script measures wall time around this command. Required
                  for automated measurement; without it, operator
                  instructions are emitted and the script exits 1.
  --help          Print this usage and exit 0.

Exit codes:
  0  success OR gate pass
  1  usage / missing --invoke
  2  target repo missing or not a directory
  3  scaling gate FAIL (elapsed > ${GATE_THRESHOLD_SECONDS}s)

Examples:
  CC_BENCH_REPO=/path/to/repo $SCRIPT_NAME \\
    --invoke "python3 scripts/graph/bench_index.py --module-all"

  $SCRIPT_NAME --warm --invoke "claude -p '/cc-master:index --code-graph'"
USAGE
}

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
MODE="cold"
INVOKE_CMD=""

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h)
      print_usage
      exit 0
      ;;
    --warm)
      MODE="warm"
      shift
      ;;
    --invoke)
      if [ $# -lt 2 ]; then
        log_err "--invoke requires a shell-command argument."
        print_usage >&2
        exit 1
      fi
      INVOKE_CMD="$2"
      shift 2
      ;;
    *)
      log_err "Unknown argument: $1"
      print_usage >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve target repo
# ---------------------------------------------------------------------------
if [ -n "${CC_BENCH_REPO:-}" ]; then
  TARGET_REPO="$CC_BENCH_REPO"
else
  log_err "CC_BENCH_REPO not set — measuring current repo"
  TARGET_REPO="$(pwd)"
fi

# Defence-in-depth: reject shell metacharacters in TARGET_REPO before it
# reaches any `sh -c` / command substitution downstream. Allowed: alnum,
# forward-slash, dot, underscore, dash.
case "$TARGET_REPO" in
  *[!A-Za-z0-9/._-]*)
    log_err "CC_BENCH_REPO contains disallowed characters. Allowed: alphanumerics, /, ., _, -."
    exit 2
    ;;
esac

if [ ! -d "$TARGET_REPO" ]; then
  log_err "Target repo not found: $TARGET_REPO"
  exit 2
fi

# Absolute path for reproducibility of the JSON artifact.
TARGET_REPO_ABS="$(cd "$TARGET_REPO" && pwd)"

# ---------------------------------------------------------------------------
# Locate kuzu_client.py relative to THIS script (before cd into target repo)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KUZU_CLIENT="$SCRIPT_DIR/kuzu_client.py"

if [ ! -f "$KUZU_CLIENT" ]; then
  log_err "kuzu_client.py not found at $KUZU_CLIENT"
  exit 1
fi

# ---------------------------------------------------------------------------
# Require --invoke for automated measurement
# ---------------------------------------------------------------------------
if [ -z "$INVOKE_CMD" ]; then
  log_err "No --invoke command supplied."
  log_err ""
  log_err "This script measures wall-time around a shell command that drives"
  log_err "the code-graph index pass. /cc-master:index is a Claude Code slash"
  log_err "command (not a shell binary), so you MUST provide a driver via"
  log_err "--invoke. Common wrappers:"
  log_err ""
  log_err "  --invoke 'python3 scripts/graph/bench_index.py --module-all'"
  log_err "  --invoke 'claude -p \"/cc-master:index --code-graph\"'"
  log_err ""
  log_err "Re-run with --invoke to record a measurement."
  exit 1
fi

# ---------------------------------------------------------------------------
# cd into target repo (all file paths below are relative to it)
# ---------------------------------------------------------------------------
cd "$TARGET_REPO_ABS"

# ---------------------------------------------------------------------------
# Cold mode: wipe .cc-master/graph.kuzu (and only that path) before the run.
# Kuzu 0.11.2 may store the DB as a single file OR a directory — use rm -rf
# which handles both.
# ---------------------------------------------------------------------------
GRAPH_PATH=".cc-master/graph.kuzu"
if [ "$MODE" = "cold" ]; then
  if [ -e "$GRAPH_PATH" ]; then
    rm -rf "$GRAPH_PATH"
  fi
fi

# ---------------------------------------------------------------------------
# Capture start time, run the invoked command, capture end time
# ---------------------------------------------------------------------------
log_err "Running: /cc-master:index --code-graph"
log_err "Driver:  $INVOKE_CMD"
log_err "Mode:    $MODE"
log_err ""

START_TS=$(date +%s)

# Run the invoked command. Propagate its exit status so measurement honesty
# is preserved — if the indexer failed, the gate does not make sense to
# evaluate. Use `set +e` around the invocation so we can capture the status
# without tripping `set -e`.
set +e
sh -c "$INVOKE_CMD"
INVOKE_STATUS=$?
set -e

END_TS=$(date +%s)

ELAPSED=$(( END_TS - START_TS ))

if [ "$INVOKE_STATUS" -ne 0 ]; then
  log_err "Invoked command exited with status $INVOKE_STATUS; skipping gate evaluation."
  log_err "Raw elapsed: ${ELAPSED}s"
  exit "$INVOKE_STATUS"
fi

# ---------------------------------------------------------------------------
# Query Kuzu for File, Symbol, REFERENCES counts. Failures are non-fatal;
# missing counts render as 0 in the JSON (graph may not exist on a
# warm-no-op case).
# ---------------------------------------------------------------------------
FILES_COUNT=0
SYMBOLS_COUNT=0
REFS_COUNT=0

run_count_query() {
  # $1 = cypher; returns integer on stdout, or "0" on any failure.
  _q="$1"
  if [ ! -e "$GRAPH_PATH" ]; then
    printf '0\n'
    return 0
  fi
  _out=$(python3 "$KUZU_CLIENT" query "$GRAPH_PATH" "$_q" 2>/dev/null || true)
  # Response shape: [{"n": <int>}]. Extract with Python for robustness —
  # jq may not be installed on every bench host.
  _n=$(printf '%s' "$_out" | python3 -c 'import json,sys
try:
    rows=json.load(sys.stdin)
    if rows and isinstance(rows,list):
        v=list(rows[0].values())[0]
        print(int(v) if v is not None else 0)
    else:
        print(0)
except Exception:
    print(0)
' 2>/dev/null || printf '0')
  printf '%s\n' "$_n"
}

FILES_COUNT=$(run_count_query "MATCH (f:File) RETURN count(f) AS n")
SYMBOLS_COUNT=$(run_count_query "MATCH (s:Symbol) RETURN count(s) AS n")
REFS_COUNT=$(run_count_query "MATCH ()-[r:REFERENCES]->() RETURN count(r) AS n")

# ---------------------------------------------------------------------------
# Decide gate status
# ---------------------------------------------------------------------------
if [ "$ELAPSED" -gt "$GATE_THRESHOLD_SECONDS" ]; then
  GATE="fail"
else
  GATE="pass"
fi

# ---------------------------------------------------------------------------
# Write JSON artifact to .cc-master/graph-perf/<iso-timestamp>.json
# ---------------------------------------------------------------------------
ARTIFACT_DIR=".cc-master/graph-perf"
mkdir -p "$ARTIFACT_DIR"

# ISO-8601 UTC timestamp — use `-u` and the POSIX strftime format.
ISO_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Filename-safe variant (strip colons) so the artifact path is portable.
FNAME_TS=$(printf '%s' "$ISO_TS" | tr ':' '-')
ARTIFACT_FILE="$ARTIFACT_DIR/${FNAME_TS}.json"

# Escape the invoke command for JSON (backslash, double-quote, newline).
ESCAPED_INVOKE=$(printf '%s' "$INVOKE_CMD" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

# Write the artifact. Use cat <<EOF for deterministic formatting.
cat >"$ARTIFACT_FILE" <<EOF
{
  "timestamp": "$ISO_TS",
  "target_repo": "$TARGET_REPO_ABS",
  "mode": "$MODE",
  "invoke_command": $ESCAPED_INVOKE,
  "elapsed_seconds": $ELAPSED,
  "files_indexed": $FILES_COUNT,
  "symbols_indexed": $SYMBOLS_COUNT,
  "references_indexed": $REFS_COUNT,
  "gate": "$GATE",
  "gate_threshold_seconds": $GATE_THRESHOLD_SECONDS
}
EOF

# ---------------------------------------------------------------------------
# Human-readable summary to stdout
# ---------------------------------------------------------------------------
printf 'Target repo:    %s\n' "$TARGET_REPO_ABS"
printf 'Mode:           %s\n' "$MODE"
printf 'Elapsed:        %ss\n' "$ELAPSED"
printf 'Files indexed:  %s\n' "$FILES_COUNT"
printf 'Symbols:        %s\n' "$SYMBOLS_COUNT"
printf 'References:     %s\n' "$REFS_COUNT"
printf 'Artifact:       %s\n' "$ARTIFACT_FILE"

# ---------------------------------------------------------------------------
# Gate enforcement
# ---------------------------------------------------------------------------
if [ "$GATE" = "fail" ]; then
  log_err "SCALING MISS: ${ELAPSED}s > ${GATE_THRESHOLD_SECONDS}s (fail). Optimize before Wave 7 depends on this."
  exit 3
fi

printf 'SCALING PASS: %ss <= %ss.\n' "$ELAPSED" "$GATE_THRESHOLD_SECONDS"
exit 0
