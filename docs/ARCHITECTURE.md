# Arquitetura — `tgbridge`

> Bridge leve entre o **Telegram** e uma sessão **interativa** de Claude Code rodando
> em **tmux**, dentro de um container Docker. Operação por **assinatura** (o agente já
> está logado interativamente — a bridge não toca em autenticação).

Este documento descreve o **mecanismo genérico** da `tgbridge`. Ao longo do texto, o
agente de exemplo é chamado de `meu-agente` (e `agente-a` / `agente-b` quando o assunto
é multi-agente). Substitua pelo nome do seu próprio agente.

---

## 1. Visão geral

A `tgbridge` opera um agente **Claude Code interativo de longa duração** pelo Telegram.
O agente roda como um processo CLI dentro de uma janela **tmux** (login por assinatura,
não API key) — e a bridge é apenas uma **camada fina de controle sobre o tmux**.

Dois fluxos resumem tudo:

- **Entrada:** mensagem no Telegram → `tmux send-keys` na sessão do agente.
- **Saída:** o agente termina de responder → dispara um **hook HTTP** → a bridge lê o
  transcript e devolve a resposta formatada ao Telegram.

### Princípios

- **Leve:** um único processo Python, poucas dependências, setup por um `.env` e um comando.
- **tmux é a fonte da verdade:** a bridge nunca embrulha o SDK; a sessão interativa
  continua retomável no terminal (`tmux attach`).
- **Assinatura, não API key:** o agente já está logado; a bridge não autentica nada.
- **Push antes de pull:** a saída vem por **hooks HTTP** (eventos estruturados), não por
  scraping de tela. Scraping (`capture-pane`) é só fallback (status/screenshot) ou para
  providers sem hooks.
- **Container-native:** roda dentro do mesmo container do agente; egress mínimo
  (basicamente `api.telegram.org` + a API do modelo). O receiver de hooks é localhost-only.
- **Reproduzível:** trocar/adicionar agente = adicionar uma entrada de *provider*, não
  reescrever a bridge.

### Diagrama do fluxo principal

```
                 Telegram (nuvem)
            ┌───────────────────────┐
            │  usuário autorizado   │
            │   (ALLOWED_USERS)     │
            └───────────┬───────────┘
                        │  getUpdates / sendMessage
                        │  (long-polling, sem webhook)
══════════════════ container Docker "meu-agente" ══════════════════
                        │
              ┌─────────▼──────────────────────────────────┐
              │   processo tgbridge  (1 loop asyncio)       │
              │                                             │
              │  (a) Telegram I/O   ── gate ALLOWED_USERS   │
              │  (b) hook receiver  ── 127.0.0.1:8787       │
              │  (c) scheduler      ── APScheduler + SQLite │
              └───┬──────────────────────────▲──────────────┘
                  │ tmux send-keys            │ POST /event
                  │  (-l literal + Enter)     │  (Bearer secret)
                  ▼                           │
        ┌──────────────────────┐    hook Stop / Notification
        │  tmux session         │───────────┘
        │  "meu-agente"         │
        │  Claude Code          │──────► API do modelo (egress)
        │  (interativo, login   │──────► MCP / ferramentas (egress)
        │   por assinatura)     │
        └──────────────────────┘
═══════════════════════════════════════════════════════════════════
```

---

## 2. Os três serviços concorrentes

A bridge é **um processo único** que sobe **três serviços no mesmo event loop asyncio**
(orquestrados em `app.py`):

### (a) Telegram I/O — `telegram_io.py`

- **Long-polling** via `getUpdates` (sem webhook, sem túnel). Só precisa de egress para
  `api.telegram.org`.
- **Gate de autorização:** só IDs em `ALLOWED_USERS` falam com o bot; toda update de outro
  `from.id` é descartada. Operação em **DM 1:1** (um usuário autorizado conversando direto
  com o bot).
