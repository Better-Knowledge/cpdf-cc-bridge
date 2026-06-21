# HEARTBEAT.md

> Lido AO VIVO a cada poll de heartbeat (sessão isolada). Avise no
> {{INTERFACE_PLATFORM}} SOMENTE se houver novidade relevante; senão responda
> exatamente `HEARTBEAT_OK`.
> Quieto à noite ({{QUIET_HOURS_START}}–{{QUIET_HOURS_END}} {{USER_TIMEZONE_ABBR}}):
> não poste salvo urgência (mas ainda atualize o seen-file).

## Dedup (obrigatório)
- Estado em `{{HEARTBEAT_SEEN_FILE}}`. Só avise um item cujo id/url NÃO esteja lá; depois
  adicione o id e salve. Mantenha ~100 ids por lista (descarte os mais antigos).

## Checagens (ajuste ao seu agente)
<!-- Adicione o que faz sentido. Exemplos:
### 1. E-mail — urgentes não lidos
### 2. Agenda — eventos nas próximas 24-48h
### 3. Notícias/menções relevantes — throttle ≥ 2h
-->
- (a definir)

## Saída
- Com novidades: UMA mensagem curta agrupando tudo.
- Sem nada: `HEARTBEAT_OK`.
