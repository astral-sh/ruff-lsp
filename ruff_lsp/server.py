"""Implementation of the LSP server for Ruff."""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import re
import shutil
import sys
import sysconfig
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, NamedTuple, Sequence, Union, cast

from lsprotocol.types import (
    CODE_ACTION_RESOLVE,
    INITIALIZE,
    NOTEBOOK_DOCUMENT_DID_CHANGE,
    NOTEBOOK_DOCUMENT_DID_CLOSE,
    NOTEBOOK_DOCUMENT_DID_OPEN,
    NOTEBOOK_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_FORMATTING,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_RANGE_FORMATTING,
    AnnotatedTextEdit,
    ClientCapabilities,
    CodeAction,
    CodeActionKind,
    CodeActionOptions,
    CodeActionParams,
    CodeDescription,
    Diagnostic,
    DiagnosticSeverity,
    DiagnosticTag,
    DidChangeNotebookDocumentParams,
    DidChangeTextDocumentParams,
    DidCloseNotebookDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenNotebookDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveNotebookDocumentParams,
    DidSaveTextDocumentParams,
    DocumentFormattingParams,
    DocumentRangeFormattingParams,
    DocumentRangeFormattingRegistrationOptions,
    Hover,
    HoverParams,
    InitializeParams,
    MarkupContent,
    MarkupKind,
    MessageType,
    NotebookCell,
    NotebookCellKind,
    NotebookDocument,
    NotebookDocumentSyncOptions,
    NotebookDocumentSyncOptionsNotebookSelectorType2,
    NotebookDocumentSyncOptionsNotebookSelectorType2CellsType,
    OptionalVersionedTextDocumentIdentifier,
    Position,
    PositionEncodingKind,
    Range,
    TextDocumentEdit,
    TextDocumentFilter_Type1,
    TextEdit,
    WorkspaceEdit,
)
from packaging.specifiers import SpecifierSet, Version
from pygls import server, uris, workspace
from pygls.workspace.position_codec import PositionCodec
from typing_extensions import Literal, Self, TypedDict, assert_never

from ruff_lsp import __version__, utils
from ruff_lsp.settings import (
    Run,
    UserSettings,
    WorkspaceSettings,
    lint_args,
    lint_enable,
    lint_run,
)
from ruff_lsp.utils import RunResult

logger = logging.getLogger(__name__)

RUFF_LSP_DEBUG = bool(os.environ.get("RUFF_LSP_DEBUG", False))

if RUFF_LSP_DEBUG:
    log_file = Path(__file__).parent.parent.joinpath("ruff-lsp.log")
    logging.basicConfig(filename=log_file, filemode="w", level=logging.DEBUG)
    logger.info("RUFF_LSP_DEBUG is active")


if sys.platform == "win32" and sys.version_info < (3, 8):
    # The ProactorEventLoop is required for subprocesses on Windows.
    # It's the default policy in Python 3.8, but not in Python 3.7.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


GLOBAL_SETTINGS: UserSettings = {}
WORKSPACE_SETTINGS: dict[str, WorkspaceSettings] = {}
INTERPRETER_PATHS: dict[str, str] = {}


class VersionModified(NamedTuple):
    version: Version
    """Last modified of the executable"""
    modified: float


EXECUTABLE_VERSIONS: dict[str, VersionModified] = {}
CLIENT_CAPABILITIES: dict[str, bool] = {
    CODE_ACTION_RESOLVE: True,
}

MAX_WORKERS = 5
LSP_SERVER = server.LanguageServer(
    name="Ruff",
    version=__version__,
    max_workers=MAX_WORKERS,
    notebook_document_sync=NotebookDocumentSyncOptions(
        notebook_selector=[
            NotebookDocumentSyncOptionsNotebookSelectorType2(
                cells=[
                    NotebookDocumentSyncOptionsNotebookSelectorType2CellsType(
                        language="python"
                    )
                ]
            )
        ],
        save=True,
    ),
)

TOOL_MODULE = "ruff.exe" if sys.platform == "win32" else "ruff"
TOOL_DISPLAY = "Ruff"

# Require at least Ruff v0.0.291 for formatting, but allow older versions for linting.
VERSION_REQUIREMENT_FORMATTER = SpecifierSet(">=0.0.291")
VERSION_REQUIREMENT_LINTER = SpecifierSet(">=0.0.189")
VERSION_REQUIREMENT_RANGE_FORMATTING = SpecifierSet(">=0.2.1")
# Version requirement for use of the `--output-format` option
VERSION_REQUIREMENT_OUTPUT_FORMAT = SpecifierSet(">=0.0.291")
# Version requirement after which Ruff avoids writing empty output for excluded files.
VERSION_REQUIREMENT_EMPTY_OUTPUT = SpecifierSet(">=0.1.6")

# Arguments provided to every Ruff invocation.
CHECK_ARGS = [
    "check",
    "--force-exclude",
    "--no-cache",
    "--no-fix",
    "--quiet",
    "--output-format",
    "json",
    "-",
]

# Arguments that are not allowed to be passed to `ruff check`.
UNSUPPORTED_CHECK_ARGS = [
    # Arguments that enforce required behavior. These can be ignored with a warning.
    "--force-exclude",
    "--no-cache",
    "--no-fix",
    "--quiet",
    # Arguments that contradict the required behavior. These can be ignored with a
    # warning.
    "--diff",
    "--exit-non-zero-on-fix",
    "-e",
    "--exit-zero",
    "--fix",
    "--fix-only",
    "-h",
    "--help",
    "--no-force-exclude",
    "--show-files",
    "--show-fixes",
    "--show-settings",
    "--show-source",
    "--silent",
    "--statistics",
    "--verbose",
    "-w",
    "--watch",
    # Arguments that are not supported at all, and will error when provided.
    # "--stdin-filename",
    # "--output-format",
]

# Arguments that are not allowed to be passed to `ruff format`.
UNSUPPORTED_FORMAT_ARGS = [
    # Arguments that enforce required behavior. These can be ignored with a warning.
    "--force-exclude",
    "--quiet",
    # Arguments that contradict the required behavior. These can be ignored with a
    # warning.
    "-h",
    "--help",
    "--no-force-exclude",
    "--silent",
    "--verbose",
    # Arguments that are not supported at all, and will error when provided.
    # "--stdin-filename",
]

# Standard code action kinds, scoped to Ruff.
SOURCE_FIX_ALL_RUFF = f"{CodeActionKind.SourceFixAll.value}.ruff"
SOURCE_ORGANIZE_IMPORTS_RUFF = f"{CodeActionKind.SourceOrganizeImports.value}.ruff"

# Notebook code action kinds.
NOTEBOOK_SOURCE_FIX_ALL = f"notebook.{CodeActionKind.SourceFixAll.value}"
NOTEBOOK_SOURCE_ORGANIZE_IMPORTS = (
    f"notebook.{CodeActionKind.SourceOrganizeImports.value}"
)

# Notebook code action kinds, scoped to Ruff.
NOTEBOOK_SOURCE_FIX_ALL_RUFF = f"notebook.{CodeActionKind.SourceFixAll.value}.ruff"
NOTEBOOK_SOURCE_ORGANIZE_IMPORTS_RUFF = (
    f"notebook.{CodeActionKind.SourceOrganizeImports.value}.ruff"
)


###
# Document
###


def _uri_to_fs_path(uri: str) -> str:
    """Convert a URI to a file system path."""
    path = uris.to_fs_path(uri)
    if path is None:
        # `pygls` raises a `Exception` as well in `workspace.TextDocument`.
        raise ValueError(f"Unable to convert URI to file path: {uri}")
    return path


