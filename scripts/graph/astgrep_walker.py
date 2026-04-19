#!/usr/bin/env python3
"""ast-grep walker for the cc-master v2 code-graph layer (subtask 77).

Walks one module directory with `ast-grep`, hashes every source file, and
extracts structural Symbol and Reference records. Emits a single JSON
document on stdout for the indexer (subtask 78) to consume and persist to
Kuzu.

Invariants:
    - All stdout output is a single top-level JSON object.
    - All errors and warnings go to stderr.
    - Stdin is never read.
    - No network I/O. No pip dependencies — Python 3.10+ stdlib only.
    - Uncaught exceptions are trapped at the top level and reported on
      stderr; Python tracebacks never leak.

Exit codes:
    0  success (JSON written to stdout)
    1  argument parsing error or uncaught exception
    2  ast-grep binary missing or unusable
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AST_GREP_INSTALL_HINT = (
    "ast-grep is required for the v2 graph engine code-graph layer.\n"
    "Install:\n"
    "  brew install ast-grep          # macOS\n"
    "  npm i -g @ast-grep/cli         # cross-platform via npm\n"
    "  cargo install ast-grep         # from source"
)

# Extension -> (language-key-for-patterns-file, ast-grep --lang value).
# JavaScript intentionally shares typescript.yml (per AC #10) — no separate
# javascript.yml is shipped. ast-grep's own language names diverge from our
# patterns-file keys: .ts -> ts, .tsx -> tsx, .js/.mjs/.cjs -> js, .jsx -> js.
EXT_LANG: dict[str, tuple[str, str]] = {
    ".py": ("python", "python"),
    ".ts": ("typescript", "ts"),
    ".tsx": ("typescript", "tsx"),
    ".js": ("typescript", "js"),
    ".jsx": ("typescript", "js"),
    ".mjs": ("typescript", "js"),
    ".cjs": ("typescript", "js"),
    ".go": ("go", "go"),
    ".java": ("java", "java"),
    ".rs": ("rust", "rust"),
}

# For file.language in output, normalize the ast-grep language back to the
# extension-language family so downstream schema is stable.
EXT_REPORT_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}

# Directory names to skip anywhere in the walk.
IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
    ".next",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
})

MAX_FILE_BYTES = 1_000_000  # 1 MB
BINARY_SNIFF_BYTES = 8192

# Symbol categories vs reference categories. Every pattern key in the YAML
# files must fall into one of these two sets.
SYMBOL_KINDS: frozenset[str] = frozenset({
    "function", "class", "method", "struct", "interface", "type", "enum",
})
REFERENCE_KINDS: frozenset[str] = frozenset({
    "call", "import", "type_ref",
})

# --- Test-file classification -------------------------------------------------
# Canonical rules live in prompts/test-file-definition.md. The patterns below
# mirror that fragment exactly; if the fragment changes, update these and the
# self-check table in `_classify_test_file_self_check()`.

# Path rules: exact directory-name match on any path component (not substring).
_TEST_DIR_NAMES: frozenset[str] = frozenset({
    "__tests__",
    "__mocks__",
    "test",
    "tests",
    "spec",
    "specs",
    "e2e",
    "cypress",
    "fixtures",
})

# Filename rules compiled as explicit regexes so the "requires a prefix before
# the dotted segment" semantics are unambiguous. Each regex matches the full
# basename.
_TEST_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    # *.test.*  — at least one char before `.test.`, then an extension.
    re.compile(r"^.+\.test\.[^.]+$"),
    # *.spec.*
    re.compile(r"^.+\.spec\.[^.]+$"),
    # *_test.*  — at least one char before `_test.`, then an extension. This
    # excludes `testify.go` because `testify` has no underscore separating a
    # `_test` suffix from the extension.
    re.compile(r"^.+_test\.[^.]+$"),
    # test_*.* — `test_` prefix with at least one more character before the dot.
    # Excludes bare `test.py`.
    re.compile(r"^test_[^.]+\.[^.]+$"),
    # *Test.java — Java test-class convention; basename must end in `Test.java`.
    # `TestHelper.java` is NOT matched (ends in `Helper.java`).
    re.compile(r"^.+Test\.java$"),
    # *IT.java — Java integration-test convention.
    re.compile(r"^.+IT\.java$"),
    # *_test.go — Go convention.
    re.compile(r"^.+_test\.go$"),
    # *.mock.*
    re.compile(r"^.+\.mock\.[^.]+$"),
    # *.fixture.*
    re.compile(r"^.+\.fixture\.[^.]+$"),
    # *.stories.*
    re.compile(r"^.+\.stories\.[^.]+$"),
    # conftest.py — exact filename.
    re.compile(r"^conftest\.py$"),
)


def classify_test_file(path: str) -> bool:
    """Return True if `path` identifies a test file per the canonical rules.

    Canonical source: ``prompts/test-file-definition.md``. The rules are
    mirrored in this module; if the fragment changes, update the constants
    above (`_TEST_DIR_NAMES`, `_TEST_FILENAME_PATTERNS`) and the self-check.

    Pure function with no side effects. Never raises on `str` input. If the
    caller passes a non-`str`, emit one stderr warning and return False —
    the walker's File-emit site must never blow up because of a rogue path
    value.
    """
    if not isinstance(path, str):
        _warn(
            f"classify_test_file: expected str, got {type(path).__name__}; "
            "treating as non-test"
        )
        return False

    # Normalize path separators so we apply the same rules on Windows-style
    # inputs. `Path.parts` handles both `/` and `\` portably.
    parts = Path(path).parts
    # The last component is the basename; everything earlier is a directory.
    # Path rules match on any *directory* component (not the basename) — a
    # source file literally named `test` with no extension is rare, but even
    # so the classifier should treat its path context, not its name, as the
    # signal for the directory rule.
    dir_components = parts[:-1] if len(parts) >= 1 else ()
    for component in dir_components:
        if component in _TEST_DIR_NAMES:
            return True

    basename = parts[-1] if parts else ""
    for pattern in _TEST_FILENAME_PATTERNS:
        if pattern.match(basename):
            return True

    return False


# Positive and negative fixtures that lock in the edge cases the canonical
# fragment enumerates. Exercised by the `--self-test` flag and imported by
# the unit-test suite in subtask #82.
_CLASSIFY_SELF_CHECK_CASES: tuple[tuple[str, bool], ...] = (
    # Positive — path rules.
    ("tests/foo.py", True),
    ("src/__tests__/x.ts", True),
    ("pkg/__mocks__/api.ts", True),
    ("app/spec/models.rb", True),
    ("app/specs/models.rb", True),
    ("e2e/login.spec.ts", True),
    ("cypress/integration/a.js", True),
    ("fixtures/users.json", True),
    # Positive — filename rules.
    ("foo.test.ts", True),
    ("bar_test.go", True),
    ("test_auth.py", True),
    ("UserTest.java", True),
    ("UserIT.java", True),
    ("service.mock.ts", True),
    ("conftest.py", True),
    ("page.stories.tsx", True),
    ("users.fixture.json", True),
    # Negative — must NOT match.
    ("testify.go", False),          # `_test` suffix required before ext
    ("best_of/foo.py", False),      # substring in dir-name, not exact match
    ("src/auth.ts", False),
    ("main.py", False),
    ("TestHelper.java", False),     # ends in Helper.java, not Test.java
    ("stories/page.tsx", False),    # `stories/` is not a path rule
    ("helper.ts", False),
    ("test.py", False),             # bare `test.py` fails test_*.* rule
    ("test.ts", False),             # bare `test.ts` has no prefix for *.test.*
)


def _run_classify_self_check() -> int:
    """Run the table-driven self-check and return the count of failures."""
    failures: list[str] = []
    for path, expected in _CLASSIFY_SELF_CHECK_CASES:
        actual = classify_test_file(path)
        if actual != expected:
            failures.append(
                f"  {path!r}: expected {expected}, got {actual}"
            )
    if failures:
        sys.stderr.write("classify_test_file self-check FAILED:\n")
        for line in failures:
            sys.stderr.write(line + "\n")
    else:
        sys.stderr.write(
            f"classify_test_file self-check: "
            f"{len(_CLASSIFY_SELF_CHECK_CASES)} cases OK\n"
        )
    return len(failures)


def _err(msg: str, code: int) -> None:
    """Print a plain-text error to stderr and exit."""
    print(msg, file=sys.stderr)
    sys.exit(code)


def _warn(msg: str) -> None:
    """Print a one-line warning to stderr."""
    print(f"warning: {msg}", file=sys.stderr)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp with second precision and trailing 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_astgrep_binary() -> str:
    """Return the ast-grep binary name on PATH, or exit 2 with install hint.

    ast-grep ships under two names: the canonical `ast-grep` and the short
    `sg`. Prefer the long name; accept the short name as fallback.
    """
    for binary in ("ast-grep", "sg"):
        try:
            subprocess.run(
                [binary, "--version"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            return binary
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        except subprocess.TimeoutExpired:
            _err(
                f"ast-grep ({binary}) timed out on --version; "
                "binary may be corrupted",
                2,
            )
    _err(AST_GREP_INSTALL_HINT, 2)


# Minimal YAML subset parser. Supports exactly the structure our pattern
# files use:
#     # comments
#     key:
#       - pattern: "string value"
#       - pattern: "string value"
# Intentionally rejects anything fancier so a malformed file fails loudly
# rather than silently mis-parsing.
_YAML_LIST_ITEM_RE = re.compile(r'^\s*-\s+pattern:\s+"(.*)"\s*$')
_YAML_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$")


def _unescape_yaml_double_quoted(s: str) -> str:
    """Handle the minimal escape set we actually emit in pattern strings."""
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _load_patterns(yml_path: Path) -> dict[str, list[str]]:
    """Parse the minimal YAML subset used by pattern files."""
    try:
        raw = yml_path.read_text(encoding="utf-8")
    except OSError as e:
        _warn(f"cannot read pattern file {yml_path}: {e}")
        return {}
    patterns: dict[str, list[str]] = {}
    current_key: str | None = None
    for line_num, line in enumerate(raw.splitlines(), start=1):
        stripped = line.split("#", 1)[0].rstrip()  # strip comments + trailing ws
        if not stripped.strip():
            continue
        # Key line (no leading whitespace).
        if not line.startswith((" ", "\t")):
            m = _YAML_KEY_RE.match(stripped)
            if m:
                current_key = m.group(1)
                patterns.setdefault(current_key, [])
                continue
            _warn(
                f"{yml_path}:{line_num}: unrecognized top-level line, skipping"
            )
            current_key = None
            continue
        # Indented list item.
        if current_key is None:
            _warn(
                f"{yml_path}:{line_num}: indented line without a key, skipping"
            )
            continue
        m = _YAML_LIST_ITEM_RE.match(line)
        if not m:
            _warn(
                f"{yml_path}:{line_num}: unrecognized pattern line, skipping"
            )
            continue
        patterns[current_key].append(_unescape_yaml_double_quoted(m.group(1)))
    return patterns


def _is_binary(path: Path) -> bool:
    """Return True if the file's first 8 KB contains a null byte."""
    try:
        with path.open("rb") as fp:
            chunk = fp.read(BINARY_SNIFF_BYTES)
    except OSError as e:
        _warn(f"cannot open {path} for binary sniff: {e}")
        return True  # skip unreadable files same as binaries
    return b"\x00" in chunk


