"""Registro de providers — torna a bridge reproduzível para outros agentes CLI."""
from dataclasses import dataclass, field

RESERVED = {
    "start", "help", "status", "stop", "screenshot",
    "schedule", "schedules", "unschedule",
}


@dataclass
class Provider:
    name: str
    launch_cmd: str
    output_mode: str  # "hooks" (push) | "poll" (pull)
    reserved_cmds: set = field(default_factory=lambda: set(RESERVED))
    passthrough: bool = True


REGISTRY = {
    "claude": Provider(name="claude", launch_cmd="claude", output_mode="hooks"),
    # Fase 5: "codex" em output_mode="poll".
}


def get(name: str) -> Provider:
    return REGISTRY.get(name) or REGISTRY["claude"]
