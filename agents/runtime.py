"""
Conversation runtime — one entry point for every mode (OpenAI / Claude / Gemini / no-LLM rules).
Factored Hackathon 2026 — Team DataMastersGT

turno(estado, mensaje) does, for every customer message:
  1. NLU with OUR models: language (ES/PT) + intent (+ prompt-injection flag) -> recorded in the trace.
  2. Calls the configured model loop (or the deterministic agent). If the LLM fails (no key, network,
     timeout) it falls back to the deterministic agent and records the fallback — the demo never breaks.
  3. Records end-to-end latency per turn (used for p50/p95 by language).
"""

from __future__ import annotations

import os
import re
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_core import EstadoConversacion  # noqa: E402
from rule_agent import AgenteReglas, RE_INYECCION  # noqa: E402


def proveedor_configurado() -> str:
    """'openai' | 'anthropic' | 'gemini' | 'reglas' — from AGENT_PROVIDER or whichever key exists."""
    p = os.environ.get("AGENT_PROVIDER", "").lower()
    if p:
        return p
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "reglas"


def analizar(mensaje: str, idioma_previo: str | None = None) -> dict:
    from ml.intent_classifier import predecir_intencion, detectar_idioma
    plano = unicodedata.normalize("NFKD", mensaje).encode("ascii", "ignore").decode().lower()
    out = {"idioma": detectar_idioma(mensaje, idioma_previo), "inyeccion": bool(RE_INYECCION.search(plano))}
    try:
        if out["idioma"] == "en":
            from ml.intent_classifier import intencion_ingles
            out.update(intencion_ingles(mensaje))
        else:
            out.update(predecir_intencion(mensaje))
    except Exception as e:  # model artifacts missing
        out.update({"intencion": None, "confianza": 0.0, "error": str(e)})
    return out


def _llm(proveedor: str):
    if proveedor == "openai":
        from openai_loop import correr_conversacion_real
    elif proveedor == "anthropic":
        from claude_loop import correr_conversacion_real
    elif proveedor == "gemini":
        from gemini_loop import correr_conversacion_real
    else:
        return None
    return correr_conversacion_real


def turno(estado: EstadoConversacion, mensaje: str, proveedor: str | None = None) -> dict:
    proveedor = proveedor or getattr(estado, "proveedor", None) or proveedor_configurado()
    t0 = time.perf_counter()
    nlu = analizar(mensaje, estado.idioma)
    # language of the conversation = first message's language; switches only on a clear message
    if estado.idioma is None or (len(mensaje.split()) >= 4 and nlu["idioma"] != estado.idioma):
        estado.idioma = nlu["idioma"]
    estado.mensajes.append({"rol": "cliente", "texto": mensaje})
    estado.registrar("nlu", texto=mensaje, **{k: nlu.get(k) for k in ("idioma", "intencion", "confianza", "top3",
                                                                         "baseline_keywords", "inyeccion")})

    modo = proveedor
    texto = None
    fn = _llm(proveedor)
    if fn is not None:
        try:
            historial = estado.__dict__.get("_historial_llm")
            texto, historial = fn(mensaje, estado, historial)
            estado.__dict__["_historial_llm"] = historial
        except Exception as e:
            estado.registrar("fallback", desde=proveedor, error=f"{type(e).__name__}: {str(e)[:200]}")
            modo = "reglas"
            estado.proveedor = "reglas"  # stay deterministic for the rest of this conversation
    if texto is None:
        modo = "reglas"
        texto = AgenteReglas().responder(mensaje, estado, nlu)

    ms = (time.perf_counter() - t0) * 1000
    estado.mensajes.append({"rol": "agente", "texto": texto, "modo": modo})
    estado.registrar("respuesta", modo=modo, ms_total=round(ms, 1), idioma=estado.idioma)
    return {"respuesta": texto, "modo": modo, "ms": round(ms, 1), "nlu": nlu}
