# bk-claude-bridge

Bridge leve entre **Telegram** e uma sessão **interativa** de agente CLI (Claude Code)
rodando em **tmux** — operável por mensagens e áudio, com slash commands, agendamento
(cron) e monitoramento. Pensado para rodar em container na VPS, um agente por bot.

> Pacote Python `tgbridge` (import), distribuído como `bk-claude-bridge`.

## Documentação

- [docs/QUICKSTART.md](docs/QUICKSTART.md) — instalar e subir seu primeiro agente, passo a passo.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — como a bridge funciona por dentro (serviços, tmux, hooks, scaffolder, memória, A2A).
- [docs/SECURITY.md](docs/SECURITY.md) — modelo de segurança (gate, env-scrub das sessões efêmeras, A2A por-agente, permissões).
- [docs/diagram-prompt.md](docs/diagram-prompt.md) — prompts para gerar o diagrama de arquitetura.

## Como funciona

- **Entrada:** mensagem do Telegram → `tmux send-keys` na sessão do agente.
- **Saída:** o agente termina → hook HTTP (`127.0.0.1`, bearer) → a bridge lê o transcript
  e devolve a resposta formatada (MarkdownV2) ao Telegram.
- **Push, não scraping.** **tmux é a fonte da verdade** (a sessão segue retomável por `tmux attach`).
- **Camada de alma.** O scaffold de um agente não gera só a infra: monta também a "alma" (templates
  `IDENTITY`/`SOUL`/`USER`/`TOOLS`/`AGENTS`/`HEARTBEAT`, `CLAUDE.md` orquestrador leve) e a memória
  hierárquica (`memory/`, `projects/`), preservando dados já existentes (create-if-missing).

## Instalação

```bash
# rodar sem instalar (quando publicado no PyPI):
uvx bk-claude-bridge --help        # expõe o comando `tgbridge`

# ou em modo dev, a partir do repo:
uv sync --extra dev
uv run tgbridge --help
```

## CLI

| Comando | Função |
|---|---|
| `tgbridge run` | sobe a bridge (Telegram polling + receiver de hooks + scheduler) |
| `tgbridge hook-install` | grava os hooks HTTP no `settings.json` do `CLAUDE_CONFIG_DIR` |
| `tgbridge init <nome> [--voice …] [--tokens FILE] [--bootstrap]` | scaffold de um agente auto-contido (infra + alma + memória); `--tokens` preenche a persona de um `KEY=VALUE`, `--bootstrap` deixa o agente criar a própria persona na 1ª sessão |
| `tgbridge attach <nome> --session <tmux> [--resume <id>]` | acopla a bridge a um agente já em execução |
| `tgbridge upgrade` | re-aplica os hooks após bump (migração de schema) |
| `tgbridge whisper init` | scaffold do microserviço Whisper compartilhado |

## Voz (opcional)

| modo | backend | observação |
|---|---|---|
| `openai` *(padrão)* | API da OpenAI | só precisa `OPENAI_API_KEY` |
| `local` | faster-whisper no container | `--extra voice-local` + ffmpeg |
| `shared` | container Whisper OpenAI-compatível | um modelo para N agentes |
| `off` | — | sem transcrição |

## Configuração (`.env`)

`TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `BRIDGE_HOOK_SECRET`, `BRIDGE_HTTP_PORT` (8787),
`TMUX_SESSION`, `TZ`, e as de voz (`VOICE_BACKEND`, `OPENAI_API_KEY`, …). Para A2A, cada agente
tem um `A2A_SECRET` próprio e usa `A2A_PEER_SECRETS` (`alvo:segredo,…`) para falar com os outros.

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest
```

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Licença [MIT](LICENSE).