- **Roteamento** (`router.py`, função pura `classify()`):

  | Entrada do usuário | Classificação | Ação |
  |---|---|---|
  | `quantos itens pendentes?` | `("prompt", texto)` | injeta no tmux como prompt |
  | `/status`, `/stop`, `/screenshot`, `/schedule…` | `("reserved", cmd)` | tratado pelo próprio bot |
  | `/compact`, `/cost`, `/clear`, `/context`… | `("passthrough", "/x")` | enviado **verbatim** ao agente |
  | `!status` | `("passthrough", "/status")` | escape de colisão de nome → força envio ao agente |

  Os comandos **reservados** do bot são: `start, help, status, stop, screenshot,
  schedule, schedules, unschedule`. Tudo que começa com `/` e **não** é reservado vira
  **passthrough** — então comandos novos do agente "simplesmente funcionam" sem manter
  lista. O prefixo `!` força passthrough para nomes que colidem (ex.: o agente também tem
  `/status`).

- **Comandos do bot:** `/status` (captura algumas linhas do pane), `/screenshot` (mais
  linhas), `/stop` (envia Escape — o "freio de mão"), `/schedule|/schedules|/unschedule`,
  `/help`, `/start`.
- **Permissões interativas:** quando o agente pede aprovação, o hook `Notification`
  (`permission_prompt`) vira um teclado inline **Permitir / Negar**; o callback envia
  `Enter`/`Escape` ao tmux.
- **Typing indicator:** ao receber um prompt, dispara `send_chat_action("typing")` a cada
  ~4s até a resposta chegar (evento `Stop`).
- **Voz (opcional):** mensagens de áudio são transcritas (`transcribe.py`,
  `VOICE_BACKEND=off|local|openai`) e seguem o **mesmo caminho** de um prompt de texto.

### (b) Hook receiver — `hooks_receiver.py`

FastAPI bindado em **`127.0.0.1:8787`** (localhost-only, **nunca** `0.0.0.0`):

- `POST /event` — recebe os eventos do Claude Code. Exige `Authorization: Bearer
  ${BRIDGE_HOOK_SECRET}`; responde **200 na hora** e enfileira o payload (nunca bloqueia o
  agente). Um worker assíncrono consome a fila e despacha para o `notifier`.
- `POST /schedule`, `GET /schedules`, `DELETE /schedule/{id}` — permitem ao próprio agente
  (ou ao operador) agendar tarefas por linguagem natural, registrando no scheduler ao vivo
  + no `jobs.db`.

### (c) Scheduler — `scheduler.py`

APScheduler (`AsyncIOScheduler`) com **jobstore SQLite** → jobs **sobrevivem a restart**.
Detalhes na seção 7.

### Fluxo completo de uma mensagem

1. Usuário manda texto no Telegram.
2. `telegram_io` recebe via long-poll, aplica o **gate** `ALLOWED_USERS`.
3. `router.classify()` decide: reserved / passthrough / prompt.
4. Para prompt/passthrough: `tmux.send_text()` injeta o texto na sessão `claude`.
5. O agente pensa, usa ferramentas, responde.
6. Ao terminar, o Claude Code dispara o hook **`Stop`** → `POST /event` (com Bearer).
7. O receiver enfileira; o `notifier` lê o transcript, formata e envia ao Telegram.

---

## 3. Como a bridge conversa com o tmux — `tmux.py`

Camada fina via `asyncio.create_subprocess_exec` (**sem `shell=True`** — evita injeção):

```python
async def send_text(session, text):
    s = norm(session)
    if text:
        await _run("send-keys", "-t", s, "-l", "--", text)  # -l = literal, -- = fim das flags
        await asyncio.sleep(0.05)
    await _run("send-keys", "-t", s, "Enter")               # Enter como tecla separada
```

Pontos-chave:

- `-l` (literal) + `--` preserva caracteres especiais e evita interpretação; o `Enter` vai
  numa chamada **separada** (TUIs perdem o Enter se vier colado ao texto).
- `interrupt()` envia **Escape** (o `/stop`, freio de mão para abortar uma ação autônoma).
- `capture(session, lines)` usa `tmux capture-pane` para `/status` e `/screenshot`.
- `norm()` normaliza o nome da sessão para `[a-zA-Z0-9_-]`.
- **Resolução da sessão alvo** (em `config.py`): `TMUX_SESSION` do `.env` (override
  explícito) → senão o **basename do `cwd`** do agente → fallback `claude`.

