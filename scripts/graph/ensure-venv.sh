#!/bin/bash
# ensure-venv.sh — idempotently create a Python venv with Kuzu installed.
#
# Runs as SessionStart hook. Exits 0 silently if venv is already healthy.
# On first run (or after a plugin update that changed the Kuzu version),
# creates ${CLAUDE_PLUGIN_DATA}/venv/ and installs Kuzu. Prefers python3.13
# because Python 3.14 has no Kuzu wheel yet.
#
# Variables (set by Claude Code):
#   CLAUDE_PLUGIN_ROOT — absolute path to plugin install dir
#   CLAUDE_PLUGIN_DATA — persistent data dir, survives updates
set -eu

KUZU_VERSION="0.11.2"
VENV_DIR="${CLAUDE_PLUGIN_DATA}/venv"
VENV_PY="${VENV_DIR}/bin/python3"
MARKER="${CLAUDE_PLUGIN_DATA}/kuzu-${KUZU_VERSION}.ok"

mkdir -p "${CLAUDE_PLUGIN_DATA}"

# Fast path: marker exists and venv still works — bail.
if [ -f "${MARKER}" ] && [ -x "${VENV_PY}" ]; then
  if "${VENV_PY}" -c "import kuzu" 2>/dev/null; then
    exit 0
  fi
fi

# Pick a Python. Prefer 3.13 (Kuzu has wheels), fall back to 3.12, then system python3.
pick_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local ver
      ver=$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "")
      case "$ver" in
        3.10|3.11|3.12|3.13)
          echo "$candidate"
          return 0
          ;;
        3.14|3.15)
          # Kuzu currently has no wheel for 3.14+; skip unless nothing else
          continue
          ;;
      esac
    fi
  done
  # Last resort: try system python3 even if 3.14+ (user may have a wheel locally)
  if command -v python3 >/dev/null 2>&1; then
    echo python3
    return 0
  fi
  return 1
}

PY_BIN=$(pick_python) || {
  echo "cc-master: no suitable Python found (need 3.10-3.13 for Kuzu)." >&2
  echo "  Install Python 3.13: brew install python@3.13 (macOS) or apt install python3.13 (Debian)" >&2
  exit 1
}

# (Re)create venv if missing or broken.
if [ ! -x "${VENV_PY}" ]; then
  echo "cc-master: creating Kuzu venv at ${VENV_DIR} using $(${PY_BIN} --version)" >&2
  rm -rf "${VENV_DIR}"
  "${PY_BIN}" -m venv "${VENV_DIR}" >&2
fi

# Install/upgrade Kuzu to the pinned version.
echo "cc-master: installing kuzu==${KUZU_VERSION} into ${VENV_DIR}" >&2
"${VENV_PY}" -m pip install --upgrade pip >&2 2>/dev/null || true
"${VENV_PY}" -m pip install --quiet "kuzu==${KUZU_VERSION}" >&2

# Verify the install.
if ! "${VENV_PY}" -c "import kuzu; assert kuzu.__version__ == '${KUZU_VERSION}'" 2>/dev/null; then
  echo "cc-master: Kuzu install verification FAILED. Run manually:" >&2
  echo "  ${VENV_PY} -m pip install kuzu==${KUZU_VERSION}" >&2
  exit 1
fi

# Write the success marker.
touch "${MARKER}"
echo "cc-master: Kuzu ${KUZU_VERSION} ready at ${VENV_PY}" >&2
exit 0
