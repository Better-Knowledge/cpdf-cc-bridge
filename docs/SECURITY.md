# Segurança — `tgbridge`

> Modelo de segurança **genérico** da biblioteca `tgbridge`: a bridge que conecta o
> Telegram a uma sessão interativa de um agente CLI rodando em `tmux`, com hooks HTTP,
> agendador (cron) e comunicação entre agentes (A2A).
>
> Este documento descreve **ameaças e defesas** da própria bridge. Ele não cobre as
> integrações específicas de cada agente (CRM, e-mail, navegador, redes sociais, etc.) —
> essas pertencem ao agente que você constrói em cima da bridge. Nos exemplos usamos
> nomes genéricos como `meu-agente`, `agente-a` e `agente-b`.

---

## 1. Modelo de ameaça

### Componentes
- **Telegram I/O** — long-polling; recebe texto/voz/comandos do usuário.
- **Receiver de hooks (FastAPI)** — `POST /event` em `127.0.0.1` (localhost-only); recebe
  os eventos do agente (Stop, Notification, etc.) e devolve a saída ao Telegram.
- **Scheduler (APScheduler)** — dispara prompts agendados em sessões `tmux` **efêmeras**.
- **A2A (opcional)** — servidor HTTP separado na rede compartilhada; um agente consulta
  outro abrindo uma sessão efêmera no destino.

### Ativos a proteger
- Token do bot Telegram (`TELEGRAM_BOT_TOKEN`).
- Credencial de login do agente (idealmente **assinatura/OAuth**, não API key — ver §5).
- Segredos da própria bridge: `BRIDGE_HOOK_SECRET`, `A2A_SECRET`, `A2A_PEER_SECRETS`.
- Dados que o agente acessa (memória, arquivos do workspace, integrações de domínio).

### Adversários relevantes
- **(a) Conteúdo não-confiável** que o agente lê (páginas web, mensagens recebidas,
  documentos e **mensagens A2A de outros agentes**) → **injeção de prompt**: o conteúdo
  tenta "instruir" o agente a exfiltrar segredos ou executar ações externas.
- **(b) Outro usuário/processo no host** com acesso ao arquivo de configuração ou aos
  logs do container.
- **(c) Container vizinho na rede compartilhada** tentando abusar do A2A.
- **(d) Exposição acidental de segredos** (logs, arquivos legíveis, repositório).

### Princípio central
**Enforcement de permissões vive no `settings.json` do agente, não no prompt/CLAUDE.md.**
As regras `permissions.allow/ask/deny` são a fronteira real; instruções em arquivos de
contexto são orientação, não barreira. Trate **toda** entrada externa (incluindo A2A)
como dados não-confiáveis, nunca como comandos a executar.

---

## 2. Superfície e gates de entrada

### 2.1 Telegram 1:1 com allowlist de usuários
- Operação em **DM 1:1**: um (ou poucos) usuário(s) autorizado(s).
- O gate `ALLOWED_USERS` (csv de ids) é aplicado nos handlers: toda update cujo
  `from.id` não esteja na lista é descartada. O mesmo gate vale para os botões inline
  (callbacks) — um clique de um id não-autorizado é recusado.
- `ALLOWED_USERS` vazio **aborta o boot** (não há modo "aberto a todos").

### 2.2 Receiver de hooks localhost-only + bearer
- O receiver de hooks faz bind em `127.0.0.1` (**nunca** `0.0.0.0`). Não é alcançável de
  fora do container.
- Todos os endpoints sensíveis (`/event`, `/schedule…`) exigem
  `Authorization: Bearer <BRIDGE_HOOK_SECRET>`; sem o header correto → **401**.
- O `BRIDGE_HOOK_SECRET` ausente **aborta o boot**.

### 2.3 Segredos fora da imagem e com permissão restrita
- Segredos chegam por `env_file`/env do container — **nunca embutidos na imagem**.
- O arquivo de ambiente (`.env`) deve ter modo **`0600`** (somente o dono lê). O
  instalador/scaffold deve criá-lo já com `0600`. Não versione `.env`, `config/` nem
  `.secrets/` (mantenha no `.gitignore`).
- **Nenhuma porta publicada no host.** O receiver é localhost-only e o A2A só escuta na
  rede privada compartilhada (ver §3).

---

## 3. Sessões efêmeras e env-scrub (anti-exfil cross-agent)

Cron e A2A não rodam no chat principal: cada disparo abre uma **sessão `tmux` efêmera e
isolada**, executa um único prompt e é encerrada. Isso importa para a segurança porque:

> **A mensagem A2A é conteúdo NÃO-confiável.** Quando o agente `agente-b` recebe um A2A,
> o texto vem de outro processo e roda como prompt na sessão efêmera. Se esse texto for
> uma injeção, ele tentará ler o ambiente (`env`) e exfiltrar segredos. Por isso a
> sessão efêmera sobe com os **segredos de infra removidos do ambiente**.

