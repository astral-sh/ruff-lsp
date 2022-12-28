"""Implementation of the LSP server for Ruff."""

from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import sys
import sysconfig
from typing import Any, Sequence, cast

from lsprotocol.types import (
    CODE_ACTION_RESOLVE,
    INITIALIZE,
    TEXT_DOCUMENT_CODE_ACTION,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    TEXT_DOCUMENT_HOVER,
    AnnotatedTextEdit,
    ClientCapabilities,
    CodeAction,
    CodeActionKind,
    CodeActionOptions,
    CodeActionParams,
    Diagnostic,
    DiagnosticSeverity,
    DiagnosticTag,
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
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
    TraceValues,
    WorkspaceEdit,
)
from pygls import protocol, server, uris, workspace
from typing_extensions import TypedDict

from ruff_lsp import __version__, utils

USER_DEFAULTS: dict[str, str] = {}
WORKSPACE_SETTINGS: dict[str, dict[str, Any]] = {}
INTERPRETER_PATHS: dict[str, str] = {}
CLIENT_CAPABILITIES: dict[str, bool] = {
    CODE_ACTION_RESOLVE: True,
}

MAX_WORKERS = 5
LSP_SERVER = server.LanguageServer(
    name="Ruff",
    version=__version__,
    max_workers=MAX_WORKERS,
)

TOOL_MODULE = "ruff"
TOOL_DISPLAY = "Ruff"
TOOL_ARGS = ["--no-cache", "--no-fix", "--quiet", "--format", "json", "-"]


###
# Linting.
###


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_OPEN)
def did_open(params: DidOpenTextDocumentParams) -> None:
    """LSP handler for textDocument/didOpen request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    diagnostics: list[Diagnostic] = _linting_helper(document)
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_SAVE)
def did_save(params: DidSaveTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    diagnostics: list[Diagnostic] = _linting_helper(document)
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CHANGE)
def did_change(params: DidChangeTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    diagnostics: list[Diagnostic] = _linting_helper(document)
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(TEXT_DOCUMENT_DID_CLOSE)
def did_close(params: DidCloseTextDocumentParams) -> None:
    """LSP handler for textDocument/didClose request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    # Publishing empty diagnostics to clear the entries for this file.
    LSP_SERVER.publish_diagnostics(document.uri, [])


def _linting_helper(document: workspace.Document) -> list[Diagnostic]:
    result = _run_tool_on_document(document, use_stdin=True)
    if result is None:
        return []
    return _parse_output_using_regex(result.stdout) if result.stdout else []


