// Translations for web UI and display: English source texts, German catalog in static/i18n/de.json.
//
//   t("Spool {n} assigned", { n: 7 })   ->  "Spool 7 assigned" / "Spule 7 zugeordnet"
//
// Language: ?lang= in the URL (the app passes its language to WebViews), else this device's choice (localStorage
// "kobra.lang", set on the settings page), else the bridge default (the bridge writes it into <html lang>, setting
// "Language"). Every request to the bridge carries X-Lang (api.js), so
// texts made by the bridge come in the same language. The catalog loads before any other module runs (top-level
// await), so constant tables may call t() directly.
// tests/test_i18n_web.py checks that every t("...") has a German entry and that no German is left in the code.

export const LANGS = { en: "English", de: "Deutsch" };
const KEY = "kobra.lang";

function stored() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } }

/** "" = follow the bridge default. */
export const chosen = stored();
const asked = new URLSearchParams(location.search).get("lang") || "";
export const lang = [asked, chosen, document.documentElement.lang].find((l) => LANGS[l]) || "en";
document.documentElement.lang = lang;

let catalog = {};
if (lang !== "en") {
  try {
    const r = await fetch(new URL(`../i18n/${lang}.json`, import.meta.url), { cache: "no-cache" });
    if (r.ok) catalog = await r.json();
  } catch { /* offline or blocked: English */ }
}

/** Translate an English text; {name} placeholders are filled from params. */
export function t(text, params) {
  const s = catalog[text] ?? text;
  if (!params) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (params[k] === undefined || params[k] === null ? m : String(params[k])));
}

/** Choose the language of this device ("" = bridge default) and reload. */
export function setLang(l) {
  try { l ? localStorage.setItem(KEY, l) : localStorage.removeItem(KEY); } catch { /* private mode */ }
  location.reload();
}

/** Locale for number and date formatting. */
export const locale = lang === "de" ? "de-DE" : "en-GB";
