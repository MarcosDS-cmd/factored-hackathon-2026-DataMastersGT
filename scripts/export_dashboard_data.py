"""Exports the EDA numbers the website needs (from the real CSVs) -> web/data/eda.json"""
import json
import os

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.environ.get("HACKATHON_DATA", os.path.join(ROOT, "hackathon-data"))
con = duckdb.connect()
for name, path in {"complaints": "complaints/**/*.csv", "cci": "call_center_interactions/**/*.csv",
                   "transcripts": "call_transcripts/**/*.csv", "surveys": "satisfaction_surveys/**/*.csv",
                   "txns": "transactions/**/*.csv"}.items():
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{B}/{path}', ignore_errors=true, union_by_name=true)")
con.execute(f"CREATE VIEW customers AS SELECT * FROM read_csv_auto('{B}/customers.csv', ignore_errors=true)")


def rows(sql):
    df = con.execute(sql).df()
    return json.loads(df.to_json(orient="records", date_format="iso"))


out = {
    "tamanos": rows("""SELECT 'Clientes' t, count(*) n FROM customers UNION ALL SELECT 'Quejas', count(*) FROM complaints
        UNION ALL SELECT 'Interacciones call center', count(*) FROM cci UNION ALL SELECT 'Transcripciones', count(*) FROM transcripts
        UNION ALL SELECT 'Encuestas', count(*) FROM surveys UNION ALL SELECT 'Transacciones (muestra)', count(*) FROM txns"""),
    "disputas": rows("""SELECT count(*) n, round(avg(claimed_amount),0) monto_prom,
        round(100.0*avg(sla_breached::int),1) pct_sla, round(avg(resolution_days),1) dias_prom,
        round(avg(resolution_satisfaction),2) satisf, sum((subcategory='Cargo no reconocido')::int) n_cargo_no_reconocido
        FROM complaints WHERE category='Transactions'""")[0],
    "por_categoria": rows("""SELECT category, count(*) n, round(avg(claimed_amount),0) monto_prom,
        round(100.0*avg(sla_breached::int),1) pct_sla, round(avg(resolution_days),1) dias
        FROM complaints GROUP BY 1 ORDER BY n DESC"""),
    "sla_por_prioridad": rows("""SELECT priority, count(*) n, round(100.0*avg(sla_breached::int),1) pct_sla,
        round(avg(resolution_days),1) dias FROM complaints GROUP BY 1
        ORDER BY CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"""),
    "por_mes": rows("""SELECT strftime(creation_date, '%Y-%m') mes, count(*) n,
        sum((category='Transactions')::int) n_transactions, round(100.0*avg(sla_breached::int),1) pct_sla
        FROM complaints GROUP BY 1 ORDER BY 1"""),
    "estado": rows("SELECT status, count(*) n FROM complaints GROUP BY 1 ORDER BY n DESC"),
    "canal": rows("SELECT reception_channel canal, count(*) n FROM complaints GROUP BY 1 ORDER BY n DESC"),
    "trazabilidad": rows("""SELECT round(100.0*avg((origin_interaction_id IS NOT NULL)::int),1) pct_ligadas, count(*) n
        FROM complaints WHERE category='Transactions'""")[0],
    "cci_por_motivo": rows("""SELECT reason_category motivo, count(*) n,
        round(100.0*avg(was_resolved::int),1) pct_resuelto_1er_contacto, round(100.0*avg(was_escalated::int),1) pct_escalado
        FROM cci GROUP BY 1 ORDER BY n DESC"""),
    "intenciones_dataset": rows("""SELECT coalesce(detected_intents, '(vacío)') intencion, count(*) n FROM transcripts
        GROUP BY 1 ORDER BY n DESC LIMIT 5"""),
    "idiomas_dataset": rows("SELECT detected_language idioma, count(*) n FROM transcripts GROUP BY 1"),
    "encuestas": rows("""SELECT survey_type tipo, round(avg(main_score),2) prom, min(main_score) min, max(main_score) max, count(*) n
        FROM surveys GROUP BY 1 ORDER BY n DESC"""),
    "calidad": rows("""SELECT count(*) total, round(100.0*avg((claimed_amount IS NULL)::int),1) pct_null_monto,
        round(100.0*avg((resolution_date IS NULL)::int),1) pct_null_resolucion FROM complaints""")[0],
    "monto_hist": rows("""SELECT least(floor(claimed_amount/500)*500, 6000) bucket, count(*) n FROM complaints
        WHERE category='Transactions' AND claimed_amount IS NOT NULL GROUP BY 1 ORDER BY 1"""),
}
os.makedirs(os.path.join(ROOT, "web", "data"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "web", "data", "eda.json"), "w"), ensure_ascii=False, indent=1)
print(json.dumps(out["disputas"]), out["trazabilidad"], out["por_mes"][:3])
