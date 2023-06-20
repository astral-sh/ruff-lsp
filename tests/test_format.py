from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from lsprotocol.types import (
    DocumentFormattingParams,
    FormattingOptions,
    TextDocumentIdentifier,
    WorkspaceEdit,
)
from pygls import server
from pygls.workspace import Workspace

from ruff_lsp.server import _format_document_impl
from tests.client import utils

original = """
x = 1
"""

expected = """x = 1
"""


class MockLanguageServer:
    root: Path
    applied_edits: list[WorkspaceEdit] = []

    def __init__(self, root):
        self.root = root

    @property
    def workspace(self) -> Workspace:
        return Workspace(str(self.root))

    def apply_edit(self, edit: WorkspaceEdit, _label: str | None = None) -> None:
        """Currently unused, but we keep it around for future tests."""
        self.applied_edits.append(edit)


@pytest.mark.asyncio
async def test_format(tmp_path):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    mock_language_server = MockLanguageServer(tmp_path)
    dummy_params = DocumentFormattingParams(
        text_document=TextDocumentIdentifier(uri=uri),
        options=FormattingOptions(tab_size=4, insert_spaces=True),
        work_done_token=None,
    )

    result = await _format_document_impl(
        cast(server.LanguageServer, mock_language_server), dummy_params
    )
    [edit] = result
    assert edit.new_text == expected
