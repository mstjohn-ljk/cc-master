#!/bin/sh
# check_kuzu.sh — verify that the Kuzu Python binding is installed and
# importable for the v2 graph engine.
#
# Exit codes:
#   0  kuzu import succeeds (prints "kuzu X.Y.Z" to stdout)
#   2  python3 absent, or kuzu binding not importable (install instructions to stderr)
#
# No minimum version is enforced here — task #4 will lock down the minimum
# when it writes the indexer against a concrete Kuzu API.
#
# POSIX sh only — no bashisms. Dependencies: python3.

set -e

log_err() {
  printf '%s\n' "$*" >&2
}

print_python_missing_and_exit() {
  log_err "python3 is required (3.9+) — Kuzu binding is a Python package."
  log_err "Install Python 3.9+ and re-run."
  exit 2
}

print_install_and_exit() {
  log_err "kuzu Python binding is required for the v2 graph engine."
  log_err "Install:"
  log_err "  pip install kuzu==0.11.2     # pin the version from plugin.json"
  log_err "  pipx install kuzu            # isolated environment alternative"
  exit 2
}

# Step 1: detect python3 interpreter.
if ! command -v python3 >/dev/null 2>&1; then
  print_python_missing_and_exit
fi

# Step 2: import kuzu and read its __version__ attribute. `|| true` guards
# `set -e` so we can inspect the captured output ourselves.
VERSION=$(python3 -c "import kuzu; print(kuzu.__version__)" 2>/dev/null || true)

if [ -z "$VERSION" ]; then
  print_install_and_exit
fi

# Step 3: success.
printf 'kuzu %s\n' "$VERSION"
exit 0
