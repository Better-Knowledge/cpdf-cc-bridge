"""Escreve os hooks HTTP + allowlists no settings.json do CLAUDE_CONFIG_DIR.
Idempotente. Único módulo que escreve em settings. Desliga o plugin telegram
do Channels (senão briga pelo bot token → 409)."""
import json
import os

_PLUGIN = "telegram@claude-plugins-official"
_SIMPLE_EVENTS = [
    "Stop", "SessionStart", "SessionEnd",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
]


def settings_path(cfg) -> str:
    return os.path.join(cfg.config_dir, "settings.json")


def build_hooks(cfg) -> dict:
    handler = {
        "type": "http",
        "url": f"http://127.0.0.1:{cfg.port}/event",
        "timeout": 5,
        # X-Tgbridge-Cron-Label: rótulo do cron interpolado do env da sessão. Presente
        # (não-vazio) só nas sessões efêmeras de cron → o receiver injeta cron_label no
        # payload e o notifier colhe a sessão no Stop. Var ausente (sessão principal) →
        # header vai vazio, hook dispara normal (não quebra a entrega).
        "headers": {
            "Authorization": "Bearer ${BRIDGE_HOOK_SECRET}",
            "X-Tgbridge-Cron-Label": "${TGBRIDGE_CRON_LABEL}",
        },
        "allowedEnvVars": ["BRIDGE_HOOK_SECRET", "TGBRIDGE_CRON_LABEL"],
    }
    hooks = {ev: [{"hooks": [handler]}] for ev in _SIMPLE_EVENTS}
    hooks["Notification"] = [{"matcher": "permission_prompt", "hooks": [handler]}]
    return hooks


def ensure(cfg) -> str:
    path = settings_path(cfg)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}

    data["hooks"] = build_hooks(cfg)
    data["allowedHttpHookUrls"] = [f"http://127.0.0.1:{cfg.port}/*"]
    data["httpHookAllowedEnvVars"] = ["BRIDGE_HOOK_SECRET", "TGBRIDGE_CRON_LABEL"]

    plugins = data.get("enabledPlugins") or {}
    plugins[_PLUGIN] = False  # desliga o Channels do Telegram
    data["enabledPlugins"] = plugins

    # Auto-aprova servidores MCP do projeto (aprovação é decisão de escopo de
    # usuário) — evita o prompt "New MCP server found" travar a sessão headless.
    data["enableAllProjectMcpServers"] = True

    os.makedirs(cfg.config_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path
