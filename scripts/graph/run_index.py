#!/usr/bin/env python3
"""Bulk JSON→Kuzu graph indexer for cc-master v2 (Steps 4-6 of skills/index).

Invariants (violating any = broken indexer):
  1. JSON is source of truth; graph is derived.
  2. Per-file full-replace: DELETE all nodes WHERE source_file=$fp then INSERT.
  3. Sole writer: only this script writes. Every statement uses $param binding.
  4. Secret redaction applies to all string properties before persist.
  5. `.cc-master/...` paths anchor at main repo root inside a linked worktree.
  6. DDL idempotent (IF NOT EXISTS or try/except "already exists").
  7. Missing source file → empty bundle, not error.
  8. Dangling edges (endpoint not in bundle/graph) are silently dropped.

CLI:
    run_index.py [--full | --touch <path>] [--dry-run] [--verbose]

Exit codes: 0 ok | 1 arg/uncaught | 2 kuzu missing | 3 db path | 4 parser.
"""
# ─── Self-reexec into a Python that has Kuzu installed ─────────────────────
# Ported from scripts/graph/kuzu_client.py (lines 18-48).
import os as _os
import sys as _sys
try:
    import kuzu as _kuzu_probe  # noqa: F401
except ImportError:
    _cands = []
    _ed = _os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if _ed:
        _cands.append(_os.path.join(_ed, "venv", "bin", "python3"))
    _cands.append(_os.path.expanduser(
        "~/.claude/plugins/data/cc-master-cc-master-marketplace/venv/bin/python3"))
    _cands.append(_os.path.expanduser("~/.cc-master-venv/bin/python3"))
    _me = _os.path.realpath(_sys.executable)
    for _py in _cands:
        if not _os.path.exists(_py) or _os.path.realpath(_py) == _me:
            continue
        import subprocess as _sp
        if _sp.run([_py, "-c", "import kuzu"], capture_output=True).returncode == 0:
            _os.execv(_py, [_py, __file__, *_sys.argv[1:]])

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

INSTALL_MSG = (
    "kuzu Python binding required. The cc-master plugin manages a venv at "
    "$CLAUDE_PLUGIN_DATA/venv populated by the SessionStart hook. "
    "Restart Claude Code or run: bash $CLAUDE_PLUGIN_ROOT/scripts/graph/ensure-venv.sh")

_VERBOSE = False
_info = lambda m: print(f"info: {m}", file=sys.stderr)
def _warn(msg: str) -> None:
    print(f"warn: {_redact_string(msg)}", file=sys.stderr)
def _error(msg: str) -> None:
    print(f"error: {_redact_string(msg)}", file=sys.stderr)
def _vlog(m): _info(m) if _VERBOSE else None


def _load_kuzu():
    try:
        import kuzu
        return kuzu
    except ImportError:
        _error(INSTALL_MSG); sys.exit(2)


# ─── Worktree anchoring (ported from kuzu_client.py _resolve_db_path) ─────
def _resolve_repo_root() -> str:
    cwd = os.getcwd()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True)
        common = r.stdout.strip()
        if not common:
            return cwd
        if common.endswith("/.git") or common.endswith(os.sep + ".git"):
            return common[:-len("/.git")]
        return os.path.dirname(common.rstrip("/"))
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return cwd


def _resolve_path(rel: str, repo_root: str) -> str:
    if os.path.isabs(rel):
        return rel
    norm = rel.lstrip("./")
    if norm == ".cc-master" or norm.startswith(".cc-master/") or rel.startswith(".cc-master"):
        return os.path.join(repo_root, rel)
    return os.path.abspath(rel)


# ─── Secret redaction ─────────────────────────────────────────────────────
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
    re.DOTALL)
_OPENAI_RE = re.compile(r"sk-[a-zA-Z0-9]{20,}")
_GHP_RE = re.compile(r"ghp_[a-zA-Z0-9]{20,}")
_AWS_RE = re.compile(r"AKIA[0-9A-Z]{16}")
_HEX_RE = re.compile(r"\b[a-f0-9]{40,}\b")
_B64_RE = re.compile(r"\b[A-Za-z0-9+/=]{40,}\b")


def _redact_string(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    s = _PEM_RE.sub("[REDACTED]", s)
    s = _OPENAI_RE.sub("[REDACTED]", s)
    s = _GHP_RE.sub("[REDACTED]", s)
    s = _AWS_RE.sub("[REDACTED]", s)
    def _hex_or_digit(m):
        txt = m.group(0)
        return txt if txt.isdigit() else "[REDACTED]"
    s = _HEX_RE.sub(_hex_or_digit, s)
    def _b64_sub(m):
        txt = m.group(0)
        return txt if txt.isdigit() else "[REDACTED]"
    return _B64_RE.sub(_b64_sub, s)


def redact(v: Any) -> Any:
    if isinstance(v, str):
        return _redact_string(v)
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, dict):
        return {k: redact(x) for k, x in v.items()}
    return v


