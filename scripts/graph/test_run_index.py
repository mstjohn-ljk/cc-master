"""Pytest suite for scripts/graph/run_index.py.

Tests use subprocess.run against run_index.py directly so the self-reexec
block at the top of the file does not interfere with import-time behavior
under pytest. Each test uses tmp_path as the project root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

INDEXER = Path(__file__).resolve().parent / "run_index.py"
PY = sys.executable  # run under the same interpreter the test was invoked with


# ─── Fixture helpers ────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _init_git(root: Path) -> None:
    """Minimal git init so `git rev-parse --git-common-dir` succeeds."""
    env = os.environ.copy()
    env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    env["GIT_AUTHOR_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = "t@t"
    subprocess.run(["git", "init", "-q", str(root)], check=True, env=env)


def _make_kanban(root: Path, num_tasks: int = 10) -> None:
    tasks = []
    for i in range(1, num_tasks + 1):
        tasks.append({
            "id": i,
            "subject": f"Task {i}",
            "description": f"Description for task {i}",
            "status": "pending",
            "owner": None,
            "blocked_by": [],
            "created_at": "2026-04-18T00:00:00Z",
            "updated_at": "2026-04-18T00:00:00Z",
            "metadata": {
                "source": "manual",
                "priority": "normal",
                "feature_id": "feat-1" if i <= 3 else None,
                "parent_id": None,
                "spec_file": f".cc-master/specs/{i}.md" if i <= 3 else None,
                "competitor_insight_ids": [],
                "phase": "",
                "wave": 1,
            },
        })
    _write_json(root / ".cc-master" / "kanban.json",
                {"version": 1, "next_id": num_tasks + 1, "tasks": tasks})


def _make_roadmap(root: Path, num_features: int = 5) -> None:
    feats = []
    for i in range(1, num_features + 1):
        feats.append({
            "id": f"feat-{i}",
            "title": f"Feature {i}",
            "description": "desc",
            "priority": "must_have",
            "complexity": "low",
            "impact": "high",
            "status": "planned",
        })
    _write_json(root / ".cc-master" / "roadmap.json",
                {"project": "test", "generated_at": "2026-04-18",
                 "phases": [{"id": "phase-1", "name": "P1", "features": feats}]})


def _make_discovery(root: Path, modules=None) -> None:
    if modules is None:
        modules = [
            {"name": "mod-a", "path": "src/a", "language": "python", "file_count": 10, "files": []},
            {"name": "mod-b", "path": "src/b", "language": "python", "file_count": 5, "files": []},
            {"name": "mod-c", "path": "src/c", "language": "python", "file_count": 3, "files": []},
        ]
    _write_json(root / ".cc-master" / "discovery.json", {"modules": modules})


def _make_spec(root: Path, n: int, extra: str = "") -> None:
    text = f"""# Spec {n}

## Requirement
Do something for task {n}.

## Production Readiness
no stubs

### Files to Modify
- src/a/file.py

{extra}
"""
    _write_text(root / ".cc-master" / "specs" / f"{n}.md", text)


def _make_plugin_manifest(root: Path, version: str = "0.21.0-test") -> None:
    _write_json(root / ".claude-plugin" / "plugin.json",
                {"name": "cc-master", "version": version})


@pytest.fixture
def fixture_project(tmp_path: Path) -> Path:
    """Build a fixture project: 10 tasks, 5 features, 3 modules, 3 specs."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git(root)
    _make_kanban(root, num_tasks=10)
    _make_roadmap(root, num_features=5)
    _make_discovery(root)
    _make_spec(root, 1)
    _make_spec(root, 2)
    _make_spec(root, 3)
    _make_plugin_manifest(root)
    return root


