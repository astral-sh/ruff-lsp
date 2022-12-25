# ruff-lsp

A [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) implementation for
[Ruff](https://github.com/charliermarsh/ruff), an extremely fast Python linter and code transformation
tool, written in Rust.

Enables Ruff to be used in any editor that supports the LSP, including [Neovim](#example-neovim),
[Sublime Text](#example-sublime-text), Emacs and more.

For Visual Studio Code, check out the [Ruff VS Code extension](https://github.com/charliermarsh/ruff-vscode).

## Highlights

### "Quick Fix" actions for auto-fixable violations (like unused imports)

![](https://user-images.githubusercontent.com/1309177/205176932-44cfc03a-120f-4bad-b710-612bdd7765d6.gif)

### "Fix all": automatically fix all auto-fixable violations

![](https://user-images.githubusercontent.com/1309177/205175763-cf34871d-5c05-4abf-9916-440afc82dbf8.gif)

### "Organize Imports": `isort`-compatible import sorting

![](https://user-images.githubusercontent.com/1309177/205175987-82e23e21-14bb-467d-9ef0-027f24b75865.gif)

## Installation and Usage

`ruff-lsp` is available as [`ruff-lsp`](https://pypi.org/project/ruff-lsp/) on PyPI:

```shell
pip install ruff-lsp
```

From there, `ruff-lsp` can be used with any editor that supports the Language Server Protocol,
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
}
```

Upon successful installation, you should see Ruff's diagnostics surfaced directly in your editor:

![Code Actions available in Neovim](https://user-images.githubusercontent.com/1309177/208278707-25fa37e4-079d-4597-ad35-b95dba066960.png)

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
package, then add something like the following to `LSP.sublime-settings`:

```json
{
  "clients": {
    "ruff-lsp": {
      "command": ["ruff-lsp"],
      "enabled": true,
      "selector": "source.python",
      "initializationOptions": {
        "settings": {
          "args": []
        }
      }
    }
  }
}
```

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

### Example: Lapce

To use `ruff-lsp` with [Lapce](https://lapce.dev/), install the [`lapce-ruff-lsp`](https://plugins.lapce.dev/plugins/abreumatheus/lapce-ruff-lsp)
plugin (which wraps `ruff-lsp`) from the Lapce plugins panel.

Upon successful installation, you should see errors surfaced directly in your editor:

![](https://user-images.githubusercontent.com/1309177/209418462-ae106d1f-dbc3-4d53-bae2-66bfccc3e841.png)

## Settings

The exact mechanism by which settings will be passed to `ruff-lsp` will vary by editor. However,
the following settings are supported:

| Settings         | Default | Description                                                                              |
|------------------|---------|------------------------------------------------------------------------------------------|
| args             | `[]`    | Custom arguments passed to `ruff`. E.g `"args": ["--config=/path/to/pyproject.toml"]`.   |
| logLevel         | `error` | Sets the tracing level for the extension.                                                |
| path             | `[]`    | Setting to provide custom `ruff` executables, to try in order. E.g. `["/path/to/ruff"]`. |
| interpreter      | `[]`    | Path to a Python interpreter to use to run the linter server.                            |
| showNotification | `off`   | Setting to control when a notification is shown.                                         |
| organizeImports  | `true`  | Whether to register Ruff as capable of handling `source.organizeImports` actions.        |
| fixAll           | `true`  | Whether to register Ruff as capable of handling `source.fixAll` actions.                 |

## Development

- Install [`just`](https://github.com/casey/just), or see the `justfile` for corresponding commands.
- Create and activate a virtual environment (e.g., `python -m venv .venv && source .venv/bin/activate`).
- Install development dependencies (`just install`).
- To automatically format the codebase, run: `just fmt`.
- To run lint and type checks, run: `just check`.
- To run tests, run: `just test`.

## License

MIT
