default: fmt check

lock:
  pip-compile --resolver=backtracking --upgrade -o requirements.txt pyproject.toml
  pip-compile --resolver=backtracking --upgrade --extra dev -o requirements-dev.txt pyproject.toml

install:
  pip install -r requirements.txt
  pip install -r requirements-dev.txt

fmt:
  ruff --fix ./ruff_lsp ./tests
  black ./ruff_lsp ./tests

check:
  ruff ./ruff_lsp ./tests
  black --check ./ruff_lsp ./tests
  mypy ./ruff_lsp ./tests

test:
  python -m unittest