def _should_skip_dir(name: str) -> bool:
    return name in IGNORE_DIRS


def _iter_module_files(module_path: Path) -> Iterable[Path]:
    """Yield Paths to every candidate file under module_path after filtering.

    Filters applied:
      - Ignore directories named in IGNORE_DIRS.
      - Skip files larger than MAX_FILE_BYTES.
      - Skip files that look binary (null byte in first 8 KB).
    Unreadable files are skipped with a stderr warning.
    """
    for dirpath, dirnames, filenames in os.walk(module_path):
        # Prune in-place so os.walk won't descend.
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            try:
                st = fpath.stat()
            except OSError as e:
                _warn(f"cannot stat {fpath}: {e}")
                continue
            # S_IFMT mask/value check for regular file (portable to stdlib).
            if (st.st_mode & 0o170000) != 0o100000:
                # Not a regular file (symlink-to-dir, device, socket, ...).
                continue
            if st.st_size > MAX_FILE_BYTES:
                _warn(
                    f"skipping {fpath}: {st.st_size} bytes exceeds "
                    f"{MAX_FILE_BYTES}"
                )
                continue
            if _is_binary(fpath):
                continue
            yield fpath


def _hash_file(path: Path) -> tuple[str, int] | None:
    """Return (sha256 hex, size) or None on error."""
    h = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as fp:
            while True:
                chunk = fp.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                total += len(chunk)
    except OSError as e:
        _warn(f"cannot hash {path}: {e}")
        return None
    return h.hexdigest(), total


