#!/bin/sh
# check_astgrep.sh — verify that ast-grep is installed and meets the minimum
# version required by the v2 graph engine code-graph layer.
#
# Exit codes:
#   0  ast-grep present and version >= MIN_VERSION (prints "ast-grep X.Y.Z" to stdout)
#   2  ast-grep absent or --version output unparseable (install instructions to stderr)
#   3  ast-grep present but older than MIN_VERSION (upgrade instructions to stderr)
#
# POSIX sh only — no bashisms. Dependencies: grep, awk, sort, printf.

set -e

MIN_VERSION="0.25.0"

log_err() {
  printf '%s\n' "$*" >&2
}

print_install_and_exit() {
  log_err "ast-grep is required for the v2 graph engine code-graph layer."
  log_err "Install:"
  log_err "  brew install ast-grep          # macOS"
  log_err "  npm i -g @ast-grep/cli         # cross-platform via npm"
  log_err "  cargo install ast-grep         # from source"
  exit 2
}

print_upgrade_and_exit() {
  _current="$1"
  _minimum="$2"
  log_err "ast-grep $_current is installed but version >= $_minimum is required."
  log_err "Upgrade:"
  log_err "  brew upgrade ast-grep          # macOS"
  log_err "  npm i -g @ast-grep/cli@latest  # npm"
  log_err "  cargo install --force ast-grep # cargo"
  exit 3
}

# Numeric semver compare: returns 0 when $1 >= $2, non-zero otherwise.
# Prefers `sort -V`; falls back to awk field-wise numeric comparison when
# sort -V is unavailable (older BSD sort).
version_ge() {
  _a="$1"
  _b="$2"

  # Probe: does sort -V actually work on this system?
  if printf 'a\n' | sort -V >/dev/null 2>&1; then
    _highest=$(printf '%s\n%s\n' "$_a" "$_b" | sort -V | tail -n 1)
    [ "$_highest" = "$_a" ]
    return $?
  fi

  # Fallback: awk splits on '.' and compares each field numerically.
  awk -v a="$_a" -v b="$_b" '
    BEGIN {
      na = split(a, aa, ".")
      nb = split(b, bb, ".")
      n = (na > nb) ? na : nb
      for (i = 1; i <= n; i++) {
        av = (aa[i] == "") ? 0 : aa[i] + 0
        bv = (bb[i] == "") ? 0 : bb[i] + 0
        if (av > bv) exit 0
        if (av < bv) exit 1
      }
      exit 0
    }
  '
}

# Step 1: detect binary. Prefer `ast-grep`, accept `sg` as alternative name.
BIN=""
if command -v ast-grep >/dev/null 2>&1; then
  BIN="ast-grep"
elif command -v sg >/dev/null 2>&1; then
  BIN="sg"
else
  print_install_and_exit
fi

# Step 2: capture and parse version output. `|| true` guards `set -e` if the
# binary exits non-zero while still writing usable output to stderr.
RAW_VERSION=$("$BIN" --version 2>&1 || true)
VERSION=$(printf '%s\n' "$RAW_VERSION" \
  | grep -o '[0-9]\{1,\}\.[0-9]\{1,\}\.[0-9]\{1,\}' \
  | head -n 1)

if [ -z "$VERSION" ]; then
  log_err "ast-grep --version output unrecognized: $RAW_VERSION"
  exit 2
fi

# Step 3: numeric comparison against MIN_VERSION.
if ! version_ge "$VERSION" "$MIN_VERSION"; then
  print_upgrade_and_exit "$VERSION" "$MIN_VERSION"
fi

# Step 4: success.
printf 'ast-grep %s\n' "$VERSION"
exit 0
