"""Implementation of the LSP server for Ruff."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import NamedTuple, Sequence, cast

from lsprotocol import validators
from lsprotocol.types import (
    CODE_ACTION_RESOLVE,
    INITIALIZE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_FORMATTING,
    TEXT_DOCUMENT_HOVER,
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
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    DocumentFormattingParams,
    Hover,
    HoverParams,
    InitializeParams,
    MarkupContent,
    MarkupKind,
    MessageType,
    OptionalVersionedTextDocumentIdentifier,
    Position,
    Range,
    TextDocumentEdit,
    TextEdit,
    WorkspaceEdit,
)
from packaging.specifiers import SpecifierSet, Version
from pygls import server, uris, workspace
from typing_extensions import TypedDict

from ruff_lsp import __version__, utils
from ruff_lsp.settings import (
    UserSettings,
    WorkspaceSettings,
    lint_args,
    lint_run,
)
from ruff_lsp.utils import RunResult

logger = logging.getLogger(__name__)

RUFF_LSP_DEBUG = bool(os.environ.get("RUFF_LSP_DEBUG", False))
RUFF_EXPERIMENTAL_FORMATTER = bool(os.environ.get("RUFF_EXPERIMENTAL_FORMATTER", False))

if RUFF_LSP_DEBUG:
    log_file = Path(__file__).parent.parent.joinpath("ruff-lsp.log")
    logging.basicConfig(filename=log_file, filemode="w", level=logging.DEBUG)
    logger.info("RUFF_LSP_DEBUG is active")
    if RUFF_EXPERIMENTAL_FORMATTER:
        logger.info("RUFF_EXPERIMENTAL_FORMATTER is active")


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
)

TOOL_MODULE = "ruff.exe" if sys.platform == "win32" else "ruff"
TOOL_DISPLAY = "Ruff"

# Require at least Ruff v0.0.291 for formatting, but allow older versions for linting.
VERSION_REQUIREMENT_FORMATTER = SpecifierSet(">=0.0.291,<0.2.0")
VERSION_REQUIREMENT_LINTER = SpecifierSet(">=0.0.189,<0.2.0")
# Version requirement for use of the "ALL" rule selector
VERSION_REQUIREMENT_ALL_SELECTOR = SpecifierSet(">=0.0.198,<0.2.0")
# Version requirement for use of the `--output-format` option
VERSION_REQUIREMENT_OUTPUT_FORMAT = SpecifierSet(">=0.0.291,<0.2.0")

# Arguments provided to every Ruff invocation.
CHECK_ARGS = [
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


###
# Linting.
###


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: DidOpenTextDocumentParams) -> None:
    """LSP handler for textDocument/didOpen request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    diagnostics: list[Diagnostic] = await _lint_document_impl(document)
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: DidCloseTextDocumentParams) -> None:
    """LSP handler for textDocument/didClose request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    # Publishing empty diagnostics to clear the entries for this file.
    LSP_SERVER.publish_diagnostics(document.uri, [])


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: DidSaveTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    if lint_run(_get_settings_by_document(document.path)) in ("onType", "onSave"):
        diagnostics: list[Diagnostic] = await _lint_document_impl(document)
        LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: DidChangeTextDocumentParams) -> None:
    """LSP handler for textDocument/didChange request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    if lint_run(_get_settings_by_document(document.path)) == "onType":
        diagnostics: list[Diagnostic] = await _lint_document_impl(document)
        LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


async def _lint_document_impl(document: workspace.TextDocument) -> list[Diagnostic]:
    result = await _run_check_on_document(document)
    if result is None:
        return []
    return _parse_output(result.stdout) if result.stdout else []


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


