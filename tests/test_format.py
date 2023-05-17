"""Unfortunately, I couldn't figure out how to integrate custom commands with the LSP
test harness, so here's a mixture of a unit and an integration test"""

from pathlib import Path
from typing import Optional

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
print("a")
# DEL
print("b")
"""

expected = """
print("a")

print("b")
"""


class MockLanguageServer:
    root: Path
    applied_edits = []

    def __init__(self, root):
        self.root = root

    @property
    def workspace(self) -> Workspace:
        return Workspace(str(self.root))

    def apply_edit(self, edit: WorkspaceEdit, _label: Optional[str] = None) -> None:
        """Currently unused, but we keep it around for future tests."""
        self.applied_edits.append(edit)


def test_format(tmp_path):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    ls = MockLanguageServer(tmp_path)
    dummy_params = DocumentFormattingParams(
        text_document=TextDocumentIdentifier(uri=uri),
        options=FormattingOptions(tab_size=4, insert_spaces=True),
        work_done_token=None,
    )
    # noinspection PyTypeChecker
    result = format_document_impl(ls, dummy_params)
    [edit] = result
    assert edit.new_text == expected