def _run(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    proc = subprocess.run(
        [PY, str(INDEXER), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _query(cwd: Path, cypher: str) -> list[dict]:
    """Run an arbitrary Cypher query via kuzu_client.py in the test's cwd."""
    client = Path(__file__).resolve().parent / "kuzu_client.py"
    db_path = cwd / ".cc-master" / "graph.kuzu"
    proc = subprocess.run(
        [PY, str(client), "query", str(db_path), cypher],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"query failed: {proc.stderr}")
    return json.loads(proc.stdout)


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_full_index_fresh(fixture_project: Path) -> None:
    rc, out, err = _run(["--full"], cwd=fixture_project)
    assert rc == 0, err
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["mode"] == "full"
    assert summary["files_total"] == 6  # kanban + roadmap + discovery + 3 specs
    assert summary["files_changed"] == 6
    assert summary["files_failed"] == 0
    assert summary["files_unchanged"] == 0

    tasks = _query(fixture_project, "MATCH (t:Task) RETURN count(t) AS c")
    assert tasks[0]["c"] == 10
    feats = _query(fixture_project, "MATCH (f:Feature) RETURN count(f) AS c")
    assert feats[0]["c"] == 5
    mods = _query(fixture_project, "MATCH (m:Module) RETURN count(m) AS c")
    assert mods[0]["c"] == 3
    specs = _query(fixture_project, "MATCH (s:Spec) RETURN count(s) AS c")
    assert specs[0]["c"] == 3

    # At least one HAS_SPEC edge (tasks 1,2,3 linked to specs 1,2,3)
    has_spec = _query(fixture_project,
                      "MATCH ()-[r:HAS_SPEC]->() RETURN count(r) AS c")
    assert has_spec[0]["c"] == 3


def test_touch_single_spec(fixture_project: Path) -> None:
    rc, out, _err = _run(["--full"], cwd=fixture_project)
    assert rc == 0

    # Capture baseline _source row for spec 2 and 3.
    baseline = _query(
        fixture_project,
        "MATCH (s:_source) RETURN s.file_path AS fp, s.content_hash AS h",
    )
    baseline_map = {r["fp"]: r["h"] for r in baseline}

    # Modify spec 1 only.
    _make_spec(fixture_project, 1, extra="\nmodified line\n")

    rc, out, err = _run(["--touch", ".cc-master/specs/1.md"],
                        cwd=fixture_project)
    assert rc == 0, err
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["mode"] == "touch"
    assert summary["touch_target"] == ".cc-master/specs/1.md"
    assert summary["files_changed"] == 1
    assert summary["files_unchanged"] == 0

    after = _query(
        fixture_project,
        "MATCH (s:_source) RETURN s.file_path AS fp, s.content_hash AS h",
    )
    after_map = {r["fp"]: r["h"] for r in after}

    # Spec 1 hash changed, specs 2 & 3 hashes unchanged.
    assert after_map[".cc-master/specs/1.md"] != baseline_map[".cc-master/specs/1.md"]
    assert after_map[".cc-master/specs/2.md"] == baseline_map[".cc-master/specs/2.md"]
    assert after_map[".cc-master/specs/3.md"] == baseline_map[".cc-master/specs/3.md"]


def test_full_twice_skips(fixture_project: Path) -> None:
    rc, out, err = _run(["--full"], cwd=fixture_project)
    assert rc == 0, err
    first = json.loads(out.strip().splitlines()[-1])
    assert first["files_changed"] == 6

    # Second run with NO flag — hash-compare should fire for every file.
    rc, out, err = _run([], cwd=fixture_project)
    assert rc == 0, err
    second = json.loads(out.strip().splitlines()[-1])
    assert second["files_total"] == 6
    assert second["files_unchanged"] == 6
    assert second["files_changed"] == 0
    assert second["nodes_inserted"] == 0
    assert second["edges_inserted"] == 0


def test_worktree_anchoring(fixture_project: Path, tmp_path: Path) -> None:
    # Create a commit so `git worktree add` has something to point at.
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    subprocess.run(["git", "add", "-A"], cwd=fixture_project,
                   check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"],
                   cwd=fixture_project, check=True, env=env)

    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt-branch", str(worktree)],
        cwd=fixture_project, check=True, env=env,
    )

    # Run indexer from within the worktree.
    rc, out, err = _run(["--full"], cwd=worktree)
    assert rc == 0, err

    # Graph file should live at the MAIN repo root, not at the worktree.
    main_graph = fixture_project / ".cc-master" / "graph.kuzu"
    wt_graph = worktree / ".cc-master" / "graph.kuzu"
    assert main_graph.exists(), "graph should be anchored at main repo root"
    assert not wt_graph.exists(), "graph should NOT be written inside worktree"


def test_secret_redaction(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _init_git(root)
    _make_plugin_manifest(root)
    _make_roadmap(root, num_features=1)
    _make_discovery(root, modules=[])

    # Task description contains a secret-shaped string and a fake PEM block.
    fake_key = "sk-test1234567890abcdefghijklmnop1234567890ABCD"
    fake_pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAxxxx\n"
        "yyyy\n"
        "-----END RSA PRIVATE KEY-----"
    )
    subj = f"Secret leak: API_KEY={fake_key} and PEM:{fake_pem} plus plaintext"

    tasks = [{
        "id": 1,
        "subject": subj,
        "description": "x",
        "status": "pending",
        "owner": None,
        "blocked_by": [],
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "metadata": {
            "source": "manual", "priority": "normal",
            "feature_id": None, "parent_id": None, "spec_file": None,
            "competitor_insight_ids": [], "phase": "", "wave": 1,
        },
    }]
    _write_json(root / ".cc-master" / "kanban.json",
                {"version": 1, "next_id": 2, "tasks": tasks})

    rc, out, err = _run(["--full"], cwd=root)
    assert rc == 0, err

    rows = _query(root, "MATCH (t:Task) RETURN t.subject AS subj")
    assert len(rows) == 1
    subject = rows[0]["subj"]
    assert fake_key not in subject
    assert "BEGIN RSA PRIVATE KEY" not in subject
    assert "[REDACTED]" in subject
    # Surrounding plaintext preserved.
    assert "Secret leak" in subject
    assert "plus plaintext" in subject


def test_40_digit_id_preserved(tmp_path: Path) -> None:
    """Pure-digit runs (timestamps, numeric IDs) must NOT be redacted."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git(root)
    _make_plugin_manifest(root)
    _make_roadmap(root, num_features=1)
    _make_discovery(root, modules=[])

    numeric_id = "1234567890" * 4  # 40 digits — no [a-f] chars
    assert len(numeric_id) == 40 and numeric_id.isdigit()
    subj = f"Invoice 40-digit id: {numeric_id} end"

    tasks = [{
        "id": 1,
        "subject": subj,
        "description": "x",
        "status": "pending",
        "owner": None,
        "blocked_by": [],
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "metadata": {
            "source": "manual", "priority": "normal",
            "feature_id": None, "parent_id": None, "spec_file": None,
            "competitor_insight_ids": [], "phase": "", "wave": 1,
        },
    }]
    _write_json(root / ".cc-master" / "kanban.json",
                {"version": 1, "next_id": 2, "tasks": tasks})

    rc, out, err = _run(["--full"], cwd=root)
    assert rc == 0, err

    rows = _query(root, "MATCH (t:Task) RETURN t.subject AS subj")
    assert len(rows) == 1
    subject = rows[0]["subj"]
    assert numeric_id in subject, (
        f"40-digit numeric ID must be preserved verbatim, got: {subject!r}")
    assert "[REDACTED]" not in subject


def test_warnings_redacted_in_summary(tmp_path: Path) -> None:
    """Warnings emitted on stderr and in stdout JSON summary must be redacted.

    We exercise _warn directly via subprocess so we don't need to trigger an
    internal warning path. We call _warn on a string containing a fake sk-
    secret and assert the raw secret never appears in stderr.
    """
    fake_key = "sk-test1234567890abcdefghijklmnop1234567890ABCD"
    # Run a tiny program that imports run_index and calls _warn.
    code = (
        "import sys, importlib.util, pathlib;"
        f"spec = importlib.util.spec_from_file_location('ri', r'{INDEXER}');"
        "m = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(m);"
        f"m._warn('leaked {fake_key}')"
    )
    proc = subprocess.run(
        [PY, "-c", code],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert fake_key not in proc.stderr, (
        f"raw secret leaked to stderr: {proc.stderr!r}")
    assert "[REDACTED]" in proc.stderr, (
        f"expected [REDACTED] in stderr, got: {proc.stderr!r}")
