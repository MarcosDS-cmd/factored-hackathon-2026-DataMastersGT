"""
Risk/priority model — reproduces 02_priority_model.ipynb exactly (same seeds) and exports it for the agent.
Factored Hackathon 2026 — Team DataMastersGT

Run:  python3 ml/priority_model.py   -> ml/artifacts/priority_model.joblib + web/data/priority_metrics.json

The agent uses predecir_prob_alto_riesgo() as an EXTRA SIGNAL shown to the human agent in the trace.
It never decides amounts or approvals — those are the permission rules in agents/tools.py.
"""

from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ART = os.path.join(HERE, "artifacts")
OUT_JSON = os.path.join(ROOT, "web", "data", "priority_metrics.json")
BASE = os.environ.get("HACKATHON_DATA", os.path.join(ROOT, "hackathon-data"))

FEAT_CAT = ["case_type", "category", "subcategory", "reception_channel", "segment", "country"]
FEAT_NUM = ["claimed_amount", "is_repeat_complainer", "credit_score", "claimed_amount_missing"]
FEAT_NUM_V2 = FEAT_NUM + ["estimated_monthly_income"]


def _pipeline(num):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
    prep = ColumnTransformer([
        ("cat", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="missing")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore"))]), FEAT_CAT),
        ("num", SimpleImputer(strategy="median"), num)])
    return Pipeline([("prep", prep), ("clf", RandomForestClassifier(
        n_estimators=300, max_depth=8, min_samples_leaf=15, class_weight="balanced", random_state=42))])


def entrenar_y_exportar(guardar: bool = True):
    import duckdb
    from sklearn.metrics import f1_score, roc_auc_score, confusion_matrix

    con = duckdb.connect()
    con.execute(f"CREATE VIEW complaints AS SELECT * FROM read_csv_auto('{BASE}/complaints/**/*.csv', ignore_errors=true, union_by_name=true)")
    con.execute(f"CREATE VIEW customers AS SELECT * FROM read_csv_auto('{BASE}/customers.csv', ignore_errors=true)")
    df = con.execute("""
        SELECT c.complaint_id, c.creation_date, c.customer_id, c.case_type, c.category, c.subcategory,
               c.reception_channel, c.claimed_amount, c.priority, c.is_repeat_complainer,
               cu.segment, cu.country, cu.credit_score, cu.estimated_monthly_income, c.sla_breached
        FROM complaints c LEFT JOIN customers cu ON c.customer_id = cu.customer_id""").df()
    df["creation_date"] = pd.to_datetime(df["creation_date"])
    df = df.sort_values("creation_date").reset_index(drop=True)
    df["sla_breached"] = df["sla_breached"].astype(int)
    df["claimed_amount_missing"] = df["claimed_amount"].isna().astype(int)
    median = df["claimed_amount"].median()

    prio_map = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    auc_prio = roc_auc_score(df["sla_breached"], df["priority"].map(prio_map))
    sla_por_prio = (df.groupby("priority")["sla_breached"].mean() * 100).round(1).to_dict()

    rng = np.random.default_rng(42)

    def score_v1(r):
        s = 0
        if pd.notna(r["claimed_amount"]) and r["claimed_amount"] > median: s += 1
        if r["is_repeat_complainer"]: s += 1
        if r["category"] in ("Transactions", "Fees"): s += 1
        if r["reception_channel"] == "Regulator": s += 2
        return s

    df["rule_risk_score"] = df.apply(score_v1, axis=1)
    df["high_risk"] = ((df["rule_risk_score"] + rng.normal(0, 0.6, size=len(df))) >= 2).astype(int)
    df["risk_score_v2"] = df["rule_risk_score"] + df["segment"].isin(["Premium", "Plus"]).astype(int)
    df["high_risk_v2"] = ((df["risk_score_v2"] + rng.normal(0, 0.6, size=len(df))) >= 2).astype(int)

    cutoff = df.iloc[int(len(df) * 0.8)]["creation_date"]
    train, test = df[df["creation_date"] < cutoff], df[df["creation_date"] >= cutoff]
    med_train = train["claimed_amount"].median()
    base = (test["claimed_amount"].fillna(0) > med_train).astype(int)

    m1 = _pipeline(FEAT_NUM).fit(train[FEAT_CAT + FEAT_NUM], train["high_risk"])
    p1 = m1.predict(test[FEAT_CAT + FEAT_NUM])
    m2 = _pipeline(FEAT_NUM_V2).fit(train[FEAT_CAT + FEAT_NUM_V2], train["high_risk_v2"])
    p2 = m2.predict(test[FEAT_CAT + FEAT_NUM_V2])
    prob2 = m2.predict_proba(test[FEAT_CAT + FEAT_NUM_V2])[:, 1]

    ohe = m1.named_steps["prep"].named_transformers_["cat"].named_steps["onehot"]
    names = list(ohe.get_feature_names_out(FEAT_CAT)) + FEAT_NUM
    imp = sorted(zip(names, m1.named_steps["clf"].feature_importances_), key=lambda x: -x[1])[:10]

    f1 = lambda yt, yp: round(float(f1_score(yt, yp, average="macro")), 3)
    res = {
        "diagnostico_etiquetas_banco": {
            "auc_prioridad_vs_sla": round(float(auc_prio), 3),
            "pct_sla_incumplido_por_prioridad": sla_por_prio,
            "nota": "AUC ~0.5: la prioridad asignada por el banco no predice el incumplimiento de SLA."},
        "split": {"tipo": "temporal 80/20", "corte": str(cutoff.date()), "n_train": len(train), "n_test": len(test)},
        "tasa_alto_riesgo": {"v1": round(float(df["high_risk"].mean()), 3), "v2": round(float(df["high_risk_v2"].mean()), 3)},
        "umbral_monto_mediana": round(float(median), 2),
        "v1": {"baseline_f1": f1(test["high_risk"], base), "ml_f1": f1(test["high_risk"], p1),
               "confusion_baseline": confusion_matrix(test["high_risk"], base).tolist(),
               "confusion_ml": confusion_matrix(test["high_risk"], p1).tolist()},
        "v2": {"baseline_f1": f1(test["high_risk_v2"], base), "ml_f1": f1(test["high_risk_v2"], p2),
               "auc_ml": round(float(roc_auc_score(test["high_risk_v2"], prob2)), 3)},
        "importancia_variables": [{"feature": n, "importancia": round(float(v), 4)} for n, v in imp],
        "promovidos_por_valor_cliente": int(((df["high_risk"] == 0) & (df["high_risk_v2"] == 1)).sum()),
        "n_total": len(df),
        "limitacion": "La etiqueta de riesgo es una regla de negocio documentada por el equipo (con ruido), no una etiqueta "
                      "historica validada por el banco: sla_breached / was_escalated / priority no tienen relacion "
                      "aprendible con las variables (AUC ~0.50).",
    }
    _CACHE["m"] = m2
    if guardar:
        import sklearn
        os.makedirs(ART, exist_ok=True)
        joblib.dump({"model": m2, "median": float(median)}, os.path.join(ART, "priority_model.joblib"))
        open(os.path.join(ART, "sklearn_version.txt"), "w").write(sklearn.__version__)
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