def _parse_output(content: bytes) -> list[Diagnostic]:
    """Parse Ruff's JSON output."""
    diagnostics: list[Diagnostic] = []

    # Ruff's output looks like:
    # [
    #   {
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
    for check in json.loads(content):
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
    """LSP handler for textDocument/hover request."""
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
            CodeActionKind.QuickFix,
            CodeActionKind.SourceFixAll,
            CodeActionKind.SourceOrganizeImports,
            f"{CodeActionKind.SourceFixAll.value}.ruff",
            f"{CodeActionKind.SourceOrganizeImports.value}.ruff",
        ],
        resolve_provider=True,
    ),
)
async def code_action(params: CodeActionParams) -> list[CodeAction] | None:
    """LSP handler for textDocument/codeAction request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)

    settings = _get_settings_by_document(document.path)

    if utils.is_stdlib_file(document.path):
        # Don't format standard library files.
        # Publishing empty diagnostics clears the entry.
        return None

    if settings["organizeImports"]:
        # Generate the "Ruff: Organize Imports" edit
        for kind in (
            CodeActionKind.SourceOrganizeImports,
            f"{CodeActionKind.SourceOrganizeImports.value}.ruff",
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                edits = await _fix_document_impl(document, only="I001")
                if edits:
                    return [
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, edits),
                            diagnostics=[],
                        )
                    ]
                else:
                    return []

    if settings["fixAll"]:
        # Generate the "Ruff: Fix All" edit.
        for kind in (
            CodeActionKind.SourceFixAll,
            f"{CodeActionKind.SourceFixAll.value}.ruff",
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                edits = await _fix_document_impl(document)
                if edits:
                    return [
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, edits),
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

    # Add "Ruff: Autofix" for every fixable diagnostic.
    if settings.get("codeAction", {}).get("fixViolation", {}).get("enable", True):
        if not params.context.only or CodeActionKind.QuickFix in params.context.only:
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
                                edit=_create_workspace_edit(document, fix),
                                diagnostics=[diagnostic],
                            ),
                        )

    # Add "Disable for this line" for every diagnostic.
    if settings.get("codeAction", {}).get("disableRuleComment", {}).get("enable", True):
        if not params.context.only or CodeActionKind.QuickFix in params.context.only:
            lines: list[str] | None = None
            for diagnostic in params.context.diagnostics:
                if diagnostic.source == "Ruff":
                    noqa_row = cast(DiagnosticData, diagnostic.data).get("noqa_row")
                    if noqa_row is not None:
                        if lines is None:
                            lines = document.lines
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
                                edit=_create_workspace_edit(document, fix),
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
                edits = await _fix_document_impl(document, only="I001")
                if edits:
                    actions.append(
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=CodeActionKind.SourceOrganizeImports,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, edits),
                            diagnostics=[],
                        ),
                    )

    if settings["fixAll"]:
        # Add "Ruff: Fix All" as a supported action.
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
                edits = await _fix_document_impl(document)
                if edits:
                    actions.append(
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=CodeActionKind.SourceFixAll,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, edits),
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
    document = LSP_SERVER.workspace.get_text_document(cast(str, params.data))

    settings = _get_settings_by_document(document.path)

    if settings["organizeImports"] and params.kind in (
        CodeActionKind.SourceOrganizeImports,
        f"{CodeActionKind.SourceOrganizeImports.value}.ruff",
    ):
        # Generate the "Ruff: Organize Imports" edit
        results = await _fix_document_impl(document, only="I001")
        params.edit = _create_workspace_edits(document, results)

    elif settings["fixAll"] and params.kind in (
        CodeActionKind.SourceFixAll,
        f"{CodeActionKind.SourceFixAll.value}.ruff",
    ):
        # Generate the "Ruff: Fix All" edit.
        results = await _fix_document_impl(document)
        params.edit = _create_workspace_edits(document, results)

    return params


@LSP_SERVER.command("ruff.applyAutofix")
async def apply_autofix(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    text_document = LSP_SERVER.workspace.get_text_document(uri)
    results = await _fix_document_impl(text_document)
    LSP_SERVER.apply_edit(
        _create_workspace_edits(text_document, results),
        "Ruff: Fix all auto-fixable problems",
    )


@LSP_SERVER.command("ruff.applyOrganizeImports")
async def apply_organize_imports(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    text_document = LSP_SERVER.workspace.get_text_document(uri)
    results = await _fix_document_impl(text_document, only="I001")
    LSP_SERVER.apply_edit(
        _create_workspace_edits(text_document, results),
        "Ruff: Format imports",
    )


@LSP_SERVER.command("ruff.applyFormat")
async def apply_format(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    text_document = LSP_SERVER.workspace.get_text_document(uri)
    results = await _format_document_impl(text_document)
    LSP_SERVER.apply_edit(
        _create_workspace_edits(text_document, results),
        "Ruff: Format document",
    )


if RUFF_EXPERIMENTAL_FORMATTER:

    @LSP_SERVER.feature(TEXT_DOCUMENT_FORMATTING)
    async def format_document(
        ls: server.LanguageServer,
        params: DocumentFormattingParams,
    ) -> list[TextEdit] | None:
        uri = params.text_document.uri
        document = ls.workspace.get_text_document(uri)
        return await _format_document_impl(document)


async def _format_document_impl(
    document: workspace.TextDocument,
) -> list[TextEdit]:
    result = await _run_format_on_document(document)
    return _result_to_edits(document, result)


async def _fix_document_impl(
    document: workspace.TextDocument,
    *,
    only: str | None = None,
) -> list[TextEdit]:
    result = await _run_check_on_document(document, extra_args=["--fix"], only=only)
    return _result_to_edits(document, result)


def _result_to_edits(
    document: workspace.TextDocument,
    result: RunResult | None,
) -> list[TextEdit]:
    if result is None:
        return []

    if not result.stdout:
        return []

    new_source = _match_line_endings(document, result.stdout.decode("utf-8"))

    # Skip last line ending in a notebook cell.
    if document.uri.startswith("vscode-notebook-cell"):
        if new_source.endswith("\r\n"):
            new_source = new_source[:-2]
        elif new_source.endswith("\n"):
            new_source = new_source[:-1]

    if new_source == document.source:
        return []

    return [
        TextEdit(
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=validators.UINTEGER_MAX_VALUE, character=0),
            ),
            new_text=new_source,
        )
    ]


def _create_workspace_edits(
    document: workspace.TextDocument,
    edits: Sequence[TextEdit | AnnotatedTextEdit],
) -> WorkspaceEdit:
    return WorkspaceEdit(
        document_changes=[
            TextDocumentEdit(
                text_document=OptionalVersionedTextDocumentIdentifier(
                    uri=document.uri,
                    version=0 if document.version is None else document.version,
                ),
                edits=list(edits),
            )
        ],
    )


def _create_workspace_edit(document: workspace.TextDocument, fix: Fix) -> WorkspaceEdit:
    return WorkspaceEdit(
        document_changes=[
            TextDocumentEdit(
                text_document=OptionalVersionedTextDocumentIdentifier(
                    uri=document.uri,
                    version=0 if document.version is None else document.version,
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


def _match_line_endings(document: workspace.TextDocument, text: str) -> str:
    """Ensures that the edited text line endings matches the document line endings."""
    expected = _get_line_endings(document.source)
    actual = _get_line_endings(text)
    if actual is None or expected is None or actual == expected:
        return text
    return text.replace(actual, expected)


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
    result = RunResult(*await process.communicate(input=source.encode("utf-8")))

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

    # Internal hidden beta feature. We want to have this in the code base, but we
    # don't want to expose it to users yet, hence the environment variable. You can
    # e.g. use this with VS Code by doing `RUFF_EXPERIMENTAL_FORMATTER=1 code .`
    # CLIENT_CAPABILITIES[TEXT_DOCUMENT_FORMATTING] = RUFF_EXPERIMENTAL_FORMATTER

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
        "importStrategy": GLOBAL_SETTINGS.get("importStrategy", "fromEnvironment"),
        "interpreter": GLOBAL_SETTINGS.get("interpreter", [sys.executable]),
        "lint": GLOBAL_SETTINGS.get("lint", {}),
        "format": GLOBAL_SETTINGS.get("format", {}),
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
        return

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
        for path in settings["path"]:
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
    document: workspace.TextDocument,
    *,
    extra_args: Sequence[str] = [],
    only: str | None = None,
) -> RunResult | None:
    """Runs the Ruff `check` subcommand  on the given document."""
    if str(document.uri).startswith("vscode-notebook-cell"):
        # Skip notebook cells
        return None

    if utils.is_stdlib_file(document.path):
        log_warning(f"Skipping standard library file: {document.path}")
        return None

    settings = _get_settings_by_document(document.path)

    executable = _find_ruff_binary(settings, VERSION_REQUIREMENT_LINTER)
    argv: list[str] = CHECK_ARGS + list(extra_args)

    for arg in lint_args(settings):
        if arg in UNSUPPORTED_CHECK_ARGS:
            log_to_output(f"Ignoring unsupported argument: {arg}")
        else:
            argv.append(arg)

    # If the Ruff version is not sufficiently recent, use the deprecated `--format`
    # argument instead of `--output-format`.
    if not VERSION_REQUIREMENT_OUTPUT_FORMAT.contains(
        executable.version, prereleases=True
    ):
        index = argv.index("--output-format")
        argv.pop(index)
        argv.insert(index, "--format")

    # If we're trying to run a single rule, add it to the command line, and disable
    # all other rules (if the Ruff version is sufficiently recent).
    if only:
        if VERSION_REQUIREMENT_ALL_SELECTOR.contains(
            executable.version, prereleases=True
        ):
            argv += ["--extend-ignore", "ALL"]
        argv += ["--extend-select", only]

    # Provide the document filename.
    argv += ["--stdin-filename", document.path]

    return await run_path(
        executable.path,
        argv,
        cwd=settings["cwd"],
        source=document.source,
    )


async def _run_format_on_document(document: workspace.TextDocument) -> RunResult | None:
    """Runs the Ruff `format` subcommand on the given document."""
    if str(document.uri).startswith("vscode-notebook-cell"):
        # Skip notebook cells
        return None

    if utils.is_stdlib_file(document.path):
        log_warning(f"Skipping standard library file: {document.path}")
        return None

    settings = _get_settings_by_document(document.path)
    executable = _find_ruff_binary(settings, VERSION_REQUIREMENT_FORMATTER)
    argv: list[str] = [
        "format",
        "--force-exclude",
        "--quiet",
        "--stdin-filename",
        document.path,
    ]

    for arg in settings.get("format", {}).get("args", []):
        if arg in UNSUPPORTED_FORMAT_ARGS:
            log_to_output(f"Ignoring unsupported argument: {arg}")
        else:
            argv.append(arg)

    return await run_path(
        executable.path,
        argv,
        cwd=settings["cwd"],
        source=document.source,
    )


async def _run_subcommand_on_document(
    document: workspace.TextDocument,
    version_requirement: SpecifierSet,
    *,
    args: Sequence[str],
) -> RunResult:
    """Runs the tool subcommand on the given document."""
    settings = _get_settings_by_document(document.path)

    executable = _find_ruff_binary(settings, version_requirement)
    argv: list[str] = list(args)
    return await run_path(
        executable.path,
        argv,
        cwd=settings["cwd"],
        source=document.source,
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
