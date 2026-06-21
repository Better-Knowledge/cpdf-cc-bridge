"""Configuração via ambiente (injetado pelo env_file do docker-compose)."""
import os
import re

# Segredos de infra removidos do ambiente das sessões efêmeras para barrar
# exfiltração cross-agent sob injeção de prompt. Chaves de domínio
# (MENTORIA_CRM_API_KEY, OPENAI_API_KEY) NÃO entram aqui — o destino A2A ainda
# precisa delas (ex.: um agente que lê um CRM).
#
# Duas listas distintas:
#  - A2A (full): a sessão é mensagem NÃO-confiável e NÃO usa o Stop hook (captura
#    por arquivo), então remove os 3 segredos. Override por EPHEMERAL_ENV_BLOCKLIST.
#  - CRON: mantém BRIDGE_HOOK_SECRET — o Stop hook (a ENTREGA da saída do cron ao
#    Telegram) autentica no receiver com `${BRIDGE_HOOK_SECRET}`; sem ele → 401 →
#    o cron não entrega. Override por CRON_ENV_BLOCKLIST.
DEFAULT_EPHEMERAL_BLOCKLIST = ("A2A_SECRET", "A2A_PEER_SECRETS", "BRIDGE_HOOK_SECRET", "TELEGRAM_BOT_TOKEN")
DEFAULT_CRON_BLOCKLIST = ("A2A_SECRET", "A2A_PEER_SECRETS", "TELEGRAM_BOT_TOKEN")


def _blocklist(env_var: str, default) -> list[str]:
    raw = os.environ.get(env_var, "")
    if raw.strip():
        return [v.strip() for v in raw.split(",") if v.strip()]
    return list(default)


def ephemeral_blocklist() -> list[str]:
    """Blocklist das sessões A2A (scrub completo dos 3 segredos de infra)."""
    return _blocklist("EPHEMERAL_ENV_BLOCKLIST", DEFAULT_EPHEMERAL_BLOCKLIST)


def cron_blocklist() -> list[str]:
    """Blocklist das sessões de cron (mantém BRIDGE_HOOK_SECRET p/ o Stop hook entregar)."""
    return _blocklist("CRON_ENV_BLOCKLIST", DEFAULT_CRON_BLOCKLIST)


def _derive_session() -> str:
    name = os.path.basename(os.getcwd().rstrip("/")) or "claude"
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


class Config:
    def __init__(self) -> None:
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        allowed = os.environ.get("ALLOWED_USERS", "").replace(" ", "")
        self.allowed_users = [int(x) for x in allowed.split(",") if x]
        self.hook_secret = os.environ.get("BRIDGE_HOOK_SECRET", "").strip()
        self.port = int(os.environ.get("BRIDGE_HTTP_PORT", "8787"))
        self.tmux_session = os.environ.get("TMUX_SESSION", "").strip() or _derive_session()
        self.default_provider = os.environ.get("DEFAULT_PROVIDER", "claude").strip()
        self.tz = os.environ.get("TZ", "America/Sao_Paulo").strip()
        self.config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "/config").strip()

        # Voz (plugável) — backend off|local|openai. Sem chave != erro fatal:
        # tratado em runtime quando chega um áudio.
        self.voice_backend = os.environ.get("VOICE_BACKEND", "off").strip().lower()
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        self.openai_transcribe_model = os.environ.get(
            "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip()
        self.whisper_model = os.environ.get("WHISPER_MODEL", "small").strip()
        self.voice_language = os.environ.get("VOICE_LANGUAGE", "pt").strip()

        # Monitoramento (Fase 2): avisos de subagente/tarefa no Telegram.
        self.monitor_events = os.environ.get("MONITOR_EVENTS", "on").strip().lower() != "off"

        # Scheduler: workspace (cwd) das sessões efêmeras de cron + sentinelas suprimidos.
        self.workspace = os.environ.get("AGENT_WORKSPACE", "").strip()
        self.suppress_sentinels = [
            s.strip().upper()
            for s in os.environ.get("SUPPRESS_SENTINELS", "NO_NEWS,HEARTBEAT_OK,A2A_DONE").split(",")
            if s.strip()
        ]

        # Sessões efêmeras (cron/A2A): segredos de infra removidos do ambiente.
        self.ephemeral_env_blocklist = ephemeral_blocklist()

        # A2A (comunicação entre agentes): servidor separado na rede compartilhada.
        self.agent_name = (os.environ.get("AGENT_NAME", "").strip() or self.tmux_session)
        self.a2a_secret = os.environ.get("A2A_SECRET", "").strip()
        self.a2a_port = int(os.environ.get("A2A_PORT", "8788"))
        self.a2a_notify = os.environ.get("A2A_NOTIFY", "on").strip().lower() != "off"
        self.a2a_enabled = bool(self.a2a_secret)
        # Allowlist de remetentes (csv). Vazio = derivar do agents-registry.json
        # (fallback: aceita qualquer remetente autenticado, com warn).
        self.a2a_allowed_senders = [
            s.strip() for s in os.environ.get("A2A_ALLOWED_SENDERS", "").split(",") if s.strip()
        ]
        # Rate-limit por remetente: no máx. N chamadas por janela (s); cada chamada
        # abre uma sessão claude (cara), então a concorrência global é serializada.
        self.a2a_rate_max = int(os.environ.get("A2A_RATE_MAX", "30"))
        self.a2a_rate_window = float(os.environ.get("A2A_RATE_WINDOW", "300"))

        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.environ.get("TGBRIDGE_DATA_DIR", project_dir)
        self.state_db = os.path.join(self.data_dir, "state.db")
        self.jobs_db = os.path.join(self.data_dir, "jobs.db")

        if not self.bot_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN ausente no ambiente.")
        if not self.allowed_users:
            raise SystemExit("ALLOWED_USERS vazio — defina os ids autorizados no .env.")
        if not self.hook_secret:
            raise SystemExit("BRIDGE_HOOK_SECRET ausente — defina no .env.")

    @property
    def default_chat_id(self) -> int:
        return self.allowed_users[0]