### Saída por hooks (push) — `hooks_install.py`

Em vez de raspar a tela, o Claude Code **avisa** por hook quando termina. O
`hooks_install.ensure()` escreve em `$CLAUDE_CONFIG_DIR/settings.json` (idempotente; **único
módulo que escreve em settings**) um handler `http` por evento:

```json
{
  "type": "http",
  "url": "http://127.0.0.1:8787/event",
  "timeout": 5,
  "headers": { "Authorization": "Bearer ${BRIDGE_HOOK_SECRET}" },
  "allowedEnvVars": ["BRIDGE_HOOK_SECRET"]
}
```

Eventos instalados: `Stop`, `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`,
`TaskCreated`, `TaskCompleted` e `Notification` (matcher `permission_prompt`). O mesmo
módulo também grava `allowedHttpHookUrls`, `httpHookAllowedEnvVars`,
`enableAllProjectMcpServers: true` (auto-aprova MCP do projeto para não travar a sessão
headless).

Eventos tratados pelo `notifier.handle_event`:

| Evento | Ação |
|---|---|
| `SessionStart` | vincula sessão ↔ chat |
| `SessionEnd` | limpa o binding |
| `Stop` | lê o transcript e envia a resposta final |
| `Notification` (`permission_prompt`) | teclado inline Permitir/Negar |
| `SubagentStart/Stop`, `TaskCreated/Completed` | avisos curtos de progresso (toggle `MONITOR_EVENTS`) |

### Formatação da saída — `notifier.py`

O transcript do Claude é um **JSONL**; seu caminho chega no payload do hook `Stop`
(`transcript_path`). O pipeline:

1. **Extrai a última mensagem do assistente** — varre o JSONL de trás para frente, pega o
   último bloco de **texto** (ignora `thinking` e `tool_use`). Retorna `(uuid, texto)`.
2. **Estabiliza** — o `Stop` pode disparar antes do registro final ser gravado; relê até o
   `uuid` repetir (evita mandar resposta parcial).
3. **Dedup** — compara o `uuid` com o último enviado por sessão (`state.py`, SQLite);
   repetido → descarta; novo → envia e grava.
4. **Chunking markdown-aware** — quebra mensagens longas **sem cortar dentro de blocos de
   código**.
5. **Conversão** → MarkdownV2; se falhar (ou passar do limite), cai para **texto puro**.
6. **Envio** — uma mensagem por chunk (limite ~4096 chars do Telegram).

> O texto enviado vem do **transcript** (já limpo), não do `capture-pane` — então não há
> ANSI para limpar no caminho normal.

---

## 4. Container Docker + bind-mounts

Cada agente é **auto-contido** numa pasta própria com `Dockerfile`, `docker-compose.yml`,
`.env`, `workspace/` e `config/`.

- **Imagem:** base `debian-slim` + `tmux`, `git`, `ripgrep`, `python3`; instala o **Claude
  Code** e o **uv** (gerencia o venv da bridge). ENV principal: `CLAUDE_CONFIG_DIR=/config`.
- **Compose:** `restart: unless-stopped`, `stdin_open` + `tty` (para `tmux attach`),
  `env_file: ./.env`, e os dois bind-mounts abaixo.

### Bind-mounts (host → container)

| Host (dentro da pasta do agente) | Container | Papel | Persistência |
|---|---|---|---|
| `./workspace` | `/home/meu-agente` | Workspace: `CLAUDE.md`, `.mcp.json`, `.claude/` (skills, settings de permissão), `tgbridge/`, `entrypoint.sh`, `state.db`/`jobs.db` | host RW |
| `./config` | `/config` (`CLAUDE_CONFIG_DIR`) | Config do Claude: credenciais OAuth, `settings.json` (hooks), `sessions/`, histórico | host RW |

Consequências práticas:

- **Login persiste:** o OAuth fica em `config/` no host → sobrevive a
  `docker compose up --build`. Não há re-login a cada deploy.
- **Editar no host reflete na hora:** `workspace/tgbridge/` é bind-mount → mexer no código
  afeta o próximo `tgbridge run` (modo dev).
