set runtimepath^=~/.vim runtimepath+=~/.vim/after
let &packpath = &runtimepath
source ~/.vimrc

" lua <<EOF
" require'nvim-treesitter.configs'.setup {
"   ensure_installed = { "ruby", "javascript", "typescript", "html", "css", "json", "graphql", "python", "scss" }, -- Install languages manually to ensure support
"   sync_install = false, -- Install parsers synchronously (only applied to `ensure_installed`)
"   auto_install = true, -- Automatically install missing parsers when entering buffer
"   highlight = {
"     enable = true, -- Enable highlighting
"     additional_vim_regex_highlighting = { "ruby", "javascript", "typescript" }, -- Required for some features like indent
"   },
"   indent = {
"     enable = true, -- Enable Tree-sitter based indentation for these languages
"   }
" }
" EOF

" live-preview.nvim config removed - switched to markdown-preview.nvim
