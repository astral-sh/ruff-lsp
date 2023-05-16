"""Unfortunately, I couldn't figure out how to integrate custom commands with the LSP
test harness, so here's a mixture of a unit and an integration test"""

from pathlib import Path
from typing import Optional

from lsprotocol.types import WorkspaceEdit
from pygls.workspace import Workspace

from ruff_lsp.server import TextDocument, apply_format_impl
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
        self.applied_edits.append(edit)


def test_format(tmp_path):
    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    ls = MockLanguageServer(tmp_path)
    doc = {
        "uri": uri,
        "languageId": "python",
        "version": 1,
        "text": original,
    }
    docs = (TextDocument(**doc),)
    # noinspection PyTypeChecker
    apply_format_impl(ls, docs)
    [edit] = ls.applied_edits
    [change] = edit.document_changes
    [text_edit] = change.edits
    assert text_edit.new_text == expected