- **Segredos via `.env`** (`env_file`), **nunca embutidos na imagem**. O arquivo `.env`
  deve ficar com permissão **`0600`**. Variáveis típicas: `TELEGRAM_BOT_TOKEN`,
  `ALLOWED_USERS`, `BRIDGE_HOOK_SECRET`, `TZ`, etc.

### Entrypoint — ordem importa

```sh
1) uv sync                       # venv da bridge (idempotente, sobre o bind-mount)
2) uv run tgbridge hook-install  # escreve os hooks ANTES do agente subir
3) tmux new-session -d -s meu-agente -c /home/meu-agente "claude"
4) while true; do uv run tgbridge run; sleep 3; done   # bridge = PID 1 lógico
```

Como a bridge é o processo de frente, o Docker enxerga seus logs/saúde e reinicia se cair.
O entrypoint também grava os segredos de infra num arquivo restrito `bridge.secret`
(`0600`) que as sessões efêmeras (cron/A2A) leem — ver seções 6 e 7.

---

## 5. Scaffolder / matriz — `tgbridge init`

O `tgbridge init <nome>` (`scaffold.py` + `templates/`) **gera um agente novo**: a infra
(container + bridge) **mais** uma "camada de alma" e a estrutura de memória. Os templates
usam **tokens `{{...}}`** substituídos no init, e a materialização é **create-if-missing**
(nunca sobrescreve dados pessoais já existentes).

O que é gerado:

- **Camada de alma:** o `CLAUDE.md` vira um **orquestrador leve** que apenas `@`-inclui os
  demais arquivos, em vez de carregar tudo inline:

  ```markdown
  # {{NAME}}
  @IDENTITY.md
  @SOUL.md
  @USER.md
  @TOOLS.md
  ...
  @AGENTS.md
  ```

  - `IDENTITY.md` / `SOUL.md` — quem o agente é (persona pública).
  - `USER.md` — quem ele atende.
  - `TOOLS.md` / `AGENTS.md` — ferramentas e o manual do workspace.
  - `HEARTBEAT.md` — rotina/heartbeat; `BOOTSTRAP.md` — modo "o agente se descreve na 1ª
    sessão e apaga o arquivo".
- **Memória hierárquica:** `memory/` (com `INDEX` + `topics/_TEMPLATE`) — ver seção 6.
- **`projects/`** com índices e READMEs de exemplo.
- **`scripts/`:** `regen-indexes.sh`, `backup-data.sh`.
- **Infra:** `Dockerfile`, `docker-compose.yml`, `.env.example`, `entrypoint.sh`,
  `workspace.gitignore`.

CLI relacionada: `tgbridge init [--tokens FILE] [--bootstrap] [--voice ...]`,
`tgbridge attach` (vincular a uma sessão tmux já existente), `tgbridge upgrade`,
`tgbridge whisper init` (whisper compartilhado, opcional).

---

## 6. Memória hierárquica (token-efficient)

Em vez de um arquivo de memória monolítico carregado inteiro a cada sessão, a memória é um
**mapa de roteamento leve** + tópicos puxados **sob demanda**:

| Caminho | Papel | Quando carrega |
|---|---|---|
| `memory/INDEX.md` | **Mapa de roteamento** leve | a **cada** sessão |
| `memory/topics/<slug>.md` | Conhecimento durável: frontmatter (`name`/`description`/`keywords`/`updated`) + links `[[...]]` | **sob demanda**, pela `description` |
| `memory/daily/AAAA-MM-DD.md` | Logs crus do dia | sob demanda |
| `memory/archive/` | Rollups (consolidações) | sob demanda |

- **STATUS não vive na memória:** o status de cada projeto/lead mora no **frontmatter do
  README** da pasta correspondente.
- **Índices regeneráveis:** `scripts/regen-indexes.sh` reescreve as regiões entre os
  marcadores `<!-- regen:*:start -->` / `<!-- regen:*:end -->` a partir do frontmatter dos
  READMEs — então os índices nunca ficam desatualizados à mão.
- A instrução "every session" do agente lê o `INDEX.md` e abre **só o tópico necessário**.

---

## 7. Scheduler (cron + one-shot)

