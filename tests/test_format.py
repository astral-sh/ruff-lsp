from __future__ import annotations

from contextlib import nullcontext

import pytest
from packaging.version import Version
from pygls.workspace import Workspace

from ruff_lsp.server import (
    VERSION_REQUIREMENT_FORMATTER,
    Document,
    _fixed_source_to_edits,
    _run_format_on_document,
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
    document = Document.from_text_document(workspace.get_text_document(uri))

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_FORMATTER.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _run_format_on_document(document)
        assert result is not None
        assert result.exit_code == 0
        [edit] = _fixed_source_to_edits(
            original_source=document.source, fixed_source=result.stdout.decode("utf-8")
        )
        assert edit.new_text == expected


@pytest.mark.asyncio
async def test_format_code_with_syntax_error(tmp_path, ruff_version: Version):
    source = """
foo =
"""

    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(source)
    uri = utils.as_uri(str(test_file))

    workspace = Workspace(str(tmp_path))
    document = Document.from_text_document(workspace.get_text_document(uri))

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_FORMATTER.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _run_format_on_document(document)
        assert result is not None
        assert result.exit_code == 2
