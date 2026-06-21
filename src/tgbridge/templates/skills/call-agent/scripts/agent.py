#!/usr/bin/env python3
"""Cliente A2A (stdlib) — fala com outros agentes via o endpoint /message deles.

Lê o roster de `agents-registry.json` (no workspace) e usa A2A_SECRET/AGENT_NAME do ambiente.

Uso:
  agent.py list
  agent.py ask <nome> "<mensagem>"
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request


def _read_secret(name: str) -> str:
    """Segredo do env ou, nas sessões efêmeras (env limpo por anti-exfil), de um arquivo
    restrito. Caminho via A2A_SECRET_FILE; senão CLAUDE_CONFIG_DIR/bridge.secret (linhas K=V)."""
    v = os.environ.get(name, "")
    if v:
        return v
    path = os.environ.get("A2A_SECRET_FILE") or os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR", "/config"), "bridge.secret")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, _, val = line.partition("=")
                if k.strip() == name:
                    return val.strip()
    except OSError:
        pass
    return ""


def _find_registry() -> str:
    """Localiza agents-registry.json SEM depender do CWD (agnóstico a runtime/skill dir):
    (1) AGENT_WORKSPACE, (2) subindo a partir deste script (o registry vive na raiz do
    workspace do agente), (3) CWD."""
    cands = []
    ws = os.environ.get("AGENT_WORKSPACE")
    if ws:
        cands.append(pathlib.Path(ws) / "agents-registry.json")
    cands += [p / "agents-registry.json" for p in pathlib.Path(__file__).resolve().parents]
    cands.append(pathlib.Path.cwd() / "agents-registry.json")
    for c in cands:
        if c.is_file():
            return str(c)
    return str(cands[0])


REGISTRY = _find_registry()
SECRET = _read_secret("A2A_SECRET")
ME = os.environ.get("AGENT_NAME", "agente")


def _peer_secret(name: str) -> str:
    """Segredo de inbound do agente ALVO (modelo por-agente). Vem de
    A2A_PEER_SECRETS='alvo:segredo,alvo2:segredo2' (env ou bridge.secret).
    Vazio → cai no SECRET próprio (modelo de segredo compartilhado)."""
    for pair in _read_secret("A2A_PEER_SECRETS").split(","):
        k, _, v = pair.partition(":")
        if k.strip() == name:
            return v.strip()
    return ""


class A2AError(RuntimeError):
    """Erro de A2A (registry ausente, agente desconhecido, falha HTTP). Importável."""


def _load_registry():
    try:
        return json.load(open(REGISTRY, encoding="utf-8")).get("agents", [])
    except Exception as e:
        raise A2AError(f"não consegui ler {REGISTRY}: {e}")


# ---- API importável (p/ wrappear como tool em SDKs code-first: OpenAI Agents SDK,
# Google ADK, Claude Agent SDK). O CLI abaixo é só um wrapper fino sobre estas funções. ----

def list_agents() -> list:
    """Roster de agentes (do agents-registry.json): [{name, url, description}, ...]."""
    return _load_registry()


def ask(name: str, message: str, timeout: float = 180.0) -> str:
    """Pergunta a outro agente via A2A e retorna a resposta (texto puro). Levanta A2AError.
    Ex.: `from agent import ask; resposta = ask("<agente>", "<pergunta>")`."""
    if os.environ.get("A2A_INBOUND"):
        raise A2AError("recusado: A2A_INBOUND ativo — você está respondendo a outro agente; não encaminhe adiante.")
    agents = {a["name"]: a for a in _load_registry()}
    if name not in agents:
        raise A2AError(f"agente '{name}' não está no registry. Use: list_agents()")
    url = agents[name]["url"].rstrip("/") + "/message"
    bearer = _peer_secret(name) or SECRET   # segredo do ALVO (por-agente) ou fallback compartilhado
    data = json.dumps({"from": ME, "message": message}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {bearer}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise A2AError(f"erro {e.code} de {name}: {e.read().decode()[:300]}")
    except Exception as e:
        raise A2AError(f"falha falando com {name} em {url}: {e}")
    return (out.get("answer") or "").strip()


def cmd_list():
    for a in list_agents():
        print(f"- {a['name']}: {a.get('description','')}  ({a.get('url','')})")


def cmd_ask(name, message):
    ans = ask(name, message)
    print(ans if ans else "(sem resposta)")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit("uso: agent.py list | ask <nome> \"<mensagem>\"")
    try:
        if a[0] == "list":
            cmd_list()
        elif a[0] == "ask" and len(a) >= 3:
            cmd_ask(a[1], " ".join(a[2:]))
        else:
            sys.exit("uso: agent.py list | ask <nome> \"<mensagem>\"")
    except A2AError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