def _symbol_id(module: str, file_rel: str, kind: str, name: str, line: int) -> str:
    """Deterministic 16-char hex ID. Spec: AC #4."""
    key = f"{module}:{file_rel}:{kind}:{name}:{line}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _relpath_from_project(module_path: Path, abs_file: Path,
                          project_root: Path) -> str | None:
    """File path relative to the project root (not the module root).

    Defence-in-depth against symlink escapes: os.walk(followlinks=False)
    already neutralises directory symlinks, but a file-level symlink whose
    target sits outside the project root would still slip through. Assert
    that the resolved abs_file is a descendant of the resolved project_root;
    if not, emit a stderr warning and return None so the caller skips the
    file entirely instead of silently falling back to a module-relative
    path that could leak absolute paths into the graph.
    """
    resolved_file = abs_file.resolve()
    resolved_root = project_root.resolve()
    try:
        return str(resolved_file.relative_to(resolved_root))
    except ValueError:
        _warn(
            f"file '{resolved_file}' resolved outside project root "
            f"'{resolved_root}' — skipping symlink-escaped file"
        )
        return None


def _run_astgrep(
    binary: str,
    lang: str,
    pattern: str,
    target: Path,
) -> list[dict[str, Any]]:
    """Invoke ast-grep for one pattern over one file; return parsed matches.

    Malformed JSON lines are skipped with a stderr warning. A non-zero exit
    from ast-grep with no matches is treated as "no matches" (ast-grep exits
    non-zero on zero matches in some versions).
    """
    cmd = [
        binary, "run",
        "--lang", lang,
        "--pattern", pattern,
        "--json=stream",
        str(target),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        _err(AST_GREP_INSTALL_HINT, 2)
    except subprocess.TimeoutExpired:
        _warn(f"ast-grep timed out on {target} (pattern={pattern!r})")
        return []

    matches: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _warn(f"malformed ast-grep JSON line from {target}: {e}")
            continue
        if isinstance(obj, dict):
            matches.append(obj)
    return matches


def _extract_names_and_lines(
    match: dict[str, Any],
) -> list[tuple[str, int]]:
    """Pull names + 1-based lines from a match dict.

    Returns a list because some patterns (e.g. `import { A, B }`) bind a
    multi-metavariable `NAMES` that encodes several references in one match.
    Preference order: single.NAME, multi.NAMES. Returns [] if neither.
    """
    out: list[tuple[str, int]] = []
    meta = match.get("metaVariables") or {}
    single = meta.get("single") or {}
    if "NAME" in single:
        try:
            name = single["NAME"]["text"]
            line = int(single["NAME"]["range"]["start"]["line"]) + 1
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if isinstance(name, str) and name:
                out.append((name, line))
        return out
    multi = meta.get("multi") or {}
    for node in multi.get("NAMES", []) or []:
        try:
            name = node["text"]
            line = int(node["range"]["start"]["line"]) + 1
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(name, str) and name:
            out.append((name, line))
    return out


def _extract_context(match: dict[str, Any]) -> str:
    """Short text snippet for the reference's `context` field."""
    text = match.get("text", "")
    if not isinstance(text, str):
        return ""
    # Cap at 200 chars; collapse internal whitespace to a single space.
    collapsed = " ".join(text.split())
    # Redact secret-shaped tokens before persistence — prevents incidental
    # credential leakage into the graph DB if a source file pastes a key
    # into a call-site literal.
    redacted = _redact_secrets(collapsed)
    return redacted[:200]


# Secret redaction patterns. Compiled once at module load to avoid per-call
# re-compile overhead. Prevents incidental credential persistence in graph DB
# when source files happen to contain hardcoded keys inside call-site text.
_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM blocks — multiline, must run before the hex/base64 fallbacks.
    (re.compile(r"-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----"),
     "<redacted-pem-block>"),
    # Known provider prefixes — specific before generic.
    (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "sk-<redacted>"),
    (re.compile(r"ghp_[A-Za-z0-9_]{20,}"), "ghp_<redacted>"),
    (re.compile(r"AKIA[A-Z0-9]{16,}"), "AKIA<redacted>"),
    # Generic high-entropy strings — 40+ hex chars, then 40+ base64 chars.
    (re.compile(r"[0-9a-fA-F]{40,}"), "<redacted-hex>"),
    (re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"), "<redacted-base64>"),
)


def _redact_secrets(text: str) -> str:
    """Apply compiled redaction patterns in order."""
    for pat, repl in _REDACTION_PATTERNS:
        text = pat.sub(repl, text)
    return text


def walk_module(
    module_name: str,
    module_path: Path,
    project_root: Path,
    patterns_dir: Path,
) -> dict[str, Any]:
    """Main walk: produce the full JSON output structure."""
    binary = _resolve_astgrep_binary()
    walked_at = _now_iso()

    files_out: list[dict[str, Any]] = []
    symbols_out: list[dict[str, Any]] = []
    references_out: list[dict[str, Any]] = []

    # symbol lookup for REFERENCES resolution: (module, file_rel, kind, name)
    # maps to the first symbol_id we emitted for it. We only resolve within
    # this module; cross-module resolution is the indexer's job.
    symbol_index: dict[tuple[str, str, str, str], str] = {}

    # Cache per-language patterns loaded from YAML.
    pattern_cache: dict[str, dict[str, list[str]]] = {}

    # First pass: enumerate files, emit File records.
    module_files: list[tuple[Path, str, str | None]] = []
    # (abs_path, rel_path_from_project, lang_key_or_None)
    for abs_file in _iter_module_files(module_path):
        rel = _relpath_from_project(module_path, abs_file, project_root)
        if rel is None:
            # Symlink escaped project root — skip without emitting File record.
            continue
        ext = abs_file.suffix.lower()
        lang_key = EXT_LANG.get(ext, (None, None))[0]
        report_lang = EXT_REPORT_LANG.get(ext)
        hashed = _hash_file(abs_file)
        if hashed is None:
            continue
        content_hash, size = hashed
        files_out.append({
            "path": rel,
            "module": module_name,
            "language": report_lang,
            "content_hash": content_hash,
            "size": size,
            # Classification rules are mirrored from
            # prompts/test-file-definition.md in `classify_test_file`.
            "is_test": classify_test_file(rel),
            "last_indexed": walked_at,
        })
        module_files.append((abs_file, rel, lang_key))

    # Second pass: for each file with a known language, run the per-kind
    # pattern invocations and collect symbols + references.
    for abs_file, rel, lang_key in module_files:
        if lang_key is None:
            continue  # unknown extension: file recorded, but no symbols
        ast_lang = EXT_LANG[abs_file.suffix.lower()][1]

        if lang_key not in pattern_cache:
            pattern_cache[lang_key] = _load_patterns(
                patterns_dir / f"{lang_key}.yml"
            )
        kinds = pattern_cache[lang_key]
        if not kinds:
            _warn(f"no patterns loaded for language {lang_key}; skipping file")
            continue

        # Dedup symbol (kind, name, line) pairs per file — multiple patterns
        # in the same kind can match the same node (e.g. `class X` and
        # `export class X` both fire on `export class X`).
        seen_symbols: set[tuple[str, str, int]] = set()
        seen_references: set[tuple[str, str, int]] = set()

        # Symbol kinds first — populate symbol_index before references so
        # same-file call sites can resolve in one pass.
        for kind in SYMBOL_KINDS:
            patterns = kinds.get(kind, [])
            for pat in patterns:
                for match in _run_astgrep(binary, ast_lang, pat, abs_file):
                    for name, line in _extract_names_and_lines(match):
                        key_dedup = (kind, name, line)
                        if key_dedup in seen_symbols:
                            continue
                        seen_symbols.add(key_dedup)
                        sid = _symbol_id(module_name, rel, kind, name, line)
                        symbols_out.append({
                            "id": sid,
                            "name": name,
                            "kind": kind,
                            "file": rel,
                            "line": line,
                            "module": module_name,
                        })
                        symbol_index.setdefault(
                            (module_name, rel, kind, name), sid
                        )

        # Reference kinds.
        for kind in REFERENCE_KINDS:
            patterns = kinds.get(kind, [])
            for pat in patterns:
                for match in _run_astgrep(binary, ast_lang, pat, abs_file):
                    ctx = _extract_context(match)
                    for name, line in _extract_names_and_lines(match):
                        key_dedup = (kind, name, line)
                        if key_dedup in seen_references:
                            continue
                        seen_references.add(key_dedup)
                        # Best-effort resolution against the same-module
                        # symbol index. Cross-module resolution is the
                        # indexer's job; unresolved -> symbol_id = null.
                        resolved_id: str | None = None
                        # Prefer narrower kinds first: `method` before `function`
                        # so `self.foo()` resolves to the method when both exist.
                        for sk in ("method", "function", "class", "struct",
                                   "interface", "type", "enum"):
                            candidate = (module_name, rel, sk, name)
                            if candidate in symbol_index:
                                resolved_id = symbol_index[candidate]
                                break
                        references_out.append({
                            "symbol_id": resolved_id,
                            "symbol_name": name,
                            "file": rel,
                            "line": line,
                            "context": ctx,
                            "kind": kind,
                        })

    return {
        "module": module_name,
        "module_path": str(module_path.resolve()),
        "walked_at": walked_at,
        "files": files_out,
        "symbols": symbols_out,
        "references": references_out,
    }


def _find_project_root(module_path: Path) -> Path:
    """Walk up from module_path looking for a .cc-master/ or .git/ marker."""
    cur = module_path.resolve()
    for _ in range(32):
        if (cur / ".cc-master").exists() or (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return module_path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Walk a module with ast-grep and emit JSON describing files, "
            "symbols, and references for the cc-master code-graph indexer."
        ),
    )
    parser.add_argument(
        "--module",
        required=False,
        help="Module node name to stamp on every emitted record.",
    )
    parser.add_argument(
        "--module-path",
        required=False,
        help="Absolute directory to walk.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the classify_test_file() table-driven self-check and exit. "
            "Exits 0 on success, 1 on any failure."
        ),
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        default=True,
        help="Print JSON to stdout (default; flag included for clarity).",
    )
    parser.add_argument(
        "--patterns-dir",
        default=None,
        help=(
            "Directory containing per-language YAML pattern files. "
            "Defaults to astgrep_patterns/ next to this script."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            "Project root used to compute file paths relative to the repo. "
            "Defaults to the nearest ancestor containing .cc-master/ or .git/."
        ),
    )

    try:
        args = parser.parse_args()
    except SystemExit as e:
        if e.code == 0:
            raise
        sys.exit(1)

    if args.self_test:
        failures = _run_classify_self_check()
        sys.exit(1 if failures else 0)

    # `--module` and `--module-path` are only optional when `--self-test` is
    # set; enforce them here so the normal walk path still requires them.
    if not args.module:
        _err("--module is required (unless --self-test)", 1)
    if not args.module_path:
        _err("--module-path is required (unless --self-test)", 1)

    # Validate ast-grep up front so we fail fast with exit code 2 before any
    # file I/O. walk_module will reuse the same binary.
    _resolve_astgrep_binary()

    module_path = Path(args.module_path)
    if not module_path.exists():
        _err(f"module path does not exist: {module_path}", 1)
    if not module_path.is_dir():
        _err(f"module path is not a directory: {module_path}", 1)

    if args.patterns_dir is not None:
        patterns_dir = Path(args.patterns_dir)
    else:
        patterns_dir = Path(__file__).resolve().parent / "astgrep_patterns"
    if not patterns_dir.is_dir():
        _err(f"patterns directory missing: {patterns_dir}", 1)

    project_root = (
        Path(args.project_root) if args.project_root
        else _find_project_root(module_path)
    )

    started = time.monotonic()
    try:
        result = walk_module(
            module_name=args.module,
            module_path=module_path,
            project_root=project_root,
            patterns_dir=patterns_dir,
        )
    except SystemExit:
        raise
    except Exception as e:
        _err(f"unexpected: {type(e).__name__}: {e}", 1)

    elapsed = time.monotonic() - started
    _warn(
        f"walk complete: {len(result['files'])} files, "
        f"{len(result['symbols'])} symbols, "
        f"{len(result['references'])} references in {elapsed:.2f}s"
    )

    if args.stdout_json:
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
