fmt:
	poetry run black ./ruff_lsp ./tests
	ruff --select I001 --fix ./ruff_lsp ./tests
