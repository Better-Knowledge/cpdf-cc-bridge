# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]
### Adicionado
- **Skills agnósticas a runtime (padrão aberto Agent Skills):** as skills empacotadas são
  instaladas no diretório canônico vendor-neutro **`.agents/skills/`** (descoberto nativamente por
  Codex CLI e Gemini CLI), com **`.claude/skills` → `../.agents/skills`** (symlink) para o Claude
  Code. Os SKILL.md referenciam seus scripts via **`${CLAUDE_SKILL_DIR}`** (dir do SKILL.md) e o
  `agent.py` é **self-locating** (acha `agents-registry.json` por AGENT_WORKSPACE/walk-up, segredo
  por env/`A2A_SECRET_FILE`) → **fim do symlink `skills/`** na raiz do workspace (acoplamento de CWD).
- **A2A (comunicação entre agentes):** servidor HTTP separado (`0.0.0.0:A2A_PORT`, só na rede
  `tgbridge-net`, bearer `A2A_SECRET`) com `POST /message` — RPC síncrono. O destino responde
  numa sessão tmux **efêmera** (`A2A_INBOUND=1`, anti-loop profundidade 1) e a resposta volta
  no corpo HTTP (capturada por arquivo; chat suprimido via `A2A_DONE`). Skill `call-agent`
  (`ask`/`list`) + `agents-registry.json` para descoberta. Receiver de hooks segue localhost-only.
- **Scheduler por sessão tmux efêmera:** cada job agendado roda um `claude` interativo
  numa sessão `cron-<label>` isolada (assinatura, sem `claude -p`), sem poluir o chat principal.
- **Endpoint local de scheduling** (`POST/GET/DELETE /schedule` no receiver) + **skill `scheduler`**
  (`templates/skills/scheduler/`) para agendar por **linguagem natural** (sem slash command).
- **Supressão de sentinela** no notifier: respostas iguais a `NO_NEWS`/`HEARTBEAT_OK`
  (config `SUPPRESS_SENTINELS`) não são postadas.
- `AGENT_WORKSPACE` (cwd das sessões de cron) em config e templates; `tmux` ganhou
  `new_session`/`kill_session`/`wait_ready`; `scheduler.parse_when`.
- **Cron robusto:** modo de permissão configurável (`CRON_PERMISSION_MODE`, default
  `bypassPermissions` com `IS_SANDBOX=1`) para a sessão de cron não travar em prompt de permissão;
  `--append-system-prompt` dedicado (saída final limpa); **watchdog** (`CRON_SESSION_TIMEOUT_MIN`)
  que encerra a sessão travada e avisa no Telegram; `misfire_grace_time` 120 min (tolera bridge fora do ar).
- **Watchdog resiliente a restart da bridge:** o watchdog vive em memória (`_watchdogs`), então
  reinício do processo `tgbridge run` (tmux sobrevive) deixava sessões de cron órfãs presas até
  serem manualmente mortas. Agora cada sessão é marcada com a user-option tmux `@cron=<label>`
  (persiste no servidor tmux) e o startup chama `scheduler.rearm_cron_watchdogs()`: mata as cron
  já estouradas e **re-arma** o watchdog (tempo restante) nas demais. Identifica cron por `@cron`
  ou prefixo `cron-`; **nunca** toca a sessão principal (`cfg.tmux_session`) nem sessões A2A.
- **Roteamento de permissão:** o botão ✅/❌ do Telegram age na sessão que está realmente no prompt
  (inclusive sessões de cron) via `tmux.find_awaiting_permission`/`list_sessions`; `wait_ready` trata
  a tela "Bypass Permissions"; `tmux.new_session` aceita `cmd` como argv.
- **Modelo por cron (otimização de cota):** `claude --model <alias>` por job, resolvido por env —
  `CRON_MODEL` (padrão de todos os crons) + `CRON_MODEL_<LABEL>` (override por job). Vazio = default
  do agente. Ex.: `CRON_MODEL=sonnet` + `CRON_MODEL_HEARTBEAT=haiku`.
- **Camada de alma e memória no scaffolder:** `scaffold.init()` + `templates/` agora geram, além da
  infra, a "alma" do agente — templates `IDENTITY`/`SOUL`/`USER`/`TOOLS`/`AGENTS`/`HEARTBEAT`/
  `BOOTSTRAP.md`, um `CLAUDE.md` orquestrador **leve** (`@`-inclui os demais), `workspace.gitignore`,
  `memory/` hierárquica (`INDEX` + `topics/_TEMPLATE`) e `projects/` (`INDEX` + `_CATEGORY_INDEX` +
  `_PROJECT_README` + `leads/INDEX`), além de `scripts/` (`regen-indexes.sh`, `backup-data.sh`).
  Novos tokens de persona/usuário/fuso (defaults neutros, derivação de fuso) e materialização
  **create-if-missing** (não clobbera dados pessoais já existentes). A CLI `tgbridge init` ganhou
  `--tokens FILE` (preenche a persona a partir de um arquivo `KEY=VALUE`) e `--bootstrap` (escreve
  `BOOTSTRAP.md` para o agente criar a própria persona na 1ª sessão). Testes de scaffold estendidos.

