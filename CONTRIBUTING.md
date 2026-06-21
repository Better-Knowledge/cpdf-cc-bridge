# Contribuindo com o bk-claude-bridge

Obrigado por contribuir! Este projeto é a biblioteca `tgbridge` (import) distribuída
como `bk-claude-bridge` (PyPI).

## Ambiente

Usamos [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev          # instala deps + pytest
uv run pytest                # roda a suíte
```

Layout `src/`:

```
src/tgbridge/        # o pacote (import tgbridge)
  templates/         # package data: scaffold de agentes + whisper
tests/               # pytest
```

## Padrões

- Python 3.11+. Mantenha o estilo e a densidade de comentários do código existente.
- Toda mudança de comportamento deve vir com teste em `tests/`.
- Sem dependências novas sem necessidade clara; voz é opcional (extras `voice-openai`/`voice-local`).
- O receiver de hooks é **localhost-only** e autenticado por bearer — não relaxe isso.

## Commits e versões

- SemVer. Atualize o `CHANGELOG.md` (seção *Não lançado*).
- Release = bump da `version` no `pyproject.toml` + tag `vX.Y.Z` (o CI publica — ver `.github/workflows`).

## Pull Requests

1. Crie uma branch a partir de `main`.
2. `uv run pytest` verde.
3. Descreva a mudança e o porquê; referencie issues.