Comandos:

```
/schedule cron <expr 5 campos> | <sessão> | <prompt>
/schedule at   <ISO8601>       | <sessão> | <prompt>
/schedules                       # lista (id, próximo disparo, prompt)
/unschedule <id>                 # remove
```

Exemplos:

```
/schedule cron 0 9 * * 1-5 | meu-agente | gere o resumo do dia
/schedule at 2026-01-02T09:00 | meu-agente | rode a verificação diária
```

Como funciona:

- APScheduler com jobstore **SQLite** (`jobs.db`) → os jobs **sobrevivem a restart**
  (`misfire_grace_time` tolera disparos atrasados, ex.: bridge fora do ar).
- Cada disparo roda o prompt numa **sessão tmux efêmera e isolada** (`cron-<label>`),
  separada do chat principal. A saída volta pelo **hook `Stop` global** → notifier.
- **Modelo por cron:** o modelo é resolvido por label (`CRON_MODEL_<LABEL>` ou
  `CRON_MODEL`) — útil para usar um modelo mais barato em rotinas frequentes.
- **Modo de permissão:** sessões de cron não têm ninguém olhando a TUI, então um prompt de
  permissão as travaria. Por isso rodam em modo não-interativo (`CRON_PERMISSION_MODE`,
  combinado com a allowlist em `.claude/settings.json`).
- **Watchdog:** se uma sessão de cron ainda estiver viva após `CRON_SESSION_TIMEOUT_MIN`
  (default 120 min), ela é encerrada e o usuário é avisado no Telegram — rede de segurança
  para sessões travadas.
- **Env-scrub:** a sessão de cron **não herda** os segredos de infra do ambiente
  (`A2A_SECRET`, `TELEGRAM_BOT_TOKEN`...), mas **mantém** `BRIDGE_HOOK_SECRET` (o hook
  `Stop` precisa dele para entregar a saída ao receiver).

---

## 8. A2A — comunicação entre agentes (multi-agente)

Quando você roda **vários agentes** (`agente-a`, `agente-b`, ...), cada um pode consultar
o outro por um canal A2A (agent-to-agent):

- Cada agente sobe um **servidor A2A separado** na **porta 8788**, exposto apenas na rede
  Docker compartilhada `tgbridge-net` (**não publicado no host**). O receiver de hooks
  (`127.0.0.1:8787`) segue intacto e separado.
- `POST /message` roda a mensagem do remetente numa **sessão tmux efêmera**, captura a
  resposta por arquivo e devolve no corpo HTTP.

### Segredo por-agente

- Cada agente tem um **`A2A_SECRET` distinto** — o bearer que ele **exige no inbound**.
- Para **chamar** outro agente, o remetente usa o segredo do **alvo** via
  `A2A_PEER_SECRETS='agente-a:<segredo>,agente-b:<segredo>'` (do env ou do arquivo
  `bridge.secret`), com fallback ao próprio segredo.
- Vantagem: um segredo vazado **não dá acesso a todos** os agentes.

### Defesas

- **Bearer** obrigatório (401 sem o segredo certo do alvo).
- **Allowlist de remetentes** (`A2A_ALLOWED_SENDERS` ou derivada do registry) — defesa em
  profundidade, já que o campo `from` é auto-declarado.
- **Rate-limit por remetente** (janela deslizante) + concorrência serializada (cada chamada
  abre uma sessão `claude`, que é cara).
- **Env-scrub completo** das sessões efêmeras A2A: como a mensagem é **não-confiável**, a
  sessão **não herda** `A2A_SECRET`, `A2A_PEER_SECRETS`, `BRIDGE_HOOK_SECRET` nem
  `TELEGRAM_BOT_TOKEN` (anti-exfil cross-agent sob injeção de prompt).
- **Anti-loop** (`A2A_INBOUND=1`): o destino não pode reenviar para um 3º agente
  (profundidade 1).

---

## 9. Abstração de provider — reprodutibilidade

O que torna a bridge reaproveitável para outros agentes CLI é o **registro de providers**
(`providers.py`). Cada provider declara:

