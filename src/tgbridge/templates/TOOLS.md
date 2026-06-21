# TOOLS.md - Local Notes

Skills define *how* tools work. This file is for *your* specifics — the stuff that's
unique to your setup. Mantenha enxuto; cresça conforme conectar ferramentas.

## Chat Logs (registro de conversas)
- Configure hooks de transcript em `.claude/settings.json` se quiser arquivar sessões.
- Saída sugerida: `chat_logs/` (privado — já no `.gitignore`).

## TTS / Voz
- Backend de voz: `{{VOICE_BACKEND}}` (escolhido no nascimento).
- Trigger sugerido: quando {{USER_CALL_NAME}} pedir resposta em áudio.
- Idioma padrão: {{USER_LANGUAGE}}.

## Python local
- Use `python3` (ou um venv dedicado em `/opt/<agente>-venvs/...` se precisar de libs).
- Segredos em `{{SECRETS_DIR_PATH}}` (uso pelos scripts; **nunca leia/exponha o conteúdo**).

## Integrações de domínio
<!-- Adicione aqui conforme conectar: Google (Calendar/Drive/Gmail), X/Twitter, CRM,
     ClickUp, etc. Documente venv, scopes, regras de impersonação e onde fica cada segredo.
     Ex.:
     ## Google Calendar
     - Python: /opt/<agente>-venvs/google/bin/python3
     - Credenciais: .secrets/google-service-account.json
     - Scope/impersonação: ...
-->
- (a definir)

---

Add whatever helps you do your job. This is your cheat sheet.
