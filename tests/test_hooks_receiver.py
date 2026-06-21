import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tgbridge.hooks_receiver import make_app

AUTH = {"Authorization": "Bearer sek"}


class _FakeSched:
    def __init__(self):
        self.jobs = []

    def add_job(self, fn, trigger, args, name, **kw):
        j = SimpleNamespace(id="j1", next_run_time=None, name=name, args=args)
        self.jobs.append(j)
        return j

    def get_jobs(self):
        return self.jobs

    def remove_job(self, jid):
        if not any(j.id == jid for j in self.jobs):
            raise KeyError(jid)
        self.jobs = [j for j in self.jobs if j.id != jid]


def _client():
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(hook_secret="sek", tz="America/Sao_Paulo",
                            default_chat_id=42, workspace="/home/x"),
        queue=asyncio.Queue(),
        scheduler=_FakeSched(),
    )
    return TestClient(make_app(ctx)), ctx


def test_requires_auth():
    c, _ = _client()
    assert c.post("/schedule", json={"when": "cron 0 9 * * *", "prompt": "p"}).status_code == 401
    assert c.get("/schedules").status_code == 401


def test_schedule_add_list_remove():
    c, ctx = _client()
    r = c.post("/schedule", headers=AUTH,
               json={"when": "cron 0 9 * * *", "prompt": "rode X", "label": "lbl"})
    assert r.status_code == 200 and r.json()["id"] == "j1"
    # args do job: [label, prompt, chat, workspace]
    assert ctx.scheduler.jobs[0].args == ["lbl", "rode X", 42, "/home/x"]

    lst = c.get("/schedules", headers=AUTH).json()["jobs"]
    assert lst and lst[0]["id"] == "j1" and lst[0]["prompt"] == "rode X"

    assert c.delete("/schedule/j1", headers=AUTH).status_code == 200
    assert c.delete("/schedule/nope", headers=AUTH).status_code == 404


def test_schedule_bad_when():
    c, _ = _client()
    r = c.post("/schedule", headers=AUTH, json={"when": "daily", "prompt": "p"})
    assert r.status_code == 400


def test_event_enqueues():
    c, ctx = _client()
    r = c.post("/event", headers=AUTH, json={"hook_event_name": "Stop"})
    assert r.status_code == 200
    assert ctx.queue.qsize() == 1


def test_event_cron_label_header():
    # Sessão de cron: header X-Tgbridge-Cron-Label presente → cron_label no payload.
    c, ctx = _client()
    c.post("/event", headers={**AUTH, "X-Tgbridge-Cron-Label": "briefing-matinal"},
           json={"hook_event_name": "Stop"})
    assert ctx.queue.get_nowait()["cron_label"] == "briefing-matinal"


def test_event_no_cron_label_for_main():
    # Sessão principal: header ausente OU ${…} não interpolado → sem cron_label.
    c, ctx = _client()
    c.post("/event", headers=AUTH, json={"hook_event_name": "Stop"})
    assert "cron_label" not in ctx.queue.get_nowait()
    c.post("/event", headers={**AUTH, "X-Tgbridge-Cron-Label": "${TGBRIDGE_CRON_LABEL}"},
           json={"hook_event_name": "Stop"})
    assert "cron_label" not in ctx.queue.get_nowait()
