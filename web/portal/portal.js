/* LATAM Bank — customer portal (demo). Talks to /api/portal/*; the API key never reaches the browser. */
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const t = (k, v) => I18N.t(k, v);
const tk = (prefix, k, fallback) => { const s = t(prefix + k); return s === prefix + k ? (fallback ?? k) : s; };
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
  const code = body.detail && typeof body.detail === "object" ? body.detail.code : null;
  const msg = code ? tk("p.err.", code, body.detail.message) : (body.detail || `Error ${r.status}`);
  if (r.status === 401 && path !== "/api/portal/login") { saveToken(null); showLogin(msg); throw new Error("401"); }
  if (!r.ok) throw new Error(msg);
  return body;
}

/* ---------------- sign in ---------------- */
const SCEN = { auto: ["ok", "auto"], auto_pt: ["ok", "auto"], pendiente: ["review", "pendiente"], escala_monto: ["esc", "escala_monto"], escala_fraude: ["esc", "escala_fraude"] };
let DEMO_PS = null;
async function loadDemo() {
  try {
    const ps = DEMO_PS || (DEMO_PS = await fetch("/data/demo_customers.json").then((r) => r.json()));
    $("#demoList").innerHTML = "";
    ps.forEach((p) => {
      const [c, key] = SCEN[p.id] || ["", ""];
      const b = document.createElement("button");
      b.type = "button"; b.className = "demo-acc";
      b.innerHTML = `<b>${esc(p.nombre)}</b><span>${esc(p.tipo_documento)} ${esc(p.documento)} · ${esc(tk("p.scen.d.", p.id, ""))}</span><em class="tag state ${c}">${esc(tk("p.scen.", key, ""))}</em>`;
      b.addEventListener("click", () => { $("#fDoc").value = p.documento; $("#fName").value = p.nombre; $("#loginBtn").focus(); });
      $("#demoList").append(b);
    });
  } catch (e) { $(".demo-accounts").hidden = true; }
}
$("#loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const doc = $("#fDoc").value.trim(), name = $("#fName").value.trim(), err = $("#loginError");
  err.hidden = true;
  if (!doc || !name) { err.textContent = t("p.err.empty"); err.hidden = false; return; }
  $("#loginBtn").disabled = true; $("#loginBtn").textContent = t("p.signingin");
  try {
    const d = await api("/api/portal/login", { method: "POST", body: JSON.stringify({ document: doc, full_name: name, lang: I18N.lang }) });
    saveToken(d.token); VIEW = d; showApp(true);
  } catch (e) { err.textContent = e.message === "Failed to fetch" ? t("p.err.net") : e.message; err.hidden = false; }
  finally { $("#loginBtn").disabled = false; $("#loginBtn").textContent = t("p.signin"); }
});
function showLogin(msg) {
  $("#viewApp").hidden = true; $("#viewLogin").hidden = false;
  if (msg) { $("#loginError").textContent = msg; $("#loginError").hidden = false; }
  document.title = t("p.title.login");
}
$("#logoutBtn").addEventListener("click", async () => { try { await api("/api/portal/logout", { method: "POST" }); } catch (e) {} saveToken(null); VIEW = null; $("#asMsgs").innerHTML = ""; showLogin(); });

/* ---------------- account ---------------- */
const DECC = { AUTO_APROBADO: "ok", PENDIENTE_REVISION: "review", ESCALADO_A_HUMANO: "esc" };
const DEC = new Proxy({}, { get: (_, k) => DECC[k] && {
  cls: DECC[k], state: t(`p.dec.${k}.s`), step: tk(`p.dec.${k}.`, "step", t(`p.dec.${k}.s`)), note: t(`p.dec.${k}.n`) } });