@enum.unique
class DocumentKind(enum.Enum):
    """The kind of document."""

    Text = enum.auto()
    """A Python file."""

    Notebook = enum.auto()
    """A Notebook Document."""

    Cell = enum.auto()
    """A cell in a Notebook Document."""


@dataclass(frozen=True)
class Document:
    """A document representing either a Python file, a Notebook cell, or a Notebook."""

    uri: str
    path: str
    source: str
    kind: DocumentKind
    version: int | None

    @classmethod
    def from_text_document(cls, text_document: workspace.TextDocument) -> Self:
        """Create a `Document` from the given Text Document."""
        return cls(
            uri=text_document.uri,
            path=text_document.path,
            kind=DocumentKind.Text,
            source=text_document.source,
            version=text_document.version,
        )

    @classmethod
    def from_notebook_document(cls, notebook_document: NotebookDocument) -> Self:
        """Create a `Document` from the given Notebook Document."""
        return cls(
            uri=notebook_document.uri,
            path=_uri_to_fs_path(notebook_document.uri),
            kind=DocumentKind.Notebook,
            source=_create_notebook_json(notebook_document),
            version=notebook_document.version,
        )

    @classmethod
    def from_notebook_cell(cls, notebook_cell: NotebookCell) -> Self:
        """Create a `Document` from the given Notebook cell."""
        return cls(
            uri=notebook_cell.document,
            path=_uri_to_fs_path(notebook_cell.document),
            kind=DocumentKind.Cell,
            source=_create_single_cell_notebook_json(
                LSP_SERVER.workspace.get_text_document(notebook_cell.document).source
            ),
            version=None,
        )

    @classmethod
    def from_cell_or_text_uri(cls, uri: str) -> Self:
        """Create a `Document` representing either a Python file or a Notebook cell from
        the given URI.

        The function will try to get the Notebook cell first, and if there's no cell
        with the given URI, it will fallback to the text document.
        """
        notebook_document = LSP_SERVER.workspace.get_notebook_document(cell_uri=uri)
        if notebook_document is not None:
            notebook_cell = next(
                (
                    notebook_cell
                    for notebook_cell in notebook_document.cells
                    if notebook_cell.document == uri
                ),
                None,
            )
            if notebook_cell is not None:
                return cls.from_notebook_cell(notebook_cell)

        # Fall back to the Text Document representing a Python file.
        text_document = LSP_SERVER.workspace.get_text_document(uri)
        return cls.from_text_document(text_document)

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Create a `Document` representing either a Python file or a Notebook from
        the given URI.

        The URI can be a file URI, a notebook URI, or a cell URI. The function will
        try to get the notebook document first, and if there's no notebook document
        with the given URI, it will fallback to the text document.
        """
        # First, try to get the Notebook Document assuming the URI is a Cell URI.
        notebook_document = LSP_SERVER.workspace.get_notebook_document(cell_uri=uri)
        if notebook_document is None:
            # If that fails, try to get the Notebook Document assuming the URI is a
            # Notebook URI.
            notebook_document = LSP_SERVER.workspace.get_notebook_document(
                notebook_uri=uri
            )
        if notebook_document:
            return cls.from_notebook_document(notebook_document)

        # Fall back to the Text Document representing a Python file.
        text_document = LSP_SERVER.workspace.get_text_document(uri)
        return cls.from_text_document(text_document)

    def is_stdlib_file(self) -> bool:
        """Return True if the document belongs to standard library."""
        return utils.is_stdlib_file(self.path)


SourceValue = Union[str, List[str]]


class CodeCell(TypedDict):
    """A code cell in a Jupyter notebook."""

    cell_type: Literal["code"]
    metadata: Any
    outputs: list[Any]
    source: SourceValue


class MarkdownCell(TypedDict):
    """A markdown cell in a Jupyter notebook."""

    cell_type: Literal["markdown"]
    metadata: Any
    source: SourceValue


class Notebook(TypedDict):
    """The JSON representation of a Notebook Document."""

    metadata: Any
    nbformat: int
    nbformat_minor: int
    cells: list[CodeCell | MarkdownCell]


def _create_notebook_json(notebook_document: NotebookDocument) -> str:
    """Create a JSON representation of the given Notebook Document."""
    cells: list[CodeCell | MarkdownCell] = []
    for notebook_cell in notebook_document.cells:
        cell_document = LSP_SERVER.workspace.get_text_document(notebook_cell.document)
        if notebook_cell.kind is NotebookCellKind.Code:
            cells.append(
                {
                    "cell_type": "code",
                    "metadata": {},
                    "outputs": [],
                    "source": cell_document.source,
                }
            )
        else:
            cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": cell_document.source,
                }
            )
    return json.dumps(
        {
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": cells,
        }
    )


def _create_single_cell_notebook_json(source: str) -> str:
    """Create a JSON representation of a single cell Notebook Document containing
    the given source."""
    return json.dumps(
        {
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "code",
                    "metadata": {},
                    "outputs": [],
                    "source": source,
                }
            ],
        }
    )


###
# Linting.
###


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: DidOpenTextDocumentParams) -> None:
    """LSP handler for textDocument/didOpen request."""
    document = Document.from_text_document(
        LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    )
    settings = _get_settings_by_document(document.path)
    if not lint_enable(settings):
        return None

    diagnostics = await _lint_document_impl(document, settings)
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: DidCloseTextDocumentParams) -> None:
    """LSP handler for textDocument/didClose request."""
    text_document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    # Publishing empty diagnostics to clear the entries for this file.
    LSP_SERVER.publish_diagnostics(text_document.uri, [])


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: DidSaveTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""
    text_document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    settings = _get_settings_by_document(text_document.path)
    if not lint_enable(settings):
        return None

    if lint_run(settings) in (
        Run.OnType,
        Run.OnSave,
    ):
        document = Document.from_text_document(text_document)
        diagnostics = await _lint_document_impl(document, settings)
        LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: DidChangeTextDocumentParams) -> None:
    """LSP handler for textDocument/didChange request."""
    text_document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    settings = _get_settings_by_document(text_document.path)
    if not lint_enable(settings):
        return None

    if lint_run(settings) == Run.OnType:
        document = Document.from_text_document(text_document)
        diagnostics = await _lint_document_impl(document, settings)
        LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(NOTEBOOK_DOCUMENT_DID_OPEN)
async def did_open_notebook(params: DidOpenNotebookDocumentParams) -> None:
    """LSP handler for notebookDocument/didOpen request."""
    notebook_document = LSP_SERVER.workspace.get_notebook_document(
        notebook_uri=params.notebook_document.uri
    )
    if notebook_document is None:
        log_warning(f"No notebook document found for {params.notebook_document.uri!r}")
        return None

    document = Document.from_notebook_document(notebook_document)
    settings = _get_settings_by_document(document.path)
    if not lint_enable(settings):
        return None

    diagnostics = await _lint_document_impl(document, settings)

    # Publish diagnostics for each cell.
    for cell_idx, diagnostics in _group_diagnostics_by_cell(diagnostics).items():
        LSP_SERVER.publish_diagnostics(
            # The cell indices are 1-based in Ruff.
            params.notebook_document.cells[cell_idx - 1].document,
            diagnostics,
        )


@LSP_SERVER.feature(NOTEBOOK_DOCUMENT_DID_CLOSE)
def did_close_notebook(params: DidCloseNotebookDocumentParams) -> None:
    """LSP handler for notebookDocument/didClose request."""
    # Publishing empty diagnostics to clear the entries for all the cells in this
    # Notebook Document.
    for cell_text_document in params.cell_text_documents:
        LSP_SERVER.publish_diagnostics(cell_text_document.uri, [])


@LSP_SERVER.feature(NOTEBOOK_DOCUMENT_DID_SAVE)
async def did_save_notebook(params: DidSaveNotebookDocumentParams) -> None:
    """LSP handler for notebookDocument/didSave request."""
    await _did_change_or_save_notebook(
        params.notebook_document.uri, run_types=[Run.OnSave, Run.OnType]
    )


@LSP_SERVER.feature(NOTEBOOK_DOCUMENT_DID_CHANGE)
async def did_change_notebook(params: DidChangeNotebookDocumentParams) -> None:
    """LSP handler for notebookDocument/didChange request."""
    await _did_change_or_save_notebook(
        params.notebook_document.uri, run_types=[Run.OnType]
    )


def _group_diagnostics_by_cell(
    diagnostics: Iterable[Diagnostic],
) -> Mapping[int, list[Diagnostic]]:
    """Group diagnostics by cell index.

    The function will return a mapping from cell number to a list of diagnostics for
    that cell. The mapping will be empty if the diagnostic doesn't contain the cell
    information.
    """
    cell_diagnostics: dict[int, list[Diagnostic]] = {}
    for diagnostic in diagnostics:
        cell = cast(DiagnosticData, diagnostic.data).get("cell")
        if cell is not None:
            cell_diagnostics.setdefault(cell, []).append(diagnostic)
    return cell_diagnostics


async def _did_change_or_save_notebook(
    notebook_uri: str, *, run_types: Sequence[Run]
) -> None:
    """Handle notebookDocument/didChange and notebookDocument/didSave requests."""
    notebook_document = LSP_SERVER.workspace.get_notebook_document(
        notebook_uri=notebook_uri
    )
    if notebook_document is None:
        log_warning(f"No notebook document found for {notebook_uri!r}")
        return None

    document = Document.from_notebook_document(notebook_document)
    settings = _get_settings_by_document(document.path)
    if not lint_enable(settings):
        return None

    if lint_run(settings) in run_types:
        cell_diagnostics = _group_diagnostics_by_cell(
            await _lint_document_impl(document, settings)
        )

        # Publish diagnostics for every code cell, replacing the previous diagnostics.
        # This is required here because a cell containing diagnostics in the first run
        # might not contain any diagnostics in the second run. In that case, we need to
        # clear the diagnostics for that cell which is done by publishing empty
        # diagnostics.
        for cell_idx, cell in enumerate(notebook_document.cells):
            if cell.kind is not NotebookCellKind.Code:
                continue
            LSP_SERVER.publish_diagnostics(
                cell.document,
                # The cell indices are 1-based in Ruff.
                cell_diagnostics.get(cell_idx + 1, []),
            )


async def _lint_document_impl(
    document: Document, settings: WorkspaceSettings
) -> list[Diagnostic]:
    result = await _run_check_on_document(document, settings)
    if result is None:
        return []

    # For `ruff check`, 0 indicates successful completion with no remaining
    # diagnostics, 1 indicates successful completion with remaining diagnostics,
    # and 2 indicates an error.
    if result.exit_code not in (0, 1):
        if result.stderr:
            show_error(f"Ruff: Lint failed ({result.stderr.decode('utf-8')})")
        return []

    return (
        _parse_output(result.stdout, settings.get("showSyntaxErrors", True))
        if result.stdout
        else []
    )


def _parse_fix(content: Fix | LegacyFix | None) -> Fix | None:
    """Parse the fix from the Ruff output."""
    if content is None:
        return None

    if content.get("edits") is None:
        # Prior to v0.0.260, Ruff returned a single edit.
        legacy_fix = cast(LegacyFix, content)
        return {
            "applicability": None,
            "message": legacy_fix.get("message"),
            "edits": [
                {
                    "content": legacy_fix["content"],
                    "location": legacy_fix["location"],
                    "end_location": legacy_fix["end_location"],
                }
            ],
        }
    else:
        # Since v0.0.260, Ruff returns a list of edits.
        fix = cast(Fix, content)

        # Since v0.0.266, Ruff returns one based column indices
        if fix.get("applicability") is not None:
            for edit in fix["edits"]:
                edit["location"]["column"] = edit["location"]["column"] - 1
                edit["end_location"]["column"] = edit["end_location"]["column"] - 1

        return fix


def _parse_output(content: bytes, show_syntax_errors: bool) -> list[Diagnostic]:
    """Parse Ruff's JSON output."""
    diagnostics: list[Diagnostic] = []

    # Ruff's output looks like:
    # [
    #   {
    #     "cell": null,
    #     "code": "F841",
    #     "message": "Local variable `x` is assigned to but never used",
    #     "location": {
    #       "row": 2,
    #       "column": 5
    #     },
    #     "end_location": {
    #       "row": 2,
    #       "column": 6
    #     },
    #     "fix": {
    #       "applicability": "Unspecified",
    #       "message": "Remove assignment to unused variable `x`",
    #       "edits": [
    #         {
    #           "content": "",
    #           "location": {
    #             "row": 2,
    #             "column": 1
    #           },
    #           "end_location": {
    #             "row": 3,
    #             "column": 1
    #           }
    #         }
    #       ]
    #     },
    #     "filename": "/path/to/test.py",
    #     "noqa_row": 2
    #   },
    #   ...
    # ]
    #
    # Input:
    # ```python
    # def a():
    #     x = 0
    #     print()
    # ```
    #
    # Cell represents the cell number in a Notebook Document. It is null for normal
    # Python files.
    for check in json.loads(content):
        if not show_syntax_errors and check["code"] is None:
            continue
        start = Position(
            line=max([int(check["location"]["row"]) - 1, 0]),
            character=int(check["location"]["column"]) - 1,
        )
        end = Position(
            line=max([int(check["end_location"]["row"]) - 1, 0]),
            character=int(check["end_location"]["column"]) - 1,
        )
        diagnostic = Diagnostic(
            range=Range(start=start, end=end),
            message=check.get("message"),
            code=check["code"],
            code_description=_get_code_description(check.get("url")),
            severity=_get_severity(check["code"]),
            source=TOOL_DISPLAY,
            data=DiagnosticData(
                fix=_parse_fix(check.get("fix")),
                # Available since Ruff v0.0.253.
                noqa_row=check.get("noqa_row"),
                # Available since Ruff v0.1.0.
                cell=check.get("cell"),
            ),
            tags=_get_tags(check["code"]),
        )
        diagnostics.append(diagnostic)

    return diagnostics


