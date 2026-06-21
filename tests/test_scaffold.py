import os

from tgbridge import scaffold


def _read(target, *parts):
    p = target
    for x in parts:
        p = p / x
    return p.read_text(encoding="utf-8")


def test_init_voice_openai_default(tmp_path):
    target = scaffold.init("demo-oai", base_dir=str(tmp_path), voice="openai")
    env = _read(target, ".env")
    assert "VOICE_BACKEND=openai" in env
    assert "OPENAI_API_KEY=" in env
    assert "api.openai.com" in env
    assert "ffmpeg" not in _read(target, "Dockerfile")
    assert "--extra voice-openai" in _read(target, "workspace", "entrypoint.sh")
    # nuvem não usa rede compartilhada
    assert "tgbridge-net" not in _read(target, "docker-compose.yml")


def test_init_voice_local(tmp_path):
    target = scaffold.init("demo-local", base_dir=str(tmp_path), voice="local")
    env = _read(target, ".env")
    assert "VOICE_BACKEND=local" in env
    assert "WHISPER_MODEL=small" in env
    assert "ffmpeg" in _read(target, "Dockerfile")
    assert "--extra voice-local" in _read(target, "workspace", "entrypoint.sh")
    assert "tgbridge-net" not in _read(target, "docker-compose.yml")


def test_init_voice_shared(tmp_path):
    target = scaffold.init("demo-shared", base_dir=str(tmp_path), voice="shared")
    env = _read(target, ".env")
    # roda no backend openai, mas apontando para o whisper interno
    assert "VOICE_BACKEND=openai" in env
    assert "OPENAI_BASE_URL=http://whisper:8000/v1" in env
    assert "OPENAI_API_KEY=local" in env
    assert "ffmpeg" not in _read(target, "Dockerfile")
    assert "--extra voice-openai" in _read(target, "workspace", "entrypoint.sh")
    compose = _read(target, "docker-compose.yml")
    assert "tgbridge-net" in compose
    assert "external: true" in compose


def test_init_voice_off(tmp_path):
    target = scaffold.init("demo-off", base_dir=str(tmp_path), voice="off")
    assert "VOICE_BACKEND=off" in _read(target, ".env")
    assert "ffmpeg" not in _read(target, "Dockerfile")
    assert "--extra" not in _read(target, "workspace", "entrypoint.sh")
    assert "tgbridge-net" not in _read(target, "docker-compose.yml")


def test_whisper_init(tmp_path):
    target = scaffold.whisper_init(base_dir=str(tmp_path))
    for f in ("app.py", "Dockerfile", "docker-compose.yml", "pyproject.toml", "README.md", ".env"):
        assert (target / f).exists(), f
    assert "/v1/audio/transcriptions" in (target / "app.py").read_text()
    assert "tgbridge-net" in (target / "docker-compose.yml").read_text()


def test_env_documents_peer_secrets(tmp_path):
    target = scaffold.init("a2a-peer", base_dir=str(tmp_path), voice="off")
    env = _read(target, ".env")
    assert "A2A_PEER_SECRETS=" in env       # modelo por-agente documentado no .env


def test_blocklists_scrub_peer_secrets():
    from tgbridge import config
    assert "A2A_PEER_SECRETS" in config.DEFAULT_EPHEMERAL_BLOCKLIST
    assert "A2A_PEER_SECRETS" in config.DEFAULT_CRON_BLOCKLIST   # peer secrets fora das sessões efêmeras


def test_init_materializes_soul(tmp_path):
    target = scaffold.init("alma", base_dir=str(tmp_path), voice="off")
    ws = target / "workspace"
    for f in ("IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "HEARTBEAT.md"):
        assert (ws / f).exists(), f
    # CLAUDE.md é orquestrador leve com @-includes
    claude = _read(target, "workspace", "CLAUDE.md")
    assert "@IDENTITY.md" in claude and "@AGENTS.md" in claude
    # gitignore do workspace protege PII + estrutura via .gitkeep
    gi = _read(ws, ".gitignore")
    assert "memory/**" in gi and "USER.md" in gi
    # memória hierárquica
    assert (ws / "memory" / "INDEX.md").exists()
    assert (ws / "memory" / "topics" / ".gitkeep").exists()
    assert (ws / "memory" / "daily").is_dir()
    assert list((ws / "memory" / "daily").glob("*.md")), "log de hoje não criado"
    # projetos
    assert (ws / "projects" / "INDEX.md").exists()
    assert (ws / "projects" / "leads" / "INDEX.md").exists()
    assert (ws / "projects" / ".gitkeep").exists()
    # scripts utilitários executáveis
    regen = ws / "scripts" / "regen-indexes.sh"
    assert regen.exists() and os.access(regen, os.X_OK)
    assert (ws / "scripts" / "backup-data.sh").exists()


def test_tokens_override_and_no_unrendered(tmp_path):
    target = scaffold.init("zelo", base_dir=str(tmp_path), voice="off",
                           tokens={"USER_CALL_NAME": "Dana", "AGENT_EMOJI": "⚡",
                                   "AGENT_ROLE_ONELINE": "copiloto pessoal"})
    ws = target / "workspace"
    assert "Dana" in _read(ws, "USER.md")
    assert "⚡" in _read(ws, "IDENTITY.md")
    assert "copiloto pessoal" in _read(ws, "CLAUDE.md")
    # nenhum placeholder {{...}} sobrando nos arquivos renderizados
    for f in ("CLAUDE.md", "AGENTS.md", "USER.md", "IDENTITY.md", "SOUL.md",
              "TOOLS.md", "HEARTBEAT.md"):
        assert "{{" not in _read(ws, f), f


def test_bootstrap_flag(tmp_path):
    with_bs = scaffold.init("combs", base_dir=str(tmp_path), voice="off", bootstrap=True)
    assert (with_bs / "workspace" / "BOOTSTRAP.md").exists()
    without = scaffold.init("nobs", base_dir=str(tmp_path), voice="off")
    assert not (without / "workspace" / "BOOTSTRAP.md").exists()


def test_create_if_missing_preserves_personal(tmp_path):
    target = scaffold.init("grow", base_dir=str(tmp_path), voice="off")
    user_md = target / "workspace" / "USER.md"
    user_md.write_text("# meus dados pessoais reais\n", encoding="utf-8")
    # reexecutar (force) não pode clobberar o USER.md já preenchido
    scaffold.init("grow", base_dir=str(tmp_path), voice="off", force=True)
    assert "meus dados pessoais reais" in user_md.read_text(encoding="utf-8")


def test_secret_is_random(tmp_path):
    a = scaffold.init("a", base_dir=str(tmp_path), voice="off")
    b = scaffold.init("b", base_dir=str(tmp_path), voice="off")
    sa = [l for l in _read(a, ".env").splitlines() if l.startswith("BRIDGE_HOOK_SECRET=")][0]
    sb = [l for l in _read(b, ".env").splitlines() if l.startswith("BRIDGE_HOOK_SECRET=")][0]
    assert sa != sb
