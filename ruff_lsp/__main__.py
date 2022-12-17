def main() -> None:
    from ruff_lsp.server import LSP_SERVER

    LSP_SERVER.start_io()


if __name__ == "__main__":
    main()