### 3.1 Como o scrub funciona
A nova sessão é lançada com prefixo `env -u <VAR> …`, removendo as variáveis listadas
antes de iniciar o processo do agente. Duas listas distintas (em `config.py`):

| Lista | Default | Variáveis removidas |
|---|---|---|
| `DEFAULT_EPHEMERAL_BLOCKLIST` (A2A) | scrub completo | `A2A_SECRET`, `A2A_PEER_SECRETS`, `BRIDGE_HOOK_SECRET`, `TELEGRAM_BOT_TOKEN` |
| `DEFAULT_CRON_BLOCKLIST` (cron) | mantém o hook secret | `A2A_SECRET`, `A2A_PEER_SECRETS`, `TELEGRAM_BOT_TOKEN` |

- **A2A faz scrub completo** dos 4 segredos: a sessão captura a resposta por **arquivo**
  (não usa o Stop hook), então não precisa de nenhum segredo de infra.
- **Cron MANTÉM `BRIDGE_HOOK_SECRET`**: a saída do cron é entregue ao Telegram pelo
  **Stop hook**, que autentica no receiver com esse bearer. Sem ele, o cron rodaria mas
  **não conseguiria entregar** o resultado (401 no receiver).

> Nota: chaves de **domínio** do agente (ex.: a credencial de uma integração que o
> destino A2A realmente precisa usar) **não** entram na blocklist por padrão — só os
> segredos de infra da bridge. Ajuste conforme o que o seu agente expõe.

### 3.2 Como as skills leem segredos sem tê-los no ambiente
Como o env é limpo nas sessões efêmeras, as skills que precisam falar com o receiver ou
com o A2A leem os segredos de um arquivo restrito: **`/config/bridge.secret`** (modo
`0600`, escrito pelo entrypoint no boot via `umask 077`). Esse arquivo contém
`BRIDGE_HOOK_SECRET`, `A2A_SECRET` e `A2A_PEER_SECRETS`.

### 3.3 Override
As listas são configuráveis por ambiente, caso precise ajustar (raramente necessário):
- `EPHEMERAL_ENV_BLOCKLIST` — sobrescreve a blocklist das sessões A2A.
- `CRON_ENV_BLOCKLIST` — sobrescreve a blocklist das sessões de cron.

### 3.4 Modo de permissão do cron
As sessões de cron são não-interativas (ninguém está olhando o TUI), então um prompt de
permissão as travaria. Por isso usam `CRON_PERMISSION_MODE` (default
`bypassPermissions`, com `IS_SANDBOX=1` quando o container roda como root). Isso **não**
desliga as defesas: as regras `deny` do `settings.json` e o **env-scrub** continuam
valendo na sessão de cron. Um watchdog encerra a sessão e avisa no Telegram se ela
exceder `CRON_SESSION_TIMEOUT_MIN`.

---

## 4. A2A — defesa em profundidade

O servidor A2A (`POST /message`) escuta em `0.0.0.0:<A2A_PORT>` mas **só na rede privada
compartilhada** — **não publique essa porta no host**. As camadas de defesa:

### 4.1 Segredo por-agente (bearer)
- Cada agente tem o **seu próprio** `A2A_SECRET` — o bearer que ele **exige no inbound**.
  Uma chamada sem `Authorization: Bearer <A2A_SECRET do destino>` → **401**.
- Para **chamar** outro agente, o remetente usa o segredo **do alvo**, configurado em
  `A2A_PEER_SECRETS='alvo:segredo,alvo2:segredo2'` (lido do env ou de
  `/config/bridge.secret`), com **fallback ao próprio segredo** (retrocompatível com o
  modo de segredo compartilhado).
- **Benefício:** um segredo vazado **não concede acesso a todos** os agentes — o blast
  radius fica restrito ao agente daquele segredo.

### 4.2 Allowlist de remetentes
- O campo `from` da chamada é **auto-declarado** (não confiável por si só — por isso o
  bearer é o gate forte). Ainda assim, o servidor filtra por allowlist:
  `A2A_ALLOWED_SENDERS` (csv) ou, se vazio, os nomes do `agents-registry.json`.
- Remetente fora da allowlist → **403**. (Allowlist vazia → aceita qualquer remetente
  **autenticado**, com warning no log — configure a allowlist em produção.)

### 4.3 Rate-limit por remetente
- No máximo `A2A_RATE_MAX` chamadas por `A2A_RATE_WINDOW` segundos, por remetente.
  Estouro → **429**. Cada chamada abre uma sessão `claude` (cara), então a concorrência
  global é **serializada** por padrão (`A2A_CONCURRENCY=1`).

