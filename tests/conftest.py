from pathlib import Path

import pytest
from packaging.version import Version

from ruff_lsp.server import _find_ruff_binary, _get_global_defaults, uris
from ruff_lsp.settings import WorkspaceSettings


@pytest.fixture(scope="session")
def ruff_version() -> Version:
    # Use the ruff-lsp directory as the workspace
    workspace_path = str(Path(__file__).parent.parent)

    settings = WorkspaceSettings(
        **_get_global_defaults(),  # type: ignore[misc]
        cwd=None,
        workspacePath=workspace_path,
        workspace=uris.from_fs_path(workspace_path),
    )

    return _find_ruff_binary(settings, version_requirement=None).version
