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
local configs = require 'lspconfig.configs'
if not configs.ruff_lsp then
  configs.ruff_lsp = {
    default_config = {
    cmd = { "ruff-lsp" },
    filetypes = {'python'},
    root_dir = require('lspconfig').util.find_git_ancestor,
    settings = {
      ruff_lsp = {
        -- Any extra CLI arguments for `ruff` go here.
        args = {}
      }
    }
  }
}
end

require('lspconfig').ruff_lsp.setup {
  on_attach = on_attach,
}
```

Upon successful installation, you should see Ruff's diagnostics surfaced directly in your editor:

![Code Actions available in Neovim](https://user-images.githubusercontent.com/1309177/208278707-25fa37e4-079d-4597-ad35-b95dba066960.png)

### Example: Sublime Text

To use `ruff-lsp` with Sublime Text, install Sublime Text's [LSP](https://github.com/sublimelsp/LSP)
package, then add something like the following to `LSP.sublime-settings`:

```json
{
  "clients": {
    "python-lsp-server": {
      "command": ["ruff-lsp"],
      "enabled": true,
      "selector": "source.python"
    }
  }
}
```

Upon successful installation, you should see errors surfaced directly in your editor:

![](https://user-images.githubusercontent.com/1309177/208266375-331ad8e5-8ac1-4735-bca8-07734eb38536.png)

## Settings

The exact mechanism by which settings will be passed to `ruff-lsp` will vary by editor. However,
the following settings are supported:

| Settings         | Default | Description                                                                            |
|------------------|---------|----------------------------------------------------------------------------------------|
| args             | `[]`    | Custom arguments passed to `ruff`. E.g `"args": ["--config=/path/to/pyproject.toml"]`. |
| logLevel         | `error` | Sets the tracing level for the extension.                                              |
| path             | `[]`    | Setting to provide custom `ruff` executable. E.g. `["~/global_env/ruff"]`.             |
| interpreter      | `[]`    | Path to a Python interpreter to use to run the linter server.                          |
| showNotification | `off`   | Setting to control when a notification is shown.                                       |

## Development

`ruff-lsp` uses Poetry for environment management and packaging. To get started, clone the
repository, install Poetry, and run `poetry install`.

To automatically format the codebase, run: `make format`.

To run lint and type checks, run: `make check`.

## License

MIT
