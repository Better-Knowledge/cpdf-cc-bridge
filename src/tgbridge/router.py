"""Namespace split + passthrough. Função pura, testável."""
from .providers import RESERVED


def classify(text: str):
    """
    Classifica uma mensagem em (kind, payload):
      - ("reserved", cmd)      -> comando do bot (RESERVED)
      - ("passthrough", text)  -> enviar verbatim ao agente no tmux
      - ("prompt", text)       -> texto comum, vira prompt no tmux

    Regras:
      - "!x"   -> força passthrough; "!status" vira "/status" (escape de colisão).
      - "/foo" reservado -> ("reserved", "foo").
      - "/foo" não reservado -> ("passthrough", "/foo").
      - texto comum -> ("prompt", texto).
    """
    t = (text or "").strip()
    if not t:
        return ("prompt", "")

    if t.startswith("!"):
        rest = t[1:].lstrip()
        if rest and not rest.startswith("/"):
            rest = "/" + rest
        return ("passthrough", rest)

    if t.startswith("/"):
        cmd = t[1:].split()[0].split("@")[0].lower() if len(t) > 1 else ""
        if cmd in RESERVED:
            return ("reserved", cmd)
        return ("passthrough", t)

    return ("prompt", t)
