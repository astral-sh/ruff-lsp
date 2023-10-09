#!/usr/bin/env python3
"""
Get the oldest supported version of a package from the pyproject.toml file.
Only supports packages specified with '>=' in the main dependencies section.

Usage:

    get-oldest-supported.py <package-name>

Example:

    pip install ruff==$(./get-oldest-supported-version.py ruff)
"""
import io
import sys
from typing import List

import packaging.requirements
import packaging.version
import toml


class UserError(Exception):
    pass


def get_oldest_supported_version(dependencies: List[str], package_name) -> str:
    for dependency in dependencies:
        requirement = packaging.requirements.Requirement(dependency)
        if requirement.name == package_name:
            for specificier in requirement.specifier:
                if specificier.operator == ">=":
                    return str(specificier.version)
            raise UserError(f"Package {package_name} does not use a '>=' specifier.")

    raise UserError(f"Package {package_name} not found in dependencies.")


def main(input_file: io.TextIOWrapper, package: str) -> None:
    pyproject = toml.load(input_file)

    try:
        dependencies = pyproject["project"]["dependencies"]
    except KeyError:
        raise UserError("No dependencies found in pyproject.toml.")

    return get_oldest_supported_version(dependencies, package)


if __name__ == "__main__":
    if not len(sys.argv) > 1:
        print("Package name required.", sys.stderr)
        exit(1)

    input_path = "pyproject.toml"
    package = sys.argv[1]

    with open(input_path) as input_file:
        try:
            print(main(input_path, package))
        except UserError as exc:
            print(exc, file=sys.stderr)
            exit(1)