def _parse_output_using_regex(content: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    line_at_1 = True
    column_at_1 = True

    line_offset = 1 if line_at_1 else 0
    col_offset = 1 if column_at_1 else 0

    # Ruff's output looks like:
    # [
    #   {
    #     "code": "F841",
    #     "message": "Local variable `x` is assigned to but never used",
    #     "fixed": false,
    #     "location": {
    #       "row": 2,
    #       "column": 5
    #     },
    #     "fix": {
    #       "content: "",
    #       "location": {
    #         "row": 2,
    #         "column: 5
    #       },
    #       "end_location": {
    #         "row": 3,
    #         "column: 0
    #       }
    #     },
    #     "filename": "/path/to/test.py"
    #   },
    #   ...
    # ]
    for check in json.loads(content):
        start = Position(
            line=max([int(check["location"]["row"]) - line_offset, 0]),
            character=int(check["location"]["column"]) - col_offset,
        )
        end = Position(
            line=max([int(check["end_location"]["row"]) - line_offset, 0]),
            character=int(check["end_location"]["column"]) - col_offset,
        )
        diagnostic = Diagnostic(
            range=Range(start=start, end=end),
            message=check.get("message"),
            severity=_get_severity(check["code"], check.get("type", "Error")),
            code=check["code"],
            source=TOOL_DISPLAY,
            data=check.get("fix"),
            tags=(
                [DiagnosticTag.Unnecessary]
                if check["code"]
                in {
                    "F401",  # `module` imported but unused
                    "F841",  # local variable `name` is assigned to but never used
                }
                else None
            ),
        )
        diagnostics.append(diagnostic)

    return diagnostics


def _get_severity(*_codes: list[str]) -> DiagnosticSeverity:
    return DiagnosticSeverity.Warning


NOQA_REGEX = re.compile(r"(?i:# noqa)(?::\s?(?P<codes>([A-Z]+[0-9]+(?:[,\s]+)?)+))?")
CODE_REGEX = re.compile(r"[A-Z]{1,3}[0-9]{3}")


@LSP_SERVER.feature(TEXT_DOCUMENT_HOVER)
def hover(params: HoverParams) -> Hover | None:
    """LSP handler for textDocument/hover request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
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
            result = _run_subcommand_on_document(document, ["--explain", code])
            if result.stdout:
                return Hover(
                    contents=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=result.stdout.strip(),
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


class Fix(TypedDict):
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
            f"{CodeActionKind.SourceFixAll}.ruff",
            f"{CodeActionKind.SourceOrganizeImports}.ruff",
        ],
        resolve_provider=True,
    ),
)
def code_action(params: CodeActionParams) -> list[CodeAction] | None:
    """LSP handler for textDocument/codeAction request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)

    # Deep copy, to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(document))

    if utils.is_stdlib_file(document.path):
        # Don't format standard library files.
        # Publishing empty diagnostics clears the entry.
        return None

    if settings["organizeImports"]:
        # Generate the "Ruff: Organize Imports" edit
        for kind in (
            CodeActionKind.SourceOrganizeImports,
            f"{CodeActionKind.SourceOrganizeImports}.ruff",
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                results = _formatting_helper(document, select="I001")
                if results is not None:
                    return [
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, results),
                            diagnostics=[],
                        )
                    ]
                else:
                    return []

    if settings["fixAll"]:
        # Generate the "Ruff: Fix All" edit.
        for kind in (
            CodeActionKind.SourceFixAll,
            f"{CodeActionKind.SourceFixAll}.ruff",
        ):
            if (
                params.context.only
                and len(params.context.only) == 1
                and kind in params.context.only
            ):
                results = _formatting_helper(document)
                if results is not None:
                    return [
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=kind,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, results),
                            diagnostics=[
                                diagnostic
                                for diagnostic in params.context.diagnostics
                                if diagnostic.source == "Ruff"
                                and diagnostic.data is not None
                            ],
                        ),
                    ]
                else:
                    return []

    actions: list[CodeAction] = []

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
                results = _formatting_helper(document, select="I001")
                if results is not None:
                    actions.append(
                        CodeAction(
                            title="Ruff: Organize Imports",
                            kind=CodeActionKind.SourceOrganizeImports,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, results),
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
                results = _formatting_helper(document)
                if results is not None:
                    actions.append(
                        CodeAction(
                            title="Ruff: Fix All",
                            kind=CodeActionKind.SourceFixAll,
                            data=params.text_document.uri,
                            edit=_create_workspace_edits(document, results),
                            diagnostics=[
                                diagnostic
                                for diagnostic in params.context.diagnostics
                                if diagnostic.source == "Ruff"
                                and diagnostic.data is not None
                            ],
                        ),
                    )

    # Add "Ruff: Autofix" for every fixable diagnostic.
    if not params.context.only or CodeActionKind.QuickFix in params.context.only:
        for diagnostic in params.context.diagnostics:
            if diagnostic.source == "Ruff":
                if diagnostic.data is not None:
                    actions.append(
                        CodeAction(
                            title=(
                                f"Ruff: Fix {diagnostic.code}"
                                if diagnostic.code
                                else "Ruff: Fix"
                            ),
                            kind=CodeActionKind.QuickFix,
                            data=params.text_document.uri,
                            edit=_create_workspace_edit(
                                document, cast(Fix, diagnostic.data)
                            ),
                            diagnostics=[diagnostic],
                        ),
                    )

    return actions if actions else None


@LSP_SERVER.feature(CODE_ACTION_RESOLVE)
def resolve_code_action(params: CodeAction) -> CodeAction:
    """LSP handler for codeAction/resolve request."""
    document = LSP_SERVER.workspace.get_document(cast(str, params.data))

    # Deep copy, to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(document))

    if settings["organizeImports"] and params.kind in (
        CodeActionKind.SourceOrganizeImports,
        f"{CodeActionKind.SourceOrganizeImports}.ruff",
    ):
        # Generate the "Ruff: Organize Imports" edit
        params.edit = _create_workspace_edits(
            document, _formatting_helper(document, select="I001") or []
        )
    elif settings["fixAll"] and params.kind in (
        CodeActionKind.SourceFixAll,
        f"{CodeActionKind.SourceFixAll}.ruff",
    ):
        # Generate the "Ruff: Fix All" edit.
        params.edit = _create_workspace_edits(
            document, _formatting_helper(document) or []
        )

    return params


@LSP_SERVER.command("ruff.applyAutofix")
def apply_autofix(arguments: tuple[TextDocument]):
    uri = arguments[0]["uri"]
    text_document = LSP_SERVER.workspace.get_document(uri)
    LSP_SERVER.apply_edit(
        _create_workspace_edits(text_document, _formatting_helper(text_document) or []),
        "Ruff: Fix all auto-fixable problems",
    )


def _formatting_helper(
    document: workspace.Document, *, select: str | None = None
) -> list[TextEdit] | None:
    result = _run_tool_on_document(
        document,
        use_stdin=True,
        extra_args=["--fix", "--select", select] if select else ["--fix"],
    )
    if result is None:
        return []

    if result.stdout:
        new_source = _match_line_endings(document, result.stdout)

        # Skip last line ending in a notebook cell.
        if document.uri.startswith("vscode-notebook-cell"):
            if new_source.endswith("\r\n"):
                new_source = new_source[:-2]
            elif new_source.endswith("\n"):
                new_source = new_source[:-1]

        if new_source != document.source:
            return [
                TextEdit(
                    range=Range(
                        start=Position(line=0, character=0),
                        end=Position(line=len(document.lines), character=0),
                    ),
                    new_text=new_source,
                )
            ]
    return None


def _create_workspace_edits(
    document: workspace.Document,
    results: Sequence[TextEdit | AnnotatedTextEdit],
) -> WorkspaceEdit:
    return WorkspaceEdit(
        document_changes=[
            TextDocumentEdit(
                text_document=OptionalVersionedTextDocumentIdentifier(
                    uri=document.uri,
                    version=0 if document.version is None else document.version,
                ),
                edits=list(results),
            )
        ],
    )


def _create_workspace_edit(document: workspace.Document, fix: Fix) -> WorkspaceEdit:
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
                                line=fix["location"]["row"] - 1,
                                character=fix["location"]["column"],
                            ),
                            end=Position(
                                line=fix["end_location"]["row"] - 1,
                                character=fix["end_location"]["column"],
                            ),
                        ),
                        new_text=fix["content"],
                    )
                ],
            )
        ],
    )


