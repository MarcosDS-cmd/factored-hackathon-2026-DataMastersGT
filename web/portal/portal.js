/* LATAM Bank — customer portal (demo). Talks to /api/portal/*; the API key never reaches the browser.
   UI language: Spanish (default) or Portuguese, each with an English subtitle under the text; or plain English. */
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TOKEN_KEY = "dmb-portal-token", LANG_KEY = "dm-lang";
let TOKEN = null, VIEW = null, BUSY = false, LANG = "es";
try { TOKEN = sessionStorage.getItem(TOKEN_KEY); } catch (e) {}
try { const l = localStorage.getItem(LANG_KEY); if (["es", "pt", "en"].includes(l)) LANG = l; } catch (e) {}
const saveToken = (t) => { TOKEN = t; try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch (e) {} };

/* ---------------- i18n: es / pt, each with an English subtitle; "en" = English only ---------------- */
const P = {
  pitch_h: { es: "¿No reconoces un cargo? Resuélvelo en pocos minutos.", pt: "Não reconhece uma cobrança? Resolva em poucos minutos.", en: "Don't recognize a charge? Sort it out in a few minutes." },
  pitch_p: { es: "Elige el cargo y nuestro asistente lo revisa contra tu cuenta. Si está dentro de sus límites, lo resuelve al instante; si no, un especialista lo toma con toda la historia, para que nunca tengas que repetirte.",
    pt: "Escolha a cobrança e nosso assistente a confere com a sua conta. Se estiver dentro dos limites, resolve na hora; se não, um especialista assume com todo o histórico, para você nunca precisar se repetir.",
    en: "Pick the charge and our assistant checks it against your account. If it's within its limits it resolves it on the spot; if not, a specialist takes over with the full story, so you never repeat yourself." },
  demo_note: { es: "Demo del Factored AI & Data Hackathon 2026. Los clientes y las transacciones son datos sintéticos del dataset del reto. Esto no es un banco real.",
    pt: "Demo do Factored AI & Data Hackathon 2026. Os clientes e as transações são dados sintéticos do dataset do desafio. Este não é um banco real.",
    en: "Demo for the Factored AI & Data Hackathon 2026. Customers and transactions are synthetic data from the challenge dataset. This is not a real bank." },
  signin_h: { es: "Inicia sesión en tu banca en línea", pt: "Entre no seu internet banking", en: "Sign in to online banking" },
  signin_p: { es: "Te verificamos con los mismos dos datos que darías en una sucursal.", pt: "Verificamos você com os mesmos dois dados que informaria em uma agência.", en: "We verify you with the same two details you'd give at a branch." },
  f_doc: { es: "Número de documento", pt: "Número do documento", en: "Document number" },
  f_name: { es: "Nombre completo, como aparece en tu documento", pt: "Nome completo, como no seu documento", en: "Full name, as on your ID" },
  ph_doc: { es: "Ej. 8778722", pt: "Ex.: 8778722", en: "e.g. 8778722" },
  ph_name: { es: "Ej. Roberto Gustavo Sánchez Romero", pt: "Ex.: Roberto Gustavo Sánchez Romero", en: "e.g. Roberto Gustavo Sánchez Romero" },
  btn_signin: { es: "Iniciar sesión", pt: "Entrar", en: "Sign in" },
  signing: { es: "Iniciando sesión…", pt: "Entrando…", en: "Signing in…" },
  demo_h: { es: "Cuentas de demostración", pt: "Contas de demonstração", en: "Demo accounts" },
  demo_p: { es: "Haz clic en una para llenar el formulario. Cada una lleva al asistente a un resultado distinto.", pt: "Clique em uma para preencher o formulário. Cada uma leva o assistente a um resultado diferente.", en: "Click one to fill in the form. Each one leads the assistant to a different outcome." },
  st_ok: { es: "Reembolso aprobado", pt: "Reembolso aprovado", en: "Refund approved" },
  st_review: { es: "Revisión estándar", pt: "Análise padrão", en: "Standard review" },
  st_esc_amount: { es: "Especialista · monto", pt: "Especialista · valor", en: "Specialist · amount" },
  st_esc_fraud: { es: "Especialista · fraude", pt: "Especialista · fraude", en: "Specialist · fraud" },
  sc_auto: { es: "Cargo pequeño, sin factores de riesgo", pt: "Cobrança pequena, sem fatores de risco", en: "Small charge, no risk factors" },
  sc_auto_pt: { es: "Cargo pequeño, escribe en portugués", pt: "Cobrança pequena, escreve em português", en: "Small charge, writes in Portuguese" },
  sc_pendiente: { es: "Cargo mediano, riesgo bajo", pt: "Cobrança média, risco baixo", en: "Mid-size charge, low risk" },
  sc_escala_monto: { es: "Cargo superior a US$1,500", pt: "Cobrança acima de US$1,500", en: "Charge above US$1,500" },
  sc_escala_fraude: { es: "Cargo pequeño marcado por fraude", pt: "Cobrança pequena sinalizada como fraude", en: "Small charge flagged for fraud" },
  err_empty: { es: "Ingresa tu número de documento y tu nombre completo.", pt: "Informe o número do documento e o nome completo.", en: "Enter your document number and your full name." },
  err_net: { es: "No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.", pt: "Não conseguimos conectar ao servidor. Verifique sua conexão e tente novamente.", en: "We couldn't reach the server. Check your connection and try again." },
  err_relogin: { es: "Inicia sesión de nuevo.", pt: "Entre novamente.", en: "Please sign in again." },
  err_nf: { es: "No encontramos una cuenta con ese número de documento.", pt: "Não encontramos uma conta com esse número de documento.", en: "We couldn't find an account with that document number." },
  err_name: { es: "El nombre no coincide con el documento registrado.", pt: "O nome não confere com o documento cadastrado.", en: "The name doesn't match the document on file." },
  err_inactive: { es: "Esta cuenta no está activa. Comunícate con una sucursal o llámanos.", pt: "Esta conta não está ativa. Fale com uma agência ou ligue para nós.", en: "This account isn't active. Please contact a branch or call us." },
  err_locked: { es: "Demasiados intentos fallidos con este documento. Inténtalo en 15 minutos o llámanos.", pt: "Tentativas falhas demais com este documento. Tente de novo em 15 minutos ou ligue para nós.", en: "Too many failed attempts for this document. Try again in 15 minutes or call us." },
  err_ended: { es: "Tu sesión terminó. Inicia sesión de nuevo.", pt: "Sua sessão terminou. Entre novamente.", en: "Your session has ended. Please sign in again." },
  err_expired: { es: "Tu sesión expiró tras 15 minutos de inactividad. Inicia sesión de nuevo.", pt: "Sua sessão expirou após 15 minutos de inatividade. Entre novamente.", en: "Your session expired after 15 minutes of inactivity. Please sign in again." },
  btn_assistant: { es: "Asistente", pt: "Assistente", en: "Assistant" },
  btn_signout: { es: "Cerrar sesión", pt: "Sair", en: "Sign out" },
  hello: { es: "Hola, {0}", pt: "Olá, {0}", en: "Hi, {0}" },
  hello_sub: { es: "{0} · cliente {1} · {2}", pt: "{0} · cliente {1} · {2}", en: "{0} · {1} customer · {2}" },
  act_h: { es: "Actividad reciente", pt: "Atividade recente", en: "Recent activity" },
  act_range: { es: "Últimos 90 días · hasta {0}", pt: "Últimos 90 dias · até {0}", en: "Last 90 days · up to {0}" },
  foot_q: { es: "¿Falta algo o no ves un cargo aquí?", pt: "Falta algo ou não vê uma cobrança aqui?", en: "Something missing or a charge you don't see here?" },
  foot_btn: { es: "Pregunta al asistente", pt: "Pergunte ao assistente", en: "Ask the assistant" },
  foot_sub: { es: "", pt: "", en: "Something missing or a charge you don't see here? Ask the assistant" },
  cases_h: { es: "Tus disputas", pt: "Suas contestações", en: "Your disputes" },
  as_title: { es: "Asistente de disputas", pt: "Assistente de contestações", en: "Dispute assistant" },
  as_sub: { es: "Resuelve lo que puede, escala lo que no", pt: "Resolve o que pode, escala o que não pode", en: "Resolves what it can, escalates what it can't" },
  as_close: { es: "Cerrar asistente", pt: "Fechar assistente", en: "Close assistant" },
  as_ph: { es: "Escribe un mensaje…", pt: "Escreva uma mensagem…", en: "Write a message…" },
  lbl_msg: { es: "Mensaje", pt: "Mensagem", en: "Message" },
  btn_send: { es: "Enviar", pt: "Enviar", en: "Send" },
  eng_llm: { es: "Asistente: modelo de IA", pt: "Assistente: modelo de IA", en: "Assistant: AI model" },
  eng_rules: { es: "Asistente: motor de reglas", pt: "Assistente: motor de regras", en: "Assistant: rules engine" },
  d_ok_state: { es: "Reembolso aprobado", pt: "Reembolso aprovado", en: "Refund approved" },
  d_ok_note: { es: "Se acredita en 24–48 horas", pt: "Creditado em 24–48 horas", en: "Credited within 24–48 hours" },
  d_rev_state: { es: "En revisión", pt: "Em análise", en: "Under review" },
  d_rev_step: { es: "Revisión estándar", pt: "Análise padrão", en: "Standard review" },
  d_rev_note: { es: "Respuesta en 5 días hábiles", pt: "Resposta em 5 dias úteis", en: "Answer within 5 business days" },
  d_esc_state: { es: "Con un especialista", pt: "Com um especialista", en: "With a specialist" },
  d_esc_step: { es: "Especialista asignado", pt: "Especialista designado", en: "Specialist assigned" },
  d_esc_note: { es: "Un especialista tiene todo el contexto", pt: "Um especialista tem todo o contexto", en: "A specialist has the full context" },
  r_amount: { es: "El monto {0} supera lo que se puede resolver automáticamente", pt: "O valor {0} está acima do que pode ser resolvido automaticamente", en: "Amount {0} is above what can be resolved automatically" },
  r_fraud: { es: "La transacción fue marcada por el monitoreo de fraude", pt: "A transação foi sinalizada pelo monitoramento de fraude", en: "The transaction was flagged by fraud monitoring" },
  r_reg: { es: "Los casos del regulador siempre pasan a un especialista", pt: "Casos do regulador sempre vão para um especialista", en: "Cases from the regulator always go to a specialist" },
  r_risk: { es: "El perfil de riesgo requiere que lo revise una persona", pt: "O perfil de risco exige que uma pessoa o revise", en: "Risk profile requires a person to review it" },
  no_tx: { es: "No hay transacciones en los últimos 90 días.", pt: "Não há transações nos últimos 90 dias.", en: "No transactions in the last 90 days." },
  btn_dispute: { es: "Disputar", pt: "Contestar", en: "Dispute" },
  aria_dispute: { es: "Disputar {0}, US${1}", pt: "Contestar {0}, US${1}", en: "Dispute {0}, US${1}" },
  charge: { es: "Cargo", pt: "Cobrança", en: "Charge" },
  case_meta: { es: "Caso {0} · cargo del {1}", pt: "Caso {0} · cobrança de {1}", en: "Case {0} · charge from {1}" },
  s1: { es: "Reportado", pt: "Reportado", en: "Reported" },
  s1d: { es: "Marcaste el cargo", pt: "Você sinalizou a cobrança", en: "You flagged the charge" },
  s2: { es: "Verificado", pt: "Verificado", en: "Checked" },
  s2d: { es: "Cotejado con tu cuenta y riesgo evaluado", pt: "Cruzado com a sua conta e risco avaliado", en: "Matched to your account and risk assessed" },
  why: { es: "Motivo: {0}.", pt: "Motivo: {0}.", en: "Why: {0}." },
  empty_cases: { es: "Aún no hay disputas. Si ves un cargo que no reconoces, presiona Disputar junto a él.", pt: "Ainda não há contestações. Se vir uma cobrança que não reconhece, clique em Contestar ao lado dela.", en: "No disputes yet. If you see a charge you don't recognize, press Dispute next to it." },
  b_ok: { es: "Tu reembolso de US${0} fue aprobado. Lo verás en tu cuenta en 24–48 horas.", pt: "Seu reembolso de US${0} foi aprovado. Você o verá na sua conta em 24–48 horas.", en: "Your refund of US${0} was approved. You'll see it in your account within 24–48 hours." },
  b_review: { es: "Tu disputa por US${0} está en revisión estándar. Te responderemos en 5 días hábiles.", pt: "Sua contestação de US${0} está em análise padrão. Responderemos em 5 dias úteis.", en: "Your dispute for US${0} is under standard review. We'll answer within 5 business days." },
  b_esc: { es: "Un especialista ya tiene el caso {0} con todo lo que le dijiste al asistente. Te contactará; no tendrás que repetir nada.", pt: "Um especialista já tem o caso {0} com tudo o que você disse ao assistente. Ele entrará em contato; você não precisará repetir nada.", en: "A specialist now has case {0} with everything you told the assistant. They'll contact you; you won't need to repeat anything." },
  b_hand_h: { es: "Un especialista te contactará", pt: "Um especialista entrará em contato", en: "A specialist will contact you" },
  b_hand_p: { es: "Referencia {0}. Puede ver tu conversación con el asistente.", pt: "Referência {0}. Ele pode ver sua conversa com o assistente.", en: "Reference {0}. They can see your conversation with the assistant." },
  greet: { es: "Hola {0}, ya iniciaste sesión, así que no necesito pedirte tu documento otra vez. Presiona «Disputar» junto a cualquier cargo que no reconozcas, o cuéntame qué pasó.",
    pt: "Olá {0}, você já entrou, então não preciso pedir seu documento de novo. Clique em «Contestar» ao lado de qualquer cobrança que não reconheça, ou me conte o que aconteceu.",
    en: "Hi {0}, you're signed in, so I don't need to ask for your ID again. Press \"Dispute\" next to any charge you don't recognize, or tell me what happened." },
  c_human: { es: "Quiero hablar con una persona", pt: "Quero falar com uma pessoa", en: "I want to talk to a person" },
  c_big: { es: "Hay un cargo de $99,999 que yo no hice", pt: "Há uma cobrança de $99,999 que eu não fiz", en: "There's a charge of $99,999 I didn't make" },
  c_why: { es: "¿Por qué escalaron mi caso?", pt: "Por que escalaram meu caso?", en: "Why was my case escalated?" },
  c_fast: { es: "¿Pueden aprobarlo más rápido?", pt: "Podem aprovar mais rápido?", en: "Can you approve it faster?" },
  w1: { es: "Cotejándolo con tu cuenta…", pt: "Conferindo com a sua conta…", en: "Matching it to your account…" },
  w2: { es: "Evaluando el riesgo…", pt: "Avaliando o risco…", en: "Checking the risk…" },
  w3: { es: "Aplicando los límites del banco…", pt: "Aplicando os limites do banco…", en: "Applying the bank's limits…" },
  m_rules: { es: "motor de reglas", pt: "motor de regras", en: "rules engine" },
  m_ai: { es: "modelo de IA", pt: "modelo de IA", en: "AI model" },
  err_assist: { es: "El asistente no respondió. Revisa tu conexión e inténtalo de nuevo.", pt: "O assistente não respondeu. Verifique sua conexão e tente novamente.", en: "The assistant didn't answer. Check your connection and try again." },
  dispute_msg: { es: "No reconozco este cargo: US${0} en {1} el {2} ({3})", pt: "Não reconheço esta cobrança: US${0} em {1} em {2} ({3})", en: "I don't recognize this charge: US${0} at {1} on {2} ({3})" },
  title_login: { es: "LATAM Bank · Banca en línea (demo)", pt: "LATAM Bank · Internet banking (demo)", en: "LATAM Bank · Online banking (demo)" },
  title_app: { es: "Tu cuenta · LATAM Bank (demo)", pt: "Sua conta · LATAM Bank (demo)", en: "Your account · LATAM Bank (demo)" },
  t_Withdrawal: { es: "Retiro", pt: "Saque", en: "Withdrawal" }, t_Transfer: { es: "Transferencia", pt: "Transferência", en: "Transfer" },
  t_Purchase: { es: "Compra", pt: "Compra", en: "Purchase" }, t_Payment: { es: "Pago", pt: "Pagamento", en: "Payment" }, t_Deposit: { es: "Depósito", pt: "Depósito", en: "Deposit" },
};
const ERR = {};   /* English server message -> key */
[["err_nf"], ["err_name"], ["err_inactive"], ["err_locked"], ["err_ended"], ["err_expired"], ["err_relogin"]].forEach(([k]) => (ERR[P[k].en] = k));
const fill = (s, a) => String(s).replace(/\{(\d+)\}/g, (_, i) => a[+i] ?? "");
const tr = (k, ...a) => fill((P[k] || {})[LANG] ?? (P[k] || {}).en ?? k, a);      /* text in the current language */
const en = (k, ...a) => fill((P[k] || {}).en ?? k, a);                              /* English text */
const subHTML = (txt) => (LANG === "en" || !txt ? "" : `<small class="sub-en" lang="en">${esc(txt)}</small>`);
const both = (k, ...a) => esc(tr(k, ...a)) + subHTML(en(k, ...a));                  /* primary + English subtitle */
const LOCALE = () => ({ es: "es", pt: "pt-BR", en: "en-US" }[LANG]);

