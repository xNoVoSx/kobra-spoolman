// Access to the bridge. This browser's key is in localStorage (pair once).

import { lang, t } from "./i18n.js";

const KEY = "kobra.key";
const VIEW_ONLY = "kobra.viewonly";

function read(store, k) { try { return store.getItem(k) || ""; } catch { return ""; } }
function write(store, k, v) { try { v ? store.setItem(k, v) : store.removeItem(k); } catch { /* private/blocked */ } }

export const auth = {
  get key() { return read(localStorage, KEY); },
  save(key) { write(localStorage, KEY, key); write(sessionStorage, VIEW_ONLY, ""); },
  clear() { write(localStorage, KEY, ""); },
  get viewOnly() { return read(sessionStorage, VIEW_ONLY) === "1"; },
  setViewOnly(on) { write(sessionStorage, VIEW_ONLY, on ? "1" : ""); },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// Every path is relative to the page: the UI also runs under a base path, e.g. Home Assistant ingress
// (/api/hassio_ingress/<token>/). The bridge tells the page in <meta name="ingress"> (ingress.py).
const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content || "";
/** "" outside Home Assistant ingress, else "snapshots" or "stream" (camera mode under ingress). */
export const ingress = meta("ingress");
/** Path relative to the page ("/api/x" -> "api/x"). */
export const rel = (path) => path.replace(/^\//, "");
/** Address other programs reach the bridge at (camera links, app pairing): under ingress not the HA path, which needs
 *  a Home Assistant login, but the bridge's direct address. */
export function directBase() {
  if (!ingress) return location.origin;
  return meta("bridge-url") || `${location.protocol}//${location.hostname}:${meta("bridge-port") || "7913"}`;
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(method, path, body) {
  const headers = { "X-Lang": lang };       // texts made by the bridge in the language of this page
  const key = auth.key;
  if (key) headers.Authorization = "Bearer " + key;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let resp;
  try {
    resp = await fetch(rel(path), { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  } catch {
    throw new ApiError(0, t("Bridge not reachable"));
  }
  let data = null;
  try { data = await resp.json(); } catch { /* empty */ }
  if (!resp.ok) {
    const err = new ApiError(resp.status, (data && data.error) || t("Error {status}", { status: resp.status }));
    if (resp.status === 401 || resp.status === 403) onUnauthorized(err);
    throw err;
  }
  return data;
}

/** GET as text (e.g. the Markdown diagnostics), same key and errors as api(). */
export async function getText(path) {
  const headers = { "X-Lang": lang };
  if (auth.key) headers.Authorization = "Bearer " + auth.key;
  let resp;
  try {
    resp = await fetch(rel(path), { headers, cache: "no-store" });
  } catch {
    throw new ApiError(0, t("Bridge not reachable"));
  }
  if (!resp.ok) {
    let msg = "";
    try { msg = (await resp.json()).error; } catch { /* not JSON */ }
    const err = new ApiError(resp.status, msg || t("Error {status}", { status: resp.status }));
    if (resp.status === 401 || resp.status === 403) onUnauthorized(err);
    throw err;
  }
  return resp.text();
}

export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const patch = (p, b) => api("PATCH", p, b);
export const del = (p) => api("DELETE", p);