```python
@dataclass
class Provider:
    name: str           # "claude" | "codex" | "gemini" | <custom>
    launch_cmd: str     # comando para iniciar na janela tmux
    output_mode: str    # "hooks" (push) | "poll" (pull)
    reserved_cmds: set
    passthrough: bool
```

- **`claude`** usa `output_mode="hooks"` — saída por push (hook `Stop`).
- Agentes **sem hooks** (Codex, Gemini, custom) usariam `output_mode="poll"` — a saída é
  lida do transcript/pane por um poller. (Mencionado como caminho de extensão; o provider
  padrão e validado é o `claude`.)

**Adicionar um agente = adicionar uma entrada de Provider**, não reescrever o core.

---

## 10. Segurança (resumo)

- **Gate de usuários:** só IDs em `ALLOWED_USERS` falam com o bot (DM 1:1).
- **Receiver localhost-only:** bind em `127.0.0.1:8787`, nunca `0.0.0.0`; exige
  `Authorization: Bearer ${BRIDGE_HOOK_SECRET}` em `/event`.
- **Permissões vivem no `settings.json`, não no `CLAUDE.md`:** `permissions.allow/ask/deny`
  + permission mode é que liberam/bloqueiam ferramentas. CLAUDE.md e skills são orientação,
  **não fronteira**.
- **`Notification` é a rede de segurança:** se o agente travar esperando aprovação fora das
  regras de allow, o `Stop` não dispara — o `Notification` te avisa no Telegram com botões.
- **Segredos sempre via `.env`/env do container** (`0600`), nunca na imagem. Não vaze o bot
  token nos logs (a bridge sobe os loggers ruidosos para WARNING).
- **A2A:** segredo por-agente + allowlist + rate-limit + env-scrub + anti-loop (seção 8).
- **Egress mínimo:** `api.telegram.org` + a API do modelo (+ MCP/ferramentas que você usar).

---

## 11. Arquivos-chave do pacote

Módulos em `src/tgbridge/`:

| Arquivo | Papel |
|---|---|
| `app.py` | Orquestrador: sobe Telegram (polling) + receiver (uvicorn) + scheduler num só loop |
| `telegram_io.py` | Handlers (texto, voz, comandos) + gate `ALLOWED_USERS` |
| `router.py` | `classify()` — reserved / passthrough / prompt |
| `tmux.py` | `send-keys` (`-l` + Enter), `capture-pane`, interrupt (Escape), sessões |
| `hooks_receiver.py` | FastAPI `POST /event` (127.0.0.1) + endpoints de `/schedule` |
| `hooks_install.py` | Escreve os hooks HTTP + allowlists no `settings.json` (idempotente) |
| `notifier.py` | Lê transcript, formata (MarkdownV2 + fallback), dedup, split, monitoramento |
| `scheduler.py` | APScheduler + jobstore SQLite; sessões efêmeras de cron + watchdog |
| `a2a.py` | Servidor A2A (porta 8788): bearer, allowlist, rate-limit, env-scrub, anti-loop |
| `config.py` | Configuração via ambiente + resolução da sessão tmux + blocklists de env-scrub |
| `providers.py` | Registro de providers (reprodutibilidade) |
| `transcribe.py` | Voz plugável (`off`/`local`/`openai`) |
| `state.py` | Estado SQLite (bindings de sessão, dedup, kv) |
| `scaffold.py` + `templates/` | `tgbridge init|attach|upgrade` + camada de alma e memória |
| `cli.py` | Entrypoints: `run`, `hook-install`, `init`, `attach`, `upgrade`, `whisper` |

---

## 12. Reprodutibilidade (resumo)

1. `tgbridge init meu-agente` — gera infra + camada de alma + memória.
2. Preencha o `.env` (`TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `BRIDGE_HOOK_SECRET`, `TZ`...).
3. Faça login do Claude Code (assinatura) — o OAuth persiste em `config/`.
4. `docker compose up -d --build` — o entrypoint sobe o `claude` em tmux + a bridge.
5. Fale com o bot no Telegram. Para um segundo agente, repita com outro nome/`.env` (e, se
   quiser A2A, registre o segredo por-agente e a rede `tgbridge-net`).
</content>
</invoke>