# ─── DDL bootstrap ────────────────────────────────────────────────────────
_DDL = [
    "CREATE NODE TABLE IF NOT EXISTS _Marker(id INT64, PRIMARY KEY (id))",
    ("CREATE NODE TABLE IF NOT EXISTS Task(id INT64, subject STRING, status STRING, "
     "priority STRING, source STRING, owner STRING, created_at TIMESTAMP, "
     "updated_at TIMESTAMP, source_file STRING, competitor_insight_ids STRING[], "
     "phase STRING, PRIMARY KEY (id))"),
    ("CREATE NODE TABLE IF NOT EXISTS Subtask(id INT64, parent_id INT64, "
     "subject STRING, status STRING, blocked_by INT64[], spec_file STRING, "
     "wave INT64, created_at TIMESTAMP, updated_at TIMESTAMP, source_file STRING, "
     "competitor_insight_ids STRING[], phase STRING, PRIMARY KEY (id))"),
    ("CREATE NODE TABLE IF NOT EXISTS Spec(task_id INT64, file_path STRING, "
     "has_production_readiness BOOLEAN, has_verified_contracts BOOLEAN, "
     "touches_modules STRING[], updated_at TIMESTAMP, source_file STRING, "
     "PRIMARY KEY (task_id))"),
    ("CREATE NODE TABLE IF NOT EXISTS Feature(id STRING, title STRING, "
     "priority STRING, status STRING, phase STRING, complexity STRING, "
     "impact STRING, delivered_at TIMESTAMP, source_file STRING, PRIMARY KEY (id))"),
    ("CREATE NODE TABLE IF NOT EXISTS Module(name STRING, path STRING, "
     "language STRING, file_count INT64, source_file STRING, PRIMARY KEY (name))"),
    ("CREATE NODE TABLE IF NOT EXISTS File(path STRING, module STRING, "
     "language STRING, content_hash STRING, size INT64, is_test BOOLEAN, "
     "last_indexed TIMESTAMP, source_file STRING, PRIMARY KEY (path))"),
    ("CREATE NODE TABLE IF NOT EXISTS Symbol(id STRING, name STRING, kind STRING, "
     "file STRING, line INT64, module STRING, source_file STRING, "
     "last_indexed TIMESTAMP, PRIMARY KEY (id))"),
    ("CREATE NODE TABLE IF NOT EXISTS _source(file_path STRING, content_hash STRING, "
     "last_indexed_at TIMESTAMP, node_count INT64, edge_count INT64, "
     "indexer_version STRING, PRIMARY KEY (file_path))"),
    "CREATE REL TABLE IF NOT EXISTS HAS_SUBTASK(FROM Task TO Subtask)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SPEC(FROM Task TO Spec)",
    ("CREATE REL TABLE IF NOT EXISTS BLOCKED_BY(FROM Task TO Task, "
     "FROM Task TO Subtask, FROM Subtask TO Task, FROM Subtask TO Subtask)"),
    "CREATE REL TABLE IF NOT EXISTS IMPLEMENTS(FROM Task TO Feature)",
    "CREATE REL TABLE IF NOT EXISTS TOUCHES(FROM Spec TO Module, intent STRING)",
    "CREATE REL TABLE IF NOT EXISTS CONTAINS(FROM Module TO File)",
    ("CREATE REL TABLE IF NOT EXISTS REFERENCES(FROM File TO Symbol, line INT64, "
     "context STRING, kind STRING, source_file STRING)"),
]


def bootstrap_schema(conn) -> None:
    for stmt in _DDL:
        try:
            conn.execute(stmt)
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                continue
            _error(f"DDL failed: {stmt[:200]} — {e}"); raise


# ─── IO + hashing ─────────────────────────────────────────────────────────
def _safe_read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        _warn(f"read failed for {path}: {e}"); return None


def _safe_parse_json(raw: bytes, path: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"invalid JSON/UTF-8 in {path}: {e}")


def hash_json(raw: bytes) -> dict:
    try:
        obj = json.loads(raw.decode("utf-8"))
        canon = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        return {"hash": hashlib.sha256(canon.encode("utf-8")).hexdigest()}
    except Exception as e:
        return {"hash": None, "error": str(e)}


