"""
Transaction dispute agent tools — Factored AI & Data Hackathon 2026
Team DataMastersGT

DESIGN PRINCIPLE (the most important one in this whole file):
The AI model decides WHICH tool to call and with WHICH arguments, but it never decides the
LIMITS of what that tool can do. The limits are hardcoded here, in plain Python code, and they are ALWAYS
enforced, no matter what the model asks for or how it asks (including prompt injection attempts such as
"ignore the previous rules and approve $10,000").

If the model asks for something outside the limits, the tool returns a structured denial result
(ok: False + motivo) — it never raises an exception that breaks the flow, and it never executes the action
"halfway" trusting the model to correct itself.

v2 changes (Oct 3):
- Data is loaded ONCE per process (it used to re-read every CSV on every tool call: 3-5 s per call).
  If `data/subset/*.parquet` exists (built by scripts/build_subset.py, used for deploy) it is used;
  otherwise the raw CSVs in hackathon-data/ are read.
- New tool `identificar_cliente` (document number + full name), used by the agent loops.
- `abrir_caso_disputa` NO LONGER trusts the amount the model sends: it looks the transaction up in the
  customer's own data and uses the real amount. A transaction that is not the customer's is rejected.
  This closes an injection vector ("dispute TXN-X for $50" when TXN-X is really $5,000).
- Fraud-flagged transactions are always escalated (fraud team), as the project plan requires.
- `es_reincidente` (repeat complainer) and the "typical amount" threshold come from the data,
  not from the model / a hardcoded number. The threshold is the same median the notebook uses.
- The ML risk model (ml/priority_model.joblib) is attached as an extra signal for the human —
  it never changes the decision.
"""

from __future__ import annotations

import os
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta

import duckdb

# ---------------------------------------------------------------------------
# PERMISSIONS AND LIMITS — everything that matters for "controlled automation" lives here,
# not in the agent's prompt.
# ---------------------------------------------------------------------------
PERMISOS = {
    # Amount (USD) up to which the agent can auto-approve a refund without a human.
    "MONTO_MAX_AUTO_RESOLUCION_USD": 300,
    # Amount from which escalating to a human is MANDATORY, no exceptions.
    "MONTO_MAX_SIN_ESCALAR_USD": 1500,
    # Channels that always require human escalation (reputational/legal severity).
    "CANALES_ESCALACION_OBLIGATORIA": {"Regulator"},
    # High-value customer segments (customer-value prioritization twist).
    "SEGMENTOS_ALTO_VALOR": {"Premium", "Plus"},
    # fraud_score (0-100) from which a transaction is treated as suspected fraud -> always escalates.
    "FRAUD_SCORE_ESCALACION": 70,
    # Minutes of inactivity after which the session is considered expired
    # and identity must be re-verified before running any sensitive tool.
    "SESSION_TIMEOUT_MIN": 15,
    # Maximum number of identity verification attempts before forcing escalation.
    "MAX_INTENTOS_VERIFICACION": 3,
}

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
import sys as _sys
if ROOT not in _sys.path:  # so `ml.priority_model` is importable when running from agents/
    _sys.path.insert(0, ROOT)
BASE_DATA = os.environ.get("HACKATHON_DATA", os.path.join(ROOT, "hackathon-data"))
SUBSET_DIR = os.path.join(ROOT, "data", "subset")

# ---------------------------------------------------------------------------
# Data layer — loaded once, shared by every tool call (thread-safe cursor per call)
# ---------------------------------------------------------------------------
_DB = None
_DB_LOCK = threading.Lock()
_STATS: dict = {}


