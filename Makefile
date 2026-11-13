.PHONY: setup dev check test build bench bench-full golden demo-gif browser

setup:
	uv sync --locked
	pnpm --dir frontend install --frozen-lockfile
	pnpm --dir frontend build
	@if git config --get core.hooksPath >/dev/null; then \
		echo "Keeping the configured core.hooksPath; run make check before committing."; \
	else \
		uv run --locked pre-commit install; \
	fi

dev:
	pnpm --dir frontend dev

check:
	uv run --locked ruff format --check .
	uv run --locked ruff check .
	uv run --locked pyright
	uv run --locked pytest -m "not model and not pg"
	uv run --locked python scripts/export_openapi.py | diff -u frontend/tests/openapi.json -
	uv run --locked python scripts/check_copy.py
	pnpm --dir frontend format:check
	pnpm --dir frontend lint
	pnpm --dir frontend check
	pnpm --dir frontend test

test:
	uv run --locked pytest -m "not model and not pg"
	pnpm --dir frontend test

build:
	uv build

golden:
	ROWSETTA_UPDATE_SQL_GOLDENS=1 uv run --locked pytest tests/golden/test_sql.py
	ROWSETTA_UPDATE_CLI_GOLDENS=1 uv run --locked pytest tests/integration/test_cli_output.py

bench bench-full:
	uv run --locked --group bench python -m scripts.bench_full $(BENCH_ARGS)

browser:
	uv run --locked python scripts/build_browser.py
	pnpm --dir frontend exec vite build --mode browser
	cp -R frontend/public/browser site/browser

demo-gif:
	pnpm --dir frontend build
	node scripts/record_demo.mjs
	scripts/check_demo_gif.sh docs/demo.gif