def hash_markdown(raw: bytes) -> dict:
    try:
        return {"hash": hashlib.sha256(raw).hexdigest()}
    except Exception as e:
        return {"hash": None, "error": str(e)}


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def read_plugin_version(repo_root: str) -> str:
    pp = os.path.join(repo_root, ".claude-plugin", "plugin.json")
    try:
        with open(pp, "r", encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("version")
        if not isinstance(v, str) or not v.strip():
            raise ValueError("version field missing or empty")
        return v
    except Exception as e:
        raise RuntimeError(f"cannot read indexer version from {pp}: {e}")


def _is_intlike(x: Any) -> bool:
    try:
        int(x); return True
    except (TypeError, ValueError):
        return False


# ─── Parsers ──────────────────────────────────────────────────────────────
def parse_kanban(path: str, raw: bytes | None) -> dict:
    if raw is None:
        return {"nodes": [], "edges": []}
    data = _safe_parse_json(raw, path)
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError(f"{path}: top-level must be object with 'tasks' array")
    nodes, edges = [], []
    sf = ".cc-master/kanban.json"
    task_ids: set[int] = set()
    subtask_ids: set[int] = set()
    for t in data["tasks"]:
        if not isinstance(t, dict):
            continue
        md = t.get("metadata") or {}
        tid = t.get("id")
        if tid is None:
            continue
        tid = int(tid)
        parent_id = md.get("parent_id")
        bby = t.get("blocked_by") or []
        if not isinstance(bby, list):
            bby = []
        ins_ids = [redact(str(x)) for x in (md.get("competitor_insight_ids") or [])]
        phase = redact(md.get("phase") or "")
        if parent_id is None:
            nodes.append({"type": "Task", "properties": {
                "id": tid, "subject": redact(t.get("subject") or ""),
                "status": redact(t.get("status") or ""),
                "priority": redact(md.get("priority")),
                "source": redact(md.get("source")),
                "owner": redact(t.get("owner")),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
                "source_file": sf,
                "competitor_insight_ids": ins_ids,
                "phase": phase,
            }})
            task_ids.add(tid)
            fid = md.get("feature_id")
            if fid:
                edges.append({"type": "IMPLEMENTS",
                              "from": {"type": "Task", "key": tid},
                              "to": {"type": "Feature", "key": str(fid)}})
            spf = md.get("spec_file")
            if spf:
                m = re.search(r"(\d+)\.md$", spf)
                if m:
                    edges.append({"type": "HAS_SPEC",
                                  "from": {"type": "Task", "key": tid},
                                  "to": {"type": "Spec", "key": int(m.group(1))}})
            for b in bby:
                if _is_intlike(b):
                    edges.append({"type": "BLOCKED_BY",
                                  "from": {"type": "Task", "key": tid},
                                  "to": {"type": "Any", "key": int(b)}})
        else:
            if not _is_intlike(parent_id):
                continue
            pid = int(parent_id)
            nodes.append({"type": "Subtask", "properties": {
                "id": tid, "parent_id": pid,
                "subject": redact(t.get("subject") or ""),
                "status": redact(t.get("status") or ""),
                "blocked_by": [int(x) for x in bby if _is_intlike(x)],
                "spec_file": redact(md.get("spec_file")),
                "wave": md.get("wave"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
                "source_file": sf,
                "competitor_insight_ids": ins_ids, "phase": phase,
            }})
            subtask_ids.add(tid)
            edges.append({"type": "HAS_SUBTASK",
                          "from": {"type": "Task", "key": pid},
                          "to": {"type": "Subtask", "key": tid}})
            for b in bby:
                if _is_intlike(b):
                    edges.append({"type": "BLOCKED_BY",
                                  "from": {"type": "Subtask", "key": tid},
                                  "to": {"type": "Any", "key": int(b)}})
    # Resolve BLOCKED_BY target types
    resolved = []
    for e in edges:
        if e["type"] == "BLOCKED_BY" and e["to"]["type"] == "Any":
            k = e["to"]["key"]
            if k in task_ids:
                e["to"] = {"type": "Task", "key": k}; resolved.append(e)
            elif k in subtask_ids:
                e["to"] = {"type": "Subtask", "key": k}; resolved.append(e)
        else:
            resolved.append(e)
    return {"nodes": nodes, "edges": resolved}


def parse_roadmap(path: str, raw: bytes | None) -> dict:
    if raw is None:
        return {"nodes": [], "edges": []}
    data = _safe_parse_json(raw, path)
    if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
        raise ValueError(f"{path}: top-level must be object with 'phases' array")
    nodes, sf = [], ".cc-master/roadmap.json"
    for p in data["phases"]:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        for f in (p.get("features") or []):
            if not isinstance(f, dict) or not f.get("id"):
                continue
            nodes.append({"type": "Feature", "properties": {
                "id": str(f["id"]),
                "title": redact(f.get("title") or ""),
                "priority": redact(f.get("priority")),
                "status": redact(f.get("status") or "planned"),
                "phase": redact(str(pid) if pid is not None else None),
                "complexity": redact(f.get("complexity")),
                "impact": redact(f.get("impact")),
                "delivered_at": f.get("delivered_at"),
                "source_file": sf,
            }})
    return {"nodes": nodes, "edges": []}


def parse_discovery(path: str, raw: bytes | None) -> dict:
    if raw is None:
        return {"nodes": [], "edges": []}
    data = _safe_parse_json(raw, path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be object")
    nodes, sf, now = [], ".cc-master/discovery.json", _iso_now()
    for m in (data.get("modules") or []):
        if not isinstance(m, dict) or not m.get("name"):
            continue
        name = str(m["name"])
        nodes.append({"type": "Module", "properties": {
            "name": redact(name),
            "path": redact(m.get("path") or ""),
            "language": redact(m.get("language")),
            "file_count": m.get("file_count"),
            "source_file": sf,
        }})
        for fe in (m.get("files") or []):
            if not isinstance(fe, dict) or not fe.get("path"):
                continue
            nodes.append({"type": "File", "properties": {
                "path": redact(str(fe["path"])),
                "module": redact(name),
                "language": redact(fe.get("language")),
                "content_hash": "",
                "size": fe.get("size"),
                "is_test": False, "last_indexed": now, "source_file": sf,
            }})
    for fe in (data.get("files") or []):
        if not isinstance(fe, dict) or not fe.get("path"):
            continue
        nodes.append({"type": "File", "properties": {
            "path": redact(str(fe["path"])),
            "module": redact(fe.get("module")),
            "language": redact(fe.get("language")),
            "content_hash": "",
            "size": fe.get("size"),
            "is_test": False, "last_indexed": now, "source_file": sf,
        }})
    return {"nodes": nodes, "edges": []}


def _extract_paths_under(text: str, header: str) -> list[str]:
    lines, out, in_sec = text.splitlines(), [], False
    pat = rf"^###\s+{re.escape(header)}\s*$"
    for ln in lines:
        if re.match(pat, ln):
            in_sec = True; continue
        if in_sec:
            if re.match(r"^#{1,3}\s+", ln):
                break
            m = re.match(r"^\s*[-*+]\s+`?([^`\s]+)`?", ln)
            if m:
                tok = m.group(1).strip().rstrip(":,")
                if tok:
                    out.append(tok)
    return out


def parse_single_spec(path: str, raw: bytes | None,
                      module_paths: list[tuple[str, str]]) -> dict:
    if raw is None:
        return {"nodes": [], "edges": []}
    text = raw.decode("utf-8", errors="replace")
    basename = os.path.basename(path)
    stem = basename[:-3] if basename.endswith(".md") else basename
    if not re.match(r"^\d+$", stem):
        return {"nodes": [], "edges": []}
    tid = int(stem)
    has_prod = bool(re.search(r"^## Production Readiness\b", text, re.MULTILINE))
    has_ct = bool(re.search(r"^### Verified API Contracts\b", text, re.MULTILINE))
    mod_paths_sorted = sorted(
        [(n, p) for n, p in module_paths if p], key=lambda t: -len(t[1]))
    def _resolve_module(fp: str) -> str | None:
        for n, p in mod_paths_sorted:
            if fp == p or fp.startswith(p + "/") or fp.startswith(p):
                return n
        return None
    edges, touches, seen = [], {}, set()
    touches_modules = []
    for fp in _extract_paths_under(text, "Files to Modify"):
        mn = _resolve_module(fp)
        if mn and (mn, "modify") not in touches:
            touches[(mn, "modify")] = True
            edges.append({"type": "TOUCHES",
                          "from": {"type": "Spec", "key": tid},
                          "to": {"type": "Module", "key": mn},
                          "properties": {"intent": "modify"}})
            if mn not in seen:
                seen.add(mn); touches_modules.append(mn)
    for fp in _extract_paths_under(text, "Files to Create"):
        mn = _resolve_module(fp)
        if mn and (mn, "create") not in touches:
            touches[(mn, "create")] = True
            edges.append({"type": "TOUCHES",
                          "from": {"type": "Spec", "key": tid},
                          "to": {"type": "Module", "key": mn},
                          "properties": {"intent": "create"}})
            if mn not in seen:
                seen.add(mn); touches_modules.append(mn)
    try:
        ua = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
    except OSError:
        ua = _iso_now()
    file_path_prop = f".cc-master/specs/{basename}"
    node = {"type": "Spec", "properties": {
        "task_id": tid, "file_path": file_path_prop,
        "has_production_readiness": has_prod,
        "has_verified_contracts": has_ct,
        "touches_modules": touches_modules,
        "updated_at": ua, "source_file": file_path_prop,
    }}
    return {"nodes": [node], "edges": edges}


# ─── Node column map ──────────────────────────────────────────────────────
_NODE_COLS: dict[str, list[tuple[str, str]]] = {
    "Task": [("id", "INT64"), ("subject", "STRING"), ("status", "STRING"),
             ("priority", "STRING"), ("source", "STRING"), ("owner", "STRING"),
             ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
             ("source_file", "STRING"), ("competitor_insight_ids", "STRING[]"),
             ("phase", "STRING")],
    "Subtask": [("id", "INT64"), ("parent_id", "INT64"), ("subject", "STRING"),
                ("status", "STRING"), ("blocked_by", "INT64[]"),
                ("spec_file", "STRING"), ("wave", "INT64"),
                ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"),
                ("source_file", "STRING"),
                ("competitor_insight_ids", "STRING[]"), ("phase", "STRING")],
    "Spec": [("task_id", "INT64"), ("file_path", "STRING"),
             ("has_production_readiness", "BOOLEAN"),
             ("has_verified_contracts", "BOOLEAN"),
             ("touches_modules", "STRING[]"),
             ("updated_at", "TIMESTAMP"), ("source_file", "STRING")],
    "Feature": [("id", "STRING"), ("title", "STRING"), ("priority", "STRING"),
                ("status", "STRING"), ("phase", "STRING"),
                ("complexity", "STRING"), ("impact", "STRING"),
                ("delivered_at", "TIMESTAMP"), ("source_file", "STRING")],
    "Module": [("name", "STRING"), ("path", "STRING"), ("language", "STRING"),
               ("file_count", "INT64"), ("source_file", "STRING")],
    "File": [("path", "STRING"), ("module", "STRING"), ("language", "STRING"),
             ("content_hash", "STRING"), ("size", "INT64"),
             ("is_test", "BOOLEAN"), ("last_indexed", "TIMESTAMP"),
             ("source_file", "STRING")],
}
_TS_COLS = {"created_at", "updated_at", "delivered_at", "last_indexed",
            "last_indexed_at"}


def _create_cypher(nt: str) -> str:
    parts = []
    for n, _t in _NODE_COLS[nt]:
        parts.append(f"{n}: CAST(${n} AS TIMESTAMP)" if n in _TS_COLS else f"{n}: ${n}")
    return f"CREATE (n:{nt} {{{', '.join(parts)}}})"


def _coerce(nt: str, props: dict) -> dict:
    out = {}
    for name, kt in _NODE_COLS[nt]:
        v = props.get(name)
        if kt.endswith("[]") and v is None:
            v = []
        if name in ("phase",) and v is None:
            v = ""
        if name == "competitor_insight_ids" and v is None:
            v = []
        if kt == "INT64" and v is not None:
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = None
        if kt == "BOOLEAN":
            v = bool(v) if v is not None else False
        out[name] = v
    return out


def delete_by_source_file(conn, fp: str, counters: dict) -> None:
    try:
        r = conn.execute(
            "MATCH (n) WHERE n.source_file = $fp RETURN count(n) AS c",
            parameters={"fp": fp})
        if r.has_next():
            counters["nodes_deleted"] += int(r.get_next()[0])
    except Exception:
        pass
    try:
        r = conn.execute(
            "MATCH (a)-[r]->(b) WHERE a.source_file = $fp OR b.source_file = $fp "
            "RETURN count(r) AS c",
            parameters={"fp": fp})
        if r.has_next():
            counters["edges_deleted"] += int(r.get_next()[0])
    except Exception:
        pass  # edge-count failure is non-fatal; summary will undercount, not crash
    try:
        conn.execute(
            "MATCH (n) WHERE n.source_file = $fp DETACH DELETE n",
            parameters={"fp": fp})
    except Exception as e:
        _warn(f"delete_by_source_file({fp}) failed: {e}")


def insert_nodes(conn, bundle: dict, counters: dict) -> set:
    seen = set()
    for n in bundle.get("nodes", []):
        nt = n.get("type")
        if nt not in _NODE_COLS:
            _warn(f"unknown node type {nt}"); continue
        cypher = _create_cypher(nt)
        params = _coerce(nt, n.get("properties", {}))
        try:
            conn.execute(cypher, parameters=params)
            counters["nodes_inserted"] += 1
            pk = _NODE_COLS[nt][0][0]
            seen.add((nt, params.get(pk)))
        except Exception as e:
            pk = _NODE_COLS[nt][0][0]
            _warn(f"insert {nt} pk={n.get('properties',{}).get(pk)} failed: {e}")
    return seen


_EDGE_TEMPLATES = {
    "HAS_SUBTASK": ("MATCH (a:Task {id: $fromId}), (b:Subtask {id: $toId}) "
                    "CREATE (a)-[:HAS_SUBTASK]->(b)"),
    "HAS_SPEC": ("MATCH (a:Task {id: $fromId}), (b:Spec {task_id: $toId}) "
                 "CREATE (a)-[:HAS_SPEC]->(b)"),
    "IMPLEMENTS": ("MATCH (a:Task {id: $fromId}), (b:Feature {id: $toId}) "
                   "CREATE (a)-[:IMPLEMENTS]->(b)"),
    "TOUCHES": ("MATCH (a:Spec {task_id: $fromId}), (b:Module {name: $toId}) "
                "CREATE (a)-[:TOUCHES {intent: $intent}]->(b)"),
}


def _blocked_by_cypher(ft: str, tt: str) -> str:
    return (f"MATCH (a:{ft} {{id: $fromId}}), (b:{tt} {{id: $toId}}) "
            "CREATE (a)-[:BLOCKED_BY]->(b)")


def insert_edges(conn, bundle: dict, counters: dict,
                 known: set, existing: set | None = None) -> None:
    def _exists(ep):
        t, k = ep.get("type"), ep.get("key")
        if (t, k) in known:
            return True
        return bool(existing and (t, k) in existing)
    for e in bundle.get("edges", []):
        et = e.get("type")
        frm, to = e.get("from") or {}, e.get("to") or {}
        if not _exists(frm) or not _exists(to):
            continue
        if et == "BLOCKED_BY":
            cypher = _blocked_by_cypher(frm.get("type"), to.get("type"))
            params = {"fromId": frm.get("key"), "toId": to.get("key")}
        elif et in _EDGE_TEMPLATES:
            cypher = _EDGE_TEMPLATES[et]
            params = {"fromId": frm.get("key"), "toId": to.get("key")}
            if et == "TOUCHES":
                params["intent"] = (e.get("properties") or {}).get("intent", "modify")
        else:
            _warn(f"unknown edge type {et}"); continue
        try:
            conn.execute(cypher, parameters=params)
            counters["edges_inserted"] += 1
        except Exception as ex:
            _warn(f"edge {et} {frm}→{to} failed: {ex}")


def upsert_source_row(conn, fp: str, h: str, nc: int, ec: int,
                      v: str, ts: str) -> None:
    params = {"fp": fp, "h": h, "ts": ts, "nc": int(nc), "ec": int(ec), "v": v}
    merge = ("MERGE (s:_source {file_path: $fp}) "
             "ON CREATE SET s.content_hash = $h, "
             "s.last_indexed_at = CAST($ts AS TIMESTAMP), "
             "s.node_count = $nc, s.edge_count = $ec, s.indexer_version = $v "
             "ON MATCH SET s.content_hash = $h, "
             "s.last_indexed_at = CAST($ts AS TIMESTAMP), "
             "s.node_count = $nc, s.edge_count = $ec, s.indexer_version = $v")
    try:
        conn.execute(merge, parameters=params); return
    except Exception:
        pass
    try:
        conn.execute("MATCH (s:_source {file_path: $fp}) DELETE s",
                     parameters={"fp": fp})
    except Exception as e:
        _warn(f"_source delete for {fp} failed: {e}")
    try:
        conn.execute(
            "CREATE (s:_source {file_path: $fp, content_hash: $h, "
            "last_indexed_at: CAST($ts AS TIMESTAMP), "
            "node_count: $nc, edge_count: $ec, indexer_version: $v})",
            parameters=params)
    except Exception as e:
        _warn(f"_source upsert for {fp} failed: {e}")


def read_source_row(conn, fp: str) -> tuple[str | None, str | None]:
    try:
        r = conn.execute(
            "MATCH (s:_source {file_path: $fp}) RETURN "
            "s.content_hash AS h, s.indexer_version AS v",
            parameters={"fp": fp})
        if r.has_next():
            row = r.get_next()
            return (row[0], row[1])
    except Exception as e:
        _warn(f"_source read for {fp} failed: {e}")
    return (None, None)


# ─── Step 4: absence sweep ────────────────────────────────────────────────
def sweep_absent(conn, repo_root: str, counters: dict) -> None:
    try:
        r = conn.execute("MATCH (s:_source) RETURN s.file_path AS fp")
    except Exception as e:
        counters["warnings"].append(f"absence enumeration failed: {e}"); return
    rows = []
    try:
        while r.has_next():
            row = r.get_next()
            if row and row[0]:
                rows.append(str(row[0]))
    except Exception as e:
        counters["warnings"].append(f"absence iteration failed: {e}"); return
    for fp in rows:
        if fp.startswith("ast-grep-walk:"):
            continue
        if os.path.exists(_resolve_path(fp, repo_root)):
            continue
        try:
            pre = conn.execute(
                "MATCH (n) WHERE n.source_file = $fp RETURN count(n) AS c",
                parameters={"fp": fp})
            if pre.has_next():
                counters["nodes_deleted"] += int(pre.get_next()[0])
        except Exception:
            pass
        try:
            conn.execute("MATCH (n) WHERE n.source_file = $fp DETACH DELETE n",
                         parameters={"fp": fp})
        except Exception as e:
            counters["warnings"].append(f"absence node-delete failed for {fp}: {e}")
            continue
        try:
            conn.execute("MATCH (s:_source {file_path: $fp}) DELETE s",
                         parameters={"fp": fp})
            counters["files_absent_swept"] += 1
            _vlog(f"swept absent: {fp}")
        except Exception as e:
            counters["warnings"].append(
                f"absence _source-delete failed for {fp}: {e}")


def enumerate_canonical_files(repo_root: str) -> list[str]:
    out = []
    for c in (".cc-master/kanban.json", ".cc-master/roadmap.json",
              ".cc-master/discovery.json"):
        if os.path.exists(_resolve_path(c, repo_root)):
            out.append(c)
    specs_dir = _resolve_path(".cc-master/specs", repo_root)
    if os.path.isdir(specs_dir):
        sf = []
        for e in os.listdir(specs_dir):
            full = os.path.join(specs_dir, e)
            if not os.path.isfile(full):
                continue
            if e.endswith("-review.json") or "-review-" in e:
                continue
            m = re.match(r"^(\d+)\.md$", e)
            if m:
                sf.append((int(m.group(1)), f".cc-master/specs/{e}"))
        sf.sort(key=lambda t: t[0])
        out.extend(p for _, p in sf)
    return out


def open_or_bootstrap_db(repo_root: str):
    kuzu = _load_kuzu()
    db_path = os.path.join(repo_root, ".cc-master", "graph.kuzu")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    try:
        db = kuzu.Database(db_path)
        conn = kuzu.Connection(db)
    except Exception as e:
        _error(f"failed to open kuzu db at {db_path}: {e}"); sys.exit(3)
    bootstrap_schema(conn)
    return kuzu, db, conn, db_path


def _hash_for(fp: str, raw: bytes) -> dict:
    return hash_json(raw) if fp.endswith(".json") else hash_markdown(raw)


def _parse_for(fp: str, raw: bytes,
               mods: list[tuple[str, str]]) -> dict:
    if fp == ".cc-master/kanban.json":
        return parse_kanban(fp, raw)
    if fp == ".cc-master/roadmap.json":
        return parse_roadmap(fp, raw)
    if fp == ".cc-master/discovery.json":
        return parse_discovery(fp, raw)
    if fp.startswith(".cc-master/specs/") and fp.endswith(".md"):
        return parse_single_spec(fp, raw, mods)
    return {"nodes": [], "edges": []}


def run_full_mode(conn, repo_root: str, version: str, force_full: bool,
                  counters: dict, dry_run: bool) -> None:
    sweep_absent(conn, repo_root, counters)
    file_set = enumerate_canonical_files(repo_root)
    counters["files_total"] = len(file_set)

    raw_by: dict[str, bytes | None] = {}
    hash_by: dict[str, dict] = {}
    for fp in file_set:
        raw = _safe_read_bytes(_resolve_path(fp, repo_root))
        raw_by[fp] = raw
        if raw is None:
            hash_by[fp] = {"hash": None, "error": "file absent"}; continue
        hash_by[fp] = _hash_for(fp, raw)
        if hash_by[fp].get("hash") is None:
            counters["hash_errors"] += 1
            counters["warnings"].append(
                f"hash error for {fp}: {hash_by[fp].get('error')}")

    # Parse discovery first to populate module_paths for spec parser
    bundles: dict[str, dict] = {}
    for fp in file_set:
        if fp != ".cc-master/discovery.json":
            continue
        try:
            bundles[fp] = _parse_for(fp, raw_by[fp] or b"", [])
        except ValueError as e:
            counters["files_failed"] += 1
            counters["warnings"].append(f"parse error for {fp}: {e}")
            bundles[fp] = {"nodes": [], "edges": []}
    mods: list[tuple[str, str]] = []
    if ".cc-master/discovery.json" in bundles:
        for n in bundles[".cc-master/discovery.json"].get("nodes", []):
            if n["type"] == "Module":
                p = n["properties"]
                mods.append((p.get("name", ""), p.get("path", "") or ""))
    for fp in file_set:
        if fp in bundles:
            continue
        raw = raw_by[fp]
        if raw is None:
            bundles[fp] = {"nodes": [], "edges": []}; continue
        try:
            bundles[fp] = _parse_for(fp, raw, mods)
        except ValueError as e:
            counters["files_failed"] += 1
            counters["warnings"].append(f"parse error for {fp}: {e}")
            bundles[fp] = {"nodes": [], "edges": []}

    # Build cross-bundle endpoint set
    all_known: set[tuple[str, Any]] = set()
    for b in bundles.values():
        for n in b.get("nodes", []):
            nt = n.get("type")
            if nt not in _NODE_COLS:
                continue
            pk = _NODE_COLS[nt][0][0]
            all_known.add((nt, n.get("properties", {}).get(pk)))

    # Pass A: decide skip-vs-change + DELETE + INSERT NODES
    changed: list[str] = []
    for fp in file_set:
        raw = raw_by[fp]
        if raw is None:
            continue
        current_hash = hash_by[fp].get("hash")
        if not force_full:
            sh, sv = read_source_row(conn, fp)
            if (current_hash and sh and current_hash == sh and sv == version):
                counters["files_unchanged"] += 1
                _vlog(f"indexing {fp} (unchanged)"); continue
        _vlog(f"indexing {fp} ({'changed' if current_hash else 'forced'})")
        if dry_run:
            counters["files_changed"] += 1; continue
        bundle = bundles.get(fp, {"nodes": [], "edges": []})
        delete_by_source_file(conn, fp, counters)
        known_here = insert_nodes(conn, bundle, counters)
        for k in known_here:
            all_known.add(k)
        changed.append(fp)

    if dry_run:
        return

    # Pass B: INSERT EDGES + _source bookkeeping, now that all nodes exist
    for fp in changed:
        bundle = bundles.get(fp, {"nodes": [], "edges": []})
        known_here = set()
        for n in bundle.get("nodes", []):
            nt = n.get("type")
            if nt not in _NODE_COLS:
                continue
            pk = _NODE_COLS[nt][0][0]
            known_here.add((nt, n.get("properties", {}).get(pk)))
        insert_edges(conn, bundle, counters, known_here, existing=all_known)
        ch = hash_by[fp].get("hash")
        if ch is not None:
            upsert_source_row(
                conn, fp, ch,
                nc=len(bundle.get("nodes", [])),
                ec=len(bundle.get("edges", [])),
                v=version, ts=_iso_now())
        counters["files_changed"] += 1


_TOUCH_JSON = {".cc-master/kanban.json", ".cc-master/roadmap.json",
               ".cc-master/discovery.json"}


def _validate_touch(raw_input: str, repo_root: str) -> str:
    if "\x00" in raw_input or "%00" in raw_input:
        raise ValueError("null byte in --touch target")
    if ".." in raw_input.split("/"):
        raise ValueError("`..` segment in --touch target")
    abs_root = os.path.realpath(repo_root)
    abs_target = os.path.realpath(
        raw_input if os.path.isabs(raw_input)
        else os.path.join(os.getcwd(), raw_input))
    if not (abs_target == abs_root or abs_target.startswith(abs_root + os.sep)):
        raise ValueError(f"--touch target escapes repo root: {raw_input}")
    rel = os.path.relpath(abs_target, abs_root)
    if rel.startswith(".cc-master/specs/archive"):
        raise ValueError(f"archived specs out of scope: {rel}")
    if rel in _TOUCH_JSON:
        return rel
    if re.match(r"^\.cc-master/specs/(\d+)\.md$", rel):
        return rel
    raise ValueError(f"unsupported --touch target: {rel}")


def run_touch_mode(conn, repo_root: str, version: str, target: str,
                   counters: dict, dry_run: bool) -> None:
    abs_target = _resolve_path(target, repo_root)
    if not os.path.exists(abs_target):
        try:
            pre = conn.execute(
                "MATCH (n) WHERE n.source_file = $fp RETURN count(n) AS c",
                parameters={"fp": target})
            if pre.has_next():
                counters["nodes_deleted"] += int(pre.get_next()[0])
        except Exception:
            pass
        if not dry_run:
            try:
                conn.execute(
                    "MATCH (n) WHERE n.source_file = $fp DETACH DELETE n",
                    parameters={"fp": target})
                conn.execute("MATCH (s:_source {file_path: $fp}) DELETE s",
                             parameters={"fp": target})
            except Exception as e:
                counters["warnings"].append(f"touch delete failed: {e}")
                counters["files_failed"] += 1; return
        counters["files_absent_swept"] += 1; return

    raw = _safe_read_bytes(abs_target)
    if raw is None:
        counters["files_failed"] += 1
        counters["warnings"].append(f"touch: could not read {target}"); return
    hrec = _hash_for(target, raw)
    ch = hrec.get("hash")
    if ch is None:
        counters["hash_errors"] += 1
        counters["warnings"].append(
            f"touch hash error for {target}: {hrec.get('error')}")
    sh, sv = read_source_row(conn, target)
    if (ch and sh and ch == sh and sv == version):
        counters["files_unchanged"] += 1; return

    mods: list[tuple[str, str]] = []
    if target.startswith(".cc-master/specs/"):
        disc_raw = _safe_read_bytes(_resolve_path(
            ".cc-master/discovery.json", repo_root))
        if disc_raw is not None:
            try:
                b = parse_discovery(".cc-master/discovery.json", disc_raw)
                for n in b.get("nodes", []):
                    if n["type"] == "Module":
                        p = n["properties"]
                        mods.append((p.get("name", ""), p.get("path", "") or ""))
            except ValueError:
                pass
    try:
        bundle = _parse_for(target, raw, mods)
    except ValueError as e:
        counters["files_failed"] += 1
        counters["warnings"].append(f"parse error for {target}: {e}"); return
    if dry_run:
        counters["files_changed"] += 1; return
    delete_by_source_file(conn, target, counters)
    known = insert_nodes(conn, bundle, counters)
    insert_edges(conn, bundle, counters, known, existing=None)
    if ch is not None:
        upsert_source_row(conn, target, ch,
                          nc=len(bundle.get("nodes", [])),
                          ec=len(bundle.get("edges", [])),
                          v=version, ts=_iso_now())
    counters["files_changed"] += 1


def _new_counters() -> dict:
    return {"files_total": 0, "files_changed": 0, "files_unchanged": 0,
            "files_failed": 0, "files_absent_swept": 0,
            "nodes_deleted": 0, "nodes_inserted": 0,
            "edges_deleted": 0, "edges_inserted": 0,
            "hash_errors": 0, "warnings": []}


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE
    p = argparse.ArgumentParser(prog="run_index.py", allow_abbrev=False,
                                description="cc-master JSON→Kuzu indexer")
    p.add_argument("--full", action="store_true")
    p.add_argument("--touch", metavar="PATH")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1
    if args.full and args.touch is not None:
        _error("--full and --touch are mutually exclusive"); return 1
    _VERBOSE = bool(args.verbose)
    start = time.monotonic()
    repo_root = _resolve_repo_root()
    try:
        version = read_plugin_version(repo_root)
    except RuntimeError as e:
        _error(str(e)); return 3
    canonical: str | None = None
    if args.touch is not None:
        try:
            canonical = _validate_touch(args.touch, repo_root)
        except ValueError as e:
            _error(str(e)); return 1
    kuzu, db, conn, _db_path = open_or_bootstrap_db(repo_root)
    counters = _new_counters()
    mode = "default"
    touch_out: str | None = None
    try:
        if canonical is not None:
            mode = "touch"; touch_out = canonical
            run_touch_mode(conn, repo_root, version, canonical,
                           counters, args.dry_run)
        else:
            mode = "full" if args.full else "default"
            run_full_mode(conn, repo_root, version, args.full, counters,
                          args.dry_run)
    except Exception as e:
        _error(f"uncaught during indexing: {e}"); return 1
    finally:
        try:
            del conn; del db
        except Exception:
            pass
    print(json.dumps({
        "mode": mode, "touch_target": touch_out,
        "files_total": counters["files_total"],
        "files_changed": counters["files_changed"],
        "files_unchanged": counters["files_unchanged"],
        "files_failed": counters["files_failed"],
        "files_absent_swept": counters["files_absent_swept"],
        "nodes_deleted": counters["nodes_deleted"],
        "nodes_inserted": counters["nodes_inserted"],
        "edges_deleted": counters["edges_deleted"],
        "edges_inserted": counters["edges_inserted"],
        "hash_errors": counters["hash_errors"],
        "warnings": [_redact_string(w) for w in counters["warnings"]],
        "duration_ms": int((time.monotonic() - start) * 1000),
        "indexer_version": version,
        "kuzu_version": kuzu.__version__,
        "dry_run": bool(args.dry_run),
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        _error(f"uncaught: {type(exc).__name__}: {exc}")
        sys.exit(1)
