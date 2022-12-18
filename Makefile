format:
	poetry run ruff --fix ./ruff_lsp
	poetry run black ./ruff_lsp

check:
	poetry run ruff ./ruff_lsp
	poetry run black --check ./ruff_lsp
	poetry run mypy ./ruff_lsp

.PHONY: fmt typecheck lint test
