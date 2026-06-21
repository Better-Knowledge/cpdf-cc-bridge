#!/usr/bin/env python3
"""Cliente de agendamento do tgbridge (stdlib apenas).

Fala com o endpoint local do bridge para criar/listar/remover jobs. Lê
BRIDGE_HTTP_PORT e BRIDGE_HOOK_SECRET do ambiente (injetados no container).

Uso:
  schedule.py add --when "cron 0 9 * * *" --prompt "..." [--label briefing]
  schedule.py add --when "at 2026-06-16T14:00" --prompt "..." [--label lembrete]
  schedule.py list
  schedule.py remove --id <job_id>
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _read_secret(name: str) -> str:
    """Segredo do env ou, nas sessões efêmeras (env limpo por anti-exfil), de um
    arquivo restrito em CLAUDE_CONFIG_DIR/bridge.secret (linhas K=V)."""
    v = os.environ.get(name, "")
    if v:
        return v
    path = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", "/config"), "bridge.secret")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, _, val = line.partition("=")
                if k.strip() == name:
                    return val.strip()
    except OSError:
        pass
    return ""


PORT = os.environ.get("BRIDGE_HTTP_PORT", "8787")
SECRET = _read_secret("BRIDGE_HOOK_SECRET")
BASE = f"http://127.0.0.1:{PORT}"


def _req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {SECRET}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"erro {e.code}: {e.read().decode()[:300]}")
    except Exception as e:  # conexão recusada etc.
        sys.exit(f"falha falando com o bridge em {BASE}: {e}")


def main() -> None:
    # Anti-loop/anti-escalada: uma sessão A2A (resposta a outro agente) NÃO pode
    # agendar jobs — senão burlaria o depth-1 rodando algo sem o flag. (H2)
    if os.environ.get("A2A_INBOUND"):
        sys.exit("recusado: sessão A2A (A2A_INBOUND) não pode agendar jobs.")
    p = argparse.ArgumentParser(prog="schedule.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="cria um job")
    a.add_argument("--when", required=True, help='"cron <expr 5 campos>" ou "at <ISO8601>"')
    a.add_argument("--prompt", required=True, help="tarefa a executar no horário")
    a.add_argument("--label", default="job", help="rótulo curto (kebab-case)")

    sub.add_parser("list", help="lista os jobs")

    r = sub.add_parser("remove", help="remove um job")
    r.add_argument("--id", required=True)

    args = p.parse_args()
    if args.cmd == "add":
        out = _req("POST", "/schedule", {"when": args.when, "prompt": args.prompt, "label": args.label})
        print(f"✅ agendado: id={out.get('id')} ({out.get('descr')}) próximo={out.get('next_run')}")
    elif args.cmd == "list":
        out = _req("GET", "/schedules")
        jobs = out.get("jobs", [])
        if not jobs:
            print("(nenhum job agendado)")
        for j in jobs:
            print(f"- {j['id']} | {j.get('name')} | próximo: {j.get('next_run')}\n    → {j.get('prompt')}")
    elif args.cmd == "remove":
        out = _req("DELETE", f"/schedule/{args.id}")
        print(f"🗑️ removido: {out.get('removed')}")


if __name__ == "__main__":
    main()
