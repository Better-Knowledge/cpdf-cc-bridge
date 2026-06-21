# Projects — Master Index

Ponto de entrada da hierarquia de projetos. Navegue por categoria; cada categoria tem seu
próprio `INDEX.md` com uma linha por projeto. **Status mora aqui** (no frontmatter de cada
`README.md`), não na memória. Esta tabela é **regenerável** (`scripts/regen-indexes.sh`).

| Categoria | Itens | Resumo |
|-----------|-------|--------|
| [[leads/INDEX]] | 0 | Pipeline comercial (por estágio) |
<!-- Adicione categorias conforme criar, ex.:
| [[dev/INDEX]] | 0 | Projetos de desenvolvimento |
| [[consulting/INDEX]] | 0 | Consultorias |
-->

## Convenções
- Categoria = pasta (`dev/`, `consulting/`, `education/`, …). Crie a partir do
  `_CATEGORY_INDEX.md`.
- Projeto = `projects/<categoria>/<CODE>-<slug>/README.md`. `CODE` = prefixo + número
  (ex.: `D01`, `C02`); `slug` = kebab-lowercase. Crie a partir do `_PROJECT_README.md`.
- Leads são flat em `leads/L<NN>-<slug>/`; o estágio vive no frontmatter (`stage:`).
