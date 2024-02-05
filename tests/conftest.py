import subprocess
from pathlib import Path

import pytest
from packaging.version import Version

from ruff_lsp.server import Executable, _find_ruff_binary, _get_global_defaults, uris
from ruff_lsp.settings import WorkspaceSettings


def _get_ruff_executable() -> Executable:
    # Use the ruff-lsp directory as the workspace
    workspace_path = str(Path(__file__).parent.parent)

    settings = WorkspaceSettings(  # type: ignore[misc]
        **_get_global_defaults(),
        cwd=None,
        workspacePath=workspace_path,
        workspace=uris.from_fs_path(workspace_path),
    )

    return _find_ruff_binary(settings, version_requirement=None)


@pytest.fixture(scope="session")
def ruff_version() -> Version:
    return _get_ruff_executable().version


def pytest_report_header(config):
    """Add ruff version to pytest header."""
    executable = _get_ruff_executable()

    # Display the long version if the executable supports it
    try:
        output = subprocess.check_output([executable.path, "version"]).decode().strip()
    except subprocess.CalledProcessError:
        output = (
            subprocess.check_output([executable.path, "--version"]).decode().strip()
        )

    version = output.replace("ruff ", "")
    return [f"ruff-version: {version}"]
