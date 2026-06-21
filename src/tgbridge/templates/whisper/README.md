# Whisper compartilhado (tgbridge)

Microserviço faster-whisper com **endpoint compatível com a API da OpenAI**
(`POST /v1/audio/transcriptions`). Sobe **uma vez** e atende vários agentes pela rede
Docker `tgbridge-net`, economizando disco (um modelo) e RAM (um processo).

## Subir

```bash
# pela raiz dos agentes (recomendado — garante a rede e sobe se estiver fora):
./install/tgbridge-install.sh whisper up

# ou manualmente:
docker network create tgbridge-net 2>/dev/null || true
cp .env.example .env        # ajuste WHISPER_MODEL se quiser
docker compose up -d --build
```

## Como os agentes usam

Crie o agente com `tgbridge init <nome> --voice shared`. Isso configura no `.env` do agente:

```ini
VOICE_BACKEND=openai
OPENAI_BASE_URL=http://whisper:8000/v1
OPENAI_API_KEY=local            # dummy — o serviço ignora a autenticação
```

E o `./install/tgbridge-install.sh up <nome>` garante este serviço no ar antes de subir o agente.

## Saúde / logs

```bash
./install/tgbridge-install.sh whisper status
docker compose logs -f whisper
```
