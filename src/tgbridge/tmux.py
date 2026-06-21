"""Camada fina sobre o tmux: injeta keystrokes e lê o pane. Sem shell=True."""
import asyncio
import re

_NORM = re.compile(r"[^a-zA-Z0-9_-]")


def norm(session: str) -> str:
    return _NORM.sub("-", session)


async def _run(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "tmux", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def send_text(session: str, text: str) -> None:
    """Envia texto literal e depois Enter (tecla separada), preservando caracteres especiais."""
    s = norm(session)
    if text:
        await _run("send-keys", "-t", s, "-l", "--", text)
        await asyncio.sleep(0.05)
    await _run("send-keys", "-t", s, "Enter")


async def send_keys(session: str, *keys: str) -> None:
    await _run("send-keys", "-t", norm(session), *keys)


async def interrupt(session: str) -> None:
    """Freio de mão: Escape (duas vezes por robustez)."""
    s = norm(session)
    await _run("send-keys", "-t", s, "Escape")
    await asyncio.sleep(0.1)
    await _run("send-keys", "-t", s, "Escape")


async def capture(session: str, lines: int = 40) -> str:
    rc, out, err = await _run("capture-pane", "-t", norm(session), "-p", "-S", f"-{lines}")
    return out if rc == 0 else f"(capture-pane falhou: {err.strip()})"


async def has_session(session: str) -> bool:
    rc, _, _ = await _run("has-session", "-t", norm(session))
    return rc == 0


async def new_session(session, cwd: str, cmd="claude", x: int = 200, y: int = 50,
                      env_unset=None, env_set=None) -> None:
    """Cria uma sessão tmux destacada rodando `cmd` em `cwd`.

    `cmd` pode ser str (rodado via shell pelo tmux) ou list/tuple de argv (exec direto,
    sem shell — evita quoting de argumentos com espaços, ex.: --append-system-prompt).
    `env_unset`/`env_set` (sessões efêmeras de cron/A2A) prefixam com `env -u … K=V …`
    para limpar segredos herdados e injetar flags (anti-exfil cross-agent)."""
    base = ["new-session", "-d", "-s", norm(session), "-c", cwd, "-x", str(x), "-y", str(y)]
    prefix = []
    if env_unset or env_set:
        prefix = ["env"]
        for v in (env_unset or []):
            if v:
                prefix += ["-u", v]
        for k, val in (env_set or {}).items():
            prefix.append(f"{k}={val}")
    if isinstance(cmd, (list, tuple)):
        await _run(*base, *prefix, *cmd)
    else:
        await _run(*base, *prefix, cmd)


async def kill_session(session: str) -> None:
    await _run("kill-session", "-t", norm(session))


async def list_sessions() -> list[str]:
    rc, out, _ = await _run("list-sessions", "-F", "#{session_name}")
    return out.split() if rc == 0 else []


async def set_option(session: str, name: str, value: str) -> None:
    """Define uma user-option do tmux (#{@name}) na sessão — marcador persistente no
    servidor tmux (sobrevive ao restart do processo da bridge)."""
    await _run("set-option", "-t", norm(session), name, value)


async def list_cron_meta() -> list[tuple[str, int, str]]:
    """(nome, epoch de criação, @cron) de cada sessão. @cron='' se não marcada.
    TAB como separador (nome é norm() → sem TAB; @cron idem)."""
    rc, out, _ = await _run(
        "list-sessions", "-F", "#{session_name}\t#{session_created}\t#{@cron}")
    if rc != 0:
        return []
    res = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].isdigit():
            res.append((p[0], int(p[1]), p[2] if len(p) > 2 else ""))
    return res


async def find_awaiting_permission(prefer: str = "") -> str | None:
    """Varre as sessões e retorna o nome da que está parada num prompt de permissão
    (pane contém o diálogo 'Do you want to …' + rodapé 'Esc to cancel'). Isso permite
    rotear o botão ✅/❌ do Telegram para a sessão CERTA que originou o pedido — inclusive
    sessões efêmeras de cron — em vez da sessão principal fixa. `prefer` é checada antes,
    como desempate quando há mais de uma aguardando."""
    names = await list_sessions()
    if prefer and prefer in names:
        names = [prefer] + [n for n in names if n != prefer]
    for name in names:
        low = (await capture(name, 40)).lower()
        if "do you want to" in low and "esc to cancel" in low:
            return name
    return None


async def wait_ready(session: str, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Espera o REPL do claude ficar pronto (poll do pane). Trata diálogos de
    abertura: 'trust this folder' (Enter) e o aviso do modo Bypass Permissions
    (seleciona '2. Yes, I accept'). Retorna True se ficou pronto.

    ⚠️ O aviso de Bypass contém '❯ 1. No, exit' — então PRECISA ser tratado ANTES
    do check genérico de '❯', senão wait_ready acha que já está pronto e o Enter
    seguinte confirma 'No, exit', matando a sessão."""
    waited = 0.0
    while waited < timeout:
        pane = await capture(session, 25)
        low = pane.lower()
        if "trust this folder" in low:
            await send_keys(session, "Enter")
            await asyncio.sleep(1.0)
            waited += 1.0
            continue
        if "bypass permissions mode" in low and "yes, i accept" in low:
            # Tela de aceitação (default = 'No, exit'); desce p/ 'Yes, I accept' e confirma.
            await send_keys(session, "Down")
            await asyncio.sleep(0.3)
            await send_keys(session, "Enter")
            await asyncio.sleep(1.2)
            waited += 1.5
            continue
        if "❯" in pane or "accept edits" in low or "shift+tab" in low:
            return True
        await asyncio.sleep(interval)
        waited += interval
    return False
