# Test File Classification

This fragment is the canonical definition of what counts as a test file, what counts as a non-source file, and what counts as production source in the cc-master plugin. It is consumed by the `build` skill's production-quality scan (Step 6: Verify Implementation) and by the v2 graph engine's code-graph walker when setting `File.is_test`. Any future change to the classification rules MUST land here first; downstream call sites mirror this file and cite it as the source of truth.

## Path Rules

A file is a test file if any path segment (an exact directory name, not a substring) matches one of:

- `__tests__/`
- `__mocks__/`
- `test/`
- `tests/`
- `spec/`
- `specs/`
- `e2e/`
- `cypress/`
- `fixtures/`

Match on directory-name equality. A directory whose name merely contains the letters `test` as a substring does not match. `src/best_of/page.tsx` is NOT a test — `best_of` is not `test/`.

## Filename Rules

A file is a test file if its basename matches any of:

- `*.test.*` (e.g. `button.test.tsx`)
- `*.spec.*` (e.g. `user.spec.ts`)
- `*_test.*` (e.g. `handler_test.py`)
- `test_*.*` (e.g. `test_parser.py` — the underscore MUST be followed by at least one more character before the extension)
- `*Test.java` (e.g. `UserServiceTest.java`)
- `*IT.java` (e.g. `PaymentFlowIT.java`)
- `*_test.go` (e.g. `handler_test.go`)
- `*.mock.*` (e.g. `api.mock.ts`)
- `*.fixture.*` (e.g. `users.fixture.json`)
- `*.stories.*` (e.g. `Button.stories.tsx`)
- `conftest.py` (exact filename)

## Non-Source Files

A file is a non-source file (also excluded from the production-quality scan) if its extension or path matches:

- `*.md`
- `*.json`
- `*.yaml`
- `*.yml`
- `*.lock`
- `*.xml`
- `*.properties`
- `*.env`
- `*.conf`
- `*.gradle`
- `pom.xml`
- Generated output directories: `build/`, `dist/`, `node_modules/`, `target/`, `.next/`, `__pycache__/`

## Production Source

A file is production source (subject to the stub/mock/skeleton scan, and marked `is_test=false` in the code graph) if and only if it matches neither the test rules nor the non-source rules above.

## Edge Cases

These cases exist because early implementations got them wrong. Keep them as verifiable assertions for any downstream unit tests.

- `testify.go` is NOT a test. The `test_*.*` rule requires a `test_` prefix followed by more characters after the underscore; `testify.go` has no underscore after `test`. It is production source.
- `src/best_of/page.tsx` is NOT a test. Path rules require exact directory-name equality (e.g. `test/`, `tests/`, `spec/`). A directory named `best_of` contains the substring `test` nowhere — and even if it did, substring matches do not trigger the rule. It is production source.
- `src/stories/page.tsx` is NOT a test. The `stories/` path is NOT listed in the path rules; only the `*.stories.*` filename rule matches test-like files (e.g. `Button.stories.tsx`). A file named `page.tsx` inside a `stories/` directory is production source.

## Usage

Skills that reference this classification MUST cite this file by path (`prompts/test-file-definition.md`) and MAY mirror the rules inline for human readability, but the inline text is a mirror — the canonical rules live here. If the inline mirror drifts from this file, this file wins.