def _get_line_endings(lines: list[str]) -> str | None:
    """Returns line endings used in the text."""
    try:
        if lines[0][-2:] == "\r\n":
            return "\r\n"
        return "\n"
    except Exception:
        return None


def _match_line_endings(document: workspace.Document, text: str) -> str:
    """Ensures that the edited text line endings matches the document line endings."""
    expected = _get_line_endings(document.source.splitlines(keepends=True))
    actual = _get_line_endings(text.splitlines(keepends=True))
    if actual == expected or actual is None or expected is None:
        return text
    return text.replace(actual, expected)


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
    user_settings = (params.initialization_options or {}).get(  # type: ignore
        "settings",
    )
    if isinstance(user_settings, dict):
        # In Sublime Text, Neovim, and probably others, we're passed a single
        # `settings`, which we'll treat as defaults for any future files.
        USER_DEFAULTS.update(user_settings)
        settings = [user_settings]
    elif isinstance(user_settings, list):
        # In VS Code, we're passed a list of `settings`, one for each workspace folder.
        # It doesn't really make sense to save these defaults.
        settings = user_settings
    else:
        settings = []

    _update_workspace_settings(settings)

    if isinstance(LSP_SERVER.lsp, protocol.LanguageServerProtocol):
        if any(setting["logLevel"] == "debug" for setting in settings):
            LSP_SERVER.lsp.trace = TraceValues.Verbose
        elif any(
            setting["logLevel"] in ["error", "warn", "info"] for setting in settings
        ):
            LSP_SERVER.lsp.trace = TraceValues.Messages
        else:
            LSP_SERVER.lsp.trace = TraceValues.Off


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


def _default_settings() -> dict[str, Any]:
    return {
        "logLevel": USER_DEFAULTS.get("logLevel", "error"),
        "args": USER_DEFAULTS.get("args", []),
        "path": USER_DEFAULTS.get("path", []),
        "interpreter": USER_DEFAULTS.get("interpreter", [sys.executable]),
        "importStrategy": USER_DEFAULTS.get("importStrategy", "fromEnvironment"),
        "showNotifications": USER_DEFAULTS.get("showNotifications", "off"),
        "organizeImports": USER_DEFAULTS.get("organizeImports", True),
        "fixAll": USER_DEFAULTS.get("fixAll", True),
    }


