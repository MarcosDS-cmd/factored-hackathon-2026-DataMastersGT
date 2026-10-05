/* LATAM Bank — customer portal (demo). Talks to /api/portal/*; the API key never reaches the browser. */
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TOKEN_KEY = "dmb-portal-token";
let TOKEN = null, VIEW = null, BUSY = false;
try { TOKEN = sessionStorage.getItem(TOKEN_KEY); } catch (e) {}
const saveToken = (t) => { TOKEN = t; try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch (e) {} };

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
  if (r.status === 401 && path !== "/api/portal/login") { saveToken(null); showLogin(body.detail || "Please sign in again."); throw new Error("401"); }
  if (!r.ok) throw new Error(body.detail || `Error ${r.status}`);
  return body;
}

/* ---------------- sign in ---------------- */
const SCEN = { auto: ["ok", "Refund approved"], auto_pt: ["ok", "Refund approved"], pendiente: ["review", "Standard review"],
  escala_monto: ["esc", "Specialist · amount"], escala_fraude: ["esc", "Specialist · fraud"] };
const SCEN_TXT = { auto: "Small charge, no risk factors", auto_pt: "Small charge, writes in Portuguese", pendiente: "Mid-size charge, low risk",
  escala_monto: "Charge above US$1,500", escala_fraude: "Small charge flagged for fraud" };
async function loadDemo() {
  try {
    const ps = await fetch("/data/demo_customers.json").then((r) => r.json());
    $("#demoList").innerHTML = "";
    ps.forEach((p) => {
      const [c, t] = SCEN[p.id] || ["", ""];
      const b = document.createElement("button");
      b.type = "button"; b.className = "demo-acc";
      b.innerHTML = `<b>${esc(p.nombre)}</b><span>${esc(p.tipo_documento)} ${esc(p.documento)} · ${esc(SCEN_TXT[p.id] || "")}</span><em class="tag state ${c}">${t}</em>`;
      b.addEventListener("click", () => { $("#fDoc").value = p.documento; $("#fName").value = p.nombre; $("#loginBtn").focus(); });
      $("#demoList").append(b);
    });
  } catch (e) { $(".demo-accounts").hidden = true; }
}
$("#loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const doc = $("#fDoc").value.trim(), name = $("#fName").value.trim(), err = $("#loginError");
  err.hidden = true;
  if (!doc || !name) { err.textContent = "Enter your document number and your full name."; err.hidden = false; return; }
  $("#loginBtn").disabled = true; $("#loginBtn").textContent = "Signing in…";
  try {
    const d = await api("/api/portal/login", { method: "POST", body: JSON.stringify({ document: doc, full_name: name }) });
    saveToken(d.token); VIEW = d; showApp(true);
  } catch (e) { err.textContent = e.message === "Failed to fetch" ? "We couldn't reach the server. Check your connection and try again." : e.message; err.hidden = false; }
  finally { $("#loginBtn").disabled = false; $("#loginBtn").textContent = "Sign in"; }
});
function showLogin(msg) {
  $("#viewApp").hidden = true; $("#viewLogin").hidden = false;
  if (msg) { $("#loginError").textContent = msg; $("#loginError").hidden = false; }
  document.title = "LATAM Bank · Online banking (demo)";
}
$("#logoutBtn").addEventListener("click", async () => { try { await api("/api/portal/logout", { method: "POST" }); } catch (e) {} saveToken(null); VIEW = null; $("#asMsgs").innerHTML = ""; showLogin(); });

/* ---------------- account ---------------- */
const DEC = {
  AUTO_APROBADO: { cls: "ok", state: "Refund approved", step: "Refund approved", note: "Credited within 24–48 hours" },
  PENDIENTE_REVISION: { cls: "review", state: "Under review", step: "Standard review", note: "Answer within 5 business days" },
  ESCALADO_A_HUMANO: { cls: "esc", state: "With a specialist", step: "Specialist assigned", note: "A specialist has the full context" },
};
const TYPE = { Withdrawal: "Withdrawal", Transfer: "Transfer", Purchase: "Purchase", Payment: "Payment", Deposit: "Deposit" };
const REASON = (r) => String(r)
  .replace(/^Amount \((.+?)\) exceeds the maximum.*$/, "Amount $1 is above what can be resolved automatically")
  .replace(/^Suspected fraud.*$/, "The transaction was flagged by fraud monitoring")
  .replace(/^Reception channel.*$/, "Cases from the regulator always go to a specialist")
  .replace(/^High risk \+ amount.*$/, "Risk profile requires a person to review it");
