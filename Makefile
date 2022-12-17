fmt:
	poetry run black ./ruff_lsp
	poetry run ruff --select I001 --fix ./ruff_lsp

typecheck:
	poetry run mypy

lint:
	poetry run black --check ./ruff_lsp
	poetry run ruff ./ruff_lsp

fix:
	poetry run ruff ./ruff_lsp --fix

.PHONY: fmt typecheck lint test
