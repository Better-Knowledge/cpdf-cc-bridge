# Memory Index — Load me first

This is the **routing map** of my memory. Each row below is a topic with a one-line
description. In a session I read this index, then open **only** the topics the task needs —
never the whole memory. (Same idea as a skill registry: the description decides the load.)

## Load protocol
- **Every session:** this index + `daily/<today>.md`.
- **Main session:** + `daily/<yesterday>.md` + topics relevant to the task.
- **Group/shared:** skip any topic tagged `private: true`.
- **Cron/A2A:** this index + the single topic the job needs.

## Topics
<!-- Regenerável: `scripts/regen-indexes.sh` reescreve a tabela entre os marcadores a partir
     do frontmatter de topics/*.md. Mantenha os marcadores. -->
<!-- regen:topics:start -->
| Topic | Private | Description |
|-------|---------|-------------|
| _(nenhum ainda — crie o primeiro em `topics/<slug>.md` a partir de `topics/_TEMPLATE.md`)_ | | |
<!-- regen:topics:end -->

## Pointers
- **Projetos & leads:** status mora em `projects/` (não aqui) → ver `projects/INDEX.md`.
- **Logs crus:** `daily/YYYY-MM-DD.md`. **Resumos antigos:** `archive/`.