function applyStatic() {
  document.documentElement.lang = LANG;
  $$("[data-t]").forEach((el) => { const k = el.dataset.t; el.innerHTML = el.hasAttribute("data-nosub") ? esc(tr(k)) : both(k); });
  $$("[data-tsub]").forEach((el) => { el.textContent = LANG === "en" ? "" : en(el.dataset.tsub); el.hidden = LANG === "en"; });
  $$("[data-tp]").forEach((el) => { const [a, k] = el.dataset.tp.split(":"); el.setAttribute(a, tr(k)); });
  $$("[data-ta]").forEach((el) => { const [a, k] = el.dataset.ta.split(":"); el.setAttribute(a, tr(k)); });
  $$(".lang-sw button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  document.title = tr(VIEW ? "title_app" : "title_login");
}
function setLang(l) {
  if (!["es", "pt", "en"].includes(l) || l === LANG) return;
  LANG = l; try { localStorage.setItem(LANG_KEY, l); } catch (e) {}
  applyStatic(); loadDemo();
  if (VIEW) { showApp(false); chips(); }
  if ($("#loginError").dataset.k) showError($("#loginError").dataset.k);
}
document.addEventListener("click", (e) => { const b = e.target.closest(".lang-sw button"); if (b) setLang(b.dataset.lang); });

/* a server/client message shown in the current language (+ English subtitle) */
function showError(key, raw) {
  const err = $("#loginError");
  if (key) { err.dataset.k = key; err.innerHTML = both(key); }
  else { delete err.dataset.k; err.textContent = raw || ""; }
  err.hidden = false;
}

/* guilloché on the sign-in panel (same security-paper motif as the project site) */
(function guil(svg) {
  const w = 700, h = 900, cx = 520, cy = 640; svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
  const gcd = (a, b) => { a = Math.round(a); b = Math.round(b); while (b) [a, b] = [b, a % b]; return a || 1; };
  let out = "";
  for (let k = 0; k < 6; k++) {
    const R = 260 - k * 18, r = 23 + k * 6, d = 44 + k * 10; let p = "";
    for (let i = 0; i <= 2600; i++) {
      const t = (i / 2600) * Math.PI * 2 * r / gcd(R, r);
      p += (i ? "L" : "M") + (cx + (R - r) * Math.cos(t) + d * Math.cos(((R - r) / r) * t)).toFixed(1) + " " + (cy + (R - r) * Math.sin(t) - d * Math.sin(((R - r) / r) * t)).toFixed(1);
    }
    out += `<path d="${p}" fill="none" stroke="#2f6f66" stroke-width="${k % 2 ? .5 : .8}" opacity="${.9 - k * .1}"/>`;
  }
  svg.innerHTML = out;
})($("#guilLogin"));

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opts.headers || {}) } });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "/api/portal/login") { saveToken(null); showLogin(ERR[body.detail] || "err_relogin"); throw new Error("401"); }
  if (!r.ok) { const e = new Error(body.detail || `Error ${r.status}`); e.detail = body.detail; throw e; }
  return body;
}