const TYPE = new Proxy({}, { get: (_, k) => tk("p.type.", String(k)) });
const status = (s) => tk("p.status.", s);
const REASON = (r) => {
  r = String(r);
  let m = r.match(/^Amount \((.+?)\) exceeds the maximum/); if (m) return t("p.r.amount", { a: m[1] });
  if (/^Suspected fraud/.test(r)) return t("p.r.fraud");
  if (/^Reception channel/.test(r)) return t("p.r.reg");
  if (/^High risk \+ amount/.test(r)) return t("p.r.risk");
  return r;
};
const fmtDate = (s) => new Date(s.replace(" ", "T")).toLocaleDateString(I18N.locale, { month: "short", day: "numeric" });
const desc = (x) => x.merchant_name || `${TYPE[x.transaction_type] || x.transaction_type} · ${x.channel}`;

function showApp(first) {
  $("#viewLogin").hidden = true; $("#viewApp").hidden = false;
  const c = VIEW.customer;
  document.title = t("p.title.app");
  $("#hello").textContent = t("p.hi", { name: (c.first_name || "").split(" ")[0] });
  $("#helloSub").textContent = t("p.sub", { full: `${c.first_name} ${c.last_name || ""}`.trim(), seg: c.segment, country: c.country });
  const llm = VIEW.engine && VIEW.engine !== "reglas";
  $("#engineBadge").textContent = llm ? t("p.engine.ai") : t("p.engine.rules");
  $("#engineBadge").className = "engine" + (llm ? " llm" : "");
  render();
  if (first || !$("#asMsgs").children.length) restoreChat();
}
function caseFor(txId) { return (VIEW.cases || []).find((c) => c.transaction_id === txId); }
function render() {
  const txs = VIEW.transactions || [];
  $("#actRange").textContent = txs.length ? t("p.range", { d: fmtDate(VIEW.today + " 00:00:00") }) : "";
  $("#txList").innerHTML = txs.length ? "" : `<li class="tx"><span class="m"><b>${t("p.noTx")}</b></span></li>`;
  txs.forEach((tx) => {
    const inbound = tx.transaction_type === "Deposit";
    const k = caseFor(tx.transaction_id);
    const li = document.createElement("li");
    li.className = "tx" + (inbound ? " in" : "");
    li.innerHTML = `<span class="d">${fmtDate(tx.transaction_date)}</span>
      <span class="m"><b>${esc(desc(tx))}</b><span>${esc(TYPE[tx.transaction_type] || tx.transaction_type)} · ${esc(tx.channel)} · ${esc(status(tx.transaction_status))}</span></span>
      <span class="a">${inbound ? "+" : "−"}US$${fmt(tx.amount_usd)}${tx.currency !== "USD" ? `<span>${fmt(tx.amount)} ${esc(tx.currency)}</span>` : ""}</span>
      <span class="act"></span>`;
    const act = $(".act", li);
    if (k) act.innerHTML = `<span class="state ${DEC[k.decision].cls}">${DEC[k.decision].state}</span>`;
    else if (!inbound) {
      const b = document.createElement("button");
      b.className = "btn-dispute"; b.type = "button"; b.textContent = t("p.dispute");
      b.setAttribute("aria-label", t("p.dispute.aria", { d: desc(tx), a: fmt(tx.amount_usd) }));
      b.addEventListener("click", () => dispute(tx, b));
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
      <div class="case-top"><div><b>${esc(c.descripcion ? descStr(c.descripcion) : t("p.case.charge"))} · US$${fmt(c.monto_usd)}</b><span class="small">${t("p.case.meta", { id: esc(c.caso_id), d: esc(c.fecha || "") })}</span></div>
      <span class="state ${D.cls}">${D.state}</span></div>
      <ol class="steps">
        <li class="done">${t("p.step.rep")}</li>
        <li class="done">${t("p.step.chk")}</li>
        <li class="done final ${D.cls}"><b>${D.step}</b>${D.note}</li>
      </ol>
      ${reasons.length ? `<p class="small">${esc(t("p.why", { r: reasons.join(". ") }))}</p>` : ""}
    </article>`;
  }).join("") : `<p class="empty-cases">${t("p.noCases")}</p>`;
  // banner for the latest outcome
  const last = cs[cs.length - 1], hd = VIEW.handoff, bn = $("#banner");
  const icon = { ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M5 12l5 5 9-11"/></svg>',
    review: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    esc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/></svg>' };
  if (last) {
    const D = DEC[last.decision];
    const text = { ok: t("p.bn.ok", { a: fmt(last.monto_usd) }), review: t("p.bn.review", { a: fmt(last.monto_usd) }),
      esc: t("p.bn.esc", { id: last.caso_id }) }[D.cls];
    bn.className = "banner " + D.cls; bn.innerHTML = `${icon[D.cls]}<b>${D.state}</b><p>${esc(text)}</p>`; bn.hidden = false;
  } else if (hd) {
    bn.className = "banner esc"; bn.innerHTML = `${icon.esc}<b>${t("p.bn.hand.h")}</b><p>${esc(t("p.bn.hand", { id: hd.handoff_id }))}</p>`; bn.hidden = false;
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
  addMsg("a", t("p.greet", { name: first }));
  (VIEW.messages || []).forEach((m) => addMsg(m.rol === "cliente" ? "c" : "a", m.texto));
  chips();
}
function chips() {
  const el = $("#asChips"); el.innerHTML = "";
  const escalado = (VIEW.cases || []).some((c) => c.decision === "ESCALADO_A_HUMANO");
  const decided = (VIEW.cases || []).length > 0;
  const list = [t("p.chip.person"), t("p.chip.fake")];
  if (decided) list.splice(1, 0, escalado ? t("p.chip.why") : t("p.chip.faster"));
  list.forEach((txt) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = txt; b.title = txt;
    b.addEventListener("click", () => send(txt)); el.append(b);
  });
}
function working() {
  const w = document.createElement("div"); w.className = "working";
  w.innerHTML = `<span>${t("p.work.1")}</span><span>${t("p.work.2")}</span><span>${t("p.work.3")}</span>`;
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
    const d = await api("/api/portal/chat", { method: "POST", body: JSON.stringify({ mensaje: text, lang: I18N.lang }) });
    stop();
    VIEW = { ...VIEW, ...d };
    addMsg("a", d.reply, d.engine === "reglas" ? t("p.meta.rules") : t("p.meta.ai"));
    render(); chips();
  } catch (e) {
    stop();
    if (e.message !== "401") addMsg("sys", t("p.noAnswer"));
  } finally { BUSY = false; $("#asSend").disabled = false; if (opts.btn) opts.btn.disabled = false; }
}
function dispute(tx, btn) {
  btn.disabled = true;
  send(t("p.disputeMsg", { a: fmt(tx.amount_usd), d: desc(tx), date: tx.transaction_date.slice(0, 10), id: tx.transaction_id }), { btn });
}
/* the backend sends descriptions like "Withdrawal · Branch" for charges without a merchant */
function descStr(s) { const m = String(s).match(/^(Withdrawal|Transfer|Purchase|Payment|Deposit) · (.+)$/); return m ? `${TYPE[m[1]]} · ${m[2]}` : s; }
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

/* ---------------- language ---------------- */
document.addEventListener("langchange", () => {
  loadDemo();
  if (VIEW && !$("#viewApp").hidden) { showApp(false); chips(); $("#asMsgs .msg.a")?.replaceChildren(document.createTextNode(t("p.greet", { name: (VIEW.customer.first_name || "").split(" ")[0] }))); }
  else document.title = t("p.title.login");
});

/* ---------------- boot ---------------- */
(async () => {
  I18N.apply();
  loadDemo();
  if (TOKEN) {
    try { VIEW = await api("/api/portal/me"); showApp(true); return; } catch (e) { saveToken(null); }
  }
  showLogin();
})();
})();
