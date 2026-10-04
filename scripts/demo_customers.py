"""Picks real customers from the dataset for the demo personas (deterministic) -> web/data/demo_customers.json"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents")); sys.path.insert(0, ROOT)
from tools import _con, _records, hoy_simulado

con = _con()
hoy = hoy_simulado()
base = f"""
WITH recientes AS (
  SELECT customer_id, count(*) n_txn FROM txns WHERE transaction_date >= TIMESTAMP '{hoy}' - INTERVAL 60 DAY GROUP BY 1)
SELECT c.customer_id, c.document_type, c.document_number, c.first_name, c.last_name, c.segment, c.country,
       t.transaction_id, t.transaction_date, t.amount, t.currency, t.amount_usd, coalesce(t.merchant_name, t.transaction_type || ' · ' || t.channel) AS merchant_name, t.transaction_type, t.channel, t.is_fraud, t.fraud_score,
       r.n_txn
FROM customers c JOIN txns t USING (customer_id) JOIN recientes r USING (customer_id)
WHERE c.customer_status = 'Active' AND r.n_txn BETWEEN 3 AND 6
  AND t.transaction_date >= TIMESTAMP '{hoy}' - INTERVAL 60 DAY
  AND c.customer_id NOT IN (SELECT customer_id FROM complaint_stats WHERE is_repeat_complainer OR n_complaints >= 2)
  AND t.transaction_type <> 'Deposit'
  AND (SELECT count(*) FROM txns t2 WHERE t2.customer_id = c.customer_id
        AND t2.amount_usd BETWEEN t.amount_usd*0.95 AND t.amount_usd*1.05) = 1
"""
def one(cond, order="c.customer_id"):
    return _records(con.execute(base + " AND " + cond + f" ORDER BY {order} LIMIT 1").df())[0]

personas = [
 ("auto", "es", "Resolución automática", "Cargo pequeño, cliente sin factores de riesgo → reembolso aprobado al instante",
  one("c.segment='Basic' AND t.amount_usd BETWEEN 40 AND 250 AND NOT t.is_fraud AND t.fraud_score < 40 AND c.country='Colombia' AND t.merchant_name IS NOT NULL")),
 ("pendiente", "es", "Revisión estándar (ambiguo)", "Monto medio y riesgo bajo: ni se auto-aprueba ni se escala",
  one("c.segment='Basic' AND t.amount_usd BETWEEN 320 AND 1200 AND NOT t.is_fraud AND t.fraud_score < 40 ", "c.customer_id DESC")),
 ("escala_monto", "pt", "Escalación por monto", "Cargo por encima de US$1,500 → handoff obligatorio a un humano",
  one("c.segment IN ('Premium','Plus') AND t.amount_usd BETWEEN 2000 AND 6000 AND NOT t.is_fraud AND t.fraud_score < 40")),
 ("escala_fraude", "es", "Sospecha de fraude", "Monto pequeño pero la transacción tiene score de fraude alto → equipo de fraude",
  one("(t.is_fraud OR t.fraud_score >= 70) AND t.amount_usd <= 300")),
 ("auto_pt", "pt", "Resolução automática (PT)", "O mesmo fluxo de resolução automática, em português",
  one("c.segment='Basic' AND t.amount_usd BETWEEN 30 AND 200 AND NOT t.is_fraud AND t.fraud_score < 40 AND c.country='Argentina' AND t.merchant_name IS NOT NULL")),
]
out = []
for key, lang, titulo, desc, r in personas:
    out.append({"id": key, "idioma": lang, "titulo": titulo, "descripcion": desc,
                "documento": r["document_number"], "tipo_documento": r["document_type"],
                "nombre": f"{r['first_name']} {r['last_name']}", "segmento": r["segment"], "pais": r["country"],
                "cargo": {"transaction_id": r["transaction_id"], "fecha": str(r["transaction_date"])[:10],
                          "monto_usd": round(r["amount_usd"], 2), "monto_local": r["amount"], "moneda": r["currency"],
                          "comercio": r["merchant_name"], "fraud_score": r["fraud_score"], "is_fraud": r["is_fraud"]}})
os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "web", "data", "demo_customers.json"), "w"), ensure_ascii=False, indent=1)
for o in out: print(o["id"], o["nombre"], o["documento"], o["segmento"], o["pais"], o["cargo"])
