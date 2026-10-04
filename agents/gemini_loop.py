"""
Loop del agente conectado a Gemini API — Factored AI & Data Hackathon 2026
Equipo DataMastersGT

NOTA (Oct 3): TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion y dispatch_tool_call
se movieron a agent_core.py (compartido por todos los proveedores) y aqui se re-exportan.

QUE HACE ESTE ARCHIVO:
Conecta el modelo (Gemini) con las tools de tools.py usando function calling / tool use.
El modelo decide QUE tool llamar y con que argumentos de negocio, pero el DESPACHO
(dispatch_tool_call) es codigo Python normal que:
  1) Nunca deja que el modelo le pase directamente el objeto de riesgo o los datos del
     cliente - los recalcula/los trae el propio codigo desde la sesion/la base de datos.
     Esto cierra un vector de inyeccion de prompt que no habiamos cerrado antes: que el
     modelo "declare" un riesgo bajo para forzar un auto-aprobado.
  2) Nunca ejecuta una tool sensible sin pasar por requiere_sesion_valida (ya en tools.py).
  3) Regresa SIEMPRE un resultado estructurado (ok/mensaje) al modelo, nunca una excepcion
     cruda - el modelo tiene que poder leer un rechazo y explicarselo al cliente.

MODO REAL vs MODO MOCK:
  - modo="real": usa la API de Gemini de verdad. Necesita GEMINI_API_KEY en el entorno.
    Instalar antes: pip install google-genai
  - modo="mock": no llama a ningun modelo. Un "modelo simulado" (FakeModel) hace las
    mismas decisiones de function-calling que se espera que Gemini haga, siguiendo un
    guion fijo por caso de prueba. Esto existe SOLO porque el entorno donde se construyo
    este proyecto bloquea la red hacia generativelanguage.googleapis.com - no es un
    sustituto de probar con la API real, es una forma de probar que el despacho de tools
    (la parte con los permisos, que es el 100% del riesgo real) funciona correctamente
    ANTES de gastar llamadas reales a la API.
  Correr con GEMINI_API_KEY configurada usa automaticamente modo real.
"""

import os
import json
from datetime import datetime, timedelta

from agent_core import (  # noqa: F401  (re-exported for claude_loop / openai_loop / tests)
    TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call, resultado_para_modelo,
)


# ---------------------------------------------------------------------------
# MODO REAL - requiere GEMINI_API_KEY y `pip install google-genai`
# ---------------------------------------------------------------------------
def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion, historial=None, modelo="gemini-2.0-flash"):
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Falta GEMINI_API_KEY en el entorno. Consiguela gratis en https://aistudio.google.com/apikey "
            "y corre: export GEMINI_API_KEY=tu_key"
        )

    client = genai.Client(api_key=api_key)
    tool = types.Tool(function_declarations=TOOL_DECLARATIONS)
    config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, tools=[tool])

    contents = historial or []
    contents.append(types.Content(role="user", parts=[types.Part(text=mensaje_usuario)]))

    # Loop: el modelo puede pedir varias tools en cadena antes de responder en texto.
    for _ in range(8):  # limite de seguridad para no entrar en loop infinito
        resp = client.models.generate_content(model=modelo, contents=contents, config=config)
        contenido = resp.candidates[0].content
        contents.append(contenido)
        llamadas = [p.function_call for p in contenido.parts if p.function_call]

        if llamadas:
            respuestas = []
            for fc in llamadas:
                resultado = dispatch_tool_call(fc.name, dict(fc.args), estado)
                respuestas.append(types.Part.from_function_response(
                    name=fc.name, response=json.loads(resultado_para_modelo(resultado))))
            contents.append(types.Content(role="user", parts=respuestas))
            continue

        return "".join(p.text or "" for p in contenido.parts), contents

    return "(se alcanzo el limite de pasos sin una respuesta final)", contents


# ---------------------------------------------------------------------------
# MODO MOCK - prueba el despacho (lo que de verdad importa) sin red.
# El "modelo" aqui es un guion fijo, no una decision real de Gemini.
# ---------------------------------------------------------------------------
class ModeloSimulado:
    """Imita las llamadas de function-calling que se espera que Gemini haga,
    siguiendo un guion por caso. NO decide nada por su cuenta - es un stub de
    pruebas, documentado como tal."""

    def __init__(self, guion: list):
        self.guion = guion
        self.i = 0

    def siguiente(self):
        paso = self.guion[self.i]
        self.i += 1
        return paso


