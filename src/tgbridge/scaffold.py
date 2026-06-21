"""Scaffold/operação reproduzível: `tgbridge init|attach|upgrade`.

Não depende das variáveis de ambiente do runtime (TELEGRAM_BOT_TOKEN etc.) —
`init`/`attach` rodam a partir de qualquer máquina com o pacote instalado.
"""
import os
import re
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

try:  # zoneinfo: padrão no 3.9+; fallback defensivo
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

VOICE_CHOICES = ("openai", "local", "shared", "off")

# bloco de rede externa adicionado ao compose do agente apenas no modo 'shared'
_NETWORKS_BLOCK = (
    "\nnetworks:\n"
    "  default:\n"
    "    name: tgbridge-net\n"
    "    external: true\n"
)

TEMPLATES = Path(__file__).parent / "templates"


def _find_project_root(start: Path) -> Path:
    """Sobe até achar o pyproject.toml — funciona no layout src/ e no flat."""
    p = start
    for _ in range(6):
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return start


# raiz do projeto (com pyproject.toml) — copiada para o workspace de cada agente
PKG_PROJECT = _find_project_root(Path(__file__).resolve().parent)
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", "*.db", "*.db-*", ".git", ".github",
    ".pytest_cache", "dist", "build", "*.egg-info",
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-") or "agente"


def _render(text: str, ctx: dict) -> str:
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def _write(dest: Path, tmpl: str, ctx: dict, *, executable: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_render((TEMPLATES / tmpl).read_text(encoding="utf-8"), ctx), encoding="utf-8")
    if executable:
        os.chmod(dest, 0o755)


def _write_if_absent(dest: Path, tmpl: str, ctx: dict, *, executable: bool = False) -> bool:
    """Materializa um template SÓ se o destino ainda não existe (create-if-missing).
    Protege dados pessoais de um agente já crescido ao reexecutar o scaffold."""
    if dest.exists():
        return False
    _write(dest, tmpl, ctx, executable=executable)
    return True


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")


# Abreviações de fuso que o tzdata expõe como numérico (-03); mapeie as comuns.
_TZ_ABBR = {"America/Sao_Paulo": "BRT", "America/Bahia": "BRT", "UTC": "UTC"}


def _tz_ctx(tz: str) -> dict:
    """Deriva tokens de fuso a partir do TZ (offset/abbr/comando/data de hoje)."""
    offset = "UTC"
    abbr = _TZ_ABBR.get(tz, "")
    today = ""
    if ZoneInfo is not None:
        try:
            now = datetime.now(ZoneInfo(tz))
            today = now.strftime("%Y-%m-%d")
            z = now.strftime("%z")  # +/-HHMM
            if z:
                offset = "UTC%+d" % (int(z[:3]),)
            if not abbr:
                name = now.strftime("%Z")
                abbr = name if name and not name[0] in "+-" else offset
        except Exception:
            pass
    if not abbr:
        abbr = offset
    return {
        "TZ": tz,
        "USER_TIMEZONE_OFFSET": offset,
        "USER_TIMEZONE_NAME": tz,
        "USER_TIMEZONE_ABBR": abbr,
        "TIMEZONE_COMMAND": "TZ='%s' date '+%%H:%%M %%Z — %%A, %%d/%%m/%%Y'" % tz,
        "TODAY": today or "1970-01-01",
    }


def _persona_defaults(name: str, tz: str) -> dict:
    """Defaults neutros para os tokens de alma/usuário — o agente nasce SEMPRE válido
    mesmo num scaffold sem entrevista; o `birth` sobrescreve via `tokens`."""
    TBD = "(a definir)"
    ctx = {
        "AGENT_ROLE_ONELINE": "agente operável por Telegram",
        "AGENT_EMOJI": "🤖",
        "AGENT_CREATURE": TBD + " — veja BOOTSTRAP.md",
        "AGENT_VIBE": TBD,
        "AGENT_AVATAR_FILENAME": "(sem avatar ainda)",
        "AGENT_AVATAR_DESCRIPTION": TBD,
        "AGENT_NAME_ETYMOLOGY": TBD,
        "AGENT_NAME_ORIGIN_STORY": "(O nome foi escolhido pelo seu humano.)",
        "USER_FULL_NAME": TBD,
        "USER_CALL_NAME": "seu humano",
        "USER_TELEGRAM_HANDLE": TBD,
        "USER_TELEGRAM_ID": TBD,
        "USER_PRONOUNS": TBD,
        "USER_LANGUAGE": "Português (BR)",
        "USER_LINKS": TBD,
        "USER_PROFESSION": TBD,
        "USER_HOBBIES": TBD,
        "USER_COMMUNICATION_STYLE": "Casual e direto.",
        "CONTAINER_WORKSPACE_PATH": "/home/%s" % name,
        "INTERFACE_PLATFORM": "Telegram via tgbridge",
        "CREDENTIALS_CONFIG_PATH": "/config",
        "SECRETS_DIR_PATH": ".secrets/",
        "HEARTBEAT_SEEN_FILE": "memory/heartbeat-seen.json",
        "QUIET_HOURS_START": "23h",
        "QUIET_HOURS_END": "08h",
    }
    ctx.update(_tz_ctx(tz))
    return ctx


