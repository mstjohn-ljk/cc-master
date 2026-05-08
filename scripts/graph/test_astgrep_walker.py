#!/usr/bin/env python3
"""Unit tests for ``classify_test_file`` (subtask #82).

Exercises the classifier defined in ``astgrep_walker.py`` against the
canonical rules in ``prompts/test-file-definition.md``. The suite is
pytest-compatible AND runnable via the stdlib fallback at the bottom of
the file — no non-stdlib dependencies are required for either mode.

Groupings follow the acceptance-criteria layout:
    - Path-rule positives (per directory name)
    - Path-rule exact-component negatives (substring must NOT match)
    - Filename-rule positives (per pattern)
    - Filename-rule prefix negatives (bare/no-prefix forms)
    - Documented edge cases: stories/, conftest, non-string inputs
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from astgrep_walker import classify_test_file  # noqa: E402


# ---------------------------------------------------------------------------
# Path rule positives (directory-name equality on any path component).
# ---------------------------------------------------------------------------
def test_path_rule_match_returns_true() -> None:
    """Every directory name listed in the canonical path rules triggers True."""
    # One case per directory name, plus a couple of cross-shape variants.
    cases = [
        "tests/foo.py",                         # tests/
        "src/__tests__/Component.tsx",          # __tests__/
        "pkg/__mocks__/fs.js",                  # __mocks__/
        "my/test/case.py",                      # test/
        "my/spec/case.py",                      # spec/
        "app/specs/scenario.py",                # specs/
        "e2e/journey.ts",                       # e2e/
        "cypress/commands.js",                  # cypress/
        "fixtures/users.json",                  # fixtures/
        "deep/nested/tests/x.py",               # tests/ not at root
        "src/feature/__tests__/Component.tsx",  # __tests__/ nested deep
    ]
    for path in cases:
        assert classify_test_file(path) is True, (
            f"expected True for path-rule case {path!r}"
        )


def test_path_rule_exact_component_match_only() -> None:
    """Directories that merely *contain* a test substring must NOT match."""
    cases = [
        "best_of/foo.py",           # substring 'test' not a component
        "contested_outcome/x.py",   # substring 'test' not a component
        "non_test_dir/y.py",        # 'non_test_dir' is not 'test'
        "src/testimonials/card.ts", # 'testimonials' is not 'tests'
        "src/specific/impl.py",     # 'specific' is not 'spec'
    ]
    for path in cases:
        assert classify_test_file(path) is False, (
            f"expected False for substring-only path {path!r}"
        )


# ---------------------------------------------------------------------------
# Filename rule positives (one per pattern).
# ---------------------------------------------------------------------------
def test_filename_rule_match_returns_true() -> None:
    """Every filename pattern in the canonical filename rules triggers True."""
    cases = [
        "foo.test.ts",              # *.test.*
        "Button.test.tsx",          # *.test.* jsx/tsx shape
        "user.spec.ts",             # *.spec.*
        "handler_test.py",          # *_test.*
        "bar_test.go",              # *_test.* (also *_test.go)
        "test_auth.py",             # test_*.*
        "test_parser.py",           # test_*.*
        "UserServiceTest.java",     # *Test.java
        "UserIT.java",              # *IT.java
        "PaymentFlowIT.java",       # *IT.java
        "api.mock.ts",              # *.mock.*
        "users.fixture.json",       # *.fixture.*
        "card.stories.tsx",         # *.stories.*
        "conftest.py",              # exact conftest.py
    ]
    for path in cases:
        assert classify_test_file(path) is True, (
            f"expected True for filename-rule case {path!r}"
        )


def test_filename_rule_requires_prefix() -> None:
    """Patterns that require at least one leading char must reject bare forms."""
    cases = [
        "testify.go",       # *_test.go requires `_test` suffix before ext
        "TestHelper.java",  # *Test.java requires Test as a SUFFIX (this is prefix)
        "testing.ts",       # no matching pattern — 'testing' has no separator
        "test.ts",          # *.test.* needs a prefix before `.test.`; *_test.* needs `_`
        "test.py",          # test_*.* requires an underscore + another char
    ]
    for path in cases:
        assert classify_test_file(path) is False, (
            f"expected False for no-prefix / wrong-shape name {path!r}"
        )


# ---------------------------------------------------------------------------
# Documented edge cases.
# ---------------------------------------------------------------------------
def test_stories_edge_case() -> None:
    """`stories/` is NOT a path rule but `*.stories.*` IS a filename rule."""
    # Directory named `stories/` must NOT trigger on its own.
    assert classify_test_file("src/stories/page.tsx") is False
    assert classify_test_file("stories/page.tsx") is False
    # Filename pattern DOES trigger regardless of surrounding directory.
    assert classify_test_file("Button.stories.tsx") is True
    assert classify_test_file("src/components/Button.stories.tsx") is True


def test_conftest_exact_filename() -> None:
    """Exact `conftest.py` matches; anything else with `conftest` in its name does not."""
    assert classify_test_file("conftest.py") is True
    assert classify_test_file("pkg/conftest.py") is True
    # Close cousins must not match — rule is exact filename equality.
    assert classify_test_file("conftest_helper.py") is False
    assert classify_test_file("my_conftest.py") is False
    assert classify_test_file("conftest.rb") is False


def test_non_string_input_safe() -> None:
    """Non-`str` inputs must return False without raising."""
    # The classifier logs a warning and returns False; we only assert on the
    # return value so the test works regardless of stderr capture config.
    assert classify_test_file(None) is False           # type: ignore[arg-type]
    assert classify_test_file(42) is False             # type: ignore[arg-type]
    assert classify_test_file([]) is False             # type: ignore[arg-type]
    assert classify_test_file({"path": "x.py"}) is False  # type: ignore[arg-type]
    assert classify_test_file(b"tests/foo.py") is False   # bytes, not str


# ---------------------------------------------------------------------------
# Spec-verbatim smoke: every positive/negative case from the AC list resolves
# the way the AC says it should. This is an additional redundancy test so a
# regression in the classifier caught here is unambiguous about which case
# failed, rather than buried inside a looped assertion list above.
# ---------------------------------------------------------------------------
def test_ac_positive_cases_verbatim() -> None:
    """The 16 positive cases from the acceptance criteria all classify True."""
    ac_positives = [
        "tests/foo.py",
        "src/__tests__/Component.tsx",
        "my/spec/case.py",
        "app/specs/scenario.py",
        "__mocks__/fs.js",
        "e2e/journey.ts",
        "cypress/commands.js",
        "foo.test.ts",
        "bar_test.go",
        "test_auth.py",
        "UserServiceTest.java",
        "UserIT.java",
        "conftest.py",
        "card.stories.tsx",
        "api.mock.ts",
        "payload.fixture.json",
    ]
    for path in ac_positives:
        assert classify_test_file(path) is True, (
            f"AC positive {path!r} must classify as test"
        )


def test_ac_negative_cases_verbatim() -> None:
    """The 14 negative cases from the acceptance criteria all classify False."""
    ac_negatives = [
        "src/main.py",
        "lib/helper.ts",
        "testify.go",
        "best_of/foo.py",
        "stories/page.tsx",
        "tester.js",
        "contest.py",
        "spectator.py",
        "TestHelper.java",
        "mainTest.go",          # *Test.go is NOT a rule — only *_test.go
        "services/users.py",
        "components/Header.tsx",
        "Dockerfile",
        "index.js",
        "README.md",
    ]
    for path in ac_negatives:
        assert classify_test_file(path) is False, (
            f"AC negative {path!r} must classify as non-test"
        )


# ---------------------------------------------------------------------------
# Stdlib fallback runner — discovers `test_*` functions defined above and
# executes each, tracking pass/fail and the first failing assertion message.
# ---------------------------------------------------------------------------
def _discover_test_functions() -> list[tuple[str, object]]:
    """Return (name, callable) pairs for every top-level `test_*` function."""
    module = sys.modules[__name__]
    out: list[tuple[str, object]] = []
    for name in sorted(vars(module)):
        if not name.startswith("test_"):
            continue
        fn = getattr(module, name)
        if callable(fn):
            out.append((name, fn))
    return out


# Counter of actual `classify_test_file` calls — every test asserts on the
# return value of one call, so this equals the number of assertions executed.
# Populated by ``_run_stdlib`` wrapping the import symbol at run time.
_CLASSIFY_CALL_COUNT = 0


def _run_stdlib() -> int:
    """Run every discovered test function; print a summary. Return exit code.

    Wraps ``classify_test_file`` in a counting proxy so the summary line can
    report an accurate count of assertions executed instead of a source-line
    heuristic that undercounts looped assertions.
    """
    global _CLASSIFY_CALL_COUNT
    import astgrep_walker as _walker  # local import so module-level import stays clean

    original = _walker.classify_test_file

    def _counting_classify(path):  # type: ignore[no-untyped-def]
        global _CLASSIFY_CALL_COUNT
        _CLASSIFY_CALL_COUNT += 1
        return original(path)

    # Patch both the walker module and our module's bound name so looped
    # assertions through either reference are counted.
    _walker.classify_test_file = _counting_classify  # type: ignore[assignment]
    this_module = sys.modules[__name__]
    this_module.classify_test_file = _counting_classify  # type: ignore[attr-defined]

    try:
        tests = _discover_test_functions()
        failures: list[tuple[str, BaseException]] = []
        for name, fn in tests:
            try:
                fn()
            except AssertionError as e:
                failures.append((name, e))
                print(f"FAIL: {name}: {e}", file=sys.stderr)
            except Exception as e:  # pragma: no cover - unexpected runtime error
                failures.append((name, e))
                print(
                    f"ERROR: {name}: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
    finally:
        _walker.classify_test_file = original  # type: ignore[assignment]
        this_module.classify_test_file = original  # type: ignore[attr-defined]

    if failures:
        print(
            f"classify_test_file unit tests: {len(failures)} of "
            f"{len(tests)} test functions FAILED",
            file=sys.stderr,
        )
        return 1

    print(
        f"classify_test_file unit tests: {len(tests)} test functions, "
        f"{_CLASSIFY_CALL_COUNT}+ assertions, all pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_run_stdlib())
