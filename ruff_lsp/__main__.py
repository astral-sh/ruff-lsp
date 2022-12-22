import argparse

from ruff_lsp import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="ruff-lsp")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()

    from ruff_lsp import server

    server.start()


if __name__ == "__main__":
    main()
