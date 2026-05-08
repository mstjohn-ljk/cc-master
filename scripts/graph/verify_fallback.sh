#!/usr/bin/env bash
# verify_fallback.sh — Acceptance-time verification for the graph read protocol
# defined in prompts/graph-read-protocol.md.
#
# Exercises the three pre-query checks defined in that contract against a real,
# populated .cc-master/graph.kuzu/ directory:
#
#   Assertion 1 — Absent-graph-path check (Check 1 in the protocol).
#                 Move the graph aside, verify the path is absent (using -e so
#                 a single-file Kuzu DB is detected just like a directory),
#                 then restore it via a trap so even a crash restores state.
#   Assertion 2 — Hash sanity check (Check 2).
#                 Query the stored _source.content_hash and compute the live
#                 canonical-JSON hash of .cc-master/kanban.json. Both values
#                 must be non-empty (mismatch is itself a valid protocol signal).
#   Assertion 3 — Cypher parse-error check (Check 3).
#                 Issue a deliberately malformed Cypher query and assert that
#                 kuzu_client.py exits 4 with "error" in stderr.
#
# Exit codes:
#   0  all three assertions passed
#   1  a pre-flight check failed or one or more assertions failed
#
# Safety: the trap that restores .cc-master/graph.kuzu/ is installed BEFORE the
# directory is moved aside. It fires on EXIT, INT, and TERM — a Ctrl-C during
# Assertion 1 still restores the graph.
#
# Dependencies: bash, python3 (with the `kuzu` binding importable),
# scripts/graph/kuzu_client.py. Non-POSIX features used: [[ ]], arithmetic
# assignment — justified by trap robustness and cleaner assertion bookkeeping.

set -eu

# Path stored WITHOUT trailing slash so -e/-d tests work when the Kuzu DB is
# a single file (newer Kuzu versions). A trailing slash forces the kernel to
# reject non-directories even with -e, which falsely fails the pre-flight.
GRAPH_DIR=".cc-master/graph.kuzu"
KANBAN_JSON=".cc-master/kanban.json"
KUZU_CLIENT="scripts/graph/kuzu_client.py"
BACKUP_DIR=""
FAILED=0

log_err() {
  printf '%s\n' "$*" >&2
}

# Restoration function — ALWAYS runs on exit (normal or abnormal). If
# BACKUP_DIR is set and the live path is absent (or different), move the
# backup back into place. Installed BEFORE any destructive operation.
#
# Kuzu DBs may be stored as either a directory (historical Kuzu layout) or
# a single file (newer Kuzu versions use a single-file DB). The restore
# logic tests both shapes with `-e` so it never loses the backup.
restore_graph() {
  # Only restore if we actually moved the graph aside AND the backup still
  # exists on disk. Both conditions guard against double-restore and against
  # running this function before the move has happened.
  if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
    if [ ! -e "$GRAPH_DIR" ]; then
      mv "$BACKUP_DIR" "$GRAPH_DIR" || log_err "WARNING: failed to restore $GRAPH_DIR from $BACKUP_DIR"
    else
      # Live path is present — don't clobber it. Leave backup for operator.
      log_err "WARNING: $GRAPH_DIR was re-created during test; backup left at $BACKUP_DIR"
    fi
  fi
}

# Install trap BEFORE any destructive step. EXIT catches normal exits; INT
# catches Ctrl-C; TERM catches kill. Together they cover every exit path.
trap restore_graph EXIT INT TERM

# ---------------------------------------------------------------------------
# Pre-flight checks — fail fast before touching the graph.
# ---------------------------------------------------------------------------

# Kuzu stores its DB as either a directory (historical layout) or a single
# file (newer versions). Accept either — the protocol's "directory exists"
# check is really "the Kuzu path exists and is readable by the process".
if [ ! -e "$GRAPH_DIR" ]; then
  log_err "ERROR: $GRAPH_DIR does not exist — run /cc-master:index first"
  exit 1
fi

if ! python3 -c "import kuzu" 2>/dev/null; then
  log_err "ERROR: kuzu Python binding missing — pip install kuzu==0.11.2"
  exit 1
fi

if [ ! -f "$KUZU_CLIENT" ]; then
  log_err "ERROR: $KUZU_CLIENT not present — cannot run assertions"
  exit 1
fi

if [ ! -f "$KANBAN_JSON" ]; then
  log_err "ERROR: $KANBAN_JSON not present — Assertion 2 requires it"
  exit 1
fi

# ---------------------------------------------------------------------------
# Assertion 1 — Absent-graph-path check.
# ---------------------------------------------------------------------------