def _get_code_description(url: str | None) -> CodeDescription | None:
    if url is None:
        return None
    else:
        return CodeDescription(href=url)


def _get_tags(code: str) -> list[DiagnosticTag] | None:
    if code in {
        "F401",  # `module` imported but unused
        "F841",  # local variable `name` is assigned to but never used
    }:
        return [DiagnosticTag.Unnecessary]
    return None


def _get_severity(code: str) -> DiagnosticSeverity:
    if code in {
        "F821",  # undefined name `name`
        "E902",  # `IOError`
        "E999",  # `SyntaxError`
        None,  # `SyntaxError` as of Ruff v0.5.0
    }:
        return DiagnosticSeverity.Error
    else:
        return DiagnosticSeverity.Warning


NOQA_REGEX = re.compile(
    r"(?i:# (?:(?:ruff|flake8): )?(?P<noqa>noqa))"
    r"(?::\s?(?P<codes>([A-Z]+[0-9]+(?:[,\s]+)?)+))?"
)
CODE_REGEX = re.compile(r"[A-Z]+[0-9]+")


@LSP_SERVER.feature(TEXT_DOCUMENT_HOVER)
async def hover(params: HoverParams) -> Hover | None:
    """LSP handler for textDocument/hover request.

    This works for both Python files and Notebook Documents. For Notebook Documents,
    the hover works at the cell level.
    """
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    match = NOQA_REGEX.search(document.lines[params.position.line])
    if not match:
        return None

    codes = match.group("codes")
    if not codes:
        return None

    codes_start = match.start("codes")
    for match in CODE_REGEX.finditer(codes):
        start, end = match.span()
        start += codes_start
        end += codes_start
        if start <= params.position.character < end:
            code = match.group()
            result = await _run_subcommand_on_document(
                document, VERSION_REQUIREMENT_LINTER, args=["--explain", code]
            )
            if result.stdout:
                return Hover(
                    contents=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=result.stdout.decode("utf-8").strip(),
                    )
                )

    return None


