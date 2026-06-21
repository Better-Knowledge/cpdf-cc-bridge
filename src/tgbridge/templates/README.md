# {{NAME}}

Agente Claude Code operável por Telegram, gerado por `tgbridge init`.
Arquitetura: ver [ARQUITETURA.md](../docs/ARQUITETURA.md) e [HANDOFF-v3.md](../docs/HANDOFF-v3.md).

## Subir

```bash
cd {{NAME}}
$EDITOR .env                 # TELEGRAM_BOT_TOKEN, ALLOWED_USERS, CLAUDE_CODE_OAUTH_TOKEN, MCP keys
docker compose up -d --build
docker compose exec -it {{NAME}} claude      # 1ª vez: login interativo (persiste em ./config)
docker compose logs -f {{NAME}}
```

## Estrutura

```
{{NAME}}/
  Dockerfile
  docker-compose.yml
  .env                       # segredos (não commitar)
  workspace/                 # -> /home/{{NAME}}
    CLAUDE.md  .mcp.json  entrypoint.sh  .claude/  tgbridge/
  config/                    # -> /config (CLAUDE_CONFIG_DIR: OAuth/login persistem)
```

## Telegram

- Texto comum → vira prompt para o agente.
- `/status` `/screenshot` `/stop` → comandos do bot.
- `/compact` `/cost` … → repassados verbatim ao Claude.
- `!status` → força o envio de `/status` ao Claude (escape de colisão).
- `/schedule cron <expr> | <sessão> | <prompt>` → agendamento.
- 🎙️ **Áudio** → transcrito e enviado como prompt (backend definido no `init`,
  via `VOICE_BACKEND` no `.env`). Para `openai`, preencha `OPENAI_API_KEY`.
  Trocar de backend depois exige editar o `.env` e `docker compose up -d --build`.
