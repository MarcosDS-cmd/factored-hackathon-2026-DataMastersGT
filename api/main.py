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
from subtitles import subtitulo  # noqa: E402
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
    # English subtitles (display only; never fed back to the agent). Template-exact for the rule agent,
    # optional LLM translation otherwise. They are computed after the answer, so they add no latency to "ms".
    idioma = r["nlu"].get("idioma")
    return {"conv_id": e.conv_id, **{k: r[k] for k in ("respuesta", "modo", "ms")}, "nlu": r["nlu"],
            "subtitulo_agente": subtitulo(r["respuesta"], "agente", e.idioma or idioma, r["modo"]),
            "subtitulo_cliente": subtitulo(body.mensaje.strip(), "cliente", idioma),
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


# --- customer portal (English UI, /portal) -----------------------------------
import secrets  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from fastapi import Header  # noqa: E402

from agent_core import dispatch_tool_call  # noqa: E402

PORTAL: dict[str, dict] = {}            # token -> {"conv_id", "transacciones"}
FALLOS_LOGIN: dict[str, list] = {}      # document -> timestamps of failed logins (brute-force guard)
MAX_FALLOS, VENTANA = 5, timedelta(minutes=15)


class LoginIn(BaseModel):
    document: str = Field(..., min_length=3, max_length=30)
    full_name: str = Field(..., min_length=3, max_length=120)


class PortalChatIn(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=1000)


def _sesion_portal(authorization: str | None):
    token = (authorization or "").removeprefix("Bearer ").strip()
    ses = PORTAL.get(token)
    e = CONVERSACIONES.get(ses["conv_id"]) if ses else None
    if not e or not e.session or not e.session.verificado:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    if e.session.expirada():
        PORTAL.pop(token, None)
        raise HTTPException(401, "Your session expired after 15 minutes of inactivity. Please sign in again.")
    return token, ses, e


def _vista_portal(ses: dict, e: EstadoConversacion) -> dict:
    c = e.cliente_cache or {}
    return {
        "customer": {k: c.get(k) for k in ("first_name", "last_name", "segment", "country")},
        "transactions": ses["transacciones"],
        "cases": e.casos,
        "handoff": e.handoff,
        "messages": e.mensajes,
        "today": str(_STATS.get("hoy_simulado"))[:10],
        "engine": proveedor_configurado(),
    }


@app.post("/api/portal/login")
def portal_login(body: LoginIn):
    doc = "".join(ch for ch in body.document if ch.isalnum()).upper()
    ahora = datetime.now()
    recientes = [t for t in FALLOS_LOGIN.get(doc, []) if ahora - t < VENTANA]
    if len(recientes) >= MAX_FALLOS:
        raise HTTPException(429, "Too many failed attempts for this document. Try again in 15 minutes or call us.")
    e = _estado(None, "Web")
    r = dispatch_tool_call("identificar_cliente", {"document_number": body.document, "nombre_completo": body.full_name}, e)
    if not r.get("ok"):
        FALLOS_LOGIN[doc] = recientes + [ahora]
        msg = {"CLIENTE_NO_ENCONTRADO": "We couldn't find an account with that document number.",
               "DATOS_NO_COINCIDEN": "The name doesn't match the document on file.",
               "CLIENTE_INACTIVO": "This account isn't active. Please contact a branch or call us."}.get(r.get("motivo"), r.get("mensaje"))
        raise HTTPException(401, msg)
    FALLOS_LOGIN.pop(doc, None)
    c = r["cliente"]
    e.idioma = "en"
    e.contexto_extra = (
        "PORTAL CONTEXT: the customer is ALREADY authenticated in the bank's online portal "
        f"(customer_id {c['customer_id']}, name {c['first_name']} {c.get('last_name', '')}). Do NOT ask for their document or "
        "name and do NOT call identificar_cliente again; use this customer_id in the tools. The portal is in English: reply "
        "in English unless the customer writes in Spanish or Portuguese. When the customer cites a transaction_id, locate it "
        "with consultar_transacciones_recientes (dias 90), then call calcular_riesgo_caso (categoria 'Transactions', canal 'Web') "
        "and abrir_caso_disputa for that transaction_id.")
    t = dispatch_tool_call("consultar_transacciones_recientes", {"customer_id": c["customer_id"], "dias": 90}, e)
    txns = [x for x in t.get("transacciones", [])]
    token = secrets.token_urlsafe(24)
    PORTAL[token] = {"conv_id": e.conv_id, "transacciones": txns}
    return {"token": token, **_vista_portal(PORTAL[token], e)}


@app.get("/api/portal/me")
def portal_me(authorization: str | None = Header(None)):
    _, ses, e = _sesion_portal(authorization)
    return _vista_portal(ses, e)


@app.post("/api/portal/chat")
def portal_chat(body: PortalChatIn, authorization: str | None = Header(None)):
    _, ses, e = _sesion_portal(authorization)
    r = turno(e, body.mensaje.strip())
    return {"reply": r["respuesta"], "engine": r["modo"], "ms": r["ms"], **_vista_portal(ses, e)}


@app.post("/api/portal/logout")
def portal_logout(authorization: str | None = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    PORTAL.pop(token, None)
    return {"ok": True}


@app.get("/portal")
@app.get("/portal/")
def portal_index():
    return FileResponse(os.path.join(WEB, "portal", "index.html"))


# --- static website ----------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
