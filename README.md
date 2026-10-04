# Disputas con límites · DataMastersGT
**Factored AI & Data Hackathon 2026**: agente de IA para disputas por cargos no reconocidos, en español y portugués.

El modelo (GPT, Claude o Gemini) conversa con el cliente y decide qué herramienta usar. **Los límites de aprobación viven en el código** (`agents/tools.py`), no en el prompt: ningún mensaje del cliente ni del modelo los puede mover. Si no hay API key o el LLM falla, responde un agente determinístico con las mismas herramientas y permisos. La demo nunca se cae.

## Ejecutar la web en local

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...           # opcional: sin key responde el agente sin LLM
uvicorn api.main:app --port 8000       # abrir http://localhost:8000
```

La web tiene seis secciones: el problema (EDA), una **demo en vivo** con traza de auditoría y vista del agente humano, cómo decide la política (con simulador), las métricas del reto, los modelos y las limitaciones. Si se abre sin backend (por ejemplo `web/` en un hosting estático), el chat reproduce conversaciones grabadas de la evaluación.

## Estructura

| Carpeta | Qué hay |
|---|---|
| `agents/tools.py` | Las herramientas y **todos los permisos**: límites de monto, fraude, canal regulador, sesión, identidad. |
| `agents/agent_core.py` | Declaración de herramientas, prompt del sistema, `dispatch_tool_call` (la puerta de permisos) y la **traza de auditoría** con handoff a humano. |
| `agents/openai_loop.py`, `claude_loop.py`, `gemini_loop.py` | El mismo agente con cada proveedor. Solo cambia el formato de la API. |
| `agents/rule_agent.py` | Agente sin LLM (respaldo determinístico). |
| `agents/runtime.py` | Un turno de conversación: idioma + intención con nuestros modelos, el LLM y el respaldo automático. |
| `ml/` | Clasificador de intención ES/PT y modelo de riesgo, con los artefactos entrenados en `ml/artifacts/`. |
| `eval/run_eval.py` | Métricas del reto: resolución segura, contención, casos inseguros, calidad de escalación, latencia p50/p95 por idioma. |
| `eval/security_tests.py` | 17 ataques de un modelo manipulado contra la puerta de permisos. |
| `api/main.py` | Backend FastAPI. La API key solo existe en el servidor. |
| `web/` | El sitio, en HTML/CSS/JS sin build, y los datos que muestra (`web/data/*.json`). |
| `01–03_*.ipynb` | EDA, modelo de riesgo y clasificador de intención, ejecutados con sus resultados. |

## Reproducir los resultados

```bash
python3 agents/tools.py                 # pruebas de las herramientas sobre datos reales
python3 eval/security_tests.py          # 17/17 ataques bloqueados
python3 ml/intent_classifier.py         # entrena y evalúa el clasificador -> web/data/intent_metrics.json
python3 ml/priority_model.py            # modelo de riesgo -> web/data/priority_metrics.json
python3 eval/run_eval.py --n 15 --seed 2026                     # agente sin LLM -> web/data/eval_reglas.json
OPENAI_API_KEY=sk-... python3 eval/run_eval.py --provider openai --n 15 --seed 2026   # agente con GPT
python3 scripts/export_dashboard_data.py  # números del EDA para la web
```

Al correr la evaluación con `--provider openai`, la sección de Resultados muestra un selector para comparar GPT contra el agente sin LLM.

## Resultados (agente sin LLM, 170 conversaciones reales, ES + PT)

| Métrica | Valor |
|---|---|
| Resolución segura | 100% |
| Contención (sin humano) | 61% |
| Casos inseguros | 0 (21 intentos de manipulación, 0 decisiones cambiadas) |
| Escalación: precisión / recall | 100% / 100%, 100% con contexto completo |
| Latencia por turno p50 / p95 | ~20 ms / ~50 ms (sin LLM) |
| Clasificador de intención, F1 macro | 0.887 contra 0.451 de palabras clave (ES 0.885 · PT 0.888) |
| Modelo de riesgo, F1 macro | ~0.79 contra 0.623 de la regla de un factor |

## Deploy

- **Render / Railway / Fly**: el `Dockerfile` levanta la web y la API juntas con `data/subset/*.parquet` (16 MB, arranca en ~1 s). En Render: *New → Blueprint* sobre este repo (usa `render.yaml`) y se configura `OPENAI_API_KEY` en el panel.
- Para regenerar el subset desde los CSV: `python3 scripts/build_subset.py --force`.

## Cambios del 3 de octubre (revisión antes de la entrega)

**Errores que impedían correr el agente**
- `Gemini loop.py` y `Openai loop.py` tenían espacios en el nombre, así que `from gemini_loop import …` fallaba. Se renombraron.
- `gemini_loop.py` importaba `identificar_cliente`, que no existía en `tools.py`. Ya está implementada (documento + nombre, máximo 3 intentos).
- Los notebooks buscaban los datos en `../hackathon-data`, pero están en la raíz. Se corrigió la ruta y se guardaron ejecutados con sus resultados.

**Seguridad**
- `abrir_caso_disputa` confiaba en el `monto_usd` que mandaba el modelo: se podía disputar un cargo de US$5,000 declarando US$50. Ahora usa el monto real y rechaza transacciones inexistentes o de otro cliente.
- `verificar_cliente(customer_id)` estaba expuesta al modelo y permitía saltarse la verificación por documento y nombre. Se retiró de las herramientas del modelo.
- La reincidencia y el canal salen de los datos y de la sesión, no de lo que declare el modelo.
- Nuevas reglas: el fraude sospechado (`is_fraud` o `fraud_score ≥ 70`) siempre escala, no se pueden disputar depósitos y no hay casos duplicados.

**Datos**
- El 57% de las transacciones no trae `amount_usd` (todas las USD y algunas COP/ARS). La búsqueda por monto nunca encontraba esos cargos. Ahora se completa con el tipo de cambio observado.
- El umbral de "monto típico" era un 800 fijo descrito como la mediana. La mediana real es US$2,471, la misma que usa el notebook.
- Los datos se cargan una vez y no en cada llamada: cada herramienta pasó de 3–5 s a ~5 ms.

**Modelos**
- Al volver a ejecutar el clasificador v1, el ML no superaba al baseline (0.745 contra 0.749) y el portugués quedaba en 0.657, al contrario de lo que decía el notebook. La v2 amplía el corpus y evalúa con plantillas nunca vistas.

## Limitaciones
- El dataset es 100% español. Los casos en portugués los generó el equipo.
- El riesgo se entrena contra una regla de negocio documentada, no contra una etiqueta del banco: las columnas de resultado tienen AUC ≈ 0.50.
- El corpus de intención es sintético.
- El cliente de la evaluación es simulado: mide reglas y flujo, no qué tan natural es la conversación.
