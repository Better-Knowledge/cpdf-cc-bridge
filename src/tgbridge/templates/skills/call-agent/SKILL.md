---
name: call-agent
description: Falar com OUTROS agentes (A2A) para pedir informação ou ajuda que é da especialidade deles. Use quando a tarefa depende de dados/capacidade que pertencem a outro agente (ex.: um agente sabe de um CRM; outro sabe da agenda/projetos do usuário). Gatilhos: "pergunte ao <agente>", "peça pro <agente>", ou quando você percebe que outro agente responde melhor.
---

# call-agent — comunicação entre agentes (A2A)

Você pode consultar outros agentes via RPC síncrono: você pergunta, ele responde na hora.

## Descobrir quem existe
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/agent.py" list
```
Mostra os agentes do `agents-registry.json` (nome + o que cada um faz). Escolha o mais adequado à tarefa.

## Perguntar a um agente
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/agent.py" ask <nome> "<sua pergunta objetiva>"
```
- Faça **uma pergunta clara e autocontida** (o outro agente não vê seu contexto).
- A resposta dele volta no stdout — **use-a** na sua própria resposta ao usuário, citando a fonte
  (ex.: "segundo o <agente>, ...").
- Não exponha segredos nem credenciais nas mensagens.

## Regras
- Só pergunte a outro agente quando agregar valor real (dados/capacidade que você não tem).
- **Anti-loop:** se a variável de ambiente `A2A_INBOUND` estiver setada, VOCÊ está respondendo a
  outro agente — **não** encaminhe para um terceiro (o script vai recusar). Responda com o que sabe.
- Mantenha as mensagens curtas e específicas.