/* ---------------- sign in ---------------- */
const SCEN = { auto: ["ok", "st_ok"], auto_pt: ["ok", "st_ok"], pendiente: ["review", "st_review"],
  escala_monto: ["esc", "st_esc_amount"], escala_fraude: ["esc", "st_esc_fraud"] };
async function loadDemo() {
  try {
    const ps = await fetch("/data/demo_customers.json").then((r) => r.json());
    $("#demoList").innerHTML = "";
    ps.forEach((p) => {
      const [c, t] = SCEN[p.id] || ["", "st_ok"];
      const b = document.createElement("button");
      b.type = "button"; b.className = "demo-acc";
      b.innerHTML = `<b>${esc(p.nombre)}</b><span>${esc(p.tipo_documento)} ${esc(p.documento)} · ${P["sc_" + p.id] ? both("sc_" + p.id) : ""}</span><em class="tag state ${c}">${esc(tr(t))}</em>`;
      b.addEventListener("click", () => { $("#fDoc").value = p.documento; $("#fName").value = p.nombre; $("#loginBtn").focus(); });
      $("#demoList").append(b);
    });
  } catch (e) { $(".demo-accounts").hidden = true; }
}
$("#loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const doc = $("#fDoc").value.trim(), name = $("#fName").value.trim(), err = $("#loginError");
  err.hidden = true; delete err.dataset.k;
  if (!doc || !name) { showError("err_empty"); return; }
  $("#loginBtn").disabled = true; $("#loginBtn").innerHTML = both("signing");
  try {
    const d = await api("/api/portal/login", { method: "POST", body: JSON.stringify({ document: doc, full_name: name, lang: LANG }) });
    saveToken(d.token); VIEW = d; showApp(true);
  } catch (e) {
    if (e.message === "Failed to fetch") showError("err_net");
    else if (ERR[e.detail]) showError(ERR[e.detail]);
    else showError(null, e.message);
  }
  finally { $("#loginBtn").disabled = false; $("#loginBtn").innerHTML = both("btn_signin"); }
});
function showLogin(msgKey) {
  $("#viewApp").hidden = true; $("#viewLogin").hidden = false; VIEW = null;
  if (msgKey) showError(msgKey);
  document.title = tr("title_login");
}
$("#logoutBtn").addEventListener("click", async () => { try { await api("/api/portal/logout", { method: "POST" }); } catch (e) {} saveToken(null); VIEW = null; $("#asMsgs").innerHTML = ""; showLogin(); });

