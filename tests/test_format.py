from __future__ import annotations

from pathlib import Path

from lsprotocol.types import (
    DocumentFormattingParams,
    FormattingOptions,
    TextDocumentIdentifier,
    WorkspaceEdit,
)
from pygls.workspace import Workspace

from ruff_lsp.server import format_document_impl
from tests.client import utils

original = """
x = 1
"""

expected = """NOT_YET_IMPLEMENTED_StmtAssign
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


def test_format(tmp_path):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    mock_language_server = MockLanguageServer(tmp_path)
    dummy_params = DocumentFormattingParams(
        text_document=TextDocumentIdentifier(uri=uri),
        options=FormattingOptions(tab_size=4, insert_spaces=True),
        work_done_token=None,
    )
    # noinspection PyTypeChecker
    result = format_document_impl(mock_language_server, dummy_params)  # type: ignore
    [edit] = result
    assert edit.new_text == expected