def _materialize_soul(ws: Path, ctx: dict, *, bootstrap: bool = False) -> None:
    """Estampa a camada de alma + memória hierárquica + projetos no workspace.
    Tudo create-if-missing: nunca sobrescreve dados pessoais de um agente já crescido."""
    for fname in ("IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "HEARTBEAT.md"):
        _write_if_absent(ws / fname, fname, ctx)

    _write_if_absent(ws / ".gitignore", "workspace.gitignore", ctx)

    _write_if_absent(ws / "scripts" / "regen-indexes.sh", "scripts/regen-indexes.sh", ctx, executable=True)
    _write_if_absent(ws / "scripts" / "backup-data.sh", "scripts/backup-data.sh", ctx, executable=True)

    # memória: índice + template de tópico + estrutura de pastas (.gitkeep) + log de hoje
    _write_if_absent(ws / "memory" / "INDEX.md", "memory/INDEX.md", ctx)
    _write_if_absent(ws / "memory" / "topics" / "_TEMPLATE.md", "memory/topics/_TEMPLATE.md", ctx)
    for d in ("memory/topics", "memory/daily", "memory/archive", "projects"):
        (ws / d).mkdir(parents=True, exist_ok=True)
        _touch(ws / d / ".gitkeep")
    today_log = ws / "memory" / "daily" / ("%s.md" % ctx["TODAY"])
    if not today_log.exists():
        today_log.write_text("# %s — Daily Log\n" % ctx["TODAY"], encoding="utf-8")

    # projetos: índice mestre + leads + stubs (categoria/projeto)
    _write_if_absent(ws / "projects" / "INDEX.md", "projects/INDEX.md", ctx)
    _write_if_absent(ws / "projects" / "leads" / "INDEX.md", "projects/leads/INDEX.md", ctx)
    _write_if_absent(ws / "projects" / "_CATEGORY_INDEX.md", "projects/_CATEGORY_INDEX.md", ctx)
    _write_if_absent(ws / "projects" / "_PROJECT_README.md", "projects/_PROJECT_README.md", ctx)

    if bootstrap:
        _write_if_absent(ws / "BOOTSTRAP.md", "BOOTSTRAP.md", ctx)


def _prompt_voice() -> str:
    """Menu interativo de backend de voz. Sem TTY → 'openai' (padrão)."""
    if not sys.stdin.isatty():
        return "openai"
    print("\nBackend de voz (transcrição de áudios do Telegram):")
    print("  [1] openai — nuvem da OpenAI (padrão; só precisa OPENAI_API_KEY)")
    print("  [2] local  — faster-whisper neste container (+ffmpeg, imagem maior)")
    print("  [3] shared — container Whisper compartilhado, OpenAI-compatível (vários agentes)")
    print("  [4] off    — sem voz")
    choice = input("Escolha [1]: ").strip() or "1"
    return {"1": "openai", "2": "local", "3": "shared", "4": "off"}.get(choice, "openai")


def _voice_ctx(voice: str) -> dict:
    """Placeholders dependentes do backend de voz.
    'shared' e 'openai' usam o mesmo backend (openai); diferem em base_url/chave/rede."""
    base = {"FFMPEG_PKG": "", "UV_SYNC_EXTRA": "", "COMPOSE_NETWORKS": ""}
    if voice == "local":
        return {**base, "FFMPEG_PKG": " ffmpeg", "UV_SYNC_EXTRA": " --extra voice-local",
                "VOICE_ENV_BLOCK": (
                    "WHISPER_MODEL=small             # tiny|base|small|medium|large-v3\n"
                    "VOICE_LANGUAGE=pt")}
    if voice == "openai":
        return {**base, "UV_SYNC_EXTRA": " --extra voice-openai",
                "VOICE_ENV_BLOCK": (
                    "OPENAI_API_KEY=                 # <-- cole sua chave da OpenAI aqui\n"
                    "OPENAI_BASE_URL=https://api.openai.com/v1\n"
                    "OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe\n"
                    "VOICE_LANGUAGE=pt")}
    if voice == "shared":
        return {**base, "UV_SYNC_EXTRA": " --extra voice-openai",
                "COMPOSE_NETWORKS": _NETWORKS_BLOCK,
                "VOICE_ENV_BLOCK": (
                    "OPENAI_API_KEY=local            # = WHISPER_SECRET do whisper (se setado); senão dummy\n"
                    "OPENAI_BASE_URL=http://whisper:8000/v1\n"
                    "OPENAI_TRANSCRIBE_MODEL=whisper-1\n"
                    "VOICE_LANGUAGE=pt")}
    return {**base, "VOICE_ENV_BLOCK": "# (voz desativada — VOICE_BACKEND=off)"}


def _backend_value(voice: str) -> str:
    """Valor de VOICE_BACKEND no .env (runtime). 'shared' roda no backend 'openai'."""
    return "openai" if voice in ("openai", "shared") else voice


def _copy_pkg(dest: Path) -> None:
    """Copia o projeto tgbridge (pyproject + pacote) para o novo agente.

    Hoje é cópia (empacotamento fica para depois — ver HANDOFF-v3.md §6);
    quando publicado no PyPI, troque por um pin de versão no entrypoint.
    """
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PKG_PROJECT, dest, ignore=_COPY_IGNORE)


