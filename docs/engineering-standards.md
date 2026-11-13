# Engineering standards

I hold every change in this repository to the rules below. CONTRIBUTING.md links
here so contributors work to the same bar.

## 1. Code

1. Clarity over cleverness. Names say what a thing is in the domain
   (`max_depth`, not `d2`). Units go in names or types (`timeout_ms`,
   `max_file_mb`).
2. Small units: a function does one thing; files stay focused (soft cap around
   300 lines). No catch-all `utils` module; name modules by responsibility.
3. Pure core, thin I/O shell. Code in `src/rowsetta/core/` has no network,
   filesystem, clock or randomness hidden inside; the API shell and the CLI pass
   them in. This is what makes it testable.
4. Types are strict and honest: no `any`, no `# type: ignore`, no `!` non-null
   assertions, no casts to silence the checker. Model states explicitly
   (discriminated unions, literal types) instead of with booleans and nullable
   fields.
5. Errors: validate at trust boundaries (user input, files, network, model
   output) and fail loudly. Every error a user can see is a `UserError` with
   what happened and the exact next step. Never swallow exceptions. No defensive
   checks for states the types already rule out.
6. No magic numbers: named constants with units and a one-line source or reason
   when non-obvious.
7. No global mutable state. No singletons unless the platform forces it.
8. Dependencies: few, maintained, pinned, licence-compatible. Never add a
   dependency for something the standard library or an existing dependency does
   in a few lines.
9. Performance and accuracy claims come from a benchmark script in `scripts/`,
   recorded in `docs/bench.json`, never from prose.

## 2. What stays out

- Comments that narrate the code, banner comments, and docstrings that restate
  the signature. Comments explain why, constraints or sources. Public APIs get
  concise doc comments.
- Wrapper functions that only forward arguments; abstract base classes with one
  implementation; factories nobody needs; "manager" or "helper" classes without
  a real responsibility.
- Try/except around everything, redundant `isinstance` checks, and re-validation
  of data that is already validated.
- Dead code, commented-out code, unused imports, parameters or exports, a `TODO`
  without an issue link, `print` debugging, leftover feature flags.
- Near-duplicate code blocks, inconsistent naming styles and mixed formatting.
- Emoji in code, logs or command-line output; marketing language in docs;
  exclamation marks in log messages.
- Logging for its own sake. Log levels mean something, and logs are structured
  where that helps.
- Tests that assert nothing meaningful, snapshot everything, or mock the unit
  under test.
- Large generated files committed without need, and code copied in for later.

## 3. Tests

- Test behaviour, not implementation. Tests are deterministic: seeded randomness
  and fixed clocks. Fast unit tests cover the pure core, integration tests cover
  the API shell and the CLI, golden files cover SQL and CLI output, and
  Hypothesis property tests cover CSV parsing and SQL boundaries.
- Every bug fix lands with the test that would have caught it.
- Coverage is a signal, not a goal: aim for high coverage of the core logic, and
  do not write tests to hit a number.

## 4. Tooling

- Python: uv with a committed lockfile; ruff for lint (`select = ["ALL"]`) and
  format; pyright in strict mode; pytest.
- TypeScript: `strict` with `noUncheckedIndexedAccess` and
  `exactOptionalPropertyTypes`; typescript-eslint `strictTypeChecked`; Prettier;
  Vitest for units; Playwright and axe-core for the interface.
- Pre-commit hooks run format, lint, type checks and gitleaks for matching files.
  `make check` runs Ruff format and lint checks, Pyright, pytest excluding model
  and PostgreSQL tests, the OpenAPI comparison, the copy check, and frontend
  Prettier, ESLint, Svelte, TypeScript and Vitest checks. It does not run
  gitleaks or Playwright.

## 5. Repository hygiene

- LICENSE, NOTICE, README, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md,
  CHANGELOG.md (Keep a Changelog), semantic versioning, `.editorconfig`, issue
  and pull request templates, Dependabot, committed lockfiles, and no secrets
  ever (`.env.example` lists the variables).
- `docs/architecture.md` with a diagram; `docs/adr/` with a short Architecture
  Decision Record for every major choice.
- Reproducibility: one command to set up (`make setup`), one to check (`make
  check`), one to run the demo (`uv run rowsetta demo`). Scripts that
  download models or datasets verify SHA-256 checksums.
- Dependency pins are checked against the registry on the date
  `docs/development.md` records; a newer stable release replaces a pin, never an
  older one.

## 6. Git

- Small, atomic commits with conventional-commit messages that explain why. One
  logical change per pull request, with a description and screenshots for
  interface changes.
- History stays clean: no "fix typo" chains on `main` (squash or fixup before
  merge).

## 7. Accessibility

- Keyboard reachable, visible focus, semantic HTML, labelled controls, colour
  contrast meeting WCAG 2.2 AA, `prefers-reduced-motion` respected, no
  information conveyed by colour alone.

## 8. Before a change is done

1. Read the files the change touches. 2. Write or update the test first where
   practical. 3. Make the smallest complete change. 4. Run `make check`; it must
   pass. 5. Re-read the diff against sections 1 and 2. 6. Commit with a proper
   message. Nothing is done with failing checks or skipped tests.