### Corrigido
- **Watchdog de cron — falso "excedeu N min".** Um watchdog vigiava a sessão por NOME; para jobs que
  disparam mais rápido que o timeout (ex.: `heartbeat` a cada 30 min vs timeout 120 min), um watchdog
  antigo matava a sessão de um disparo NOVO e mandava um alarme falso. Agora há **um watchdog por
  label**, cancelado a cada novo disparo (`_watchdogs`); a rede de segurança p/ jobs infrequentes que
  travam de verdade é preservada.
- **Entrega de cron sob env-scrub.** O env-scrub removia `BRIDGE_HOOK_SECRET` da sessão de cron, mas o
  Stop hook (que entrega a saída) autentica com `${BRIDGE_HOOK_SECRET}` → 401. Cron passou a usar uma
  blocklist própria (`CRON_ENV_BLOCKLIST`) que **mantém** `BRIDGE_HOOK_SECRET` (A2A segue com scrub completo).
- **Skills não descobertas em agentes novos.** O scaffolder copiava `templates/skills/` para
  `workspace/skills/` (dir real), caminho que o Claude Code NÃO descobre — então a skill de A2A
  (`call-agent`) e demais não carregavam, e o agente novo não conseguia INICIAR chamadas A2A. Agora
  instala em `.claude/skills/` (caminho descoberto) e deixa `skills` como symlink de compat. A skill
  A2A foi padronizada como **`call-agent`** (era `agents`).

### Segurança
- **Env-scrub** das sessões efêmeras (cron/A2A): `A2A_SECRET`/`BRIDGE_HOOK_SECRET`/`TELEGRAM_BOT_TOKEN`
  removidos do ambiente (`env -u …`; override `EPHEMERAL_ENV_BLOCKLIST`). Skills lêem o segredo de
  `/config/bridge.secret` (0600, escrito pelo entrypoint); `schedule.py` recusa sob `A2A_INBOUND`.
- **A2A:** allowlist de remetente (`A2A_ALLOWED_SENDERS` ou `agents-registry.json`) → 403; rate-limit
  por remetente (`A2A_RATE_MAX`/`A2A_RATE_WINDOW`) → 429; `notify` com `sender` sanitizado.
- **Permissões (templates):** `deny` de escrita em `.mcp.json`/`.claude/settings*.json`/
  `agents-registry.json`/`.secrets/**`.
- **Logs:** `httpx`/`telegram` em WARNING (não vaza o bot token). **Whisper:** bearer opcional
  (`WHISPER_SECRET`). `init` cria `.env` com `0600`.
- **A2A por-agente (segredos distintos):** cada agente passa a ter um `A2A_SECRET` **distinto**
  (o bearer que ele exige no inbound; receptor inalterado). Para chamar outro agente, o sender
  (`templates/skills/agents/scripts/agent.py`) usa o segredo do **alvo** via
  `A2A_PEER_SECRETS='alvo:segredo,...'` (lido de env ou de `/config/bridge.secret`), com **fallback**
  ao próprio segredo — retrocompatível com o modelo de segredo compartilhado. O
  `templates/entrypoint.sh` grava `A2A_PEER_SECRETS` em `/config/bridge.secret`; `A2A_PEER_SECRETS`
  foi adicionado a `DEFAULT_EPHEMERAL_BLOCKLIST` e `DEFAULT_CRON_BLOCKLIST` (env-scrub das sessões
  efêmeras) e documentado em `env.example`. Benefício: um segredo vazado não dá acesso a todos os agentes.

## [0.1.0] - 2026-06-15
### Adicionado
- Bridge Telegram ↔ sessão interativa do Claude Code em tmux (entrada via `tmux send-keys`,
  saída via hooks HTTP em `127.0.0.1`).
- Router de slash commands: reservados + passthrough verbatim + escape `!`.
- Scheduler (APScheduler + jobstore SQLite): `/schedule`, `/schedules`, `/unschedule`.
- Monitoramento: avisos de `SubagentStart/Stop` e `TaskCreated/Completed` (toggle `MONITOR_EVENTS`).
- Voz plugável: `openai` (nuvem, padrão), `local` (faster-whisper), `shared`
  (container Whisper OpenAI-compatível) e `off`.
- CLI `tgbridge`: `run`, `hook-install`, `init`, `attach`, `upgrade`, `whisper init`.
- Scaffold de agentes auto-contidos (workspace/ + config/) e microserviço Whisper compartilhado.

[Não lançado]: https://github.com/Better-Knowledge/bk-claude-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Better-Knowledge/bk-claude-bridge/releases/tag/v0.1.0