/* ---------------- account ---------------- */
const DEC = {
  AUTO_APROBADO: { cls: "ok", state: "d_ok_state", step: "d_ok_state", note: "d_ok_note" },
  PENDIENTE_REVISION: { cls: "review", state: "d_rev_state", step: "d_rev_step", note: "d_rev_note" },
  ESCALADO_A_HUMANO: { cls: "esc", state: "d_esc_state", step: "d_esc_step", note: "d_esc_note" },
};
const typeName = (x, lang = LANG) => { const k = "t_" + x; return P[k] ? P[k][lang] : x; };
/* backend gives risk factors / escalation reasons in English; map them to a message key */
function reasonKey(r) {
  r = String(r); let m;
  if ((m = r.match(/^Amount \((.+?)\) exceeds the maximum/))) return ["r_amount", m[1]];
  if (/^Suspected fraud/.test(r)) return ["r_fraud"];
  if (/^Reception channel/.test(r)) return ["r_reg"];
  if (/^High risk \+ amount/.test(r)) return ["r_risk"];
  return null;
}
const fmtDate = (s) => new Date(s.replace(" ", "T")).toLocaleDateString(LOCALE(), { month: "short", day: "numeric" });
const desc = (t) => t.merchant_name || `${typeName(t.transaction_type)} · ${t.channel}`;
const descEn = (t) => t.merchant_name || `${typeName(t.transaction_type, "en")} · ${t.channel}`;

