"""
Loop del agente conectado a la API de OpenAI — Factored AI & Data Hackathon 2026
Equipo DataMastersGT

Version equivalente a gemini_loop.py y claude_loop.py pero usando el formato de
tool calling de OpenAI (Chat Completions: tool_calls / role="tool").

La logica de permisos (dispatch_tool_call) es EXACTAMENTE LA MISMA que en los
otros dos archivos — se importa de gemini_loop.py. Lo unico que cambia es como
se habla con la API, no como se deciden los permisos.

Requiere: pip install openai
          export OPENAI_API_KEY=tu_key

NOTA: este archivo no se pudo probar en vivo desde el sandbox donde se construyo
el proyecto — el proxy de red de ese entorno bloquea api.openai.com (igual que
bloqueaba generativelanguage.googleapis.com). Probarlo requiere correrlo en tu
maquina o en el entorno final del equipo.
"""

import os
from gemini_loop import TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call


def _a_formato_openai(tool_decl: dict) -> dict:
    """OpenAI espera las tools envueltas en {"type": "function", "function": {...}}
    y usa 'parameters' igual que Gemini (mismo JSON schema), solo cambia el wrapper."""
    return {
        "type": "function",
        "function": {
            "name": tool_decl["name"],
            "description": tool_decl["description"],
            "parameters": tool_decl["parameters"],
        },
    }


OPENAI_TOOLS = [_a_formato_openai(t) for t in TOOL_DECLARATIONS]


def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion,
                              historial=None, modelo="gpt-4o-mini"):
    import openai
    import json

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en el entorno. export OPENAI_API_KEY=tu_key")

    client = openai.OpenAI(api_key=api_key)
    mensajes = historial or [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    mensajes.append({"role": "user", "content": mensaje_usuario})

    for _ in range(8):  # limite de seguridad
        resp = client.chat.completions.create(
            model=modelo,
            messages=mensajes,
            tools=OPENAI_TOOLS,
        )
        msg = resp.choices[0].message
        mensajes.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content, mensajes

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            resultado = dispatch_tool_call(tc.function.name, args, estado)
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(resultado),
            })

    return "(se alcanzo el limite de pasos sin una respuesta final)", mensajes


if __name__ == "__main__":
    import sys

    if not os.environ.get("OPENAI_API_KEY"):
        print("Falta OPENAI_API_KEY — exportala antes de correr este archivo con un caso real.")
        print("Mientras tanto, usa 'python3 gemini_loop.py' para probar el despacho en modo mock (sin API).")
        sys.exit(0)

    estado = EstadoConversacion()
    mensaje = "Hola, quiero disputar un cargo de $120 que no reconozco en mi cuenta"
    print(f"Cliente: {mensaje}\n")
    texto, _ = correr_conversacion_real(mensaje, estado)
    print(f"Agente: {texto}")
