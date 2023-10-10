from __future__ import annotations

from contextlib import nullcontext

import pytest
from pygls.workspace import Workspace

from ruff_lsp.server import (
    VERSION_REQUIREMENT_FORMATTER,
    _find_ruff_binary,
    _format_document_impl,
    _get_settings_by_document,
)
from tests.client import utils

original = """
x = 1
"""

expected = """x = 1
"""


@pytest.mark.asyncio
async def test_format(tmp_path):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    workspace = Workspace(str(tmp_path))
    document = workspace.get_document(uri)

    settings = _get_settings_by_document(document.path)
    executable = _find_ruff_binary(settings, version_requirement=None)

    handle_unsupported = (
        pytest.raises(
            RuntimeError, match=f"Ruff .* required, but found {executable.version}"
        )
        if not VERSION_REQUIREMENT_FORMATTER.contains(executable.version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _format_document_impl(document)
        [edit] = result
        assert edit.new_text == expected
