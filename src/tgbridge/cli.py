"""Entrypoints da CLI: run, hook-install, init, attach, upgrade.

`run`/`hook-install` precisam do ambiente do runtime (Config). `init`/`attach`/
`upgrade` são utilitários de scaffold/operação e NÃO exigem TELEGRAM_BOT_TOKEN etc.
"""
import argparse
import asyncio
import sys

_USAGE = "uso: tgbridge [run|hook-install|init|attach|upgrade|whisper]"


def _parse_tokens_file(path: str) -> dict:
    """Lê um arquivo KEY=VALUE (uma linha por token) p/ preencher a persona no init.
    Ignora linhas vazias/comentários; valor pode conter '='."""
    out: dict = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def main() -> None:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "run"
    rest = argv[1:]

    if cmd == "run":
        from .config import Config
        from .app import run

        asyncio.run(run(Config()))
        return

    if cmd == "hook-install":
        from .config import Config
        from . import hooks_install

        print(f"hooks instalados em {hooks_install.ensure(Config())}")
        return

    if cmd == "init":
        p = argparse.ArgumentParser(prog="tgbridge init")
        p.add_argument("name", help="nome do novo agente (vira pasta + sessão tmux)")
        p.add_argument("--dir", default=None, help="diretório base (default: cwd)")
        p.add_argument("--provider", default="claude")
        p.add_argument("--voice", choices=["openai", "local", "shared", "off"], default=None,
                       help="backend de voz (sem isto, pergunta interativamente; padrão openai)")
        p.add_argument("--force", action="store_true", help="sobrescreve se já existir")
        p.add_argument("--tokens", default=None,
                       help="arquivo KEY=VALUE p/ preencher a persona (nome do humano, emoji, fuso...)")
        p.add_argument("--bootstrap", action="store_true",
                       help="escreve BOOTSTRAP.md (o agente cria a persona na 1ª sessão)")
        a = p.parse_args(rest)
        from . import scaffold

        tokens = _parse_tokens_file(a.tokens) if a.tokens else None
        scaffold.init(a.name, base_dir=a.dir, provider=a.provider, force=a.force,
                      voice=a.voice, tokens=tokens, bootstrap=a.bootstrap)
        return

    if cmd == "attach":
        p = argparse.ArgumentParser(prog="tgbridge attach")
        p.add_argument("name", help="nome lógico do agente alvo")
        p.add_argument("--session", required=True, help="sessão tmux existente")
        p.add_argument("--resume", default=None, help="session-id p/ claude -p --resume")
        p.add_argument("--config-dir", default=None, help="CLAUDE_CONFIG_DIR do alvo")
        p.add_argument("--dir", default=None)
        a = p.parse_args(rest)
        from . import scaffold

        scaffold.attach(a.name, session=a.session, resume=a.resume,
                        config_dir=a.config_dir, base_dir=a.dir)
        return

    if cmd == "whisper":
        sub = rest[0] if rest else ""
        if sub != "init":
            print("uso: tgbridge whisper init [--dir D] [--force]")
            sys.exit(2)
        p = argparse.ArgumentParser(prog="tgbridge whisper init")
        p.add_argument("--dir", default=None, help="raiz dos agentes (default: cwd)")
        p.add_argument("--force", action="store_true")
        a = p.parse_args(rest[1:])
        from . import scaffold

        scaffold.whisper_init(base_dir=a.dir, force=a.force)
        return

    if cmd == "upgrade":
        p = argparse.ArgumentParser(prog="tgbridge upgrade")
        p.add_argument("--config-dir", default=None)
        a = p.parse_args(rest)
        from . import scaffold

        scaffold.upgrade(config_dir=a.config_dir)
        return

    print(f"comando desconhecido: {cmd}\n{_USAGE}")
    sys.exit(2)
