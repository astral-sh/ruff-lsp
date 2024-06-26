default: fmt check

lock:
  uv lock

upgrade:
  uv lock --upgrade

sync:
  uv sync --dev

fmt:
  uv run --dev -- ruff check --fix-only ./ruff_lsp ./tests
  uv run --dev -- ruff format ./ruff_lsp ./tests

check:
  uv run --dev -- ruff check ./ruff_lsp ./tests
  uv run --dev -- ruff format --check ./ruff_lsp ./tests
  uv run --dev -- mypy ./ruff_lsp ./tests

test:
  uv run --dev --verbose -- pytest