###
# Code Actions.
###


class TextDocument(TypedDict):
    uri: str
    version: int


class Location(TypedDict):
    row: int
    column: int


class Edit(TypedDict):
    content: str
    location: Location
    end_location: Location


class Fix(TypedDict):
    """A fix for a diagnostic, represented as a list of edits."""

    applicability: str | None
    message: str | None
    edits: list[Edit]


class DiagnosticData(TypedDict, total=False):
    fix: Fix | None
    noqa_row: int | None
    cell: int | None


class LegacyFix(TypedDict):
    """A fix for a diagnostic, represented as a single edit.

    Matches Ruff's output prior to v0.0.260.
    """

    message: str | None
    content: str
    location: Location
    end_location: Location


@LSP_SERVER.feature(
    TEXT_DOCUMENT_CODE_ACTION,
    CodeActionOptions(
        code_action_kinds=[
            # Standard code action kinds.
            CodeActionKind.QuickFix,
            CodeActionKind.SourceFixAll,
            CodeActionKind.SourceOrganizeImports,
            # Standard code action kinds, scoped to Ruff.
            SOURCE_FIX_ALL_RUFF,
            SOURCE_ORGANIZE_IMPORTS_RUFF,
            # Notebook code action kinds.
            NOTEBOOK_SOURCE_FIX_ALL,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS,
            # Notebook code action kinds, scoped to Ruff.
            NOTEBOOK_SOURCE_FIX_ALL_RUFF,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS_RUFF,
        ],
        resolve_provider=True,
    ),
)
async def code_action(params: CodeActionParams) -> list[CodeAction] | None:
    """LSP handler for textDocument/codeAction request.

    Code actions work at a text document level which is either a Python file or a
    cell in a Notebook document. The function will try to get the Notebook cell
    first, and if there's no cell with the given URI, it will fallback to the text
    document.
    """

    def document_from_kind(uri: str, kind: str) -> Document:
        if kind in (
            # For `notebook`-scoped actions, use the Notebook Document instead of
            # the cell, despite being passed the URI of the first cell.
            # See: https://github.com/microsoft/vscode/issues/193120
            NOTEBOOK_SOURCE_FIX_ALL,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS,
            NOTEBOOK_SOURCE_FIX_ALL_RUFF,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS_RUFF,
        ):
            return Document.from_uri(uri)
        else:
            return Document.from_cell_or_text_uri(uri)

    document_path = _uri_to_fs_path(params.text_document.uri)
    settings = _get_settings_by_document(document_path)

    if settings.get("ignoreStandardLibrary", True) and utils.is_stdlib_file(
        document_path
    ):
        # Don't format standard library files.
        # Publishing empty list clears the entry.
        return None

    if settings["organizeImports"]:
        # Generate the "Ruff: Organize Imports" edit
        for kind in (
            CodeActionKind.SourceOrganizeImports,
            SOURCE_ORGANIZE_IMPORTS_RUFF,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS,
            NOTEBOOK_SOURCE_ORGANIZE_IMPORTS_RUFF,
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                workspace_edit = await _fix_document_impl(
                    document_from_kind(params.text_document.uri, kind),
                    settings,
                    only=["I001", "I002"],
                )
                if workspace_edit:
                    return [
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=workspace_edit,
                            diagnostics=[],
                        )
                    ]
                else:
                    return []

    # If the linter is enabled, generate the "Ruff: Fix All" edit.
    if lint_enable(settings) and settings["fixAll"]:
        for kind in (
            CodeActionKind.SourceFixAll,
            SOURCE_FIX_ALL_RUFF,
            NOTEBOOK_SOURCE_FIX_ALL,
            NOTEBOOK_SOURCE_FIX_ALL_RUFF,
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                workspace_edit = await _fix_document_impl(
                    document_from_kind(params.text_document.uri, kind),
                    settings,
                )
                if workspace_edit:
                    return [
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=workspace_edit,
                            diagnostics=[
                                diagnostic
                                for diagnostic in params.context.diagnostics
                                if diagnostic.source == "Ruff"
                                and cast(DiagnosticData, diagnostic.data).get("fix")
                                is not None
                            ],
                        ),
                    ]
                else:
                    return []

    actions: list[CodeAction] = []

    # If the linter is enabled, add "Ruff: Autofix" for every fixable diagnostic.
    if lint_enable(settings) and settings.get("codeAction", {}).get(
        "fixViolation", {}
    ).get("enable", True):
        if not params.context.only or CodeActionKind.QuickFix in params.context.only:
            # This is a text document representing either a Python file or a
            # Notebook cell.
            text_document = LSP_SERVER.workspace.get_text_document(
                params.text_document.uri
            )
            for diagnostic in params.context.diagnostics:
                if diagnostic.source == "Ruff":
                    fix = cast(DiagnosticData, diagnostic.data).get("fix")
                    if fix is not None:
                        title: str
                        if fix.get("message"):
                            title = f"Ruff ({diagnostic.code}): {fix['message']}"
                        elif diagnostic.code:
                            title = f"Ruff: Fix {diagnostic.code}"
                        else:
                            title = "Ruff: Fix"

                        actions.append(
                            CodeAction(
                                title=title,
                                kind=CodeActionKind.QuickFix,
                                data=params.text_document.uri,
                                edit=_create_workspace_edit(
                                    text_document.uri, text_document.version, fix
                                ),
                                diagnostics=[diagnostic],
                            ),
                        )

    # If the linter is enabled, add "Disable for this line" for every diagnostic.
    if lint_enable(settings) and settings.get("codeAction", {}).get(
        "disableRuleComment", {}
    ).get("enable", True):
        if not params.context.only or CodeActionKind.QuickFix in params.context.only:
            # This is a text document representing either a Python file or a
            # Notebook cell.
            text_document = LSP_SERVER.workspace.get_text_document(
                params.text_document.uri
            )
            lines: list[str] | None = None
            for diagnostic in params.context.diagnostics:
                if diagnostic.source == "Ruff":
                    noqa_row = cast(DiagnosticData, diagnostic.data).get("noqa_row")
                    if noqa_row is not None:
                        if lines is None:
                            lines = text_document.lines
                        line = lines[noqa_row - 1].rstrip("\r\n")

                        match = NOQA_REGEX.search(line)
                        if match and match.group("codes") is not None:
                            # `foo  # noqa: OLD` -> `foo  # noqa: OLD,NEW`
                            codes = match.group("codes") + f", {diagnostic.code}"
                            start, end = match.start("codes"), match.end("codes")
                            new_line = line[:start] + codes + line[end:]
                        elif match:
                            # `foo  # noqa` -> `foo  # noqa: NEW`
                            end = match.end("noqa")
                            new_line = line[:end] + f": {diagnostic.code}" + line[end:]
                        else:
                            # `foo` -> `foo  # noqa: NEW`
                            new_line = f"{line}  # noqa: {diagnostic.code}"
                        fix = Fix(
                            message=None,
                            applicability=None,
                            edits=[
                                Edit(
                                    content=new_line,
                                    location=Location(
                                        row=noqa_row,
                                        column=0,
                                    ),
                                    end_location=Location(
                                        row=noqa_row,
                                        column=len(line),
                                    ),
                                )
                            ],
                        )

                        title = f"Ruff ({diagnostic.code}): Disable for this line"

                        actions.append(
                            CodeAction(
                                title=title,
                                kind=CodeActionKind.QuickFix,
                                data=params.text_document.uri,
                                edit=_create_workspace_edit(
                                    text_document.uri, text_document.version, fix
                                ),
                                diagnostics=[diagnostic],
                            ),
                        )

    if settings["organizeImports"]:
        # Add "Ruff: Organize Imports" as a supported action.
        if not params.context.only or (
            CodeActionKind.SourceOrganizeImports in params.context.only
        ):
            if CLIENT_CAPABILITIES[CODE_ACTION_RESOLVE]:
                actions.append(
                    CodeAction(
                        title="Ruff: Organize Imports",
                        kind=CodeActionKind.SourceOrganizeImports,
                        data=params.text_document.uri,
                        edit=None,
                        diagnostics=[],
                    ),
                )
            else:
                workspace_edit = await _fix_document_impl(
                    Document.from_cell_or_text_uri(params.text_document.uri),
                    settings,
                    only=["I001", "I002"],
                )
                if workspace_edit:
                    actions.append(
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=CodeActionKind.SourceOrganizeImports,
                            data=params.text_document.uri,
                            edit=workspace_edit,
                            diagnostics=[],
                        ),
                    )

    # If the linter is enabled, add "Ruff: Fix All" as a supported action.
    if lint_enable(settings) and settings["fixAll"]:
        if not params.context.only or (
            CodeActionKind.SourceFixAll in params.context.only
        ):
            if CLIENT_CAPABILITIES[CODE_ACTION_RESOLVE]:
                actions.append(
                    CodeAction(
                        title="Ruff: Fix All",
                        kind=CodeActionKind.SourceFixAll,
                        data=params.text_document.uri,
                        edit=None,
                        diagnostics=[],
                    ),
                )
            else:
                workspace_edit = await _fix_document_impl(
                    Document.from_cell_or_text_uri(params.text_document.uri),
                    settings,
                )
                if workspace_edit:
                    actions.append(
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=CodeActionKind.SourceFixAll,
                            data=params.text_document.uri,
                            edit=workspace_edit,
                            diagnostics=[
                                diagnostic
                                for diagnostic in params.context.diagnostics
                                if diagnostic.source == "Ruff"
                                and cast(DiagnosticData, diagnostic.data).get("fix")
                                is not None
                            ],
                        ),
                    )

    return actions if actions else None