const fmtDate = (s) => new Date(s.replace(" ", "T")).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const desc = (t) => t.merchant_name || `${TYPE[t.transaction_type] || t.transaction_type} · ${t.channel}`;

function showApp(first) {
  $("#viewLogin").hidden = true; $("#viewApp").hidden = false;
  const c = VIEW.customer;
  document.title = "Your account · LATAM Bank (demo)";
  $("#hello").textContent = `Hi, ${(c.first_name || "").split(" ")[0]}`;
  $("#helloSub").textContent = `${c.first_name} ${c.last_name || ""} · ${c.segment} customer · ${c.country}`;
  const llm = VIEW.engine && VIEW.engine !== "reglas";
  $("#engineBadge").textContent = llm ? "Assistant: AI model" : "Assistant: rules engine";
  $("#engineBadge").className = "engine" + (llm ? " llm" : "");
  render();
  if (first || !$("#asMsgs").children.length) restoreChat();
}
function caseFor(txId) { return (VIEW.cases || []).find((c) => c.transaction_id === txId); }
function render() {
  const txs = VIEW.transactions || [];
  $("#actRange").textContent = txs.length ? `Last 90 days · up to ${fmtDate(VIEW.today + " 00:00:00")}` : "";
  $("#txList").innerHTML = txs.length ? "" : `<li class="tx"><span class="m"><b>No transactions in the last 90 days.</b></span></li>`;
  txs.forEach((t) => {
    const inbound = t.transaction_type === "Deposit";
    const k = caseFor(t.transaction_id);
    const li = document.createElement("li");
    li.className = "tx" + (inbound ? " in" : "");
    li.innerHTML = `<span class="d">${fmtDate(t.transaction_date)}</span>
      <span class="m"><b>${esc(desc(t))}</b><span>${esc(TYPE[t.transaction_type] || t.transaction_type)} · ${esc(t.channel)} · ${esc(t.transaction_status)}</span></span>
      <span class="a">${inbound ? "+" : "−"}US$${fmt(t.amount_usd)}${t.currency !== "USD" ? `<span>${fmt(t.amount)} ${esc(t.currency)}</span>` : ""}</span>
      <span class="act"></span>`;
    const act = $(".act", li);
    if (k) act.innerHTML = `<span class="state ${DEC[k.decision].cls}">${DEC[k.decision].state}</span>`;
    else if (!inbound) {
      const b = document.createElement("button");
      b.className = "btn-dispute"; b.type = "button"; b.textContent = "Dispute";
      b.setAttribute("aria-label", `Dispute ${desc(t)}, US$${fmt(t.amount_usd)}`);
      b.addEventListener("click", () => dispute(t, b));
      act.append(b);
    }
    $("#txList").append(li);
  });
  // cases
  const cs = VIEW.cases || [];
  $("#caseList").innerHTML = cs.length ? cs.slice().reverse().map((c) => {
    const D = DEC[c.decision];
    const reasons = (c.motivos_escalacion || []).map(REASON);
    return `<article class="case">
      <div class="case-top"><div><b>${esc(c.descripcion || "Charge")} · US$${fmt(c.monto_usd)}</b><span class="small">Case ${esc(c.caso_id)} · charge from ${esc(c.fecha || "")}</span></div>
      <span class="state ${D.cls}">${D.state}</span></div>
      <ol class="steps">
        <li class="done"><b>Reported</b>You flagged the charge</li>
        <li class="done"><b>Checked</b>Matched to your account and risk assessed</li>
        <li class="done final ${D.cls}"><b>${D.step}</b>${D.note}</li>
      </ol>
      ${reasons.length ? `<p class="small">Why: ${esc(reasons.join(". "))}.</p>` : ""}
    </article>`;
  }).join("") : `<p class="empty-cases">No disputes yet. If you see a charge you don't recognize, press <b>Dispute</b> next to it.</p>`;
  // banner for the latest outcome
  const last = cs[cs.length - 1], hd = VIEW.handoff, bn = $("#banner");
  const icon = { ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M5 12l5 5 9-11"/></svg>',
    review: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    esc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/></svg>' };
  if (last) {
    const D = DEC[last.decision];
    const text = { ok: `Your refund of US$${fmt(last.monto_usd)} was approved. You'll see it in your account within 24–48 hours.`,
      review: `Your dispute for US$${fmt(last.monto_usd)} is under standard review. We'll answer within 5 business days.`,
      esc: `A specialist now has case ${last.caso_id} with everything you told the assistant. They'll contact you; you won't need to repeat anything.` }[D.cls];
    bn.className = "banner " + D.cls; bn.innerHTML = `${icon[D.cls]}<b>${D.state}</b><p>${esc(text)}</p>`; bn.hidden = false;
  } else if (hd) {
    bn.className = "banner esc"; bn.innerHTML = `${icon.esc}<b>A specialist will contact you</b><p>Reference ${esc(hd.handoff_id)}. They can see your conversation with the assistant.</p>`; bn.hidden = false;
  } else bn.hidden = true;
}

/* ---------------- assistant ---------------- */
function addMsg(cls, text, meta) {
  const m = document.createElement("div");
  m.className = "msg " + cls;
  m.innerHTML = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  if (meta) { const s = document.createElement("span"); s.className = "meta"; s.textContent = meta; m.append(s); }
  $("#asMsgs").append(m); $("#asMsgs").scrollTop = $("#asMsgs").scrollHeight; return m;
}
function restoreChat() {
  $("#asMsgs").innerHTML = "";
  const first = (VIEW.customer.first_name || "").split(" ")[0];
  addMsg("a", `Hi ${first}, you're signed in, so I don't need to ask for your ID again. Press "Dispute" next to any charge you don't recognize, or tell me what happened.`);
  (VIEW.messages || []).forEach((m) => addMsg(m.rol === "cliente" ? "c" : "a", m.texto));
  chips();
}
function chips() {
  const el = $("#asChips"); el.innerHTML = "";
  const escalado = (VIEW.cases || []).some((c) => c.decision === "ESCALADO_A_HUMANO");
  const decided = (VIEW.cases || []).length > 0;
  const list = ["I want to talk to a person", "There's a charge of $99,999 I didn't make"];
  if (decided) list.splice(1, 0, escalado ? "Why was my case escalated?" : "Can you approve it faster?");
  list.forEach((t) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = t; b.title = t;
    b.addEventListener("click", () => send(t)); el.append(b);
  });
}
function working() {
  const w = document.createElement("div"); w.className = "working";
  w.innerHTML = "<span>Matching it to your account…</span><span>Checking the risk…</span><span>Applying the bank's limits…</span>";
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
  addMsg("c", text);
  const stop = working();
  try {
    const d = await api("/api/portal/chat", { method: "POST", body: JSON.stringify({ mensaje: text }) });
    stop();
    VIEW = { ...VIEW, ...d };
    addMsg("a", d.reply, d.engine === "reglas" ? "rules engine" : "AI model");
    render(); chips();
  } catch (e) {
    stop();
    if (e.message !== "401") addMsg("sys", "The assistant didn't answer. Check your connection and try again.");
  } finally { BUSY = false; $("#asSend").disabled = false; if (opts.btn) opts.btn.disabled = false; }
}
function dispute(t, btn) {
  btn.disabled = true;
  send(`I don't recognize this charge: US$${fmt(t.amount_usd)} at ${desc(t)} on ${t.transaction_date.slice(0, 10)} (${t.transaction_id})`, { btn });
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
  loadDemo();
  if (TOKEN) {
    try { VIEW = await api("/api/portal/me"); showApp(true); return; } catch (e) { saveToken(null); }
  }
  showLogin();
})();
})();