BACKUP_DIR="/tmp/graph-backup-$$"
mv "$GRAPH_DIR" "$BACKUP_DIR"

# Use -e (not -d) so the absence check is correct whether Kuzu stored the DB
# as a directory or a single file. -d would return non-zero for a regular
# file even when the path DOES exist, making the assertion misleading.
if [ -e "$GRAPH_DIR" ]; then
  log_err "FAIL: Assertion 1 — $GRAPH_DIR still present after move-aside"
  FAILED=$((FAILED + 1))
else
  printf 'PASS: Assertion 1 — absent-graph-path check\n'
fi

# Restore immediately so Assertions 2 and 3 have a live graph to query.
mv "$BACKUP_DIR" "$GRAPH_DIR"
BACKUP_DIR=""

# ---------------------------------------------------------------------------
# Assertion 2 — Hash sanity check.
# ---------------------------------------------------------------------------

# Stored hash from the graph. Query returns a JSON array of row objects; parse
# out the `hash` field. If the row is absent or parsing fails, STORED_HASH
# will be empty.
STORED_RAW=$(python3 "$KUZU_CLIENT" query "$GRAPH_DIR" \
  'MATCH (s:_source {file_path: ".cc-master/kanban.json"}) RETURN s.content_hash AS hash' \
  2>/dev/null || true)
STORED_HASH=$(printf '%s' "$STORED_RAW" | python3 -c '
import json, sys
try:
    rows = json.loads(sys.stdin.read() or "[]")
    if rows and isinstance(rows, list) and isinstance(rows[0], dict):
        print(rows[0].get("hash", "") or "")
    else:
        print("")
except Exception:
    print("")
' 2>/dev/null || true)

# Live canonical-JSON hash via the exact one-liner from graph-read-protocol.md.
LIVE_HASH=$(python3 -c "import json,hashlib,sys; o=json.load(open(sys.argv[1])); print(hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':')).encode()).hexdigest())" "$KANBAN_JSON" 2>/dev/null || true)

if [ -z "$STORED_HASH" ] || [ -z "$LIVE_HASH" ]; then
  printf 'FAIL: Assertion 2 — hash sanity check (stored=%s live=%s)\n' \
    "$STORED_HASH" "$LIVE_HASH"
  FAILED=$((FAILED + 1))
else
  MATCH="no"
  if [ "$STORED_HASH" = "$LIVE_HASH" ]; then
    MATCH="yes"
  fi
  printf 'PASS: Assertion 2 — hash sanity check (stored=%s live=%s match=%s)\n' \
    "$STORED_HASH" "$LIVE_HASH" "$MATCH"
fi

# ---------------------------------------------------------------------------
# Assertion 3 — Cypher parse-error check.
# ---------------------------------------------------------------------------

# Capture stderr to a temp file; capture exit code separately. We deliberately
# do NOT pipe through tee or similar — we want the raw exit code of the
# kuzu_client invocation, not of a downstream filter.
STDERR_FILE=$(mktemp -t verify-fallback-stderr.XXXXXX)
# Using an explicit `|| true` would mask the exit code; instead we disable
# `set -e` locally with a grouped command and recapture $? immediately.
set +e
python3 "$KUZU_CLIENT" query "$GRAPH_DIR" 'RETURN garbage))' >/dev/null 2>"$STDERR_FILE"
RC=$?
set -e

STDERR_CONTENT=$(cat "$STDERR_FILE" 2>/dev/null || true)
rm -f "$STDERR_FILE"

# Case-insensitive substring check for "error".
STDERR_LOWER=$(printf '%s' "$STDERR_CONTENT" | tr '[:upper:]' '[:lower:]')
STDERR_HAS_ERROR=0
case "$STDERR_LOWER" in
  *error*) STDERR_HAS_ERROR=1 ;;
esac

if [ "$RC" = "4" ] && [ "$STDERR_HAS_ERROR" = "1" ]; then
  printf 'PASS: Assertion 3 — Cypher parse error surfaces as exit 4\n'
else
  # Truncate stderr snippet to 120 chars to keep output readable.
  SNIPPET=$(printf '%s' "$STDERR_CONTENT" | head -c 120)
  printf 'FAIL: Assertion 3 — expected exit 4 (got %s) / stderr %s\n' "$RC" "$SNIPPET"
  FAILED=$((FAILED + 1))
fi

# ---------------------------------------------------------------------------
# Final verdict.
# ---------------------------------------------------------------------------

if [ "$FAILED" = "0" ]; then
  printf 'All assertions passed.\n'
  exit 0
else
  printf 'One or more assertions failed.\n'
  exit 1
fi
