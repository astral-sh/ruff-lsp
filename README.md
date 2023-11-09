# ruff-lsp

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![image](https://img.shields.io/pypi/v/ruff-lsp.svg)](https://pypi.python.org/pypi/ruff-lsp)
[![image](https://img.shields.io/pypi/l/ruff-lsp.svg)](https://pypi.python.org/pypi/ruff-lsp)
[![image](https://img.shields.io/pypi/pyversions/ruff-lsp.svg)](https://pypi.python.org/pypi/ruff-lsp)
[![Actions status](https://github.com/astral-sh/ruff-lsp/workflows/CI/badge.svg)](https://github.com/astral-sh/ruff-lsp/actions)

A [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) implementation for
[Ruff](https://github.com/astral-sh/ruff), an extremely fast Python linter and code formatter,
written in Rust.

Ruff can be used to replace Flake8 (plus dozens of plugins), Black, isort, pyupgrade, and more,
all while executing tens or hundreds of times faster than any individual tool.

`ruff-lsp` enables Ruff to be used in any editor that supports the LSP, including [Neovim](#example-neovim),
[Sublime Text](#example-sublime-text), Emacs and more. For Visual Studio Code, check out the
[Ruff VS Code extension](https://github.com/astral-sh/ruff-vscode).

`ruff-lsp` supports surfacing Ruff diagnostics and providing Code Actions to fix them, but is
intended to be used alongside another Python LSP in order to support features like navigation and
autocompletion.

## Highlights

### "Quick Fix" actions for auto-fixable violations (like unused imports)

![Using the "Quick Fix" action to fix a violation](https://user-images.githubusercontent.com/1309177/205176932-44cfc03a-120f-4bad-b710-612bdd7765d6.gif)

### "Fix all": automatically fix all auto-fixable violations

![Using the "Fix all" action to fix all violations](https://user-images.githubusercontent.com/1309177/205175763-cf34871d-5c05-4abf-9916-440afc82dbf8.gif)

### "Format Document": Black-compatible code formatting

![Using the "Format Document" action to format Python source code](https://github.com/astral-sh/ruff-lsp/assets/1309177/51c27215-87fb-490c-b1d6-ee81ab4171a1)

### "Organize Imports": `isort`-compatible import sorting

![Using the "Organize Imports" action to sort and deduplicate Python imports](https://user-images.githubusercontent.com/1309177/205175987-82e23e21-14bb-467d-9ef0-027f24b75865.gif)

## Installation

`ruff-lsp` is available as [`ruff-lsp`](https://pypi.org/project/ruff-lsp/) on PyPI:

```shell
pip install ruff-lsp
```

### Community packages

[An Alpine Linux package](https://pkgs.alpinelinux.org/packages?name=ruff-lsp)
is available in the `testing` repository:

    apk add ruff-lsp

[An Arch Linux package](https://archlinux.org/packages/extra/any/ruff-lsp/) is
available in the `Extra` repository:

    pacman -S ruff-lsp

## Setup

Once installed, `ruff-lsp` can be used with any editor that supports the Language Server Protocol,
including Neovim, Emacs, Sublime Text, and more.

### Example: Neovim

For example, to use `ruff-lsp` with Neovim, install `ruff-lsp` from PyPI along with
[`nvim-lspconfig`](https://github.com/neovim/nvim-lspconfig). Then, add something like the following
to your `init.lua`:

```lua
-- See: https://github.com/neovim/nvim-lspconfig/tree/54eb2a070a4f389b1be0f98070f81d23e2b1a715#suggested-configuration
local opts = { noremap=true, silent=true }
vim.keymap.set('n', '<space>e', vim.diagnostic.open_float, opts)
vim.keymap.set('n', '[d', vim.diagnostic.goto_prev, opts)
vim.keymap.set('n', ']d', vim.diagnostic.goto_next, opts)
vim.keymap.set('n', '<space>q', vim.diagnostic.setloclist, opts)

-- Use an on_attach function to only map the following keys
-- after the language server attaches to the current buffer
local on_attach = function(client, bufnr)
  -- Enable completion triggered by <c-x><c-o>
  vim.api.nvim_buf_set_option(bufnr, 'omnifunc', 'v:lua.vim.lsp.omnifunc')

  -- Mappings.
  -- See `:help vim.lsp.*` for documentation on any of the below functions
  local bufopts = { noremap=true, silent=true, buffer=bufnr }
  vim.keymap.set('n', 'gD', vim.lsp.buf.declaration, bufopts)
  vim.keymap.set('n', 'gd', vim.lsp.buf.definition, bufopts)
  vim.keymap.set('n', 'K', vim.lsp.buf.hover, bufopts)
  vim.keymap.set('n', 'gi', vim.lsp.buf.implementation, bufopts)
  vim.keymap.set('n', '<C-k>', vim.lsp.buf.signature_help, bufopts)
  vim.keymap.set('n', '<space>wa', vim.lsp.buf.add_workspace_folder, bufopts)
  vim.keymap.set('n', '<space>wr', vim.lsp.buf.remove_workspace_folder, bufopts)
  vim.keymap.set('n', '<space>wl', function()
    print(vim.inspect(vim.lsp.buf.list_workspace_folders()))
  end, bufopts)
  vim.keymap.set('n', '<space>D', vim.lsp.buf.type_definition, bufopts)
  vim.keymap.set('n', '<space>rn', vim.lsp.buf.rename, bufopts)
  vim.keymap.set('n', '<space>ca', vim.lsp.buf.code_action, bufopts)
  vim.keymap.set('n', 'gr', vim.lsp.buf.references, bufopts)
  vim.keymap.set('n', '<space>f', function() vim.lsp.buf.format { async = true } end, bufopts)
end

-- Configure `ruff-lsp`.
-- See: https://github.com/neovim/nvim-lspconfig/blob/master/doc/server_configurations.md#ruff_lsp
-- For the default config, along with instructions on how to customize the settings
require('lspconfig').ruff_lsp.setup {
  on_attach = on_attach,
  init_options = {
    settings = {
      -- Any extra CLI arguments for `ruff` go here.
      args = {},
    }
  }
}
```

Upon successful installation, you should see Ruff's diagnostics surfaced directly in your editor:

![Code Actions available in Neovim](https://user-images.githubusercontent.com/1309177/208278707-25fa37e4-079d-4597-ad35-b95dba066960.png)

Note that if you're using Ruff alongside another LSP (like Pyright), you may want to defer to that
LSP for certain capabilities, like `textDocument/hover`:

```lua
local on_attach = function(client, bufnr)
  -- Disable hover in favor of Pyright
  client.server_capabilities.hoverProvider = false
end

require('lspconfig').ruff_lsp.setup {
  on_attach = on_attach,
}
```

Ruff also integrates with [`coc.nvim`](https://github.com/neoclide/coc.nvim/wiki/Language-servers#using-ruff-lsp):

```json
"languageserver": {
  "ruff-lsp": {
    "command": "ruff-lsp",
    "filetypes": ["python"]
  }
}
```

### Example: Sublime Text

To use `ruff-lsp` with Sublime Text, install Sublime Text's [LSP](https://github.com/sublimelsp/LSP)
and [LSP-ruff](https://github.com/sublimelsp/LSP-ruff) package.

Upon successful installation, you should see errors surfaced directly in your editor:

![Code Actions available in Sublime Text](https://user-images.githubusercontent.com/1309177/208266375-331ad8e5-8ac1-4735-bca8-07734eb38536.png)

### Example: Helix

To use `ruff-lsp` with [Helix](https://helix-editor.com/), add something like the following to
`~/.config/helix/languages.toml`:

```toml
[[language]]
name = "python"
scope = "source.python"
language-server = { command = "ruff-lsp" }
config = { settings = { args = [] } }
```

Upon successful installation, you should see errors surfaced directly in your editor:

![](https://user-images.githubusercontent.com/1309177/209262106-71e34f8d-73cc-4889-89f7-3f54a4481c52.png)

Future versions of Helix support the use of multiple language servers. The following configuration
would enable the use of `ruff-lsp` alongside a language server like `pyright`:

```toml
[[language]]
name = "python"
roots = ["pyproject.toml"]
language-servers = ["pyright", "ruff"]

[language-server.pyright]
command = "pyright-langserver"
args = ["--stdio"]

[language-server.ruff]
command = "ruff-lsp"
config = { settings = { run = "onSave" } }
```

### Example: Lapce

To use `ruff-lsp` with [Lapce](https://lapce.dev/), install the [`lapce-ruff-lsp`](https://plugins.lapce.dev/plugins/abreumatheus/lapce-ruff-lsp)
plugin (which wraps `ruff-lsp`) from the Lapce plugins panel.

Upon successful installation, you should see errors surfaced directly in your editor:

![](https://user-images.githubusercontent.com/1309177/209418462-ae106d1f-dbc3-4d53-bae2-66bfccc3e841.png)

### Example: Kate

To use `ruff-lsp` with [Kate](https://kate-editor.org/), add something like the following to
the LSP client's `settings.json`:

```json
{
  "servers": {
    "python": {
      "command": ["ruff-lsp"],
      "url": "https://github.com/astral-sh/ruff-lsp",
      "highlightingModeRegex": "^Python$"
    }
  }
}
```

## Fix safety

Ruff's automatic fixes are labeled as "safe" and "unsafe". By default, the "Fix all" action will not apply unsafe
fixes. However, unsafe fixes can be applied manually with the "Quick fix" action. Application of unsafe fixes when
using "Fix all" can be enabled by setting `unsafe-fixes = true` in your Ruff configuration file or adding
`--unsafe-fixes` flag to the "Lint args" setting.

See the [Ruff fix docs](https://docs.astral.sh/ruff/configuration/#fix-safety) for more details on how fix
safety works.

## Jupyter Notebook Support

`ruff-lsp` has support for Jupyter Notebooks via the [Notebook Document Synchronization] capabilities of the Language
Server Protocol which were added in 3.17. This allows `ruff-lsp` to provide full support for all of the existing capabilities
available for Python files in Jupyter Notebooks, including diagnostics, code actions, and formatting.

This requires clients, such as Visual Studio Code, to support the notebook-related capabilities. In addition to the editor support,
it also requires Ruff version `v0.1.3` or later.

[Notebook Document Synchronization]: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#notebookDocument_synchronization

## Settings

The exact mechanism by which settings will be passed to `ruff-lsp` will vary by editor. However,
the following settings are supported:

| Settings                             | Default  | Description                                                                                                                                                                                                                                                        |
|--------------------------------------| -------- |--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| lint.args                            | `[]`     | Additional command-line arguments to pass to `ruff check`, e.g., `"args": ["--config=/path/to/pyproject.toml"]`. Supports a subset of Ruff's command-line arguments, ignoring those that are required to operate the LSP, like `--force-exclude` and `--verbose`.  |
| lint.run                             | `onType` | Run Ruff on every keystroke (`onType`) or on save (`onSave`).                                                                                                                                                                                                      |
| format.args                          | `[]`     | Additional command-line arguments to pass to `ruff format`, e.g., `"args": ["--config=/path/to/pyproject.toml"]`. Supports a subset of Ruff's command-line arguments, ignoring those that are required to operate the LSP, like `--force-exclude` and `--verbose`. |
| path                                 | `[]`     | Path to a custom `ruff` executable, e.g., `["/path/to/ruff"]`.                                                                                                                                                                                                     |
| interpreter                          | `[]`     | Path to a Python interpreter to use to run the linter server.                                                                                                                                                                                                      |
| organizeImports                      | `true`   | Whether to register Ruff as capable of handling `source.organizeImports` actions.                                                                                                                                                                                  |
| fixAll                               | `true`   | Whether to register Ruff as capable of handling `source.fixAll` actions.                                                                                                                                                                                           |
| codeAction.fixViolation.enable       | `true`   | Whether to display Quick Fix actions to autofix violations.                                                                                                                                                                                                        |
| logLevel                             | `error`  | Sets the tracing level for the extension: `error`, `warn`, `info`, or `debug`.                                                                                                                                                                                     |
| codeAction.disableRuleComment.enable | `true`   | Whether to display Quick Fix actions to disable rules via `noqa` suppression comments.                                                                                                                                                                             |

## Development

- Install [`just`](https://github.com/casey/just), or see the `justfile` for corresponding commands.
- Create and activate a virtual environment (e.g., `python -m venv .venv && source .venv/bin/activate`).
- Install development dependencies (`just install`). To run the `test_format.py` test, you need to install a custom ruff build with `--features format`, e.g. `maturin develop --features format -m ../ruff/crates/ruff_cli/Cargo.toml`.
- To automatically format the codebase, run: `just fmt`.
- To run lint and type checks, run: `just check`.
- To run tests, run: `just test`. This is just a wrapper around pytest, which you can use as usual.

## License

MIT

<div align="center">
  <a target="_blank" href="https://astral.sh" style="background:none">
    <img src="https://raw.githubusercontent.com/astral-sh/ruff/main/assets/svg/Astral.svg">
  </a>
</div>
