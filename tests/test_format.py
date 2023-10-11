from __future__ import annotations

from contextlib import nullcontext

import pytest
from packaging.version import Version
from pygls.workspace import Workspace

from ruff_lsp.server import (
    VERSION_REQUIREMENT_FORMATTER,
    _format_document_impl,
)
from tests.client import utils

original = """
x = 1
"""

expected = """x = 1
"""


@pytest.mark.asyncio
async def test_format(tmp_path, ruff_version: Version):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    workspace = Workspace(str(tmp_path))
    document = workspace.get_text_document(uri)

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_FORMATTER.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _format_document_impl(document)
        [edit] = result
        assert edit.new_text == expected
