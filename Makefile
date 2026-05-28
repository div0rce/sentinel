.PHONY: dev check test lint typecheck fmt migrate migration seed eval
dev: ; docker compose up -d db && uv run uvicorn backend.app.main:app --reload
check: lint typecheck test
lint: ; uv run ruff check . && uv run ruff format --check .
typecheck: ; uv run mypy .
test: ; uv run pytest -q
fmt: ; uv run ruff format . && uv run ruff check --fix .
migrate: ; uv run alembic upgrade head
migration: ; uv run alembic revision --autogenerate -m "$(m)"
seed: ; uv run python -m backend.app.ingest --path data/sample
eval: ; uv run python -m eval.run && cat eval/RESULTS.md
