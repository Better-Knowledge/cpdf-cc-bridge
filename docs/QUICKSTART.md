# QUICKSTART — `tgbridge`

Guia rápido e prático para colocar **um agente Claude Code operável pelo Telegram**
no ar do zero. Ao final você terá um bot do Telegram que conversa com um agente
Claude Code rodando dentro de um container Docker.

`tgbridge` é uma **bridge leve** entre o Telegram e uma sessão **interativa** do
Claude Code rodando em `tmux`: você manda mensagem (ou áudio), ela vira prompt para
o agente; quando o agente termina, a resposta volta formatada para o seu Telegram.

> Em todo o guia o nome do agente é o placeholder **`meu-agente`** — troque pelo
> nome que você quiser (vira a pasta, o container e a sessão `tmux`).

---

## 1. Pré-requisitos

Você vai precisar de:

1. **Docker** (com `docker compose`) instalado e funcionando.
   - Teste: `docker run --rm hello-world`
2. **Python + `uv`** na sua máquina, só para rodar a CLI de scaffold.
   - Instale o `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
3. **Um bot do Telegram** — fale com o [@BotFather](https://t.me/BotFather),
   mande `/newbot`, escolha um nome e um username. Ele devolve um
   **`TELEGRAM_BOT_TOKEN`** (algo como `123456:ABC-DEF...`). Guarde.
4. **O seu user id do Telegram** — fale com o [@userinfobot](https://t.me/userinfobot)
   (ou similar). É um número, ex.: `987654321`. Só esse id poderá usar o bot.
5. **(Recomendado) Login do Claude Code por assinatura** — gere um token OAuth
   na sua máquina, onde você já está logado no Claude Code:

   ```bash
   claude setup-token
   ```

   Copie o valor para usar como **`CLAUDE_CODE_OAUTH_TOKEN`** no `.env`. Sem ele,
   você faz o login interativo na primeira vez que subir o container (passo 5).

---

## 2. Obter a CLI (`tgbridge`)

A CLI vem no pacote Python `bk-claude-bridge` e expõe o comando **`tgbridge`**.

**Modo dev — a partir deste repositório** (recomendado hoje):

```bash
# na raiz do repositório bk-claude-bridge
uv sync --extra dev
uv run tgbridge --help
```

A partir daqui, todo comando `tgbridge ...` deste guia roda como `uv run tgbridge ...`.

> **Futuro (PyPI):** quando o pacote for publicado, dá para rodar sem clonar nada
> com `uvx bk-claude-bridge --help` (o binário exposto continua sendo `tgbridge`).
> Por enquanto, use o modo dev acima.

---

## 3. Criar um agente

```bash
# de dentro da pasta onde você quer guardar seus agentes
uv run tgbridge init meu-agente
```

Isso cria a pasta `meu-agente/` **auto-contida**, com:

- **Infra:** `Dockerfile`, `docker-compose.yml`, `.env` (criado com permissão
  **`0600`**, pois guarda segredos), `README.md` e uma cópia do pacote `tgbridge`.
- **Workspace** (`workspace/` → vira `/home/meu-agente` no container) com:
  `CLAUDE.md` (orquestrador leve), `.mcp.json`, `entrypoint.sh`, `.claude/settings.json`,
  `skills/`, `agents-registry.json`, a **camada de alma**
  (`IDENTITY/SOUL/USER/TOOLS/AGENTS/HEARTBEAT.md`) e a **memória hierárquica**
  (`memory/` com índice + tópicos + logs diários, `projects/`).
- **`config/`** → vira `/config` no container; é onde o login/OAuth do Claude persiste.

A camada de alma é **create-if-missing**: rodar o `init` de novo na mesma pasta
**não sobrescreve** dados pessoais que você já tenha editado.

### Flags úteis do `init`

| Flag | Para quê |
|---|---|
| `--voice openai\|local\|shared\|off` | Backend de transcrição de áudios (ver §7). Se omitir, pergunta no terminal; padrão `openai`. |
| `--tokens FILE` | Arquivo `KEY=VALUE` (uma por linha) que **preenche a persona** — nome do humano, emoji-assinatura, fuso, etc. Linhas vazias e `#` são ignoradas. |
| `--bootstrap` | Escreve um `BOOTSTRAP.md` no workspace: o próprio agente cria a persona na primeira sessão. |
| `--dir D` | Pasta base onde criar o agente (padrão: diretório atual). |
| `--force` | Sobrescreve se a pasta já existir. |

