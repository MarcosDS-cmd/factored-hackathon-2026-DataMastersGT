"""
Intent classifier (ES/PT) — baseline vs. ML, honest evaluation, export for the agent.
Factored Hackathon 2026 — Team DataMastersGT

Run:  python3 ml/intent_classifier.py      -> trains, evaluates, writes:
        ml/artifacts/intent_model.joblib    (intent pipeline)
        ml/artifacts/lang_model.joblib      (language detector ES/PT)
        web/data/intent_metrics.json        (metrics shown on the website)

Use from the agent:
    from ml.intent_classifier import predecir_intencion, detectar_idioma
"""

from __future__ import annotations

import json
import os
import unicodedata

import joblib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ART = os.path.join(HERE, "artifacts")
OUT_JSON = os.path.join(ROOT, "web", "data", "intent_metrics.json")
CLASES = ["Transactional", "Product", "Complaint", "Technical", "Commercial", "Retention"]

# Baseline = the SAME keyword list used in 03_intent_classifier.ipynb (v1), accent-normalized so it is not
# penalized by customers typing without accents.
KEYWORDS = {
    "Transactional": ["cargo", "cobro", "transferencia", "retiro", "deposito", "transacao", "cobranca", "retirada"],
    "Product": ["tarjeta", "prestamo", "cuenta", "limite", "cartao", "emprestimo", "conta"],
    "Complaint": ["molesto", "queja", "reclamo", "grosero", "insatisfeito", "reclamacao", "mal-educado"],
    "Technical": ["app", "aplicacion", "clave", "token", "aplicativo", "senha", "site"],
    "Commercial": ["promocion", "oferta", "puntos", "promocoes", "pontos"],
    "Retention": ["cancelar", "cerrar", "cambiar de banco", "mudar de banco"],
}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return texto.lower()


