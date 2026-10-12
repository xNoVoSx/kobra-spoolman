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

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(method, path, body) {
  const headers = { "X-Lang": lang };       // texts made by the bridge in the language of this page
  const key = auth.key;
  if (key) headers.Authorization = "Bearer " + key;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let resp;
  try {
    resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
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

export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const patch = (p, b) => api("PATCH", p, b);
export const del = (p) => api("DELETE", p);
