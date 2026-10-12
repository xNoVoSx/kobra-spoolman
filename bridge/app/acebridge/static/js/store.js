// Shared state of the UI. The bridge is the source; here is only what it reported last.

import { useEffect, useState } from "../vendor/preact-htm.module.js";
import { get } from "./api.js";
import { t } from "./i18n.js";

const listeners = new Set();
export const S = {
  me: undefined,        // paired device (undefined = not checked yet, null = not paired)
  setupRequired: false,
  st: null,             // /api/app/state
  stErr: null,
  spools: null,         // /api/app/spools (all active spools)
  jobs: null,           // /api/jobs
  catalog: null,        // /api/app/catalog
  health: null,         // /api/health
  sel: null,            // selected spool (id)
  selFil: null,         // selected filament (id or "neu" = new)
  dialog: null,         // {kind, ...}
  menu: null,           // context menu {x, y, items}
  toasts: [],
  pairing: false,       // force the pairing page (e.g. a write attempt without a key)
  pairReason: null,
  q: "",                // search on the shelf
  filter: "all",        // filter on the shelf (key, see spools.js)
};

export function set(patch) {
  Object.assign(S, typeof patch === "function" ? patch(S) : patch);
  listeners.forEach((fn) => fn());
}

/** Redraw the component when the state changes. */
export function useStore() {
  const [, tick] = useState(0);
  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return S;
}

let toastId = 0;
export function toast(text, kind = "") {
  const id = ++toastId;
  set({ toasts: [...S.toasts, { id, text, kind }] });
  setTimeout(() => set({ toasts: S.toasts.filter((x) => x.id !== id) }), kind === "bad" ? 7000 : 3500);
}

export const canWrite = () => !!S.me;

// ------------------------------------------------------------ loading
// fingerprint of the UI this page was loaded with (the bridge puts it into index.html)
const UI_TAG = document.querySelector('meta[name="ui-tag"]')?.content || null;

/** New UI on the bridge (update)? Then reload - but not in the middle of a dialog or while typing. */
function reloadIfUpdated(st) {
  if (!UI_TAG || !st?.ui || st.ui === UI_TAG) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
  // open dialog, typing or an open editor (spool/filament, maybe unsaved): try again later
  const editing = /^#\/(filament|regal|filamente)/.test(location.hash) && (S.sel != null || S.selFil != null);
  if (S.dialog || typing || editing) return;
  location.reload();
}

export async function loadState() {
  try {
    const st = await get("/api/app/state");
    set({ st, stErr: null });
    reloadIfUpdated(st);
  } catch (e) {
    set({ stErr: e.message });
  }
}
export async function loadSpools() {
  try { set({ spools: (await get("/api/app/spools")).spools }); } catch { /* the view keeps the old state */ }
}
export async function loadJobs() {
  try { set({ jobs: (await get("/api/jobs?limit=60")).jobs }); } catch { /* see above */ }
}
export async function loadCatalog() {
  try { set({ catalog: await get("/api/app/catalog") }); } catch (e) { toast(t("Catalog: {error}", { error: e.message }), "bad"); }
}
export async function loadHealth() {
  try { set({ health: await get("/api/health") }); } catch { /* see above */ }
}
export async function reloadAll() {
  await Promise.all([loadState(), loadSpools()]);
}

/** After a change: fetch state and spools again. */
export async function after(promise, okText) {
  try {
    const res = await promise;
    if (okText) toast(okText, "ok");
    await reloadAll();
    return res;
  } catch (e) {
    if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    throw e;
  }
}

// ------------------------------------------------------------ helpers for views
export function spoolById(id) {
  if (id == null) return null;
  const all = S.spools || [];
  const hit = all.find((s) => s.spool_id === id);
  if (hit) return hit;
  for (const sl of S.st?.slots || []) if (sl.spool?.spool_id === id) return sl.spool;
  return (S.st?.shelf || []).find((s) => s.spool_id === id) || null;
}
export function openDialog(kind, props = {}) { set({ dialog: { kind, ...props }, menu: null }); }
export function closeDialog() { set({ dialog: null }); }
/** Writing action: without pairing go to the pairing page first. */
export function guard(fn) {
  return (...args) => {
    if (!canWrite()) { set({ pairing: true }); return; }
    return fn(...args);
  };
}
