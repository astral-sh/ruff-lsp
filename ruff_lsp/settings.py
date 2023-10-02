from __future__ import annotations

from typing_extensions import Literal, TypedDict

Run = Literal["onSave", "onType"]


class UserSettings(TypedDict, total=False):
    """Settings for the Ruff Language Server."""

    logLevel: Literal["error", "warning", "info", "debug"]
    """The log level for the Ruff server. Defaults to "error"."""

    path: list[str]
    """Path to a custom `ruff` executable."""

    interpreter: list[str]
    """Path to a Python interpreter to use to run the linter server."""

    importStrategy: Literal["fromEnvironment", "useBundled"]
    """Strategy for loading the `ruff` executable."""

    codeAction: CodeActions
    """Settings for the `source.codeAction` capability."""

    organizeImports: bool
    """Whether to register Ruff as capable of handling `source.organizeImports`."""

    fixAll: bool
    """Whether to register Ruff as capable of handling `source.fixAll`."""

    lint: Lint
    """Settings specific to lint capabilities."""

    format: Format
    """Settings specific to format capabilities."""

    # Deprecated: use `lint.args` instead.
    args: list[str]
    """Additional command-line arguments to pass to `ruff check`."""

    # Deprecated: use `lint.run` instead.
    run: Run
    """Run Ruff on every keystroke (`onType`) or on save (`onSave`)."""


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


class Lint(TypedDict, total=False):
    args: list[str]
    """Additional command-line arguments to pass to `ruff check`."""

    run: Run
    """Run Ruff on every keystroke (`onType`) or on save (`onSave`)."""


class Format(TypedDict, total=False):
    args: list[str]
    """Additional command-line arguments to pass to `ruff format`."""


def lint_args(settings: UserSettings) -> list[str]:
    """Get the `lint.args` setting from the user settings."""
    if "lint" in settings and "args" in settings["lint"]:
        return settings["lint"]["args"]
    elif "args" in settings:
        return settings["args"]
    else:
        return []


def lint_run(settings: UserSettings) -> Run:
    """Get the `lint.run` setting from the user settings."""
    if "lint" in settings and "run" in settings["lint"]:
        return settings["lint"]["run"]
    elif "run" in settings:
        return settings["run"]
    else:
        return "onType"
