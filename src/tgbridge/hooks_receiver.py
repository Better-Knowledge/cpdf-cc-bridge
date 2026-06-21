"""Receiver FastAPI (localhost-only). POST /event responde 200 na hora e enfileira.
Também expõe /schedule (POST/GET/DELETE) para o agente agendar por linguagem natural
(via a skill scheduler) ou para o operador — registra no scheduler ao vivo + jobs.db."""
from fastapi import FastAPI, Header, HTTPException, Request

from . import scheduler as sched_mod


def make_app(ctx) -> FastAPI:
    app = FastAPI(title="tgbridge-hooks")
    expected = f"Bearer {ctx.cfg.hook_secret}"

    def _auth(authorization: str) -> None:
        if authorization != expected:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.post("/event")
    async def event(request: Request, authorization: str = Header(default="")):
        _auth(authorization)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        # Rótulo de cron via header (interpolado de ${TGBRIDGE_CRON_LABEL} no settings):
        # presente só nas sessões efêmeras de cron → permite ao notifier colher a sessão
        # assim que o Stop entregar. Sessão principal manda vazio (ou ${…} se a var não
        # interpolar) → ignorado.
        label = (request.headers.get("x-tgbridge-cron-label") or "").strip()
        if isinstance(payload, dict) and label and not label.startswith("${"):
            payload["cron_label"] = label
        # Nunca bloquear o Claude: responde já e processa em background.
        await ctx.queue.put(payload)
        return {"ok": True}

    @app.post("/schedule")
    async def schedule_add(request: Request, authorization: str = Header(default="")):
        _auth(authorization)
        body = await request.json()
        when = (body.get("when") or "").strip()
        prompt = (body.get("prompt") or "").strip()
        label = (body.get("label") or "").strip() or "job"
        if not when or not prompt:
            raise HTTPException(status_code=400, detail="campos 'when' e 'prompt' obrigatórios")
        try:
            trigger, descr = sched_mod.parse_when(when, ctx.cfg.tz)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        job = ctx.scheduler.add_job(
            sched_mod.run_scheduled_prompt,
            trigger,
            args=[label, prompt, ctx.cfg.default_chat_id, ctx.cfg.workspace],
            name=f"{label} · {descr}",
            misfire_grace_time=7200,  # 120 min: tolera disparo atrasado (ex.: bridge fora do ar)
            replace_existing=False,
        )
        nxt = job.next_run_time.isoformat() if job.next_run_time else None
        return {"ok": True, "id": job.id, "label": label, "descr": descr, "next_run": nxt}

    @app.get("/schedules")
    async def schedule_list(authorization: str = Header(default="")):
        _auth(authorization)
        jobs = []
        for j in ctx.scheduler.get_jobs():
            prompt = j.args[1] if len(j.args) > 1 else ""
            jobs.append({
                "id": j.id,
                "name": j.name,
                "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                "prompt": (prompt or "")[:80],
            })
        return {"jobs": jobs}

    @app.delete("/schedule/{job_id}")
    async def schedule_remove(job_id: str, authorization: str = Header(default="")):
        _auth(authorization)
        try:
            ctx.scheduler.remove_job(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail=f"job {job_id} não encontrado")
        return {"ok": True, "removed": job_id}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app