_CACHE = {}


def _modelo():
    if "m" not in _CACHE:
        import sklearn
        ver_file = os.path.join(ART, "sklearn_version.txt")
        mismo = os.path.exists(ver_file) and open(ver_file).read().strip() == sklearn.__version__
        if mismo:
            _CACHE["m"] = joblib.load(os.path.join(ART, "priority_model.joblib"))["model"]
        elif os.path.exists(os.path.join(BASE, "complaints")):
            # artifact from another scikit-learn version -> retrain in memory from the CSVs (same seeds, ~5 s)
            entrenar_y_exportar(guardar=False)
        else:
            _CACHE["m"] = None
    return _CACHE["m"]


def predecir_prob_alto_riesgo(cliente: dict, monto: float, categoria: str, canal: str, reincidente: bool):
    m = _modelo()
    if m is None:
        return None
    row = pd.DataFrame([{
        "case_type": "Complaint", "category": categoria,
        "subcategory": "Cargo no reconocido" if categoria == "Transactions" else None,
        "reception_channel": canal, "segment": cliente.get("segment"), "country": cliente.get("country"),
        "claimed_amount": monto, "is_repeat_complainer": int(bool(reincidente)),
        "credit_score": cliente.get("credit_score"), "claimed_amount_missing": int(monto is None),
        "estimated_monthly_income": cliente.get("estimated_monthly_income")}])
    return round(float(m.predict_proba(row)[0, 1]), 3)


if __name__ == "__main__":
    r = entrenar_y_exportar()
    print(json.dumps({k: r[k] for k in ("diagnostico_etiquetas_banco", "v1", "v2", "promovidos_por_valor_cliente")},
                     indent=1, ensure_ascii=False))
    print(predecir_prob_alto_riesgo({"segment": "Premium", "country": "México", "credit_score": 700,
                                     "estimated_monthly_income": 5000}, 3000, "Transactions", "App", False))
