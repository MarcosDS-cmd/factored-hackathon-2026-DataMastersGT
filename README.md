# Disputes with Limits · DataMastersGT

**Factored AI & Data Hackathon 2026** · Team **DataMastersGT** (Guatemala 🇬🇹) — Marcos Diaz & Daniel Machic · An AI agent that resolves unrecognized-charge disputes for a bank, in **Spanish and Portuguese**, where **approval limits live in code, not in the prompt**.

**Live demo:** https://disputas-datamastersgt.onrender.com  ·  **Customer portal (English):** https://disputas-datamastersgt.onrender.com/portal

> The free Render tier sleeps when idle. The first request can take ~30 s to wake the service.

---

## The idea in 30 seconds

A language model talks to the customer and decides *which tool to call and with what arguments*. It never decides the outcome. Every action goes through a permission gate written in Python (`agents/tools.py`), which enforces:

| Rule | Value |
|---|---|
| Auto-approval | amount ≤ US$300 and low risk |
| Mandatory human escalation | amount ≥ US$1,500 |
| Suspected fraud (`is_fraud` or `fraud_score ≥ 70`) | always escalates |
| Regulator channel | always escalates |
| High risk and amount > US$300 | escalates |
| Identity | document number + full name, max 3 attempts |
| Session | expires after 15 min of inactivity |

Amounts, risk, repeat-complainer status and channel are read from bank data and the server-side session, **never from what the model or the customer claims**. If there is no API key or the LLM fails, a deterministic agent with the same tools and permissions answers, so the demo never goes down.

---

## The three case types (try them in the live demo)

The demo's *Demo accounts* section preloads real customers from the dataset, one per scenario.

| Case | Customer (document · name) | What happens |
|---|---|---|
| **1. Normal resolution** | CE 8778722 · Roberto Gustavo Sánchez Romero (ES) | US$243.63 charge, low risk → refund auto-approved |
| **2. Ambiguous** | DNI 28695942 · Manuel Rodríguez Guerrero (ES) | US$344.04, low risk: above the auto-approval limit but not escalation-worthy → standard review |
| **3. Human escalation** | DNI 17521506 · Antonio Campos Ruiz (PT) | US$4,189.18 → mandatory handoff to a human with full context |

Also available: suspected fraud (CC 8590206241 · Gabriela Molina Díaz, fraud score 79 → fraud team) and automatic resolution in Portuguese (DNI 92426913 · Alberto Álvarez Giménez).

---

## Results

Evaluated on 170 real-data conversations, ES + PT, with the rule-based agent (no LLM). An LLM comparison (GPT) can be added with `--provider openai`.

| Metric | Value |
|---|---|
| Safe resolution | 100% |
| Containment (no human needed) | 61% |
| Unsafe cases | 0 (21 manipulation attempts, 0 decisions changed) |
| Escalation precision / recall | 100% / 100% (100% with full context) |
| Per-turn latency p50 / p95 | ~20 ms / ~50 ms (without LLM) |
| Security tests | 17/17 attacks blocked |

### Baseline vs. ML

| Model | Baseline | ML | Notes |
|---|---|---|---|
| Intent classifier (macro F1) | 0.451 (keywords) | **0.887** | ES 0.885 · PT 0.888 · TF-IDF words+chars + logistic regression · 1,273 phrases from 216 templates · StratifiedGroupKFold by template, so the model is always tested on wordings it has never seen |
| Risk model (macro F1) | 0.623 (single-factor rule) | **0.792** | AUC 0.899 · temporal split, cutoff 2026-05-14 · 1,430 cases promoted by customer value |
| Language detection | n/a | 99.7% accuracy | ES / PT |

### What the 17 security tests cover

A manipulated model tries to: declare a false amount, dispute another customer's charge, read another customer's data, skip identity verification, use an internal customer ID, brute-force identity, open a case without a risk calculation, lie about repeat-complainer status, hide the Regulator channel, widen the search tolerance, dispute a deposit, claim a double refund, keep acting after session expiry, invent a tool, or send corrupt arguments. All are rejected by the gate.

