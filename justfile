default: fmt check

lock:
  poetry lock

install:
  poetry install

fmt:
  poetry run ruff --fix ./ruff_lsp ./tests
  poetry run black ./ruff_lsp ./tests

check:
  poetry run ruff ./ruff_lsp ./tests
  poetry run black --check ./ruff_lsp ./tests
  poetry run mypy ./ruff_lsp ./tests

test:
  poetry run python -m unittest
