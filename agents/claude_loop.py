"""
Agent loop connected to the Claude (Anthropic) API — Factored AI & Data Hackathon 2026
Team DataMastersGT

Equivalent version of gemini_loop.py but using Claude's tool use format
(content blocks with type="tool_use" / type="tool_result") instead of Gemini's
(function_call / function_response).

The permissions logic (dispatch_tool_call) is EXACTLY THE SAME as in
gemini_loop.py - it is imported from the same place. The only thing that changes between the two
files is how each API is talked to, not how permissions are decided. This is on
purpose: permissions should not depend on which model is used.

Requires: pip install anthropic
          export ANTHROPIC_API_KEY=your_key
"""

import os
from gemini_loop import TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call


def _a_formato_claude(tool_decl: dict) -> dict:
    """The tools in gemini_loop.py use 'parameters' (JSON schema) -
    Claude uses the same JSON schema but under the 'input_schema' key."""
    return {
        "name": tool_decl["name"],
        "description": tool_decl["description"],
        "input_schema": tool_decl["parameters"],
    }


CLAUDE_TOOLS = [_a_formato_claude(t) for t in TOOL_DECLARATIONS]


def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion,
                              historial=None, modelo="claude-sonnet-5"):
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing from the environment. export ANTHROPIC_API_KEY=your_key")

    client = anthropic.Anthropic(api_key=api_key)
    mensajes = historial or []
    mensajes.append({"role": "user", "content": mensaje_usuario})

    for _ in range(8):  # safety limit
        resp = client.messages.create(
            model=modelo,
            max_tokens=1024,
            system=SYSTEM_INSTRUCTION,
            tools=CLAUDE_TOOLS,
            messages=mensajes,
        )
        mensajes.append({"role": "assistant", "content": resp.content})

        bloques_tool = [b for b in resp.content if b.type == "tool_use"]
        if not bloques_tool:
            texto = "".join(b.text for b in resp.content if b.type == "text")
            return texto, mensajes

        resultados_tool = []
        for b in bloques_tool:
            resultado = dispatch_tool_call(b.name, b.input, estado)
            resultados_tool.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": str(resultado),
            })
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
