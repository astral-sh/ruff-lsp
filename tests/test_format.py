from __future__ import annotations

import pytest
from pygls.workspace import Workspace

from ruff_lsp.server import _format_document_impl
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

    result = await _format_document_impl(document)
    [edit] = result
    assert edit.new_text == expected
