from __future__ import annotations

from typing_extensions import Literal, TypedDict


class UserSettings(TypedDict, total=False):
    """Settings for the Ruff Language Server."""

    logLevel: Literal["error", "warning", "info", "debug"]
    """The log level for the Ruff server. Defaults to "error"."""

    args: list[str]
    """Additional command-line arguments to pass to `ruff`."""

    path: list[str]
    """Path to a custom `ruff` executable."""

    interpreter: list[str]
    """Path to a Python interpreter to use to run the linter server."""

    importStrategy: Literal["fromEnvironment", "useBundled"]
    """Strategy for loading the `ruff` executable."""

    run: Literal["onSave", "onType"]
    """Run Ruff on every keystroke (`onType`) or on save (`onSave`)."""

    codeAction: CodeActions
    """Settings for the `source.codeAction` capability."""

    organizeImports: bool
    """Whether to register Ruff as capable of handling `source.organizeImports`."""

    fixAll: bool
    """Whether to register Ruff as capable of handling `source.fixAll`."""


class WorkspaceSettings(TypedDict, UserSettings):
    cwd: str | None
    """The current working directory for the workspace."""

    workspacePath: str
    """The path to the workspace."""

    workspace: str
    """The workspace name."""


class CodeActions(TypedDict, total=False):
    fixViolation: CodeAction
    """Code action to fix a violation."""

    disableRuleComment: CodeAction
    """Code action to disable the rule on the current line."""


class CodeAction(TypedDict, total=False):
    enable: bool
    """Whether to enable the code action."""
