"""Test for linting over LSP."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from threading import Event

from packaging.version import Version
from typing_extensions import Self

from tests.client import defaults, session, utils

# Increase this if you want to attach a debugger
TIMEOUT_SECONDS = 10

CONTENTS = """import sys

print(x)
"""

VERSION_REQUIREMENT_ASTRAL_DOCS = Version("0.0.291")
VERSION_REQUIREMENT_APPLICABILITY_RENAME = Version("0.1.0")


@dataclass(frozen=True)
class Applicability:
    safe: str
    unsafe: str
    display: str

    @classmethod
    def from_ruff_version(cls, ruff_version: Version) -> Self:
        if ruff_version >= VERSION_REQUIREMENT_APPLICABILITY_RENAME:
            return cls(safe="safe", unsafe="unsafe", display="display")
        else:
            return cls(safe="Automatic", unsafe="Suggested", display="Manual")


class TestServer:
    maxDiff = None

    def test_linting_example(self, ruff_version: Version) -> None:
        expected_docs_url = (
            "https://docs.astral.sh/ruff/"
            if ruff_version >= VERSION_REQUIREMENT_ASTRAL_DOCS
            else "https://beta.ruff.rs/docs/"
        )
        applicability = Applicability.from_ruff_version(ruff_version)

        with tempfile.NamedTemporaryFile(suffix=".py") as fp:
            fp.write(CONTENTS.encode())
            fp.flush()
            uri = utils.as_uri(fp.name)

            actual = []
            with session.LspSession(cwd=os.getcwd(), module="ruff_lsp") as ls_session:
                ls_session.initialize(defaults.VSCODE_DEFAULT_INITIALIZE)

                done = Event()

                def _handler(params):
                    nonlocal actual
                    actual = params
                    done.set()

                ls_session.set_notification_callback(
                    session.PUBLISH_DIAGNOSTICS, _handler
                )

                ls_session.notify_did_open(
                    {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "python",
                            "version": 1,
                            "text": CONTENTS,
                        }
                    }
                )

                # Wait to receive all notifications.
                done.wait(TIMEOUT_SECONDS)

                expected = {
                    "diagnostics": [
                        {
                            "code": "F401",
                            "codeDescription": {
                                "href": expected_docs_url + "rules/unused-import"
                            },
                            "data": {
                                "fix": {
                                    "applicability": applicability.safe,
                                    "edits": [
                                        {
                                            "content": "",
                                            "end_location": {"column": 0, "row": 2},
                                            "location": {"column": 0, "row": 1},
                                        }
                                    ],
                                    "message": "Remove unused import: `sys`",
                                },
                                "noqa_row": 1,
                                "cell": None,
                            },
                            "message": "`sys` imported but unused",
                            "range": {
                                "end": {"character": 10, "line": 0},
                                "start": {"character": 7, "line": 0},
                            },
                            "severity": 2,
                            "source": "Ruff",
                            "tags": [1],
                        },
                        {
                            "code": "F821",
                            "codeDescription": {
                                "href": expected_docs_url + "rules/undefined-name"
                            },
                            "data": {"fix": None, "noqa_row": 3, "cell": None},
                            "message": "Undefined name `x`",
                            "range": {
                                "end": {"character": 7, "line": 2},
                                "start": {"character": 6, "line": 2},
                            },
                            "severity": 1,
                            "source": "Ruff",
                        },
                    ],
                    "uri": uri,
                }
            assert expected == actual

    def test_no_initialization_options(self, ruff_version: Version) -> None:
        expected_docs_url = (
            "https://docs.astral.sh/ruff/"
            if ruff_version >= VERSION_REQUIREMENT_ASTRAL_DOCS
            else "https://beta.ruff.rs/docs/"
        )
        applicability = Applicability.from_ruff_version(ruff_version)

        with tempfile.NamedTemporaryFile(suffix=".py") as fp:
            fp.write(CONTENTS.encode())
            fp.flush()
            uri = utils.as_uri(fp.name)

            actual = []
            with session.LspSession(cwd=os.getcwd(), module="ruff_lsp") as ls_session:
                ls_session.initialize(
                    {
                        **defaults.VSCODE_DEFAULT_INITIALIZE,
                        "initializationOptions": None,
                    }
                )

                done = Event()

                def _handler(params):
                    nonlocal actual
                    actual = params
                    done.set()

                ls_session.set_notification_callback(
                    session.PUBLISH_DIAGNOSTICS, _handler
                )

                ls_session.notify_did_open(
                    {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "python",
                            "version": 1,
                            "text": CONTENTS,
                        }
                    }
                )

                # Wait to receive all notifications.
                done.wait(TIMEOUT_SECONDS)

                expected = {
                    "diagnostics": [
                        {
                            "code": "F401",
                            "codeDescription": {
                                "href": expected_docs_url + "rules/unused-import"
                            },
                            "data": {
                                "fix": {
                                    "applicability": applicability.safe,
                                    "edits": [
                                        {
                                            "content": "",
                                            "end_location": {"column": 0, "row": 2},
                                            "location": {"column": 0, "row": 1},
                                        }
                                    ],
                                    "message": "Remove unused import: `sys`",
                                },
                                "noqa_row": 1,
                                "cell": None,
                            },
                            "message": "`sys` imported but unused",
                            "range": {
                                "end": {"character": 10, "line": 0},
                                "start": {"character": 7, "line": 0},
                            },
                            "severity": 2,
                            "source": "Ruff",
                            "tags": [1],
                        },
                        {
                            "code": "F821",
                            "codeDescription": {
                                "href": expected_docs_url + "rules/undefined-name"
                            },
                            "data": {"fix": None, "noqa_row": 3, "cell": None},
                            "message": "Undefined name `x`",
                            "range": {
                                "end": {"character": 7, "line": 2},
                                "start": {"character": 6, "line": 2},
                            },
                            "severity": 1,
                            "source": "Ruff",
                        },
                    ],
                    "uri": uri,
                }
            assert expected == actual