function showApp(first) {
  $("#viewLogin").hidden = true; $("#viewApp").hidden = false;
  const c = VIEW.customer;
  document.title = tr("title_app");
  $("#hello").innerHTML = both("hello", (c.first_name || "").split(" ")[0]);
  $("#helloSub").textContent = tr("hello_sub", c.first_name, c.segment, c.country) + "";
  const llm = VIEW.engine && VIEW.engine !== "reglas";
  $("#engineBadge").textContent = tr(llm ? "eng_llm" : "eng_rules");
  $("#engineBadge").className = "engine" + (llm ? " llm" : "");
  render();
  if (first || !$("#asMsgs").children.length) restoreChat();
}
function caseFor(txId) { return (VIEW.cases || []).find((c) => c.transaction_id === txId); }
function render() {
  const txs = VIEW.transactions || [];
  $("#actRange").textContent = txs.length ? tr("act_range", fmtDate(VIEW.today + " 00:00:00")) : "";
  $("#txList").innerHTML = txs.length ? "" : `<li class="tx"><span class="m"><b>${both("no_tx")}</b></span></li>`;
  txs.forEach((t) => {
    const inbound = t.transaction_type === "Deposit";
    const k = caseFor(t.transaction_id);
    const li = document.createElement("li");
    li.className = "tx" + (inbound ? " in" : "");
    li.innerHTML = `<span class="d">${fmtDate(t.transaction_date)}</span>
      <span class="m"><b>${esc(desc(t))}</b><span>${esc(typeName(t.transaction_type))} · ${esc(t.channel)} · ${esc(t.transaction_status)}</span></span>
      <span class="a">${inbound ? "+" : "−"}US$${fmt(t.amount_usd)}${t.currency !== "USD" ? `<span>${fmt(t.amount)} ${esc(t.currency)}</span>` : ""}</span>
      <span class="act"></span>`;
    const act = $(".act", li);
    if (k) act.innerHTML = `<span class="state ${DEC[k.decision].cls}">${esc(tr(DEC[k.decision].state))}${subHTML(en(DEC[k.decision].state))}</span>`;
    else if (!inbound) {
      const b = document.createElement("button");
      b.className = "btn-dispute"; b.type = "button"; b.innerHTML = both("btn_dispute");
      b.setAttribute("aria-label", tr("aria_dispute", desc(t), fmt(t.amount_usd)));
      b.addEventListener("click", () => dispute(t, b));
      act.append(b);
    }
    $("#txList").append(li);
  });
  // cases
  const cs = VIEW.cases || [];
  $("#caseList").innerHTML = cs.length ? cs.slice().reverse().map((c) => {
    const D = DEC[c.decision];
    const reasons = (c.motivos_escalacion || []).map(reasonKey).filter(Boolean);
    const rTxt = reasons.map(([k, ...a]) => tr(k, ...a)).join(". "), rEn = reasons.map(([k, ...a]) => en(k, ...a)).join(". ");
    return `<article class="case">
      <div class="case-top"><div><b>${esc(c.descripcion || tr("charge"))} · US$${fmt(c.monto_usd)}</b><span class="small">${esc(tr("case_meta", c.caso_id, c.fecha || ""))}${subHTML(en("case_meta", c.caso_id, c.fecha || ""))}</span></div>
      <span class="state ${D.cls}">${esc(tr(D.state))}${subHTML(en(D.state))}</span></div>
      <ol class="steps">
        <li class="done"><b>${both("s1")}</b>${both("s1d")}</li>
        <li class="done"><b>${both("s2")}</b>${both("s2d")}</li>
        <li class="done final ${D.cls}"><b>${both(D.step)}</b>${both(D.note)}</li>
      </ol>
      ${reasons.length ? `<p class="small">${esc(tr("why", rTxt))}${subHTML(en("why", rEn))}</p>` : ""}
    </article>`;
  }).join("") : `<p class="empty-cases">${both("empty_cases")}</p>`;
  // banner for the latest outcome
  const last = cs[cs.length - 1], hd = VIEW.handoff, bn = $("#banner");
  const icon = { ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M5 12l5 5 9-11"/></svg>',
    review: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    esc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/></svg>' };
  if (last) {
    const D = DEC[last.decision];
    const key = { ok: "b_ok", review: "b_review", esc: "b_esc" }[D.cls], arg = D.cls === "esc" ? last.caso_id : fmt(last.monto_usd);
    bn.className = "banner " + D.cls; bn.innerHTML = `${icon[D.cls]}<b>${both(D.state)}</b><p>${both(key, arg)}</p>`; bn.hidden = false;
  } else if (hd) {
    bn.className = "banner esc"; bn.innerHTML = `${icon.esc}<b>${both("b_hand_h")}</b><p>${both("b_hand_p", esc(hd.handoff_id))}</p>`; bn.hidden = false;
  } else bn.hidden = true;
}

/* ---------------- assistant ---------------- */
const SUBS = {};   /* English subtitle by exact message text we generate on the client (chips, dispute button, greeting) */
function addMsg(cls, text, meta, sub) {
  const m = document.createElement("div");
  m.className = "msg " + cls;
  m.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  setSub(m, sub, text);
  if (meta) { const s = document.createElement("span"); s.className = "meta"; s.textContent = meta; m.append(s); }
  $("#asMsgs").append(m); $("#asMsgs").scrollTop = $("#asMsgs").scrollHeight; return m;
}
function setSub(m, sub, orig) {
  m.querySelector(".sub-en")?.remove();
  if (!sub || sub.trim() === (orig || "").trim()) return;
  const el = document.createElement("small"); el.className = "sub-en"; el.lang = "en"; el.title = "English subtitle";
  el.innerHTML = esc(sub).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const meta = m.querySelector(".meta"); meta ? m.insertBefore(el, meta) : m.append(el);
}
function restoreChat() {
  $("#asMsgs").innerHTML = "";
  const first = (VIEW.customer.first_name || "").split(" ")[0];
  addMsg("a", tr("greet", first), null, en("greet", first));
  (VIEW.messages || []).forEach((m) => addMsg(m.rol === "cliente" ? "c" : "a", m.texto, null, m.sub || SUBS[m.texto]));
  chips();
}
function chips() {
  const el = $("#asChips"); el.innerHTML = "";
  const escalado = (VIEW.cases || []).some((c) => c.decision === "ESCALADO_A_HUMANO");
  const decided = (VIEW.cases || []).length > 0;
  const list = ["c_human", "c_big"];
  if (decided) list.splice(1, 0, escalado ? "c_why" : "c_fast");
  list.forEach((k) => {
    const t = tr(k); SUBS[t] = en(k);
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.title = en(k);
    b.innerHTML = esc(t) + subHTML(en(k));
    b.addEventListener("click", () => send(t)); el.append(b);
  });
}
function working() {
  const w = document.createElement("div"); w.className = "working";
  w.innerHTML = ["w1", "w2", "w3"].map((k) => `<span>${both(k)}</span>`).join("");
  $("#asMsgs").append(w); $("#asMsgs").scrollTop = $("#asMsgs").scrollHeight;
  const spans = $$("span", w); let i = 0;
  spans[0].classList.add("on");
  const iv = setInterval(() => { i = Math.min(i + 1, spans.length - 1); spans[i].classList.add("on"); }, reduced ? 10 : 650);
  return () => { clearInterval(iv); w.remove(); };
}
async function send(text, opts = {}) {
  text = (text || "").trim(); if (!text || BUSY) return;
  BUSY = true; $("#asSend").disabled = true; $("#asInp").value = "";
  openAssistant();
  const mc = addMsg("c", text, null, SUBS[text]);
  const stop = working();
  try {
    const d = await api("/api/portal/chat", { method: "POST", body: JSON.stringify({ mensaje: text, lang: LANG }) });
    stop();
    const { subtitulo_agente, subtitulo_cliente, ...rest } = d;
    VIEW = { ...VIEW, ...rest };
    if (subtitulo_cliente && !mc.querySelector(".sub-en")) setSub(mc, subtitulo_cliente, text);
    addMsg("a", d.reply, tr(d.engine === "reglas" ? "m_rules" : "m_ai"), subtitulo_agente);
    render(); chips();
  } catch (e) {
    stop();
    if (e.message !== "401") addMsg("sys", tr("err_assist"), null, en("err_assist"));
  } finally { BUSY = false; $("#asSend").disabled = false; if (opts.btn) opts.btn.disabled = false; }
}
function dispute(t, btn) {
  btn.disabled = true;
  const day = t.transaction_date.slice(0, 10);
  const text = tr("dispute_msg", fmt(t.amount_usd), desc(t), day, t.transaction_id);
  SUBS[text] = en("dispute_msg", fmt(t.amount_usd), descEn(t), day, t.transaction_id);
  send(text, { btn });
}
$("#asForm").addEventListener("submit", (e) => { e.preventDefault(); send($("#asInp").value); });
$("#asInp").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("#asInp").value); } });
$("#askBtn").addEventListener("click", () => { openAssistant(); $("#asInp").focus(); });

/* mobile: assistant as a bottom sheet */
const mq = matchMedia("(max-width: 1020px)");
let backdrop = null;
function openAssistant() {
  if (!mq.matches) return;
  $("#assistant").classList.add("open"); $("#helpBtn").setAttribute("aria-expanded", "true");
  if (!backdrop) { backdrop = document.createElement("div"); backdrop.className = "backdrop"; backdrop.addEventListener("click", closeAssistant); document.body.append(backdrop); }
}
function closeAssistant() {
  $("#assistant").classList.remove("open"); $("#helpBtn").setAttribute("aria-expanded", "false");
  backdrop?.remove(); backdrop = null;
}
$("#helpBtn").addEventListener("click", () => ($("#assistant").classList.contains("open") ? closeAssistant() : openAssistant()));
$("#closeAs").addEventListener("click", closeAssistant);
addEventListener("keydown", (e) => { if (e.key === "Escape") closeAssistant(); });

/* ---------------- boot ---------------- */
(async () => {
  applyStatic();
  loadDemo();
  if (TOKEN) {
    try { VIEW = await api("/api/portal/me"); applyStatic(); showApp(true); return; } catch (e) { saveToken(null); }
  }
  showLogin();
})();
})();
