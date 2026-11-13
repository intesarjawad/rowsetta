# Contributing

Read the [engineering standards](docs/engineering-standards.md) before changing code.
Keep changes scoped to one task and include evidence for changed behaviour.

Use `make setup` to install locked Python and frontend dependencies and the
pre-commit hook. Use `make check` before review. It checks formatting, lint,
strict types and tests on both stacks. Model and PostgreSQL tests have separate
markers; the default check needs neither credentials nor a database.

Keep `uv.lock` and `frontend/pnpm-lock.yaml` with dependency changes. Python 3.13
is the local default; CI also covers Python 3.14.
Use `make dev` to run the frontend and `make build` to build artifacts.
Do not commit credentials, model weights, local environment files or user data.

Document decisions in `docs/adr/` and measured findings in `docs/`. Before review,
explain the problem, the resulting behaviour and the checks you ran. Follow the
[code of conduct](CODE_OF_CONDUCT.md) and [security policy](SECURITY.md).

Branch protection and CodeQL default setup require a hosted repository. See
[development notes](docs/development.md).