def init(name: str, base_dir: str | None = None, provider: str = "claude",
         force: bool = False, voice: str | None = None,
         tokens: dict | None = None, bootstrap: bool = False) -> Path:
    name = _slug(name)
    base = Path(base_dir or os.getcwd()).resolve()
    target = base / name
    if target.exists() and not force:
        raise SystemExit(f"{target} já existe — use --force para sobrescrever.")

    if voice is None:
        voice = _prompt_voice()
    if voice not in VOICE_CHOICES:
        raise SystemExit(f"--voice inválido: {voice} (use {'|'.join(VOICE_CHOICES)})")

    tz = (tokens or {}).get("TZ") or os.environ.get("TZ", "America/Sao_Paulo")
    ctx = {
        "NAME": name,
        "HOOK_SECRET": secrets.token_hex(32),
        "PORT": os.environ.get("BRIDGE_HTTP_PORT", "8787"),
        "PROVIDER": provider,
        "VOICE_BACKEND": _backend_value(voice),
        **_voice_ctx(voice),
        **_persona_defaults(name, tz),   # tokens de alma/usuário/fuso (defaults neutros)
    }
    if tokens:
        ctx.update(tokens)               # overrides do `birth` (nome do humano, emoji, etc.)

    ws = target / "workspace"
    (target / "config").mkdir(parents=True, exist_ok=True)

    # raiz do agente
    _write(target / "Dockerfile", "Dockerfile", ctx)
    _write(target / "docker-compose.yml", "docker-compose.yml", ctx)
    _write(target / ".dockerignore", "dockerignore", ctx)
    _write(target / ".env", "env.example", ctx)
    os.chmod(target / ".env", 0o600)   # contém bot token, A2A_SECRET, chave do CRM
    _write(target / "README.md", "README.md", ctx)

    # workspace (-> /home/<name>)
    _write(ws / "CLAUDE.md", "CLAUDE.md", ctx)
    _write(ws / ".mcp.json", "mcp.json", ctx)
    _write(ws / "entrypoint.sh", "entrypoint.sh", ctx, executable=True)
    _write(ws / ".claude" / "settings.json", "claude-settings.json", ctx)

    # skills empacotadas -> .agents/skills/ (local CANÔNICO vendor-neutro do padrão aberto
    # Agent Skills: Codex CLI e Gemini CLI descobrem aqui direto). .claude/skills é um ALIAS
    # (symlink) p/ o Claude Code descobrir o mesmo folder. As skills referenciam seus próprios
    # scripts via ${CLAUDE_SKILL_DIR} (dir do SKILL.md) → não há symlink `skills/` na raiz.
    skills_src = TEMPLATES / "skills"
    if skills_src.is_dir():
        shutil.copytree(skills_src, ws / ".agents" / "skills", dirs_exist_ok=True)
        alias = ws / ".claude" / "skills"            # Claude lê .claude/skills (segue o symlink)
        if not alias.exists():
            alias.symlink_to("../.agents/skills")     # relativo a .claude/ → ../.agents/skills

    # registry A2A (renderizado com o nome do agente)
    _write(ws / "agents-registry.json", "agents-registry.json", ctx)

    # pacote da bridge
    _copy_pkg(ws / "tgbridge")

    # camada de alma + memória hierárquica + projetos (create-if-missing)
    _materialize_soul(ws, ctx, bootstrap=bootstrap)

    print(f"✓ agente '{name}' criado em {target} (voz: {voice})")
    print("Próximos passos:")
    print(f"  cd {target}")
    key_hint = " + OPENAI_API_KEY" if voice == "openai" else ""
    print(f"  $EDITOR .env            # TELEGRAM_BOT_TOKEN, ALLOWED_USERS, CLAUDE_CODE_OAUTH_TOKEN{key_hint}")
    if voice == "shared":
        print("  ./install/tgbridge-install.sh whisper init   # (1ª vez) cria shared/whisper/")
        print(f"  ./install/tgbridge-install.sh up {name}      # garante rede + whisper, e sobe o agente")
    else:
        print("  docker compose up -d --build")
    print(f"  docker compose exec -it {name} claude   # login na 1ª vez")
    return target


