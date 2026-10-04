"""
Agent loop connected to the Claude (Anthropic) API — Factored AI & Data Hackathon 2026
Team DataMastersGT

Equivalent to gemini_loop.py / openai_loop.py but using Claude's tool use format
(content blocks with type="tool_use" / type="tool_result").

The permissions logic (dispatch_tool_call) is EXACTLY THE SAME — it comes from agent_core.py.
Permissions should not depend on which model is used.

Requires: pip install anthropic
          export ANTHROPIC_API_KEY=your_key
          (optional) export ANTHROPIC_MODEL=claude-sonnet-5-5
"""

import os
import time

from agent_core import TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call, resultado_para_modelo

MODELO_DEFAULT = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def _a_formato_claude(tool_decl: dict) -> dict:
    """Claude uses the same JSON schema but under the 'input_schema' key."""
    return {"name": tool_decl["name"], "description": tool_decl["description"], "input_schema": tool_decl["parameters"]}


CLAUDE_TOOLS = [_a_formato_claude(t) for t in TOOL_DECLARATIONS]
_CLIENT = None


def _cliente():
    global _CLIENT
    if _CLIENT is None:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is missing. export ANTHROPIC_API_KEY=your_key")
        _CLIENT = anthropic.Anthropic(api_key=api_key, timeout=30)
    return _CLIENT


def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion, historial=None, modelo=None):
    modelo = modelo or MODELO_DEFAULT
    client = _cliente()
    mensajes = historial or []
    mensajes.append({"role": "user", "content": mensaje_usuario})

    for _ in range(8):  # safety limit
        t0 = time.perf_counter()
        resp = client.messages.create(model=modelo, max_tokens=1024, system=SYSTEM_INSTRUCTION,
                                      tools=CLAUDE_TOOLS, messages=mensajes)
        ms = (time.perf_counter() - t0) * 1000
        bloques_tool = [b for b in resp.content if b.type == "tool_use"]
        estado.registrar("llm", proveedor="anthropic", modelo=modelo, ms=round(ms, 1),
                         tokens_in=resp.usage.input_tokens, tokens_out=resp.usage.output_tokens,
                         tool_calls=[b.name for b in bloques_tool])
        mensajes.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})

        if not bloques_tool:
            return "".join(b.text for b in resp.content if b.type == "text"), mensajes

        resultados_tool = []
        for b in bloques_tool:
            resultado = dispatch_tool_call(b.name, b.input, estado)
            resultados_tool.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": resultado_para_modelo(resultado)})
        mensajes.append({"role": "user", "content": resultados_tool})

    return "(step limit reached without a final answer)", mensajes


if __name__ == "__main__":
    import sys

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is missing — export it before running this file with a real case.")
        print("Meanwhile, use 'python3 gemini_loop.py' to test the dispatch in mock mode (no API).")
        sys.exit(0)

    estado = EstadoConversacion()
    mensaje = "Hola, quiero disputar un cargo de $120 que no reconozco en mi cuenta"
    print(f"Customer: {mensaje}\n")
    texto, _ = correr_conversacion_real(mensaje, estado)
    print(f"Agent: {texto}")