---

## Repository map

| Path | Contents |
|---|---|
| `agents/tools.py` | The tools and **all permissions**: amount limits, fraud, regulator channel, session, identity. |
| `agents/agent_core.py` | Tool declarations, system prompt, `dispatch_tool_call` (the permission gate) and the **audit trace** with human handoff. |
| `agents/openai_loop.py`, `claude_loop.py`, `gemini_loop.py` | The same agent with each provider. Only the API format changes. |
| `agents/rule_agent.py` | LLM-free deterministic fallback. |
| `agents/runtime.py` | One conversation turn: language + intent with our models, the LLM, and automatic fallback. |
| `ml/` | ES/PT intent classifier and risk model, with trained artifacts in `ml/artifacts/`. |
| `eval/run_eval.py` | Challenge metrics: safe resolution, containment, unsafe cases, escalation quality, latency by language. |
| `eval/security_tests.py` | The 17 attacks against the permission gate. |
| `api/main.py` | FastAPI backend. The API key only exists on the server. |
| `web/` | The site (plain HTML/CSS/JS, no build) and its data (`web/data/*.json`). |
| `web/portal/` | English customer portal: login, transactions, disputes, assistant. |
| `notebooks/` | `01_eda`, `02_priority_model`, `03_intent_classifier`, executed with results. |
| `hackathon-data/` | Sample of the challenge dataset (CSV, partitioned by date). |
| `data/subset/` | Clean tables used by the agent, as parquet (16 MB, for deployment). |
| `scripts/` | Utilities: demo customers, EDA data for the web, subset builder. |

**Suggested reading order:** `notebooks/` (01 → 02 → 03) for the problem and models, then `agents/tools.py` and `agents/agent_core.py` for the agent and its permissions, then `eval/` for the evidence, then `web/` served by `api/main.py` for the demo.

---

