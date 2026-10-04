"""
Agent loop connected to the OpenAI API — Factored AI & Data Hackathon 2026
Team DataMastersGT

Equivalent to gemini_loop.py and claude_loop.py but using OpenAI's tool calling format
(Chat Completions: tool_calls / role="tool").

The permissions logic (dispatch_tool_call) is EXACTLY THE SAME as in the other loops — it comes from
agent_core.py. The only thing that changes is how the API is spoken to, not how permissions are decided.

Requires: pip install openai
          export OPENAI_API_KEY=your_key
          (optional) export OPENAI_MODEL=gpt-4o-mini
"""

import json
import os
import time

from agent_core import TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call, resultado_para_modelo

MODELO_DEFAULT = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _a_formato_openai(tool_decl: dict) -> dict:
    """OpenAI expects tools wrapped in {"type": "function", "function": {...}} (same JSON schema)."""
    return {"type": "function", "function": {
        "name": tool_decl["name"], "description": tool_decl["description"], "parameters": tool_decl["parameters"]}}


OPENAI_TOOLS = [_a_formato_openai(t) for t in TOOL_DECLARATIONS]
_CLIENT = None


def _cliente():
    global _CLIENT
    if _CLIENT is None:
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing. export OPENAI_API_KEY=your_key")
        _CLIENT = openai.OpenAI(api_key=api_key, timeout=30)
    return _CLIENT


def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion, historial=None, modelo=None):
    """One customer turn: the model may chain several tool calls before answering in text.
    Every model call is recorded in estado.traza (latency + tokens) next to the tool calls."""
    modelo = modelo or MODELO_DEFAULT
    client = _cliente()
    mensajes = historial or [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    mensajes.append({"role": "user", "content": mensaje_usuario})

    for _ in range(8):  # safety limit
        t0 = time.perf_counter()
        resp = client.chat.completions.create(model=modelo, messages=mensajes, tools=OPENAI_TOOLS, temperature=0.2)
        ms = (time.perf_counter() - t0) * 1000
        msg = resp.choices[0].message
        uso = resp.usage
        estado.registrar("llm", proveedor="openai", modelo=modelo, ms=round(ms, 1),
                         tokens_in=getattr(uso, "prompt_tokens", None), tokens_out=getattr(uso, "completion_tokens", None),
                         tool_calls=[tc.function.name for tc in (msg.tool_calls or [])])
        mensajes.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or "", mensajes

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            resultado = dispatch_tool_call(tc.function.name, args, estado)
            mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado_para_modelo(resultado)})

    return "(step limit reached without a final answer)", mensajes


if __name__ == "__main__":
    import sys

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing — export it before running this file with a real case.")
        print("Meanwhile: 'python3 gemini_loop.py' tests the dispatch in mock mode, and")
        print("'python3 rule_agent.py' runs the no-LLM fallback agent.")
        sys.exit(0)

    estado = EstadoConversacion()
    historial = None
    for mensaje in ["Hola, quiero disputar un cargo que no reconozco",
                    "Mi documento es " + (sys.argv[1] if len(sys.argv) > 1 else "00000000") + " y me llamo Juan Perez"]:
        print(f"Customer: {mensaje}")
        texto, historial = correr_conversacion_real(mensaje, estado, historial)
        print(f"Agent: {texto}\n")
    print(json.dumps(estado.resumen()["traza"], indent=1, ensure_ascii=False, default=str)[:3000])
