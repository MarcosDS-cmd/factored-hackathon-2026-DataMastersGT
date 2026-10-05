/* Shared i18n for the project site and the customer portal.
   - Dictionaries register themselves with I18N.register({es:{...}, en:{...}, pt:{...}}).
   - Static HTML: data-i18n="key" (text), data-i18n-html="key" (markup), data-i18n-attr="placeholder:key;aria-label:key".
   - Any element with class "lang-switch" gets ES | EN | PT buttons.
   - The choice is stored in localStorage ("dm-lang"), so both pages open in the same language.
   - Changing language fires a "langchange" event so each page re-renders its dynamic parts. */
window.I18N = (() => {
  "use strict";
  const KEY = "dm-lang", LANGS = ["es", "en", "pt"], LOCALE = { es: "es-ES", en: "en-US", pt: "pt-BR" };
  const NAMES = { es: "Español", en: "English", pt: "Português" };
  const dicts = { es: {}, en: {}, pt: {} };
  let lang = null;
  try { lang = localStorage.getItem(KEY); } catch (e) {}
  if (!LANGS.includes(lang)) lang = document.documentElement.dataset.defaultLang || "en";

  function register(d) { for (const l of LANGS) Object.assign(dicts[l], d[l] || {}); }
  function t(key, vars) {
    let s = dicts[lang][key];
    if (s == null) s = dicts.en[key];
    if (s == null) return key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? vars[k] : m));
    return s;
  }
  function apply(root = document) {
    document.documentElement.lang = lang;
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
      el.dataset.i18nAttr.split(";").forEach((pair) => {
        const [attr, k] = pair.split(":").map((x) => x.trim());
        if (attr && k) el.setAttribute(attr, t(k));
      });
    });
    const tt = document.documentElement.dataset.i18nTitle;
    if (tt) document.title = t(tt);
    mount();
  }
  function mount() {
    document.querySelectorAll(".lang-switch").forEach((box) => {
      if (!box.dataset.ready) {
        box.dataset.ready = "1";
        box.setAttribute("role", "group");
        box.innerHTML = LANGS.map((l) => `<button type="button" data-l="${l}" lang="${l}" title="${NAMES[l]}" aria-label="${NAMES[l]}">${l.toUpperCase()}</button>`).join("");
        box.addEventListener("click", (e) => { const b = e.target.closest("button[data-l]"); if (b) set(b.dataset.l); });
      }
      box.setAttribute("aria-label", t("lang.label"));
      box.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.l === lang)));
    });
  }
  function set(l) {
    if (!LANGS.includes(l) || l === lang) return;
    lang = l;
    try { localStorage.setItem(KEY, l); } catch (e) {}
    apply();
    document.dispatchEvent(new CustomEvent("langchange", { detail: { lang } }));
  }
  register({ es: { "lang.label": "Idioma" }, en: { "lang.label": "Language" }, pt: { "lang.label": "Idioma" } });
  return { t, set, apply, register, get lang() { return lang; }, get locale() { return LOCALE[lang]; }, LANGS };
})();