def whisper_init(base_dir: str | None = None, force: bool = False) -> Path:
    """Renderiza o microserviço Whisper compartilhado em <root>/shared/whisper/."""
    base = Path(base_dir or os.getcwd()).resolve()
    target = base / "shared" / "whisper"
    if target.exists() and not force:
        print(f"shared/whisper já existe em {target} (use --force para sobrescrever).")
        return target
    target.mkdir(parents=True, exist_ok=True)
    src = TEMPLATES / "whisper"
    for fname in ("app.py", "Dockerfile", "docker-compose.yml", "pyproject.toml", "README.md"):
        shutil.copyfile(src / fname, target / fname)
    shutil.copyfile(src / "env.example", target / ".env")
    print(f"✓ whisper compartilhado criado em {target}")
    print("  suba com:  ./install/tgbridge-install.sh whisper up")
    return target


def _hook_cfg(config_dir: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        config_dir=(config_dir or os.environ.get("CLAUDE_CONFIG_DIR", "/config")),
        port=int(os.environ.get("BRIDGE_HTTP_PORT", "8787")),
    )


def attach(name: str, session: str, resume: str | None = None,
           config_dir: str | None = None, base_dir: str | None = None) -> None:
    """Acopla a bridge a um agente JÁ em execução: instala os hooks no
    CLAUDE_CONFIG_DIR do alvo e descreve como rodar a bridge contra a sessão
    tmux existente (e/ou o caminho headless `claude -p --resume`)."""
    from . import hooks_install

    name = _slug(name)
    cfg = _hook_cfg(config_dir)
    path = hooks_install.ensure(cfg)
    print(f"✓ hooks instalados em {path} (receiver 127.0.0.1:{cfg.port})")

    secret = secrets.token_hex(32)
    print("\nConfigure o ambiente da bridge (export ou .env):")
    print(f"  export TMUX_SESSION={session}")
    print(f"  export BRIDGE_HOOK_SECRET={secret}   # deve casar com o header dos hooks")
    print(f"  export BRIDGE_HTTP_PORT={cfg.port}")
    print("  export TELEGRAM_BOT_TOKEN=...  ALLOWED_USERS=...")
    print("\nSuba a bridge contra a sessão existente:")
    print("  tgbridge run            # (ou: uvx tgbridge run)")

    if resume:
        print("\nDisparo headless (cron/one-shot) sem TUI, retomando o contexto:")
        print(f'  claude -p --resume {resume} "<prompt>"')
        print("  -> a saída volta pelo hook Stop; sem hooks, leia o transcript (modo poll).")


def upgrade(config_dir: str | None = None) -> None:
    """Re-aplica os hooks (idempotente) após um bump de versão/migração de schema."""
    from . import hooks_install

    path = hooks_install.ensure(_hook_cfg(config_dir))
    print(f"✓ hooks atualizados em {path}")
