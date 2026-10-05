"""
Agent loop connected to the Gemini API — Factored AI & Data Hackathon 2026
Team DataMastersGT

NOTE (Oct 3): TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion and dispatch_tool_call
were moved to agent_core.py (shared by all providers) and are re-exported here.

WHAT THIS FILE DOES:
It connects the model (Gemini) to the tools in tools.py using function calling / tool use.
The model decides WHICH tool to call and with which business arguments, but the DISPATCH
(dispatch_tool_call) is plain Python code that:
  1) Never lets the model hand it the risk object or the customer data directly - the code
     itself recalculates them / fetches them from the session and the database.
     This closes a prompt-injection vector we had not closed before: the model
     "declaring" a low risk to force an auto-approval.
  2) Never runs a sensitive tool without going through requiere_sesion_valida (already in tools.py).
  3) ALWAYS returns a structured result (ok/message) to the model, never a raw exception
     - the model must be able to read a rejection and explain it to the customer.

REAL MODE vs MOCK MODE:
  - mode="real": uses the real Gemini API. Needs GEMINI_API_KEY in the environment.
    Install first: pip install google-genai
  - mode="mock": calls no model. A "simulated model" (FakeModel) makes the same
    function-calling decisions Gemini is expected to make, following a fixed script
    per test case. It exists ONLY because the environment where this project was built
    blocks the network to generativelanguage.googleapis.com - it is not a substitute for
    testing with the real API, it is a way to check that the tool dispatch (the part that
    holds the permissions, which is 100% of the real risk) works correctly BEFORE
    spending real API calls.
  Running with GEMINI_API_KEY set automatically uses real mode.
"""

import os
import json
from datetime import datetime, timedelta

from agent_core import (  # noqa: F401  (re-exported for claude_loop / openai_loop / tests)
    TOOL_DECLARATIONS, SYSTEM_INSTRUCTION, EstadoConversacion, dispatch_tool_call, resultado_para_modelo,
)


# ---------------------------------------------------------------------------
# REAL MODE - requires GEMINI_API_KEY and `pip install google-genai`
# ---------------------------------------------------------------------------
def correr_conversacion_real(mensaje_usuario: str, estado: EstadoConversacion, historial=None, modelo="gemini-2.0-flash"):
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing from the environment. Get one for free at https://aistudio.google.com/apikey "
            "and run: export GEMINI_API_KEY=your_key"
        )

    client = genai.Client(api_key=api_key)
    tool = types.Tool(function_declarations=TOOL_DECLARATIONS)
    sistema = SYSTEM_INSTRUCTION + ("\n\n" + estado.contexto_extra if estado.contexto_extra else "")
    config = types.GenerateContentConfig(system_instruction=sistema, tools=[tool])

    contents = historial or []
    contents.append(types.Content(role="user", parts=[types.Part(text=mensaje_usuario)]))

    # Loop: the model may request several tools in a chain before answering in text.
    for _ in range(8):  # safety limit to avoid an infinite loop
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

    return "(step limit reached without a final answer)", contents


# ---------------------------------------------------------------------------
# MOCK MODE - tests the dispatch (what really matters) without a network.
# The "model" here is a fixed script, not a real Gemini decision.
# ---------------------------------------------------------------------------
class ModeloSimulado:
    """Imitates the function-calling calls Gemini is expected to make,
    following a script per case. It decides NOTHING on its own - it is a test
    stub, documented as such."""

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
    print("MOCK MODE - testing the tool dispatch with 3 scripts (one per mandatory case)")
    print("(no API is called - see the file docstring for why)")
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

    print("\n--- CASE A: normal resolution (auto-approved), low amount ---")
    guion_a = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_1}},
        {"tipo": "tool_call", "nombre": "calcular_riesgo_caso", "args": {
            "monto_reclamado": bajo["amount_usd"], "categoria": "Service", "canal_recepcion": "App", "es_reincidente": False}},
        {"tipo": "tool_call", "nombre": "abrir_caso_disputa", "args": {
            "customer_id": cid_1, "transaction_id": bajo["transaction_id"], "monto_usd": bajo["amount_usd"],
            "categoria": "Service", "canal_recepcion": "App"}},
        {"tipo": "texto_final", "texto": "Done, your refund was approved automatically."},
    ]
    log_a, _ = correr_conversacion_mock(guion_a)
    for paso in log_a:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_a[2]["resultado"]["decision"] == "AUTO_APROBADO"

    print("\n--- CASE B: escalation to a human, high amount ---")
    guion_b = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_2}},
        {"tipo": "tool_call", "nombre": "calcular_riesgo_caso", "args": {
            "monto_reclamado": 5000, "categoria": "Fees", "canal_recepcion": "Call Center", "es_reincidente": True}},
        {"tipo": "tool_call", "nombre": "abrir_caso_disputa", "args": {
            "customer_id": cid_2, "transaction_id": alto["transaction_id"], "monto_usd": 5000,
            "categoria": "Fees", "canal_recepcion": "Call Center"}},
        {"tipo": "texto_final", "texto": "Your case needs review by a human agent, who will contact you soon."},
    ]
    log_b, _ = correr_conversacion_mock(guion_b)
    for paso in log_b:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_b[2]["resultado"]["decision"] == "ESCALADO_A_HUMANO"

    print("\n--- CASE C: ambiguous, the model 'tries' to force a charge that does not exist ---")
    guion_c = [
        {"tipo": "tool_call", "nombre": "verificar_cliente", "args": {"customer_id": cid_1}},
        {"tipo": "tool_call", "nombre": "buscar_cargo_disputado", "args": {"customer_id": cid_1, "monto_aprox": 999999.99}},
        {"tipo": "texto_final", "texto": "I cannot find that charge on your account. Can you give me more details, or should I pass you to an agent?"},
    ]
    log_c, _ = correr_conversacion_mock(guion_c)
    for paso in log_c:
        print(" ", paso.get("accion"), "->", paso.get("resultado", paso.get("texto")))
    assert log_c[1]["resultado"]["encontrada"] is False

    print("\n--- CASE D (extra security): the 'model' tries to force a low risk without having calculated it ---")
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
        "FAILED: abrir_caso_disputa must not run without a risk calculated by the system itself"

    print("\nALL DISPATCH SCRIPTS PASSED ✅")
    print("(The dispatch is the same code that would run with real Gemini; only the API key is missing)")
