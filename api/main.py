"""
Web backend — serves the website and connects it to the agent.
Factored Hackathon 2026 — Team DataMastersGT

    pip install -r requirements.txt
    export OPENAI_API_KEY=sk-...        # optional: without it the deterministic agent answers
    uvicorn api.main:app --port 8000    # open http://localhost:8000

The API key lives only on the server (env var); the browser never sees it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "agents")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent_core import EstadoConversacion  # noqa: E402
from runtime import turno, proveedor_configurado  # noqa: E402
from tools import PERMISOS, _con, umbral_monto_tipico, _STATS  # noqa: E402

WEB = os.path.join(ROOT, "web")
MAX_CONVERSACIONES = 500
CONVERSACIONES: "OrderedDict[str, EstadoConversacion]" = OrderedDict()
LOCK = threading.Lock()

app = FastAPI(title="Agente de disputas — DataMastersGT", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _warmup():
    t0 = time.time()
    _con()  # load data once
    try:
        from runtime import analizar
        analizar("hola, tengo un cargo que no reconozco")  # load ML models once
    except Exception:
        pass
    print(f"[startup] data + models ready in {time.time() - t0:.1f}s | provider: {proveedor_configurado()}")


class ChatIn(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=1000)
    conv_id: str | None = None
    canal: str = "App"
    proveedor: str | None = None  # "openai" | "anthropic" | "gemini" | "reglas" (None = server default)


def _estado(conv_id: str | None, canal: str) -> EstadoConversacion:
    with LOCK:
        if conv_id and conv_id in CONVERSACIONES:
            CONVERSACIONES.move_to_end(conv_id)
            return CONVERSACIONES[conv_id]
        e = EstadoConversacion(canal=canal if canal in ("App", "Web", "Call Center", "Email", "Regulator") else "App")
        CONVERSACIONES[e.conv_id] = e
        while len(CONVERSACIONES) > MAX_CONVERSACIONES:
            CONVERSACIONES.popitem(last=False)
        return e


@app.get("/api/health")
def health():
    return {"ok": True, "proveedor": proveedor_configurado(),
            "llm_disponible": proveedor_configurado() != "reglas",
            "modelo": os.environ.get("OPENAI_MODEL", "gpt-4o-mini") if proveedor_configurado() == "openai" else None,
            "datos": _STATS.get("fuente_datos"), "hoy_simulado": str(_STATS.get("hoy_simulado")),
            "conversaciones_activas": len(CONVERSACIONES)}


@app.get("/api/politica")
def politica():
    return {"auto_max_usd": PERMISOS["MONTO_MAX_AUTO_RESOLUCION_USD"],
            "escalar_desde_usd": PERMISOS["MONTO_MAX_SIN_ESCALAR_USD"],
            "fraud_score_escalacion": PERMISOS["FRAUD_SCORE_ESCALACION"],
            "canales_escalacion": sorted(PERMISOS["CANALES_ESCALACION_OBLIGATORIA"]),
            "segmentos_alto_valor": sorted(PERMISOS["SEGMENTOS_ALTO_VALOR"]),
            "umbral_monto_tipico": round(umbral_monto_tipico(), 2),
            "session_timeout_min": PERMISOS["SESSION_TIMEOUT_MIN"],
            "max_intentos_verificacion": PERMISOS["MAX_INTENTOS_VERIFICACION"]}


@app.post("/api/chat")
def chat(body: ChatIn):
    e = _estado(body.conv_id, body.canal)
    proveedor = body.proveedor if body.proveedor in ("openai", "anthropic", "gemini", "reglas") else None
    if proveedor and proveedor != "reglas" and proveedor_configurado() == "reglas":
        proveedor = "reglas"  # no key on the server -> deterministic agent
    r = turno(e, body.mensaje.strip(), proveedor)  # conversations are independent; tools use their own cursors
    return {"conv_id": e.conv_id, **{k: r[k] for k in ("respuesta", "modo", "ms")}, "nlu": r["nlu"],
            "estado": e.resumen()}


class NluIn(BaseModel):
    texto: str = Field(..., min_length=1, max_length=500)


@app.post("/api/nlu")
def nlu(body: NluIn):
    """Our own intent classifier + language detector, exposed so the website can show them working."""
    from runtime import analizar
    return analizar(body.texto)


@app.get("/api/conversacion/{conv_id}")
def conversacion(conv_id: str):
    e = CONVERSACIONES.get(conv_id)
    if not e:
        raise HTTPException(404, "Conversation not found (the server keeps the last 500 in memory).")
    return e.resumen()


@app.get("/api/handoffs")
def handoffs():
    """Human-agent queue: every conversation the AI handed off, newest first, with its context package."""
    cola = [{"conv_id": cid, **e.handoff, "casos": e.casos, "mensajes": e.mensajes[-6:]}
            for cid, e in reversed(CONVERSACIONES.items()) if e.handoff]
    return {"n": len(cola), "cola": cola[:50]}


# --- static website ----------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