### 4.4 Anti-loop (profundidade 1)
- A sessão efêmera do destino sobe com `A2A_INBOUND=1`. Isso impede que um agente
  encaminhe uma chamada A2A para um terceiro agente (profundidade máxima 1), evitando
  loops e cadeias de exfiltração.

### 4.5 Higienização do remetente
- O nome do remetente (auto-declarado) é sanitizado antes de ir para log/notificação:
  quebras de linha removidas e tamanho limitado, para não injetar no Telegram.

---

## 5. Permissões do agente (`settings.json`)

O template de `settings.json` traz um conjunto mínimo de `deny` que protege a própria
configuração de segurança contra um agente sob injeção:

**Negar ESCRITA (Write/Edit) em arquivos que controlam segurança:**
- `.mcp.json` — impede habilitar um servidor MCP malicioso (relevante porque
  `enableAllProjectMcpServers` auto-aprova MCPs do projeto).
- `.claude/settings.json` e `.claude/settings.local.json` — impede o agente afrouxar as
  próprias permissões.
- `agents-registry.json` — impede adulterar a allowlist A2A.

**Negar LEITURA de segredos:**
- `.secrets/**` — diretório de segredos do agente.
- `/config/bridge.secret` (e `Bash(cat /config/bridge.secret*)`) — o arquivo restrito de
  segredos de infra.

**`defaultMode` + `allow`/`ask`:** escolha o modo conforme o quão autônomo o agente
precisa ser. Recomendação: mover **ações externas e irreversíveis** (envio de mensagens,
exclusões, exportações) para `ask` ou `deny` — não confie em orientação textual para
isso, pois injeção de prompt ignora orientação. Mantenha o `allow` o mais estreito
possível (evite `Bash(curl *)`/`Bash(source *)` genéricos, que são canais de exfiltração).

---

## 6. Boas práticas operacionais

- **Login por assinatura/OAuth**, não API key, quando o agente suportar — assim não há
  chave de longa duração no ambiente que possa ser exfiltrada.
- **Rotacione os segredos** periodicamente e sempre que suspeitar de exposição:
  token do bot (BotFather), `BRIDGE_HOOK_SECRET`, `A2A_SECRET` (de cada agente) e o
  re-login do agente. Com segredo A2A por-agente, rotacionar um não derruba os outros.
- **Não publique portas internas.** Receiver = localhost; A2A/whisper = só na rede
  privada. Mantenha essa rede restrita aos agentes.
- **Isole o container:** prefira usuário não-root quando viável; considere
  `cap_drop: [ALL]`, `no-new-privileges`, `read_only` e limites de recurso
  (`cpus`/`mem_limit`/`pids_limit`) no compose. Não monte `docker.sock` no agente.
- **Reduza vazamento em logs:** mantenha o nível de log de clientes HTTP em WARNING para
  não registrar URLs que contenham o token do bot.
- **Dados pessoais fora do git:** versione apenas estrutura e persona pública; mantenha
  memória/dados gitignorados e faça backup **cifrado e com acesso restrito**.
- **Prefira `trash` a `rm`** em fluxos automatizados, para reduzir o dano de uma
  exclusão induzida por injeção.

---

## 7. Checklist de verificação

Use após instalar ou alterar o setup:

**Gates de entrada**
- [ ] Mensagem de um id fora de `ALLOWED_USERS` é ignorada.
- [ ] `POST /event` sem o bearer correto → **401**; receiver não escuta em `0.0.0.0`.
- [ ] `ls -l <agente>/.env` mostra **`-rw-------`** (0600).
- [ ] Nenhuma porta interna publicada no host (`docker ps` / compose sem `ports:` para
      receiver e A2A).

**A2A**
- [ ] Chamada com o segredo **errado** (ex.: o próprio, contra um alvo distinto) → **401**.
- [ ] Chamada com o segredo correto do alvo → resposta (round-trip ok).
- [ ] Remetente fora da allowlist → **403**.
- [ ] Exceder o rate-limit → **429**.

**Sessões efêmeras / segredos**
- [ ] Dentro de uma sessão efêmera, `env` **não** mostra `A2A_SECRET`,
      `A2A_PEER_SECRETS` nem `TELEGRAM_BOT_TOKEN` (e, no A2A, nem `BRIDGE_HOOK_SECRET`).
- [ ] `/config/bridge.secret` existe com modo **0600** e o agente **não** consegue lê-lo
      (regra `deny`).

**Permissões**
- [ ] Tentativa de escrever `.mcp.json` / `.claude/settings*.json` /
      `agents-registry.json` é negada.
- [ ] Tentativa de ler `.secrets/**` é negada.
- [ ] Ação externa irreversível cai em `ask`/`deny` (não executa sozinha).
</content>
</invoke>