@LSP_SERVER.feature(CODE_ACTION_RESOLVE)
async def resolve_code_action(params: CodeAction) -> CodeAction:
    """LSP handler for codeAction/resolve request."""
    # We set the `data` field to the document URI during codeAction request.
    document = Document.from_cell_or_text_uri(cast(str, params.data))

    settings = _get_settings_by_document(document.path)

    if (
        settings["organizeImports"]
        and params.kind == CodeActionKind.SourceOrganizeImports
    ):
        # Generate the "Organize Imports" edit
        params.edit = await _fix_document_impl(
            document, settings, only=["I001", "I002"]
        )

    elif (
        lint_enable(settings)
        and settings["fixAll"]
        and params.kind == CodeActionKind.SourceFixAll
    ):
        # Generate the "Fix All" edit.
        params.edit = await _fix_document_impl(document, settings)

    return params


@LSP_SERVER.command("ruff.applyAutofix")
async def apply_autofix(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    document = Document.from_uri(uri)
    settings = _get_settings_by_document(document.path)
    if not lint_enable(settings):
        return None

    workspace_edit = await _fix_document_impl(document, settings)
    if workspace_edit is None:
        return None
    LSP_SERVER.apply_edit(workspace_edit, "Ruff: Fix all auto-fixable problems")


@LSP_SERVER.command("ruff.applyOrganizeImports")
async def apply_organize_imports(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    document = Document.from_uri(uri)
    settings = _get_settings_by_document(document.path)
    workspace_edit = await _fix_document_impl(document, settings, only=["I001", "I002"])
    if workspace_edit is None:
        return None
    LSP_SERVER.apply_edit(workspace_edit, "Ruff: Format imports")


@LSP_SERVER.command("ruff.applyFormat")
async def apply_format(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    document = Document.from_uri(uri)
    settings = _get_settings_by_document(document.path)

    result = await _run_format_on_document(document, settings)
    if result is None:
        return None

    # For `ruff format`, 0 indicates successful completion, non-zero indicates an error.
    if result.exit_code != 0:
        if result.stderr:
            show_error(f"Ruff: Format failed ({result.stderr.decode('utf-8')})")
        return None

    workspace_edit = _result_to_workspace_edit(document, result)
    if workspace_edit is None:
        return None
    LSP_SERVER.apply_edit(workspace_edit, "Ruff: Format document")


@LSP_SERVER.feature(TEXT_DOCUMENT_FORMATTING)
async def format_document(params: DocumentFormattingParams) -> list[TextEdit] | None:
    return await _format_document_impl(params, None)


@LSP_SERVER.feature(
    TEXT_DOCUMENT_RANGE_FORMATTING,
    DocumentRangeFormattingRegistrationOptions(
        document_selector=[
            TextDocumentFilter_Type1(language="python", scheme="file"),
            TextDocumentFilter_Type1(language="python", scheme="untitled"),
        ],
        ranges_support=False,
        work_done_progress=False,
    ),
)
async def format_document_range(
    params: DocumentRangeFormattingParams,
) -> list[TextEdit] | None:
    return await _format_document_impl(
        DocumentFormattingParams(
            params.text_document, params.options, params.work_done_token
        ),
        params.range,
    )


async def _format_document_impl(
    params: DocumentFormattingParams, range: Range | None
) -> list[TextEdit] | None:
    # For a Jupyter Notebook, this request can only format a single cell as the
    # request itself can only act on a text document. A cell in a Notebook is
    # represented as a text document. The "Notebook: Format notebook" action calls
    # this request for every cell.
    document = Document.from_cell_or_text_uri(params.text_document.uri)

    settings = _get_settings_by_document(document.path)

    # We don't support range formatting of notebooks yet but VS Code
    # doesn't seem to respect the document filter. For now, format the entire cell.
    range = None if document.kind is DocumentKind.Cell else range

    result = await _run_format_on_document(document, settings, range)
    if result is None:
        return None

    # For `ruff format`, 0 indicates successful completion, non-zero indicates an error.
    if result.exit_code != 0:
        if result.stderr:
            show_error(f"Ruff: Format failed ({result.stderr.decode('utf-8')})")
        return None

    if not VERSION_REQUIREMENT_EMPTY_OUTPUT.contains(
        result.executable.version, prereleases=True
    ):
        if not result.stdout and document.source.strip():
            return None

    if document.kind is DocumentKind.Cell:
        return _result_single_cell_notebook_to_edits(document, result)
    else:
        return _fixed_source_to_edits(
            original_source=document.source, fixed_source=result.stdout.decode("utf-8")
        )


async def _fix_document_impl(
    document: Document,
    settings: WorkspaceSettings,
    *,
    only: Sequence[str] | None = None,
) -> WorkspaceEdit | None:
    result = await _run_check_on_document(
        document,
        settings,
        extra_args=["--fix"],
        only=only,
    )

    if result is None:
        return None

    # For `ruff check`, 0 indicates successful completion with no remaining
    # diagnostics, 1 indicates successful completion with remaining diagnostics,
    # and 2 indicates an error.
    if result.exit_code not in (0, 1):
        if result.stderr:
            show_error(f"Ruff: Fix failed ({result.stderr.decode('utf-8')})")
        return None

    return _result_to_workspace_edit(document, result)


def _result_to_workspace_edit(
    document: Document, result: ExecutableResult | None
) -> WorkspaceEdit | None:
    """Converts a run result to a WorkspaceEdit."""
    if result is None:
        return None

    if not VERSION_REQUIREMENT_EMPTY_OUTPUT.contains(
        result.executable.version, prereleases=True
    ):
        if not result.stdout and document.source.strip():
            return None

    if document.kind is DocumentKind.Text:
        edits = _fixed_source_to_edits(
            original_source=document.source, fixed_source=result.stdout.decode("utf-8")
        )
        return WorkspaceEdit(
            document_changes=[
                _create_text_document_edit(document.uri, document.version, edits)
            ]
        )
    elif document.kind is DocumentKind.Notebook:
        notebook_document = LSP_SERVER.workspace.get_notebook_document(
            notebook_uri=document.uri
        )
        if notebook_document is None:
            log_warning(f"No notebook document found for {document.uri!r}")
            return None

        output_notebook_cells = cast(
            Notebook, json.loads(result.stdout.decode("utf-8"))
        )["cells"]
        if len(output_notebook_cells) != len(notebook_document.cells):
            log_warning(
                f"Number of cells in the output notebook doesn't match the number of "
                f"cells in the input notebook. Input: {len(notebook_document.cells)}, "
                f"Output: {len(output_notebook_cells)}"
            )
            return None

        cell_document_changes: list[TextDocumentEdit] = []
        for cell_idx, cell in enumerate(notebook_document.cells):
            if cell.kind is not NotebookCellKind.Code:
                continue
            cell_document = LSP_SERVER.workspace.get_text_document(cell.document)
            edits = _fixed_source_to_edits(
                original_source=cell_document.source,
                fixed_source=output_notebook_cells[cell_idx]["source"],
            )
            cell_document_changes.append(
                _create_text_document_edit(
                    cell_document.uri,
                    cell_document.version,
                    edits,
                )
            )

        return WorkspaceEdit(document_changes=list(cell_document_changes))
    elif document.kind is DocumentKind.Cell:
        text_edits = _result_single_cell_notebook_to_edits(document, result)
        if text_edits is None:
            return None
        return WorkspaceEdit(
            document_changes=[
                _create_text_document_edit(document.uri, document.version, text_edits)
            ]
        )
    else:
        assert_never(document.kind)


def _result_single_cell_notebook_to_edits(
    document: Document, result: ExecutableResult
) -> list[TextEdit] | None:
    """Converts a run result to a list of TextEdits.

    The result is expected to be a single cell Notebook Document.
    """
    output_notebook = cast(Notebook, json.loads(result.stdout.decode("utf-8")))
    # The input notebook contained only one cell, so the output notebook should
    # also contain only one cell.
    output_cell = next(iter(output_notebook["cells"]), None)
    if output_cell is None or output_cell["cell_type"] != "code":
        log_warning(
            f"Unexpected output working with a notebook cell: {output_notebook}"
        )
        return None
    # We can't use the `document.source` here because it's in the Notebook format
    # i.e., it's a JSON string containing a single cell with the source.
    original_source = LSP_SERVER.workspace.get_text_document(document.uri).source
    return _fixed_source_to_edits(
        original_source=original_source, fixed_source=output_cell["source"]
    )


def _fixed_source_to_edits(
    *, original_source: str, fixed_source: str | list[str]
) -> list[TextEdit]:
    """Converts the fixed source to a list of TextEdits.

    If the fixed source is a list of strings, it is joined together to form a single
    string with an assumption that the line endings are part of the strings itself.
    """
    if isinstance(fixed_source, list):
        fixed_source = "".join(fixed_source)

    new_source = _match_line_endings(original_source, fixed_source)

    if new_source == original_source:
        return []

    # Reduce the text edit by omitting the common suffix and postfix (lines)
    # from the text edit. I chose this basic diffing because "proper" diffing has
    # the downside that it can be very slow in some cases. Black uses a diffing approach
    # that takes time into consideration, but it requires spawning a thread to stop
    # the diffing after a given time, which feels very heavy weight.
    # This basic "diffing" has a guaranteed `O(n)` runtime and is sufficient to
    # prevent transmitting the entire source document when formatting a range
    # or formatting a document where most of the code remains unchanged.
    #
    # https://github.com/microsoft/vscode-black-formatter/blob/main/bundled/tool/lsp_edit_utils.py
    new_lines = new_source.splitlines(True)
    original_lines = original_source.splitlines(True)

    start_offset = 0
    end_offset = 0

    for new_line, original_line in zip(new_lines, original_lines):
        if new_line == original_line:
            start_offset += 1
        else:
            break

    for new_line, original_line in zip(
        reversed(new_lines[start_offset:]), reversed(original_lines[start_offset:])
    ):
        if new_line == original_line:
            end_offset += 1
        else:
            break

    trimmed_new_source = "".join(new_lines[start_offset : len(new_lines) - end_offset])

    return [
        TextEdit(
            range=Range(
                start=Position(line=start_offset, character=0),
                end=Position(line=len(original_lines) - end_offset, character=0),
            ),
            new_text=trimmed_new_source,
        )
    ]


def _create_text_document_edit(
    uri: str, version: int | None, edits: Sequence[TextEdit | AnnotatedTextEdit]
) -> TextDocumentEdit:
    return TextDocumentEdit(
        text_document=OptionalVersionedTextDocumentIdentifier(
            uri=uri,
            version=0 if version is None else version,
        ),
        edits=list(edits),
    )


def _create_workspace_edit(uri: str, version: int | None, fix: Fix) -> WorkspaceEdit:
    return WorkspaceEdit(
        document_changes=[
            TextDocumentEdit(
                text_document=OptionalVersionedTextDocumentIdentifier(
                    uri=uri,
                    version=0 if version is None else version,
                ),
                edits=[
                    TextEdit(
                        range=Range(
                            start=Position(
                                line=edit["location"]["row"] - 1,
                                character=edit["location"]["column"],
                            ),
                            end=Position(
                                line=edit["end_location"]["row"] - 1,
                                character=edit["end_location"]["column"],
                            ),
                        ),
                        new_text=edit["content"],
                    )
                    for edit in fix["edits"]
                ],
            )
        ],
    )


def _get_line_endings(text: str) -> str | None:
    """Returns line endings used in the text."""
    for i in range(len(text)):
        if text[i] == "\r":
            if i < len(text) - 1 and text[i + 1] == "\n":
                return "\r\n"  # CLRF
            else:
                return "\r"  # CR
        elif text[i] == "\n":
            return "\n"  # LF
    return None  # No line ending found


def _match_line_endings(original_source: str, fixed_source: str) -> str:
    """Ensures that the edited text line endings matches the document line endings."""
    expected = _get_line_endings(original_source)
    actual = _get_line_endings(fixed_source)
    if actual is None or expected is None or actual == expected:
        return fixed_source
    return fixed_source.replace(actual, expected)


async def run_path(
    program: str,
    argv: Sequence[str],
    *,
    source: str,
    cwd: str | None = None,
) -> RunResult:
    """Runs as an executable."""
    log_to_output(f"Running Ruff with: {program} {argv}")

    process = await asyncio.create_subprocess_exec(
        program,
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    result = RunResult(
        *await process.communicate(input=source.encode("utf-8")),
        exit_code=await process.wait(),
    )

    if result.stderr:
        log_to_output(result.stderr.decode("utf-8"))

    return result


###
# Lifecycle.
###


@LSP_SERVER.feature(INITIALIZE)
def initialize(params: InitializeParams) -> None:
    """LSP handler for initialize request."""
    # Extract client capabilities.
    CLIENT_CAPABILITIES[CODE_ACTION_RESOLVE] = _supports_code_action_resolve(
        params.capabilities
    )

    # Extract `settings` from the initialization options.
    workspace_settings: list[WorkspaceSettings] | WorkspaceSettings | None = (
        params.initialization_options or {}
    ).get(
        "settings",
    )
    global_settings: UserSettings | None = (params.initialization_options or {}).get(
        "globalSettings", {}
    )

    log_to_output(
        f"Workspace settings: "
        f"{json.dumps(workspace_settings, indent=4, ensure_ascii=False)}"
    )
    log_to_output(
        f"Global settings: "
        f"{json.dumps(global_settings, indent=4, ensure_ascii=False)}"
    )

    # Preserve any "global" settings.
    if global_settings:
        GLOBAL_SETTINGS.update(global_settings)
    elif isinstance(workspace_settings, dict):
        # In Sublime Text, Neovim, and probably others, we're passed a single
        # `settings`, which we'll treat as defaults for any future files.
        GLOBAL_SETTINGS.update(workspace_settings)

    # Update workspace settings.
    settings: list[WorkspaceSettings]
    if isinstance(workspace_settings, dict):
        settings = [workspace_settings]
    elif isinstance(workspace_settings, list):
        # In VS Code, we're passed a list of `settings`, one for each workspace folder.
        settings = workspace_settings
    else:
        settings = []

    _update_workspace_settings(settings)


def _supports_code_action_resolve(capabilities: ClientCapabilities) -> bool:
    """Returns True if the client supports codeAction/resolve request for edits."""
    if capabilities.text_document is None:
        return False

    if capabilities.text_document.code_action is None:
        return False

    if capabilities.text_document.code_action.resolve_support is None:
        return False

    return "edit" in capabilities.text_document.code_action.resolve_support.properties


###
# Settings.
###


def _get_global_defaults() -> UserSettings:
    settings: UserSettings = {
        "codeAction": GLOBAL_SETTINGS.get("codeAction", {}),
        "fixAll": GLOBAL_SETTINGS.get("fixAll", True),
        "format": GLOBAL_SETTINGS.get("format", {}),
        "ignoreStandardLibrary": GLOBAL_SETTINGS.get("ignoreStandardLibrary", True),
        "importStrategy": GLOBAL_SETTINGS.get("importStrategy", "fromEnvironment"),
        "interpreter": GLOBAL_SETTINGS.get("interpreter", [sys.executable]),
        "lint": GLOBAL_SETTINGS.get("lint", {}),
        "logLevel": GLOBAL_SETTINGS.get("logLevel", "error"),
        "organizeImports": GLOBAL_SETTINGS.get("organizeImports", True),
        "path": GLOBAL_SETTINGS.get("path", []),
    }

    # Deprecated: use `lint.args` instead.
    if "args" in GLOBAL_SETTINGS:
        settings["args"] = GLOBAL_SETTINGS["args"]

    # Deprecated: use `lint.run` instead.
    if "run" in GLOBAL_SETTINGS:
        settings["run"] = GLOBAL_SETTINGS["run"]

    return settings


def _update_workspace_settings(settings: list[WorkspaceSettings]) -> None:
    if not settings:
        workspace_path = os.getcwd()
        WORKSPACE_SETTINGS[workspace_path] = {
            **_get_global_defaults(),  # type: ignore[misc]
            "cwd": workspace_path,
            "workspacePath": workspace_path,
            "workspace": uris.from_fs_path(workspace_path),
        }
        return None

    for setting in settings:
        if "workspace" in setting:
            workspace_path = uris.to_fs_path(setting["workspace"])
            WORKSPACE_SETTINGS[workspace_path] = {
                **_get_global_defaults(),  # type: ignore[misc]
                **setting,
                "cwd": workspace_path,
                "workspacePath": workspace_path,
                "workspace": setting["workspace"],
            }
        else:
            workspace_path = os.getcwd()
            WORKSPACE_SETTINGS[workspace_path] = {
                **_get_global_defaults(),  # type: ignore[misc]
                **setting,
                "cwd": workspace_path,
                "workspacePath": workspace_path,
                "workspace": uris.from_fs_path(workspace_path),
            }


def _get_document_key(document_path: str) -> str | None:
    document_workspace = Path(document_path)
    workspaces = {s["workspacePath"] for s in WORKSPACE_SETTINGS.values()}

    while document_workspace != document_workspace.parent:
        if str(document_workspace) in workspaces:
            return str(document_workspace)
        document_workspace = document_workspace.parent
    return None


def _get_settings_by_document(document_path: str) -> WorkspaceSettings:
    key = _get_document_key(document_path)
    if key is None:
        # This is either a non-workspace file or there is no workspace.
        workspace_path = os.fspath(Path(document_path).parent)
        return {
            **_get_global_defaults(),  # type: ignore[misc]
            "cwd": None,
            "workspacePath": workspace_path,
            "workspace": uris.from_fs_path(workspace_path),
        }

    return WORKSPACE_SETTINGS[str(key)]


###
# Internal execution APIs.
###


class Executable(NamedTuple):
    path: str
    """The path to the executable."""

    version: Version
    """The version of the executable."""


class ExecutableResult(NamedTuple):
    executable: Executable
    """The executable."""

    stdout: bytes
    """The stdout of running the executable."""

    stderr: bytes
    """The stderr of running the executable."""

    exit_code: int
    """The exit code of running the executable."""


def _find_ruff_binary(
    settings: WorkspaceSettings, version_requirement: SpecifierSet | None
) -> Executable:
    """Returns the executable along with its version.

    If the executable doesn't meet the version requirement, raises a RuntimeError and
    displays an error message.
    """
    path = _find_ruff_binary_path(settings)

    version = _executable_version(path)
    if version_requirement and not version_requirement.contains(
        version, prereleases=True
    ):
        message = f"Ruff {version_requirement} required, but found {version} at {path}"
        show_error(message)
        raise RuntimeError(message)
    log_to_output(f"Found ruff {version} at {path}")

    return Executable(path, version)


def _find_ruff_binary_path(settings: WorkspaceSettings) -> str:
    """Returns the path to the executable."""
    bundle = get_bundle()

    if settings["path"]:
        # 'path' setting takes priority over everything.
        paths = settings["path"]
        if isinstance(paths, str):
            paths = [paths]
        for path in paths:
            path = os.path.expanduser(os.path.expandvars(path))
            if os.path.exists(path):
                log_to_output(f"Using 'path' setting: {path}")
                return path
        else:
            log_to_output(f"Could not find executable in 'path': {settings['path']}")

    if settings["importStrategy"] == "useBundled" and bundle:
        # If we're loading from the bundle, use the absolute path.
        log_to_output(f"Using bundled executable: {bundle}")
        return bundle

    if settings["interpreter"] and not utils.is_current_interpreter(
        settings["interpreter"][0]
    ):
        # If there is a different interpreter set, find its script path.
        if settings["interpreter"][0] not in INTERPRETER_PATHS:
            INTERPRETER_PATHS[settings["interpreter"][0]] = utils.scripts(
                os.path.expanduser(os.path.expandvars(settings["interpreter"][0]))
            )

        path = os.path.join(INTERPRETER_PATHS[settings["interpreter"][0]], TOOL_MODULE)
    else:
        path = os.path.join(sysconfig.get_path("scripts"), TOOL_MODULE)

    # First choice: the executable in the current interpreter's scripts directory.
    if os.path.exists(path):
        log_to_output(f"Using interpreter executable: {path}")
        return path
    else:
        log_to_output(f"Interpreter executable ({path}) not found")

    # Second choice: the executable in the global environment.
    environment_path = shutil.which("ruff")
    if environment_path:
        log_to_output(f"Using environment executable: {environment_path}")
        return environment_path

    # Third choice: bundled executable.
    if bundle:
        log_to_output(f"Falling back to bundled executable: {bundle}")
        return bundle

    # Last choice: just return the expected path for the current interpreter.
    log_to_output(f"Unable to find interpreter executable: {path}")
    return path


def _executable_version(executable: str) -> Version:
    """Returns the version of the executable."""
    # If the user change the file (e.g. `pip install -U ruff`), invalidate the cache
    modified = Path(executable).stat().st_mtime
    if (
        executable not in EXECUTABLE_VERSIONS
        or EXECUTABLE_VERSIONS[executable].modified != modified
    ):
        version = utils.version(executable)
        log_to_output(f"Inferred version {version} for: {executable}")
        EXECUTABLE_VERSIONS[executable] = VersionModified(version, modified)
    return EXECUTABLE_VERSIONS[executable].version


async def _run_check_on_document(
    document: Document,
    settings: WorkspaceSettings,
    *,
    extra_args: Sequence[str] = [],
    only: Sequence[str] | None = None,
) -> ExecutableResult | None:
    """Runs the Ruff `check` subcommand  on the given document source."""
    if settings.get("ignoreStandardLibrary", True) and document.is_stdlib_file():
        log_warning(f"Skipping standard library file: {document.path}")
        return None

    executable = _find_ruff_binary(settings, VERSION_REQUIREMENT_LINTER)
    argv: list[str] = CHECK_ARGS + list(extra_args)

    skip_next_arg = False
    for arg in lint_args(settings):
        if skip_next_arg:
            skip_next_arg = False
            continue
        if arg in UNSUPPORTED_CHECK_ARGS:
            log_to_output(f"Ignoring unsupported argument: {arg}")
            continue
        # If we're trying to run a single rule, we need to make sure to skip any of the
        # arguments that would override it.
        if only is not None:
            # Case 1: Option and its argument as separate items
            # (e.g. `["--select", "F821"]`).
            if arg in ("--select", "--extend-select", "--ignore", "--extend-ignore"):
                # Skip the following argument assuming it's a list of rules.
                skip_next_arg = True
                continue
            # Case 2: Option and its argument as a single item
            # (e.g. `["--select=F821"]`).
            elif arg.startswith(
                ("--select=", "--extend-select=", "--ignore=", "--extend-ignore=")
            ):
                continue
        argv.append(arg)

    # If the Ruff version is not sufficiently recent, use the deprecated `--format`
    # argument instead of `--output-format`.
    if not VERSION_REQUIREMENT_OUTPUT_FORMAT.contains(
        executable.version, prereleases=True
    ):
        index = argv.index("--output-format")
        argv.pop(index)
        argv.insert(index, "--format")

    # If we're trying to run a single rule, add it to the command line.
    if only is not None:
        for rule in only:
            argv += ["--select", rule]

    # Provide the document filename.
    argv += ["--stdin-filename", document.path]

    return ExecutableResult(
        executable,
        *await run_path(
            executable.path,
            argv,
            cwd=settings["cwd"],
            source=document.source,
        ),
    )


async def _run_format_on_document(
    document: Document, settings: WorkspaceSettings, format_range: Range | None = None
) -> ExecutableResult | None:
    """Runs the Ruff `format` subcommand on the given document source."""
    if settings.get("ignoreStandardLibrary", True) and document.is_stdlib_file():
        log_warning(f"Skipping standard library file: {document.path}")
        return None

    version_requirement = (
        VERSION_REQUIREMENT_FORMATTER
        if format_range is None
        else VERSION_REQUIREMENT_RANGE_FORMATTING
    )
    executable = _find_ruff_binary(settings, version_requirement)
    argv: list[str] = [
        "format",
        "--force-exclude",
        "--quiet",
        "--stdin-filename",
        document.path,
    ]

    if format_range:
        codec = PositionCodec(PositionEncodingKind.Utf16)
        format_range = codec.range_from_client_units(
            document.source.splitlines(True), format_range
        )

        argv.extend(
            [
                "--range",
                f"{format_range.start.line + 1}:{format_range.start.character + 1}-{format_range.end.line + 1}:{format_range.end.character + 1}",  # noqa: E501
            ]
        )

    for arg in settings.get("format", {}).get("args", []):
        if arg in UNSUPPORTED_FORMAT_ARGS:
            log_to_output(f"Ignoring unsupported argument: {arg}")
        else:
            argv.append(arg)

    return ExecutableResult(
        executable,
        *await run_path(
            executable.path,
            argv,
            cwd=settings["cwd"],
            source=document.source,
        ),
    )


async def _run_subcommand_on_document(
    document: workspace.TextDocument,
    version_requirement: SpecifierSet,
    *,
    args: Sequence[str],
) -> ExecutableResult:
    """Runs the tool subcommand on the given document."""
    settings = _get_settings_by_document(document.path)

    executable = _find_ruff_binary(settings, version_requirement)
    argv: list[str] = list(args)

    return ExecutableResult(
        executable,
        *await run_path(
            executable.path,
            argv,
            cwd=settings["cwd"],
            source=document.source,
        ),
    )


###
# Logging.
###


def log_to_output(message: str) -> None:
    LSP_SERVER.show_message_log(message, MessageType.Log)


def show_error(message: str) -> None:
    """Show a pop-up with an error. Only use for critical errors."""
    LSP_SERVER.show_message_log(message, MessageType.Error)
    LSP_SERVER.show_message(message, MessageType.Error)


def log_warning(message: str) -> None:
    LSP_SERVER.show_message_log(message, MessageType.Warning)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["onWarning", "always"]:
        LSP_SERVER.show_message(message, MessageType.Warning)


def log_always(message: str) -> None:
    LSP_SERVER.show_message_log(message, MessageType.Info)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["always"]:
        LSP_SERVER.show_message(message, MessageType.Info)


###
# Bundled mode.
###

_BUNDLED_PATH: str | None = None


def set_bundle(path: str) -> None:
    """Sets the path to the bundled Ruff executable."""
    global _BUNDLED_PATH
    _BUNDLED_PATH = path


def get_bundle() -> str | None:
    """Returns the path to the bundled Ruff executable."""
    return _BUNDLED_PATH


###
# Start up.
###


def start() -> None:
    LSP_SERVER.start_io()


if __name__ == "__main__":
    start()
