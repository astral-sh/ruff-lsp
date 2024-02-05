from __future__ import annotations

from contextlib import nullcontext

import pytest
from lsprotocol.types import Position, Range
from packaging.version import Version
from pygls.workspace import Workspace

from ruff_lsp.server import (
    VERSION_REQUIREMENT_FORMATTER,
    VERSION_REQUIREMENT_RANGE_FORMATTING,
    Document,
    _fixed_source_to_edits,
    _get_settings_by_document,
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
    settings = _get_settings_by_document(document.path)

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_FORMATTER.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _run_format_on_document(document, settings, None)
        assert result is not None
        assert result.exit_code == 0
        [edit] = _fixed_source_to_edits(
            original_source=document.source, fixed_source=result.stdout.decode("utf-8")
        )
        assert edit.new_text == ""
        assert edit.range == Range(
            start=Position(line=0, character=0), end=Position(line=1, character=0)
        )


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
    settings = _get_settings_by_document(document.path)

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_FORMATTER.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _run_format_on_document(document, settings, None)
        assert result is not None
        assert result.exit_code == 2


@pytest.mark.asyncio
async def test_format_range(tmp_path, ruff_version: Version):
    original = """x   = 1



print( "Formatted")

print ("Not formatted")
"""

    expected = """print("Formatted")\n"""

    test_file = tmp_path.joinpath("main.py")
    test_file.write_text(original)
    uri = utils.as_uri(str(test_file))

    workspace = Workspace(str(tmp_path))
    document = Document.from_text_document(workspace.get_text_document(uri))
    settings = _get_settings_by_document(document.path)

    handle_unsupported = (
        pytest.raises(RuntimeError, match=f"Ruff .* required, but found {ruff_version}")
        if not VERSION_REQUIREMENT_RANGE_FORMATTING.contains(ruff_version)
        else nullcontext()
    )

    with handle_unsupported:
        result = await _run_format_on_document(
            document,
            settings,
            Range(
                start=Position(line=1, character=0),
                end=(Position(line=4, character=19)),
            ),
        )
        assert result is not None
        assert result.exit_code == 0
        [edit] = _fixed_source_to_edits(
            original_source=document.source, fixed_source=result.stdout.decode("utf-8")
        )
        assert edit.new_text == expected
        assert edit.range == Range(
            start=Position(line=3, character=0), end=Position(line=5, character=0)
        )