def correr_conversacion_mock(guion: list):
    estado = EstadoConversacion()
    modelo = ModeloSimulado(guion)
    log = []
    while modelo.i < len(modelo.guion):
        paso = modelo.siguiente()
        if paso["tipo"] == "tool_call":
            resultado = dispatch_tool_call(paso["nombre"], paso["args"], estado)
            log.append({"accion": f"tool_call:{paso['nombre']}", "args": paso["args"], "resultado": resultado})
        elif paso["tipo"] == "texto_final":
            log.append({"accion": "texto_final", "texto": paso["texto"]})
    return log, estado


if __name__ == "__main__":
    print("=" * 70)
    print("MODO MOCK - probando el despacho de tools con 3 guiones (uno por caso obligatorio)")
    print("(sin llamar a ninguna API - ver docstring del archivo para el porque)")
    print("=" * 70)

    from tools import _con, _records
    con = _con()
    q = ("SELECT c.customer_id, t.transaction_id, t.amount_usd FROM customers c JOIN txns t USING (customer_id) "
         "WHERE c.customer_status='Active' AND c.segment='Basic' AND NOT t.is_fraud AND t.fraud_score < 70 "
         "AND c.customer_id NOT IN (SELECT customer_id FROM complaint_stats) AND t.amount_usd {} "
         "ORDER BY c.customer_id LIMIT 1")
    bajo = _records(con.execute(q.format("BETWEEN 50 AND 250")).df())[0]
    alto = _records(con.execute(q.format("> 3000")).df())[0]
    cid_1, cid_2 = bajo["customer_id"], alto["customer_id"]

    print("\n--- CASO A: resolucion normal (auto-aprobado), monto bajo ---")
    guion_a = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_1}},
        {"tipo": "tool_call", "nombre": "calcular_riesgo_caso", "args": {
            "monto_reclamado": bajo["amount_usd"], "categoria": "Service", "canal_recepcion": "App", "es_reincidente": False}},
        {"tipo": "tool_call", "nombre": "abrir_caso_disputa", "args": {
            "customer_id": cid_1, "transaction_id": bajo["transaction_id"], "monto_usd": bajo["amount_usd"],
            "categoria": "Service", "canal_recepcion": "App"}},
        {"tipo": "texto_final", "texto": "Listo, tu reembolso quedo aprobado automaticamente."},
    ]
    log_a, _ = correr_conversacion_mock(guion_a)
    for paso in log_a:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_a[2]["resultado"]["decision"] == "AUTO_APROBADO"

    print("\n--- CASO B: escalacion a humano, monto alto ---")
    guion_b = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_2}},
        {"tipo": "tool_call", "nombre": "calcular_riesgo_caso", "args": {
            "monto_reclamado": 5000, "categoria": "Fees", "canal_recepcion": "Call Center", "es_reincidente": True}},
        {"tipo": "tool_call", "nombre": "abrir_caso_disputa", "args": {
            "customer_id": cid_2, "transaction_id": alto["transaction_id"], "monto_usd": 5000,
            "categoria": "Fees", "canal_recepcion": "Call Center"}},
        {"tipo": "texto_final", "texto": "Tu caso necesita revision de un agente humano, te va a contactar pronto."},
    ]
    log_b, _ = correr_conversacion_mock(guion_b)
    for paso in log_b:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_b[2]["resultado"]["decision"] == "ESCALADO_A_HUMANO"

    print("\n--- CASO C: ambiguo, el modelo 'intenta' forzar un cargo que no existe ---")
    guion_c = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_1}},
        {"tipo": "tool_call", "nombre": "buscar_cargo_disputado", "args": {"customer_id": cid_1, "monto_aprox": 999999.99}},
        {"tipo": "texto_final", "texto": "No encuentro ese cargo en tu cuenta, me ayudas con mas detalles o te paso con un agente?"},
    ]
    log_c, _ = correr_conversacion_mock(guion_c)
    for paso in log_c:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_c[1]["resultado"]["encontrada"] is False

    print("\n--- CASO D (seguridad extra): el 'modelo' intenta forzar un riesgo bajo sin haberlo calculado ---")
    guion_d = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_2}},
        {"tipo": "tool_call", "nombre": "abrir_caso_disputa", "args": {
            "customer_id": cid_2, "transaction_id": alto["transaction_id"], "monto_usd": 50,
            "categoria": "Service", "canal_recepcion": "App"}},
    ]
    log_d, _ = correr_conversacion_mock(guion_d)
    for paso in log_d:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_d[1]["resultado"]["ok"] is False and log_d[1]["resultado"]["motivo"] == "RIESGO_NO_CALCULADO", \
        "FALLO: abrir_caso_disputa no deberia ejecutarse sin un riesgo calculado por el propio sistema"

    print("\nTODOS LOS GUIONES DE DESPACHO PASARON ✅")
    print("(El despacho es el mismo codigo que correria con Gemini real; falta solo conectar la API key)")
