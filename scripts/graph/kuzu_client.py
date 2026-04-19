#!/usr/bin/env python3
"""Thin Kuzu CLI wrapper for cc-master skills.

Invariants:
    - All stdout output is JSON (json.dumps results only).
    - All errors go to stderr as {"error": "<msg>"} with a non-zero exit code.
    - Stdin is never read; the script is non-interactive.
    - Uncaught exceptions are caught at the top level and reported as JSON on
      stderr; Python tracebacks never leak.

Exit codes:
    0  success
    1  argument parsing error or uncaught exception
    2  kuzu Python binding not installed
    3  database path not found (query/close on non-existent db)
    4  Cypher parse or runtime error
"""
# Self-reexec into the plugin's managed venv if the current interpreter
# can't import kuzu. This lets the script work on systems where python3
# is 3.14 (no Kuzu wheel) or PEP 668-locked. The venv is created by
# scripts/graph/ensure-venv.sh (runs as SessionStart hook).
import os as _os
import sys as _sys
try:
    import kuzu as _kuzu_probe  # noqa: F401
except ImportError:
    _data = _os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if _data:
        _venv_py = _os.path.join(_data, "venv", "bin", "python3")
        if _os.path.exists(_venv_py) and _os.path.realpath(_venv_py) != _os.path.realpath(_sys.executable):
            _os.execv(_venv_py, [_venv_py, __file__, *_sys.argv[1:]])
    # fall through — _load_kuzu() below will emit the standard error

import argparse
import json
import sys
from pathlib import Path
from typing import Any

INSTALL_MSG = (
    "kuzu Python binding required. The cc-master plugin manages a venv at "
    "$CLAUDE_PLUGIN_DATA/venv populated by the SessionStart hook. "
    "If you see this error, restart your Claude Code session or run: "
    "bash $CLAUDE_PLUGIN_ROOT/scripts/graph/ensure-venv.sh"
)


def _err(msg: str, code: int) -> None:
    """Print a JSON error to stderr and exit with the given code."""
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


def _warn(msg: str) -> None:
    """Print a one-line warning to stderr (not JSON — this is out-of-band)."""
    print(f"warning: {msg}", file=sys.stderr)


def _load_kuzu():
    """Import kuzu or exit 2 with an install hint."""
    try:
        import kuzu  # noqa: PLC0415
        return kuzu
    except ImportError:
        _err(INSTALL_MSG, 2)


def _jsonable(value: Any) -> Any:
    """Coerce a Kuzu cell value into something json.dumps can handle.

    Native JSON types pass through. Anything else becomes str(value) and a
    warning is emitted to stderr.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    # Fallback: stringify unknown types (datetime, UUID, Decimal, bytes, ...).
    _warn(f"coercing non-JSON value of type {type(value).__name__} to str")
    try:
        return str(value)
    except Exception as e:  # pragma: no cover — str() should not fail
        _warn(f"str() failed on {type(value).__name__}: {e}")
        return None


def cmd_init(args: argparse.Namespace) -> None:
    """Create (or open) a Kuzu DB at db_path and ensure _Marker exists."""
    kuzu = _load_kuzu()
    db_path = Path(args.db_path).resolve()
    # Ensure parent exists. Kuzu will create db_path itself as a directory.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    # IF NOT EXISTS makes DDL idempotent. Some Kuzu builds may still raise a
    # DuplicateTable-style error — swallow anything matching "already exists".
    try:
        conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS _Marker(id INT64, PRIMARY KEY (id))"
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise
    print(json.dumps({
        "status": "ok",
        "db_path": str(db_path),
        "kuzu_version": kuzu.__version__,
    }))


def cmd_query(args: argparse.Namespace) -> None:
    """Execute a Cypher query against an existing Kuzu DB and emit JSON rows."""
    kuzu = _load_kuzu()
    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        _err(f"database not found at {db_path}", 3)

    parameters = None
    if args.params_json is not None:
        try:
            parameters = json.loads(args.params_json)
        except json.JSONDecodeError as e:
            _err(f"invalid --params-json: {e}", 1)
        if not isinstance(parameters, dict):
            _err(
                "invalid --params-json: expected JSON object (dict), got "
                f"{type(parameters).__name__}",
                1,
            )

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    try:
        if parameters is None:
            result = conn.execute(args.cypher)
        else:
            result = conn.execute(args.cypher, parameters=parameters)
    except Exception as e:
        # Kuzu raises a variety of exception types (RuntimeError, custom
        # kuzu errors) for bad Cypher. Treat all as Cypher errors.
        _err(str(e), 4)

    try:
        columns = result.get_column_names()
    except Exception as e:
        _err(f"failed to read column names: {e}", 4)

    rows: list[dict[str, Any]] = []
    try:
        while result.has_next():
            values = result.get_next()
            row = {columns[i]: _jsonable(values[i]) for i in range(len(columns))}
            rows.append(row)
    except Exception as e:
        _err(f"failed to iterate result rows: {e}", 4)

    print(json.dumps(rows))


def cmd_close(args: argparse.Namespace) -> None:
    """Open and immediately release a DB to force flush and drop locks."""
    kuzu = _load_kuzu()
    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        _err(f"database not found at {db_path}", 3)
    # Construct and drop references — Kuzu releases OS locks on GC. Keep
    # references local so they go out of scope at function return.
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    del conn
    del db
    print(json.dumps({"status": "closed"}))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Thin Kuzu CLI for cc-master skills",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sp_init = sub.add_parser("init", help="Initialize a Kuzu database")
    sp_init.add_argument("db_path", help="Directory path for the Kuzu database")
    sp_init.set_defaults(func=cmd_init)

    sp_query = sub.add_parser("query", help="Execute a Cypher query")
    sp_query.add_argument("db_path", help="Existing Kuzu database directory")
    sp_query.add_argument("cypher", help="Cypher query string")
    sp_query.add_argument(
        "--params-json",
        default=None,
        help="JSON object passed as parameters= to connection.execute",
    )
    sp_query.set_defaults(func=cmd_query)

    sp_close = sub.add_parser("close", help="Close a Kuzu database")
    sp_close.add_argument("db_path", help="Existing Kuzu database directory")
    sp_close.set_defaults(func=cmd_close)

    try:
        args = parser.parse_args()
    except SystemExit:
        # argparse already printed its own usage/error to stderr on exit 2.
        # Normalize argument errors to exit code 1 per the CLI contract.
        code = sys.exc_info()[1].code if sys.exc_info()[1] is not None else 1
        if code == 0:
            raise  # --help success
        sys.exit(1)

    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        _err(f"unexpected: {type(e).__name__}: {e}", 1)


if __name__ == "__main__":
    main()
