---
name: scheduler
description: Agendar/lembrar tarefas recorrentes ou pontuais a partir de linguagem natural (sem slash command). Use quando o usuário pedir para agendar, lembrar, repetir, ou rodar algo num horário ("todo dia 9h...", "toda sexta", "amanhã às 14h", "a cada 2 horas", "me lembra em 20 minutos").
---

# Scheduler — agendar por linguagem natural

Você pode criar/listar/remover tarefas agendadas. No horário, o bridge roda o **prompt**
numa sessão isolada e a saída vai para o Telegram (jobs de checagem que retornarem
`NO_NEWS` não são postados).

## Quando usar
O usuário pediu, em linguagem natural, para agendar/lembrar/repetir algo. Você **traduz**
o pedido para uma expressão de tempo e um prompt, e chama o script abaixo. **Não** peça ao
usuário para usar `/schedule` — faça por ele.

## Como agendar
1. Traduza o tempo:
   - Recorrente → **cron de 5 campos** `min hora dia mês dia-da-semana` (timezone **BRT/America/Sao_Paulo**).
     - "todo dia 9h" → `0 9 * * *` · "toda sexta 13h" → `0 13 * * 5` · "a cada 2h das 6 às 22" → `0 6-22/2 * * *`
   - Pontual → **ISO8601** (BRT), ex.: `2026-06-16T14:00`.
2. Defina um `label` curto (kebab-case) e o `prompt` (a tarefa que VOCÊ vai executar no horário —
   escreva na 2ª pessoa, como uma instrução para você mesmo; para checagens, instrua a responder
   apenas `NO_NEWS` se não houver novidade e a registrar um resumo em `memory/AAAA-MM-DD.md`).
3. Rode:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/schedule.py" add --when "cron 0 9 * * *" --label briefing \
     --prompt "Monte o briefing matinal de hoje..."
   ```
   Para pontual: `--when "at 2026-06-16T14:00"`.
4. Confirme ao usuário em uma linha (o quê + quando + próximo disparo retornado).

## Listar / remover
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/schedule.py" list
python3 "${CLAUDE_SKILL_DIR}/scripts/schedule.py" remove --id <job_id>
```

## Observações
- Horários sempre em **BRT**. Cheque a referência com `TZ='America/Sao_Paulo' date` se precisar.
- O script fala com o bridge local (`127.0.0.1`), autenticado pelo ambiente — não precisa de chave manual.
- Jobs sobrevivem a restart (persistidos no `jobs.db`).
