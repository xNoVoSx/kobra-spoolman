// Zugriff auf die Bridge. Der Schluessel dieses Browsers liegt im localStorage (einmal koppeln).

const KEY = "kobra.key";
const VIEW_ONLY = "kobra.viewonly";

function read(store, k) { try { return store.getItem(k) || ""; } catch { return ""; } }
function write(store, k, v) { try { v ? store.setItem(k, v) : store.removeItem(k); } catch { /* privat/gesperrt */ } }

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
  const headers = {};
  const key = auth.key;
  if (key) headers.Authorization = "Bearer " + key;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let resp;
  try {
    resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  } catch {
    throw new ApiError(0, "Bridge nicht erreichbar");
  }
  let data = null;
  try { data = await resp.json(); } catch { /* leer */ }
  if (!resp.ok) {
    const err = new ApiError(resp.status, (data && data.error) || `Fehler ${resp.status}`);
    if (resp.status === 401 || resp.status === 403) onUnauthorized(err);
    throw err;
  }
  return data;
}

export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const patch = (p, b) => api("PATCH", p, b);
export const del = (p) => api("DELETE", p);