def _update_workspace_settings(settings: list[dict[str, Any]]) -> None:
    if not settings:
        workspace_path = os.getcwd()
        WORKSPACE_SETTINGS[workspace_path] = {
            **_default_settings(),
            "workspaceFS": workspace_path,
            "workspace": uris.from_fs_path(workspace_path),
        }
        return

    for setting in settings:
        if "workspace" in setting:
            workspace_path = uris.to_fs_path(setting["workspace"])
            WORKSPACE_SETTINGS[workspace_path] = {
                **_default_settings(),
                **setting,
                "workspaceFS": workspace_path,
                "workspace": setting["workspace"],
            }
        else:
            workspace_path = os.getcwd()
            WORKSPACE_SETTINGS[workspace_path] = {
                **_default_settings(),
                **setting,
                "workspaceFS": workspace_path,
                "workspace": uris.from_fs_path(workspace_path),
            }


def _get_document_key(document: workspace.Document) -> str | None:
    document_workspace = pathlib.Path(document.path)
    workspaces = {s["workspaceFS"] for s in WORKSPACE_SETTINGS.values()}

    while document_workspace != document_workspace.parent:
        if str(document_workspace) in workspaces:
            return str(document_workspace)
        document_workspace = document_workspace.parent
    return None


def _get_settings_by_document(document: workspace.Document | None) -> dict[str, Any]:
    if document is None or document.path is None:
        return list(WORKSPACE_SETTINGS.values())[0]

    key = _get_document_key(document)
    if key is None:
        workspace_path = os.fspath(pathlib.Path(document.path).parent)
        return {
            **_default_settings(),
            "workspaceFS": workspace_path,
            "workspace": uris.from_fs_path(workspace_path),
        }

    return WORKSPACE_SETTINGS[str(key)]


###
# Internal execution APIs.
###


def _executable_path(settings: dict[str, Any]) -> str:
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
        if bundle and not os.path.exists(path):
            log_to_output(
                f"External interpreter executable ({path}) not found; "
                f"falling back to bundled executable: {bundle}"
            )
            path = bundle
        else:
            log_to_output(f"Using external interpreter executable: {path}")
        return path

    # If the interpreter is same as the interpreter running this process, get the
    # script path directly.
    path = os.path.join(sysconfig.get_path("scripts"), TOOL_MODULE)
    if bundle and not os.path.exists(path):
        log_to_output(
            f"Interpreter executable ({path}) not found; "
            f"falling back to bundled executable: {bundle}"
        )
        path = bundle
    else:
        log_to_output(f"Using interpreter executable: {path}")
    return path


def _run_tool_on_document(
    document: workspace.Document,
    use_stdin: bool = False,
    extra_args: Sequence[str] = [],
) -> utils.RunResult | None:
    """Runs tool on the given document.

    If `use_stdin` is `True` then contents of the document is passed to the tool via
    stdin.
    """
    if str(document.uri).startswith("vscode-notebook-cell"):
        # Skip notebook cells
        return None

    if utils.is_stdlib_file(document.path):
        log_warning(f"Skipping standard library file: {document.path}")
        return None

    # Deep copy, to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(document))

    argv: list[str] = (
        [_executable_path(settings)] + TOOL_ARGS + settings["args"] + list(extra_args)
    )
    if use_stdin:
        argv += ["--stdin-filename", document.path]
    else:
        argv += [document.path]

    log_to_output(f"Running Ruff with: {argv}")
    result: utils.RunResult = utils.run_path(
        argv=argv,
        use_stdin=use_stdin,
        cwd=settings["workspaceFS"],
        source=document.source.replace("\r\n", "\n"),
    )
    if result.stderr:
        log_to_output(result.stderr)

    return result


def _run_subcommand_on_document(
    document: workspace.Document,
    args: Sequence[str],
) -> utils.RunResult:
    """Runs the tool subcommand on the given document."""
    # Deep copy, to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(document))

    argv: list[str] = [_executable_path(settings)] + list(args)

    log_to_output(f"Running Ruff with: {argv}")
    result: utils.RunResult = utils.run_path(
        argv=argv,
        use_stdin=False,
        cwd=settings["workspaceFS"],
    )
    if result.stderr:
        log_to_output(result.stderr)

    return result


###
# Logging.
###


def log_to_output(message: str, msg_type: MessageType = MessageType.Log) -> None:
    LSP_SERVER.show_message_log(message, msg_type)


def log_error(message: str) -> None:
    LSP_SERVER.show_message_log(message, MessageType.Error)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in [
        "onError",
        "onWarning",
        "always",
    ]:
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
