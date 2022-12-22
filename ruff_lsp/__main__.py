import argparse
import sys

from ruff_lsp import __version__


def main() -> None:
    from ruff_lsp.server import LSP_SERVER

    parser = argparse.ArgumentParser(prog="ruff-lsp")
    parser.add_argument(
        "--version",
        help="display version information and exit",
        action="store_true",
    )
    args = parser.parse_args()
    if args.version:
        print(__version__)
        sys.exit(0)
    else:
        LSP_SERVER.start_io()


if __name__ == "__main__":
    main()