> **Observação sobre o `birth`:** existe um wrapper interativo opcional (`birth`)
> que faz o *nascimento completo* de um agente — `init` + `.env` preenchido +
> login do Claude + registro entre agentes (A2A) + entrevista de persona. Ele é um
> conveniente "tudo em um", mas **não faz parte deste pacote**. Este guia cobre o
> fluxo manual com `tgbridge init`, que funciona sozinho.

---

## 4. Configurar o `.env`

Abra `meu-agente/.env` no seu editor. As chaves principais:

```ini
# Telegram
TELEGRAM_BOT_TOKEN=          # token do @BotFather (passo 1.3)
ALLOWED_USERS=               # seu user id do Telegram; vários separados por vírgula

# Claude Code — login por assinatura (gere com: claude setup-token)
CLAUDE_CODE_OAUTH_TOKEN=     # cole o token; ou deixe vazio e faça login no passo 5

# Fuso horário
TZ=America/Sao_Paulo
```

Chaves que já vêm preenchidas/geradas — normalmente **não precisa mexer**:

| Chave | O que é |
|---|---|
| `BRIDGE_HOOK_SECRET` | Bearer entre o hook do Claude e a bridge. Gerado aleatório no `init`. |
| `BRIDGE_HTTP_PORT` | Porta do receiver de hooks (só localhost). |
| `TMUX_SESSION` | Nome da sessão `tmux` (= nome do agente). |
| `TZ` | Fuso do agente — usado em horários e no scheduler. |
| `MONITOR_EVENTS` | `on`/`off`: avisos de subagente/tarefa no Telegram. |
| `VOICE_BACKEND` | Backend de voz escolhido no `init` (`off`/`local`/`openai`). |

Se escolheu `--voice openai`, preencha também **`OPENAI_API_KEY`** (o `init` já deixa
a linha pronta no `.env`).

### Multi-agente (A2A) — só se você for ter mais de um agente

Cada agente tem um **segredo próprio e distinto** que valida as chamadas que **ele recebe**:

```ini
A2A_SECRET=                  # vazio = A2A desativado. Bearer que ESTE agente exige no inbound.
A2A_PEER_SECRETS=            # segredos dos agentes que VOCÊ chama: 'alvo:segredo,outro:segredo2'
```

`A2A_PEER_SECRETS` lista o `A2A_SECRET` **de cada agente alvo** que você quer chamar.
Detalhes em §8. Para um único agente, deixe ambos vazios.

> O `.env` guarda segredos reais — **nunca** faça commit dele. Ele já nasce `0600`.

---

## 5. Subir o agente

```bash
cd meu-agente
docker compose up -d --build
```

Acompanhe os logs da bridge:

```bash
docker compose logs -f meu-agente
```

**Primeiro login (apenas se você deixou `CLAUDE_CODE_OAUTH_TOKEN` vazio):**

```bash
docker compose exec -it meu-agente claude
```

Isso abre o Claude Code interativo dentro do container; faça o login uma vez. Ele
persiste em `./config` (montado em `/config`), então sobrevive a restarts. Depois
do login, saia do Claude e o bot já estará respondendo no Telegram.

---

## 6. Falar com o agente no Telegram

Abra uma conversa com o seu bot e mande mensagens. Resumo dos comandos:

| No Telegram | O que faz |
|---|---|
| qualquer texto | vira um **prompt** para o agente |
| `/help` | ajuda do bot |
| `/status` | estado da sessão do agente |
| `/stop` | interrompe o que o agente está fazendo |
| `/screenshot` | snapshot da tela (`tmux`) da sessão |
| `/schedule cron <expr> \| <sessão> \| <prompt>` | agenda uma tarefa recorrente/pontual |
| `!status` | força enviar `/status` **ao Claude** (escape, quando há colisão de comando) |
| 🎙️ áudio | transcrito e enviado como prompt (ver §7) |