## Run it locally

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...          # optional: without a key the rule-based agent answers
uvicorn api.main:app --port 8000      # open http://localhost:8000
```

The site has six sections: the problem (EDA), a **live demo** with an audit trace and a human-agent view, how the policy decides (with a simulator), the challenge metrics, the models, and the limitations. If opened without the backend (e.g. `web/` on static hosting), the chat replays recorded evaluation conversations.

### Customer portal (`/portal`, English)

The end-customer experience. The customer signs in with document + name (the same verification the agent uses), sees the last 90 days of transactions and clicks **Dispute** on a charge. The agent resolves it on the spot (refund approved or standard review) or escalates it to a specialist with full context. The customer sees the status of each dispute.

- Sessions are random server-side tokens that expire after 15 min of inactivity; 5 failed attempts per document within 15 min lock the login.
- The agent answers in the customer's language (English, Spanish or Portuguese). In English, intent is detected by keywords because the ML classifier is trained on ES/PT.

---

## Reproduce the results

```bash
python3 agents/tools.py                  # tool tests on real data
python3 eval/security_tests.py           # 17/17 attacks blocked
python3 ml/intent_classifier.py          # trains and evaluates -> web/data/intent_metrics.json
python3 ml/priority_model.py             # risk model -> web/data/priority_metrics.json
python3 eval/run_eval.py --n 15 --seed 2026                     # rule-based agent -> web/data/eval_reglas.json
OPENAI_API_KEY=sk-... python3 eval/run_eval.py --provider openai --n 15 --seed 2026   # agent with GPT
python3 scripts/export_dashboard_data.py # EDA numbers for the web
```

When the evaluation runs with `--provider openai`, the Results section shows a selector to compare GPT against the rule-based agent.

---

## Path to production

What is already production-shaped: permissions enforced server-side, an audit trace for every tool call, session expiry and brute-force lockout, a deterministic fallback, a Docker image that starts in ~1 s, and a health check.

What a bank would still need:

1. **Real identity and authentication.** Replace document + name with the bank's own authentication (OTP / app login); keep the same gate behind it.
2. **Real data connectors.** Swap the parquet subset for read access to the core banking and card-dispute systems, with write access limited to opening a case.
3. **Human handoff queue.** Connect escalations to the bank's case-management tool, with the audit trace attached.
4. **Monitoring and human review.** Track containment, escalation rate, overrides and latency; sample auto-approved cases for review; re-check thresholds with the bank's risk team.
5. **Retraining on bank labels.** Replace the documented business rule with validated historical outcomes (see limitations) and monitor drift.
6. **Real Portuguese data and an LLM comparison.** Validate with native-speaker conversations and run the LLM evaluation at scale.
7. **Compliance.** PII handling, retention policy, regulator-channel procedures, security review.

---

## Next steps: how to scale the project

| Step | Why |
|---|---|
| Replace our risk rule with a real bank label | Once reliable history exists of which cases actually caused loss, fraud or churn, retrain against that instead of our documented rule. |
| Expand the intent corpus with real, anonymized conversations | Our synthetic corpus proves the concept; production needs thousands of real, human-reviewed labeled examples. |
| Add languages beyond Spanish and Portuguese | The architecture (classifier + agent) is not tied to a language: it grows by adding training corpus, not by redesigning. |
| Move risk scoring to a periodic retraining pipeline | So the model does not go stale when fraud or dispute patterns change. |
| Instrument cost, latency (p50/p95) and error rate in production | The challenge asks us to measure these; here we show they work, next is tracking them over time. |
| Add concurrency and load testing | Tests so far run one conversation at a time; we have not measured behavior with many simultaneous customers. |
| Persist a full audit log of every agent action | Today the system explains each decision in the trace; regulators need a durable record. |
| Run more aggressive prompt-injection tests | We proved amount limits cannot be bypassed; we have not tried more sophisticated attacks (e.g. extracting other customers' data through indirect paths). |
| Add cost monitoring and usage limits for the LLM API | Every agent call costs tokens; spend must be capped before exposing it to real traffic. |
| Separate test and production environments | Standard for banking systems; real data only in production so tests never touch real accounts. |
| Protect personal data (PII) | With real customers: encryption, access control and compliance with financial data-protection rules, none of which apply to this synthetic dataset. |

---

## Deploy

- **Render / Railway / Fly:** the `Dockerfile` starts the web and the API together with `data/subset/*.parquet` (16 MB, ~1 s startup). On Render: *New → Blueprint* on this repo (uses `render.yaml`) and set `OPENAI_API_KEY` in the dashboard.
- To rebuild the subset from the CSVs: `python3 scripts/build_subset.py --force`.

---

## Limitations (stated openly)

- The dataset is 100% Spanish. The Portuguese cases were generated by the team.
- Risk is trained against a documented business rule, not a bank label: the outcome columns (`sla_breached`, `was_escalated`, `priority`) have AUC ≈ 0.50 against the available variables. The bank's own priority does not predict SLA breaches (AUC 0.509).
- The intent corpus is synthetic (1,273 phrases from 216 templates).
- 57% of transactions have no `amount_usd`; we complete it with the observed exchange rate.
- The simulated customer used in the evaluation measures rules and flow, not how natural the conversation feels.
- Reference date for all calculations is 2026-06-18.

---

## Engineering notes

Fixes made during the final review, kept here because they affect trust in the results:

- **Security:** `abrir_caso_disputa` no longer trusts the amount sent by the model (a US$5,000 charge could be disputed as US$50); it uses the real amount and rejects non-existent or another customer's transactions. `verificar_cliente(customer_id)` was removed from the model's tools so identity cannot be bypassed. Repeat-complainer status and channel come from data and session. New rules: suspected fraud always escalates, deposits cannot be disputed, no duplicate cases.
- **Models:** re-running the v1 classifier showed ML did not beat the baseline (0.745 vs 0.749) and Portuguese was at 0.657. v2 expands the corpus and evaluates on unseen templates.
- **Performance:** data is loaded once instead of per call; each tool went from 3–5 s to ~5 ms.

---

## Team

**DataMastersGT** · Guatemala 🇬🇹

- Marcos Diaz
- Daniel Machic

*Factored AI & Data Hackathon 2026*