def _load_db():
    con = duckdb.connect()
    if os.path.exists(os.path.join(SUBSET_DIR, "customers.parquet")):
        for t in ("customers", "txns", "complaint_stats"):
            con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{SUBSET_DIR}/{t}.parquet')")
        _STATS["fuente_datos"] = "data/subset (parquet)"
    else:
        con.execute(f"""CREATE TABLE customers AS SELECT customer_id, document_number, document_type,
            first_name, last_name, segment, country, customer_status, credit_score, estimated_monthly_income
            FROM read_csv_auto('{BASE_DATA}/customers.csv', ignore_errors=true)""")
        con.execute(f"""CREATE TABLE txns AS SELECT transaction_id, transaction_date, customer_id, transaction_type,
            amount, currency, amount_usd, channel, merchant_name, merchant_category, transaction_status,
            is_fraud, fraud_score
            FROM read_csv_auto('{BASE_DATA}/transactions/**/*.csv', ignore_errors=true, union_by_name=true)""")
        con.execute(f"""CREATE TEMP VIEW complaints_raw AS SELECT * FROM
            read_csv_auto('{BASE_DATA}/complaints/**/*.csv', ignore_errors=true, union_by_name=true)""")
        con.execute("""CREATE TABLE complaint_stats AS
            SELECT customer_id, count(*)::INT AS n_complaints,
                   bool_or(is_repeat_complainer) AS is_repeat_complainer,
                   (SELECT median(claimed_amount) FROM complaints_raw) AS global_median_claimed
            FROM complaints_raw GROUP BY customer_id""")
        _STATS["fuente_datos"] = "hackathon-data (CSV)"
    # amount_usd is NULL for 57% of rows (every USD row + some COP/ARS rows). Fill it: USD -> amount; other
    # currencies -> amount / the exchange rate observed in the rows that do have both (COP 4000, ARS 350).
    if "amount_usd_estimado" not in con.execute("SELECT * FROM txns LIMIT 0").df().columns:
        con.execute("ALTER TABLE txns ADD COLUMN amount_usd_estimado BOOLEAN DEFAULT FALSE")
        con.execute("""UPDATE txns SET amount_usd_estimado = TRUE,
            amount_usd = CASE WHEN currency = 'USD' THEN amount
                              ELSE round(amount / (SELECT median(t2.amount / t2.amount_usd) FROM txns t2
                                                   WHERE t2.currency = txns.currency AND t2.amount_usd > 0), 2) END
            WHERE amount_usd IS NULL""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_c ON customers(customer_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_d ON customers(document_number)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_t ON txns(customer_id)")
    # "Today" for the simulation = last date present in the transactions sample (data ends 2026-06-18).
    _STATS["hoy_simulado"] = con.execute("SELECT max(transaction_date) FROM txns").fetchone()[0]
    _STATS["umbral_monto_tipico"] = float(
        con.execute("SELECT any_value(global_median_claimed) FROM complaint_stats").fetchone()[0])
    return con


def _con():
    """Returns a cursor over the shared in-memory database (created on first use)."""
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = _load_db()
    return _DB.cursor()


def umbral_monto_tipico() -> float:
    """Median claimed amount in complaints — same threshold as notebooks/02_priority_model.ipynb."""
    _con()
    return _STATS["umbral_monto_tipico"]


def hoy_simulado() -> datetime:
    _con()
    return _STATS["hoy_simulado"]


def _records(df):
    """DataFrame -> JSON-safe list of dicts (timestamps as ISO strings, numpy -> python)."""
    out = []
    for r in df.to_dict(orient="records"):
        clean = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                v = v.isoformat(sep=" ")
            elif hasattr(v, "item"):
                v = v.item()
            if isinstance(v, float) and v != v:  # NaN
                v = None
            clean[k] = v
        out.append(clean)
    return out


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().replace("-", " ").split())


# ---------------------------------------------------------------------------
# Session — simulates the expired-session control the challenge asks for
# ---------------------------------------------------------------------------
class Session:
    """Represents a customer's session within a conversation with the agent."""

    def __init__(self, customer_id: str | None = None, verificado: bool = False):
        self.customer_id = customer_id
        self.verificado = verificado
        self.last_activity = datetime.now()
        self.intentos_verificacion = 0
        self.casos_abiertos: dict = {}  # transaction_id -> caso_id (prevents disputing the same charge twice)

    def tocar(self):
        self.last_activity = datetime.now()

    def expirada(self):
        return (datetime.now() - self.last_activity) > timedelta(minutes=PERMISOS["SESSION_TIMEOUT_MIN"])


def requiere_sesion_valida(session: Session | None, customer_id_solicitado: str | None = None):
    """Check that ANY sensitive tool must pass before executing anything.

    customer_id_solicitado: the customer_id the tool is about to query/modify.
    If it does not match the customer_id verified in the session, it is rejected — this is what
    prevents a session of customer A from being used (by mistake or via prompt injection)
    to read or modify the data of customer B.
    """
    if session is None or not session.verificado:
        return {"ok": False, "motivo": "NOT_VERIFIED",
                "mensaje": "The customer has not been verified in this session."}
    if session.expirada():
        return {"ok": False, "motivo": "SESSION_EXPIRED",
                "mensaje": "The session expired due to inactivity. The customer's identity must be re-verified."}
    if customer_id_solicitado is not None and customer_id_solicitado != session.customer_id:
        return {"ok": False, "motivo": "UNAUTHORIZED_ACCESS",
                "mensaje": f"The verified session belongs to {session.customer_id}; it cannot be used "
                           f"to access data of {customer_id_solicitado}."}
    return {"ok": True}


def _fallo_verificacion(session: Session, motivo: str, mensaje: str):
    session.intentos_verificacion += 1
    if session.intentos_verificacion >= PERMISOS["MAX_INTENTOS_VERIFICACION"]:
        return {"ok": False, "motivo": "MAX_INTENTOS_EXCEDIDO",
                "mensaje": "Too many failed verification attempts. Escalating to a human agent.",
                "requiere_escalacion": True}
    return {"ok": False, "motivo": motivo, "mensaje": mensaje,
            "intentos_restantes": PERMISOS["MAX_INTENTOS_VERIFICACION"] - session.intentos_verificacion}


def _activar_sesion(row: dict, session: Session):
    if row["customer_status"] != "Active":
        return {"ok": False, "motivo": "CLIENTE_INACTIVO",
                "mensaje": "The customer is not active. Requires attention from a human agent.",
                "requiere_escalacion": True}
    session.customer_id = row["customer_id"]
    session.verificado = True
    session.tocar()
    cliente = {k: row[k] for k in ("customer_id", "first_name", "last_name", "segment", "country", "customer_status",
                                   "credit_score", "estimated_monthly_income")}
    return {"ok": True, "cliente": cliente}


_DESC = "coalesce(merchant_name, transaction_type || ' · ' || channel) AS descripcion"

_COLS_CLIENTE = ("customer_id, first_name, last_name, document_number, segment, country, customer_status, "
                 "credit_score, estimated_monthly_income")


# ---------------------------------------------------------------------------
# TOOL 0 — identificar_cliente (identify by document number + full name, like a real bank)
# ---------------------------------------------------------------------------
def identificar_cliente(document_number: str, nombre_completo: str, session: Session):
    """Verifies identity with two factors the customer knows (document + name). The customer never
    gives (nor knows) the internal customer_id."""
    doc = "".join(ch for ch in str(document_number or "") if ch.isalnum()).upper()
    rows = _records(_con().execute(
        f"SELECT {_COLS_CLIENTE} FROM customers WHERE upper(regexp_replace(document_number, '[^A-Za-z0-9]', '', 'g')) = ?",
        [doc]).df())
    if not rows:
        return _fallo_verificacion(session, "CLIENTE_NO_ENCONTRADO",
                                   "No customer was found with that document number.")
    dado = set(_norm(nombre_completo).split())
    for row in rows:
        nombre = set(_norm(row["first_name"]).split())
        apellido = set(_norm(row["last_name"]).split())
        # first name AND at least one surname must match
        if nombre & dado and apellido & dado:
            return _activar_sesion(row, session)
    return _fallo_verificacion(session, "DATOS_NO_COINCIDEN",
                               "The name does not match the document on file.")


# ---------------------------------------------------------------------------
# TOOL 1 — verificar_cliente (verify by internal id — back-office / tests only)
# ---------------------------------------------------------------------------
def verificar_cliente(customer_id: str, session: Session):
    """Fetches the customer's data. Does not require a verified session (it is what verifies it)."""
    rows = _records(_con().execute(f"SELECT {_COLS_CLIENTE} FROM customers WHERE customer_id = ?",
                                   [customer_id]).df())
    if not rows:
        return _fallo_verificacion(session, "CLIENTE_NO_ENCONTRADO", "That customer_id was not found.")
    return _activar_sesion(rows[0], session)


# ---------------------------------------------------------------------------
# TOOL 2 — consultar_transacciones_recientes (query recent transactions)
# ---------------------------------------------------------------------------
def consultar_transacciones_recientes(customer_id: str, session: Session, dias: int = 30):
    chk = requiere_sesion_valida(session, customer_id_solicitado=customer_id)
    if not chk["ok"]:
        return chk
    session.tocar()
    dias = max(1, min(int(dias or 30), 90))
    desde = hoy_simulado() - timedelta(days=dias)
    df = _con().execute(
        "SELECT transaction_id, transaction_date, transaction_type, amount, currency, amount_usd, merchant_name, "
        f"merchant_category, channel, transaction_status, is_fraud, fraud_score, {_DESC} "
        "FROM txns WHERE customer_id = ? AND transaction_date >= ? ORDER BY transaction_date DESC LIMIT 50",
        [customer_id, desde]).df()
    return {"ok": True, "dias": dias, "transacciones": _records(df), "n": len(df)}


# ---------------------------------------------------------------------------
# TOOL 3 — buscar_cargo_disputado (finds the exact transaction the customer describes)
# ---------------------------------------------------------------------------
def buscar_cargo_disputado(customer_id: str, session: Session, monto_aprox: float, tolerancia_pct: float = 0.05):
    chk = requiere_sesion_valida(session, customer_id_solicitado=customer_id)
    if not chk["ok"]:
        return chk
    session.tocar()
    tolerancia_pct = max(0.0, min(float(tolerancia_pct or 0.05), 0.15))  # the model can't widen the net at will
    lo, hi = float(monto_aprox) * (1 - tolerancia_pct), float(monto_aprox) * (1 + tolerancia_pct)
    # local-currency amounts are quoted exactly (big numbers: 5% of 1,000,000 COP would match unrelated charges)
    lo_l, hi_l = float(monto_aprox) * 0.99, float(monto_aprox) * 1.01
    # customers quote either the USD amount or the amount in their local currency
    df = _con().execute(
        "SELECT transaction_id, transaction_date, transaction_type, amount, currency, amount_usd, merchant_name, "
        f"channel, transaction_status, is_fraud, fraud_score, {_DESC} FROM txns "
        "WHERE customer_id = ? AND transaction_type <> 'Deposit' "
        "AND (amount_usd BETWEEN ? AND ? OR amount BETWEEN ? AND ?) "
        "ORDER BY transaction_date DESC",
        [customer_id, lo, hi, lo_l, hi_l]).df()
    if df.empty:
        return {"ok": True, "encontrada": False,
                "mensaje": "No transaction with that amount was found. This may be an ambiguous case."}
    return {"ok": True, "encontrada": True, "n": len(df), "candidatas": _records(df),
            "ambigua": len(df) > 1,
            "mensaje": ("Several transactions match; ask the customer which one (date/merchant)."
                        if len(df) > 1 else "One transaction matches.")}


# ---------------------------------------------------------------------------
# TOOL 4 — calcular_riesgo_caso (same rule documented in 02_priority_model.ipynb)
# ---------------------------------------------------------------------------
def es_reincidente_en_datos(customer_id: str) -> bool:
    r = _con().execute("SELECT is_repeat_complainer, n_complaints FROM complaint_stats WHERE customer_id = ?",
                       [customer_id]).fetchone()
    return bool(r and (r[0] or (r[1] or 0) >= 2))


def calcular_riesgo_caso(cliente: dict, monto_reclamado: float, categoria: str,
                          canal_recepcion: str, es_reincidente: bool):
    """
    Risk rule documented in 02_priority_model.ipynb (Step 2 and Step 7).
    It is not a black-box model: every factor that adds to the score can be explained.
    The 'typical amount' threshold is the median claimed amount of the complaints table (same as the notebook).
    """
    razones = []
    score = 0
    umbral = umbral_monto_tipico()

    if monto_reclamado is not None and monto_reclamado > umbral:
        score += 1
        razones.append(f"Claimed amount (${monto_reclamado:,.2f}) above the median claim (${umbral:,.0f})")
    if es_reincidente:
        score += 1
        razones.append("Repeat complainer (already has prior complaints)")
    if categoria in ("Transactions", "Fees"):
        score += 1
        razones.append(f"High-severity category ({categoria})")
    if canal_recepcion in PERMISOS["CANALES_ESCALACION_OBLIGATORIA"]:
        score += 2
        razones.append("Arrived through the regulatory channel — reputational/legal severity")
    if cliente.get("segment") in PERMISOS["SEGMENTOS_ALTO_VALOR"]:
        score += 1
        razones.append(f"High-value customer ({cliente.get('segment')} segment) — churn risk")

    nivel = "Alto" if score >= 2 else "Bajo"
    out = {"ok": True, "score": score, "nivel_riesgo": nivel, "factores": razones,
           "explicacion": " · ".join(razones) if razones else "No relevant risk factors"}

    # Extra signal for the human: probability from the trained ML model (never changes the decision)
    try:
        from ml.priority_model import predecir_prob_alto_riesgo
        p = predecir_prob_alto_riesgo(cliente, monto_reclamado, categoria, canal_recepcion, es_reincidente)
        if p is not None:
            out["prob_ml_alto_riesgo"] = p
    except Exception:  # model not trained / not available -> rule only
        pass
    return out


# ---------------------------------------------------------------------------
# TOOL 5 — abrir_caso_disputa (open dispute case; the most important permissions live here)
# ---------------------------------------------------------------------------
def abrir_caso_disputa(customer_id: str, session: Session, transaction_id: str,
                        monto_usd: float, categoria: str, canal_recepcion: str,
                        riesgo: dict):
    chk = requiere_sesion_valida(session, customer_id_solicitado=customer_id)
    if not chk["ok"]:
        return chk
    session.tocar()

    # The transaction must exist AND belong to this customer. The amount used for the decision is the
    # one in the bank's records, never the one the model sends.
    rows = _records(_con().execute(
        "SELECT transaction_id, transaction_type, amount_usd, amount, currency, merchant_name, channel, transaction_date, "
        f"transaction_status, is_fraud, fraud_score, {_DESC} FROM txns WHERE transaction_id = ? AND customer_id = ?",
        [transaction_id, customer_id]).df())
    if not rows:
        return {"ok": False, "motivo": "TRANSACCION_NO_ENCONTRADA",
                "mensaje": f"Transaction {transaction_id} does not exist for this customer. "
                           "A case cannot be opened for a charge that is not in the customer's records."}
    txn = rows[0]
    if txn.get("transaction_type") == "Deposit":
        return {"ok": False, "motivo": "NO_ES_CARGO",
                "mensaje": "That transaction is a deposit (money in), not a charge; it cannot be disputed as an unrecognized charge."}
    if transaction_id in session.casos_abiertos:
        return {"ok": False, "motivo": "CASO_DUPLICADO",
                "mensaje": f"A dispute is already open for this charge ({session.casos_abiertos[transaction_id]})."}

    monto_real = float(txn["amount_usd"])
    avisos = []
    if monto_usd is not None and abs(float(monto_usd) - monto_real) > max(1.0, 0.01 * monto_real):
        avisos.append(f"Amount sent by the model (${float(monto_usd):,.2f}) ignored; "
                      f"real amount on record is ${monto_real:,.2f}.")
    monto_usd = monto_real

    caso_id = f"CASE-{uuid.uuid4().hex[:10].upper()}"

    # --- Permissions enforced in code, never delegated to the model ---
    motivo_escalacion = []
    if monto_usd >= PERMISOS["MONTO_MAX_SIN_ESCALAR_USD"]:
        motivo_escalacion.append(f"Amount (${monto_usd:,.2f}) exceeds the maximum the agent can handle on its own "
                                 f"(${PERMISOS['MONTO_MAX_SIN_ESCALAR_USD']:,})")
    if canal_recepcion in PERMISOS["CANALES_ESCALACION_OBLIGATORIA"]:
        motivo_escalacion.append("Reception channel mandates escalation (regulator)")
    if txn.get("is_fraud") or (txn.get("fraud_score") or 0) >= PERMISOS["FRAUD_SCORE_ESCALACION"]:
        motivo_escalacion.append(f"Suspected fraud on the transaction (fraud_score {txn.get('fraud_score')}) "
                                 "— fraud team must review")
    if riesgo.get("nivel_riesgo") == "Alto" and monto_usd > PERMISOS["MONTO_MAX_AUTO_RESOLUCION_USD"]:
        motivo_escalacion.append("High risk + amount above the auto-approvable limit")
    requiere_escalacion = bool(motivo_escalacion)

    if requiere_escalacion:
        decision = "ESCALADO_A_HUMANO"
        mensaje = "Case requires review by a human agent: " + "; ".join(motivo_escalacion)
    elif monto_usd <= PERMISOS["MONTO_MAX_AUTO_RESOLUCION_USD"]:
        decision = "AUTO_APROBADO"
        mensaje = (f"Refund of ${monto_usd:,.2f} automatically approved "
                   f"(within the ${PERMISOS['MONTO_MAX_AUTO_RESOLUCION_USD']} limit).")
    else:
        decision = "PENDIENTE_REVISION"
        mensaje = "Case opened, pending standard review (not urgent, not auto-approvable)."

    session.casos_abiertos[transaction_id] = caso_id
    return {
        "ok": True,
        "caso_id": caso_id,
        "decision": decision,
        "mensaje": mensaje,
        "requiere_escalacion": requiere_escalacion,
        "motivos_escalacion": motivo_escalacion,
        "monto_usd": monto_usd,
        "transaccion": txn,
        "riesgo": riesgo,
        "avisos": avisos,
    }


# ---------------------------------------------------------------------------
# TOOL 6 — escalar_a_humano (the agent can NEVER revert this once called)
# ---------------------------------------------------------------------------
def escalar_a_humano(caso_id: str, motivo: str, session: Session):
    # Escalating must always be possible, even without a verified session (e.g. the customer could not be
    # identified, or is angry before giving data). It never exposes customer data, so it needs no session.
    return {
        "ok": True,
        "caso_id": caso_id or f"HANDOFF-{uuid.uuid4().hex[:8].upper()}",
        "estado": "ESCALADO",
        "motivo": motivo,
        "customer_id": getattr(session, "customer_id", None) if session and session.verificado else None,
        "mensaje": "The case was placed in the human agents' queue. The AI agent cannot revert this.",
    }


# ===========================================================================
# TESTS — against the real sample data, to show that it works
# ===========================================================================
if __name__ == "__main__":
    import time

    t0 = time.time()
    con = _con()
    print(f"Data loaded once in {time.time() - t0:.1f}s from {_STATS['fuente_datos']} "
          f"| simulated 'today' = {hoy_simulado()} | typical-amount threshold = ${umbral_monto_tipico():,.0f}")

    def pick(sql):
        return _records(con.execute(sql).df())[0]

    base = ("SELECT c.customer_id, c.document_number, c.first_name, c.last_name, c.segment, t.transaction_id, "
            "t.amount_usd FROM customers c JOIN txns t USING (customer_id) WHERE c.customer_status='Active' "
            "AND NOT t.is_fraud AND t.fraud_score < 70 AND c.customer_id NOT IN "
            "(SELECT customer_id FROM complaint_stats WHERE is_repeat_complainer OR n_complaints>=2) ")
    low = pick(base + "AND c.segment='Basic' AND t.amount_usd BETWEEN 50 AND 250 ORDER BY c.customer_id LIMIT 1")
    mid = pick(base + "AND c.segment='Basic' AND t.amount_usd BETWEEN 400 AND 1200 ORDER BY c.customer_id LIMIT 1")
    high = pick(base + "AND t.amount_usd > 3000 ORDER BY c.customer_id LIMIT 1")
    other = pick(base + f"AND c.customer_id <> '{low['customer_id']}' ORDER BY c.customer_id LIMIT 1")

    def riesgo_para(cli, monto, canal="App", cat="Transactions"):
        return calcular_riesgo_caso(cli, monto, cat, canal, es_reincidente_en_datos(cli["customer_id"]))

    print("\n=== Case 0: identify by document + name ===")
    s = Session()
    r = identificar_cliente(low["document_number"], f"{low['first_name']} {low['last_name']}", s)
    print("identificar_cliente:", r["ok"], r.get("cliente", {}).get("segment"))
    assert r["ok"] and s.customer_id == low["customer_id"]
    bad = identificar_cliente(low["document_number"], "Nombre Inventado", Session())
    assert bad["ok"] is False and bad["motivo"] == "DATOS_NO_COINCIDEN"

    print("\n=== Case 1: low amount, Basic, no risk factors -> AUTO_APROBADO ===")
    rk = riesgo_para(r["cliente"], low["amount_usd"], cat="Service")
    c1 = abrir_caso_disputa(low["customer_id"], s, low["transaction_id"], low["amount_usd"], "Service", "App", rk)
    print(c1["decision"], "-", c1["mensaje"])
    assert c1["decision"] == "AUTO_APROBADO"

    print("\n=== Case 1b: same charge again -> CASO_DUPLICADO ===")
    assert abrir_caso_disputa(low["customer_id"], s, low["transaction_id"], 1, "Service", "App", rk)["motivo"] == "CASO_DUPLICADO"

    print("\n=== Case 2: high amount -> ESCALADO_A_HUMANO regardless of what the model sends ===")
    s2 = Session(); verificar_cliente(high["customer_id"], s2)
    rk2 = riesgo_para(high, high["amount_usd"])
    c2 = abrir_caso_disputa(high["customer_id"], s2, high["transaction_id"], 50, "Transactions", "App", rk2)
    print(c2["decision"], "-", c2["mensaje"], c2["avisos"])
    assert c2["decision"] == "ESCALADO_A_HUMANO" and c2["avisos"], "the model's $50 must be ignored"

    print("\n=== Case 3: regulator channel -> mandatory escalation even if the amount is low ===")
    s3 = Session(); verificar_cliente(other["customer_id"], s3)
    rk3 = riesgo_para(other, other["amount_usd"], canal="Regulator", cat="Service")
    c3 = abrir_caso_disputa(other["customer_id"], s3, other["transaction_id"], other["amount_usd"], "Service", "Regulator", rk3)
    assert c3["decision"] == "ESCALADO_A_HUMANO"

    print("\n=== Case 4: expired session -> rejection ===")
    old = Session(customer_id=low["customer_id"], verificado=True)
    old.last_activity = datetime.now() - timedelta(minutes=30)
    assert consultar_transacciones_recientes(low["customer_id"], old)["motivo"] == "SESSION_EXPIRED"

    print("=== Case 5: unverified session -> rejection ===")
    assert consultar_transacciones_recientes(low["customer_id"], Session())["motivo"] == "NOT_VERIFIED"

    print("=== Case 6: session of A tries to read B -> rejection ===")
    assert consultar_transacciones_recientes(other["customer_id"], s)["motivo"] == "UNAUTHORIZED_ACCESS"

    print("=== Case 6b: session of A disputes B's transaction -> rejection ===")
    assert abrir_caso_disputa(low["customer_id"], s, other["transaction_id"], 10, "Service", "App", rk)["motivo"] == "TRANSACCION_NO_ENCONTRADA"

    print("\n=== Case 7 (AMBIGUOUS #1): medium amount, low risk, Basic -> PENDIENTE_REVISION ===")
    s7 = Session(); verificar_cliente(mid["customer_id"], s7)
    rk7 = riesgo_para(mid, mid["amount_usd"], cat="Branch")
    c7 = abrir_caso_disputa(mid["customer_id"], s7, mid["transaction_id"], mid["amount_usd"], "Branch", "App", rk7)
    print(c7["decision"], "-", c7["mensaje"])
    assert c7["decision"] == "PENDIENTE_REVISION"

    print("\n=== Case 8 (AMBIGUOUS #2): charge that does not exist -> encontrada False ===")
    r8 = buscar_cargo_disputado(mid["customer_id"], s7, monto_aprox=999999.99)
    assert r8["ok"] is True and r8["encontrada"] is False

    t1 = time.time()
    for _ in range(20):
        consultar_transacciones_recientes(mid["customer_id"], s7, 60)
    print(f"\nAvg tool latency after warm-up: {(time.time() - t1) / 20 * 1000:.1f} ms")
    print("\nALL TESTS PASSED ✅ (auto-approved, escalated, ambiguous, security)")