Comandos que o bot não reconhece (`/compact`, `/cost`, …) são repassados **verbatim**
ao Claude.

---

## 7. (Opcional) Voz

O agente pode transcrever áudios do Telegram e tratá-los como prompts. O backend é
escolhido no `init` (`--voice`) e fixado em `VOICE_BACKEND` no `.env`:

| `--voice` | Como funciona | Precisa de |
|---|---|---|
| `openai` *(padrão)* | transcrição na nuvem da OpenAI | `OPENAI_API_KEY` no `.env` |
| `local` | `faster-whisper` dentro do próprio container | nada (modelo embutido; imagem maior, + `ffmpeg`) |
| `shared` | usa um container **Whisper compartilhado** (vários agentes, um processo só) | rede `tgbridge-net` + o serviço whisper de pé |
| `off` | sem voz | — |

**Trocar de backend depois:** edite `VOICE_BACKEND` (e chaves relacionadas) no `.env`
e rode `docker compose up -d --build`.

**Whisper compartilhado** (`--voice shared`): primeiro crie o microserviço com
`uv run tgbridge whisper init` (gera `shared/whisper/`); ele sobe **uma vez** na rede
`tgbridge-net` e é consumido por todos os agentes em modo `shared`. Se o whisper cair,
a voz falha graciosamente (mensagem de erro) sem derrubar o agente.

---

## 8. (Opcional) Multi-agente (A2A)

Vários agentes podem conversar entre si (Agent-to-Agent). O básico:

1. **Rede compartilhada** — os agentes precisam estar na mesma rede Docker
   `tgbridge-net` (em `--voice shared` o compose já entra nela; caso contrário,
   crie-a e ligue os agentes a ela).
2. **Segredo por agente** — cada agente tem o seu próprio `A2A_SECRET` (distinto,
   nunca compartilhado). É o bearer que **valida o que aquele agente recebe**.
3. **Chamar outro agente** — para chamar o `outro-agente`, este agente precisa do
   `A2A_SECRET` **do alvo**, listado em
   `A2A_PEER_SECRETS='outro-agente:SEGREDO_DO_OUTRO,...'`.
4. **Registro** — cada agente conhece os demais pelo `agents-registry.json`
   (no workspace), que lista nome + descrição de cada agente disponível.

Para um único agente, ignore esta seção (deixe `A2A_SECRET` vazio).

---

## 9. Comandos da CLI (resumo)

| Comando | O que faz |
|---|---|
| `tgbridge init <nome> [--voice …] [--tokens FILE] [--bootstrap] [--dir D] [--force]` | Scaffold de um **novo** agente auto-contido (infra + alma + memória). |
| `tgbridge attach <nome> --session <tmux> [--resume <id>] [--config-dir D]` | Acopla a bridge a um agente **já em execução** (instala os hooks e fala com a sessão `tmux` existente). |
| `tgbridge upgrade [--config-dir D]` | Re-aplica os hooks no `settings.json` após um bump de versão (idempotente). |
| `tgbridge whisper init [--dir D] [--force]` | Cria o microserviço Whisper compartilhado em `shared/whisper/`. |
| `tgbridge run` | Sobe a bridge (Telegram polling + receiver de hooks + scheduler). *Roda dentro do container, via `entrypoint.sh` — você normalmente não chama à mão.* |
| `tgbridge hook-install` | Grava/atualiza os hooks HTTP no `settings.json` do `CLAUDE_CONFIG_DIR`. *Idem: roda no boot do container.* |

---

## Operação no dia a dia

```bash
docker compose up -d --build              # subir / aplicar mudanças do .env ou Dockerfile
docker compose logs -f meu-agente         # ver os logs da bridge
docker compose exec -it meu-agente claude  # abrir o Claude interativo (login / debug)
docker compose down                       # parar
```

Pronto. Bom proveito com o seu `meu-agente`.
