"""Utility functions and classes for use with running tools over LSP."""

from __future__ import annotations

import os
import os.path
import pathlib
import site
import subprocess
import sys
import sysconfig
from typing import Any, NamedTuple

from packaging.version import Version


def as_list(content: Any | list[Any] | tuple[Any, ...]) -> list[Any]:
    """Ensures we always get a list"""
    if isinstance(content, (list, tuple)):
        return list(content)
    return [content]


def _get_sys_config_paths() -> list[str]:
    """Returns paths from sysconfig.get_paths()."""
    return [
        path
        for group, path in sysconfig.get_paths().items()
        if group not in ["data", "platdata", "scripts"]
    ]


def _get_extensions_dir() -> list[str]:
    """This is the extensions folder under ~/.vscode or ~/.vscode-server."""

    # The path here is calculated relative to the tool
    # this is because users can launch VS Code with custom
    # extensions folder using the --extensions-dir argument
    path = pathlib.Path(__file__).parent.parent.parent.parent
    #                              ^     bundled  ^  extensions
    #                            tool        <extension>
    if path.name == "extensions":
        return [os.fspath(path)]
    return []


_stdlib_paths = set(
    str(pathlib.Path(p).resolve())
    for p in (
        as_list(site.getsitepackages())
        + as_list(site.getusersitepackages())
        + _get_sys_config_paths()
        + _get_extensions_dir()
    )
)


def is_same_path(file_path1: str, file_path2: str) -> bool:
    """Returns true if two paths are the same."""
    return pathlib.Path(file_path1) == pathlib.Path(file_path2)


def normalize_path(file_path: str) -> str:
    """Returns normalized path."""
    return str(pathlib.Path(file_path).resolve())


def is_current_interpreter(executable: str) -> bool:
    """Returns true if the executable path is same as the current interpreter."""
    return is_same_path(executable, sys.executable)


def is_stdlib_file(file_path: str) -> bool:
    """Return True if the file belongs to the standard library."""
    normalized_path = str(pathlib.Path(file_path).resolve())
    return any(normalized_path.startswith(path) for path in _stdlib_paths)


def scripts(interpreter: str) -> str:
    """Returns the absolute path to an interpreter's scripts directory."""
    return (
        subprocess.check_output(
            [
                interpreter,
                "-c",
                "import sysconfig; print(sysconfig.get_path('scripts'))",
            ]
        )
        .decode()
        .strip()
    )


def version(executable: str) -> Version:
    """Returns the version of the executable at the given path."""
    output = subprocess.check_output([executable, "--version"]).decode().strip()
    version = output.replace("ruff ", "")  # no removeprefix in 3.7 :/
    return Version(version)


class RunResult(NamedTuple):
    """Object to hold result from running tool."""

    stdout: bytes
    """The stdout of running the executable."""

    stderr: bytes
    """The stderr of running the executable."""

    exit_code: int
    """The exit code of running the executable."""
