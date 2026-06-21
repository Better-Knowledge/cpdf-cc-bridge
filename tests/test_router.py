from tgbridge.router import classify


def test_plain_text_is_prompt():
    assert classify("quantos clientes na etapa proposta?") == (
        "prompt", "quantos clientes na etapa proposta?")


def test_reserved_command():
    assert classify("/status") == ("reserved", "status")
    assert classify("/schedule cron 0 9 * * 1-5 | g | p") == ("reserved", "schedule")


def test_reserved_strips_botname():
    assert classify("/status@alice_bot") == ("reserved", "status")


def test_unknown_slash_is_passthrough():
    assert classify("/compact") == ("passthrough", "/compact")
    assert classify("/cost") == ("passthrough", "/cost")


def test_bang_forces_passthrough_of_reserved_name():
    # !status deve virar /status enviado ao agente
    assert classify("!status") == ("passthrough", "/status")
    assert classify("!/status") == ("passthrough", "/status")


def test_empty():
    assert classify("   ") == ("prompt", "")