def keyword_predict(texto: str) -> str:
    t = normalizar(texto)
    scores = {k: sum(1 for w in ws if w in t) for k, ws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Transactional"


def construir_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline, FeatureUnion

    feats = FeatureUnion([
        ("word", TfidfVectorizer(preprocessor=normalizar, ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("char", TfidfVectorizer(preprocessor=normalizar, analyzer="char_wb", ngram_range=(2, 5), min_df=2,
                                 sublinear_tf=True)),
    ])
    return Pipeline([("feats", feats), ("clf", LogisticRegression(max_iter=3000, C=10, class_weight="balanced"))])


def construir_lang():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    return Pipeline([("v", TfidfVectorizer(preprocessor=normalizar, analyzer="char_wb", ngram_range=(1, 4))),
                     ("c", LogisticRegression(max_iter=2000))])


def evaluar_y_exportar():
    import sys
    from sklearn.metrics import f1_score, confusion_matrix, classification_report, accuracy_score
    from sklearn.model_selection import StratifiedGroupKFold

    sys.path.insert(0, HERE)
    from intent_corpus import generar

    df = generar()
    y, X, g = df["label"].values, df["text"].values, df["template_id"].values
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)

    oof_ml = np.empty(len(df), dtype=object)
    oof_lang = np.empty(len(df), dtype=object)
    fold_f1 = []
    for tr, te in cv.split(X, y, groups=g):
        m = construir_pipeline().fit(X[tr], y[tr])
        oof_ml[te] = m.predict(X[te])
        lm = construir_lang().fit(X[tr], df["lang"].values[tr])
        oof_lang[te] = lm.predict(X[te])
        fold_f1.append({"ml": f1_score(y[te], oof_ml[te], average="macro"),
                        "baseline": f1_score(y[te], [keyword_predict(t) for t in X[te]], average="macro")})
    oof_base = np.array([keyword_predict(t) for t in X], dtype=object)

    def bloque(pred, mask=None):
        mask = np.ones(len(df), bool) if mask is None else mask
        rep = classification_report(y[mask], pred[mask], labels=CLASES, output_dict=True, zero_division=0)
        return {"f1_macro": round(f1_score(y[mask], pred[mask], average="macro", labels=CLASES), 3),
                "accuracy": round(accuracy_score(y[mask], pred[mask]), 3),
                "n": int(mask.sum()),
                "por_clase": {c: round(rep[c]["f1-score"], 3) for c in CLASES}}

    res = {
        "corpus": {"n_frases": len(df), "n_templates": int(df["template_id"].nunique()),
                   "por_idioma": df["lang"].value_counts().to_dict(),
                   "por_clase": df["label"].value_counts().to_dict(),
                   "ejemplos": df.sample(8, random_state=3)[["text", "label", "lang"]].to_dict(orient="records")},
        "metodo_eval": "StratifiedGroupKFold (5 folds) agrupando por plantilla: el modelo siempre se evalua con "
                       "formulaciones que nunca vio en entrenamiento.",
        "baseline": {"nombre": "Palabras clave (lista del notebook v1)", **bloque(oof_base)},
        "ml": {"nombre": "TF-IDF palabras + caracteres + Regresion Logistica", **bloque(oof_ml)},
        "por_idioma": {lang: {"baseline": bloque(oof_base, df["lang"].values == lang)["f1_macro"],
                              "ml": bloque(oof_ml, df["lang"].values == lang)["f1_macro"],
                              "n": int((df["lang"].values == lang).sum())} for lang in ("es", "pt")},
        "folds": [{k: round(v, 3) for k, v in f.items()} for f in fold_f1],
        "confusion_ml": {"labels": CLASES, "matrix": confusion_matrix(y, oof_ml, labels=CLASES).tolist()},
        "confusion_baseline": {"labels": CLASES, "matrix": confusion_matrix(y, oof_base, labels=CLASES).tolist()},
        "deteccion_idioma": {"accuracy": round(accuracy_score(df["lang"], oof_lang), 4)},
        "v1": {"nota": "Version anterior: 144 frases, split aleatorio (con fuga de plantillas)",
               "baseline": 0.749, "ml": 0.745, "es": 0.861, "pt": 0.657},
    }
    res["mejora_vs_baseline"] = round(res["ml"]["f1_macro"] - res["baseline"]["f1_macro"], 3)

    os.makedirs(ART, exist_ok=True)
    joblib.dump(construir_pipeline().fit(X, y), os.path.join(ART, "intent_model.joblib"))
    joblib.dump(construir_lang().fit(X, df["lang"].values), os.path.join(ART, "lang_model.joblib"))
    import sklearn
    open(os.path.join(ART, "sklearn_version.txt"), "w").write(sklearn.__version__)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


# ---------------------------------------------------------------------------
# Inference helpers used by the agent / API
# ---------------------------------------------------------------------------
_M = {}

PT_MARKERS = (" nao ", " voce", " meu ", " minha ", " uma ", " cobranca", " cartao", " obrigad", " ola", " estou ",
              " quero ", " nao.", "ção", "ções", "ã", "õ")


def _modelo(nombre):
    import sys
    # the pickled pipeline references `normalizar`; make it resolvable whatever name this module was imported as
    for alias in ("intent_classifier", "ml.intent_classifier", "__main__"):
        mod = sys.modules.get(alias)
        if mod is None or not hasattr(mod, "normalizar"):
            sys.modules[alias] = sys.modules[__name__] if alias != "__main__" else sys.modules.get("__main__")
    if nombre not in _M:
        import sklearn
        ver_file = os.path.join(ART, "sklearn_version.txt")
        mismo = os.path.exists(ver_file) and open(ver_file).read().strip() == sklearn.__version__
        try:
            if not mismo:
                raise RuntimeError("artifact saved with another scikit-learn version")
            _M[nombre] = joblib.load(os.path.join(ART, f"{nombre}.joblib"))
        except Exception:
            # artifact missing or from another scikit-learn version -> retrain from the corpus in memory (~3 s)
            import sys as _s
            _s.path.insert(0, HERE)
            from intent_corpus import generar
            df = generar()
            if nombre == "intent_model":
                _M[nombre] = construir_pipeline().fit(df["text"].values, df["label"].values)
            else:
                _M[nombre] = construir_lang().fit(df["text"].values, df["lang"].values)
    return _M[nombre]


def predecir_intencion(texto: str) -> dict:
    m = _modelo("intent_model")
    p = m.predict_proba([texto])[0]
    orden = np.argsort(p)[::-1]
    clases = m.classes_
    return {"intencion": str(clases[orden[0]]), "confianza": round(float(p[orden[0]]), 3),
            "top3": [{"intencion": str(clases[i]), "p": round(float(p[i]), 3)} for i in orden[:3]],
            "baseline_keywords": keyword_predict(texto)}


ES_WORDS = {"soy", "mi", "mis", "y", "el", "los", "las", "tengo", "quiero", "hola", "cargo", "cobro", "usted", "ustedes",
            "gracias", "nombre", "llamo", "hice", "reconozco", "tarjeta", "cuenta", "por", "favor", "puedo", "necesito",
            "ayer", "esto", "este", "muy", "pero", "si", "yo", "una", "es", "esta", "estoy", "la", "del", "al", "lo", "con",
            "hay", "hoy", "nadie", "deja", "puede", "pueden"}
PT_WORDS = {"sou", "meu", "minha", "e", "o", "os", "as", "tenho", "quero", "ola", "oi", "cobranca", "voce", "voces",
            "obrigado", "obrigada", "nome", "chamo", "fiz", "reconheco", "cartao", "conta", "pelo", "favor", "posso",
            "preciso", "ontem", "isso", "este", "muito", "mas", "sim", "eu", "uma", "nao", "esta", "estou", "da", "do", "na",
            "com", "ao", "pra", "hoje", "ninguem", "deixa", "pode", "podem", "ja", "tem"}


def detectar_idioma(texto: str, previo: str | None = None) -> str:
    """ES/PT. Function-word vote first (robust for short messages full of names/numbers), char-ngram model as tie-break.
    Very short messages without signal keep the conversation's previous language."""
    palabras = [w for w in normalizar(texto).replace(",", " ").replace(".", " ").split() if w.isalpha()]
    es = sum(w in ES_WORDS and w not in PT_WORDS for w in palabras)
    pt = sum(w in PT_WORDS and w not in ES_WORDS for w in palabras)
    if "ñ" in texto.lower() or "¿" in texto:
        es += 2
    if any(c in texto.lower() for c in "ãõç") or "ção" in texto.lower():
        pt += 2
    if abs(es - pt) >= 1 and max(es, pt) >= 1:
        return "es" if es > pt else "pt"
    if len(palabras) < 4 and previo:
        return previo
    try:
        return str(_modelo("lang_model").predict([texto])[0])
    except Exception:
        return previo or "es"


if __name__ == "__main__":
    import importlib, sys
    sys.path.insert(0, ROOT)
    mod = importlib.import_module("ml.intent_classifier")  # pickle functions under a stable module name
    evaluar_y_exportar, predecir_intencion, detectar_idioma = mod.evaluar_y_exportar, mod.predecir_intencion, mod.detectar_idioma
    r = evaluar_y_exportar()
    print(json.dumps({k: r[k] for k in ("baseline", "ml", "por_idioma", "mejora_vs_baseline", "deteccion_idioma", "folds")},
                     indent=1, ensure_ascii=False))
    for t in ["Hola, tengo un cargo de $120 en Netflix que no reconozco", "Olá, quero cancelar meu cartão",
              "la app no abre", "quiero hablar con un supervisor, esto es una verguenza"]:
        print(detectar_idioma(t), predecir_intencion(t)["intencion"], "|", t)
