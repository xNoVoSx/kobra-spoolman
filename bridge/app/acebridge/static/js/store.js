// Gemeinsamer Zustand der Oberflaeche. Die Bridge ist die Quelle; hier liegt nur, was sie zuletzt gemeldet hat.

import { useEffect, useState } from "../vendor/preact-htm.module.js";
import { get } from "./api.js";

const listeners = new Set();
export const S = {
  me: undefined,        // gekoppeltes Geraet (undefined = noch nicht geprueft, null = nicht gekoppelt)
  setupRequired: false,
  st: null,             // /api/app/state
  stErr: null,
  spools: null,         // /api/app/spools (alle aktiven Spulen)
  jobs: null,           // /api/jobs
  catalog: null,        // /api/app/catalog
  health: null,         // /api/health
  sel: null,            // ausgewaehlte Spule (id)
  selFil: null,         // ausgewaehltes Filament (id oder "neu")
  dialog: null,         // {kind, ...}
  menu: null,           // Kontextmenue {x, y, items}
  toasts: [],
  pairing: false,       // Kopplungsseite erzwingen (z.B. Schreibversuch ohne Schluessel)
  pairReason: null,
  q: "",                // Suche im Regal
  filter: "alle",       // Filter im Regal
};

export function set(patch) {
  Object.assign(S, typeof patch === "function" ? patch(S) : patch);
  listeners.forEach((fn) => fn());
}

/** Komponente neu zeichnen, wenn sich der Zustand aendert. */
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
  setTimeout(() => set({ toasts: S.toasts.filter((t) => t.id !== id) }), kind === "bad" ? 7000 : 3500);
}

export const canWrite = () => !!S.me;

// ------------------------------------------------------------ Laden
// Fingerabdruck der Oberflaeche, mit der diese Seite geladen wurde (setzt die Bridge in index.html)
const UI_TAG = document.querySelector('meta[name="ui-tag"]')?.content || null;

/** Neue Oberflaeche auf der Bridge (Update)? Dann neu laden - aber nicht mitten in einem Dialog oder beim Tippen. */
function reloadIfUpdated(st) {
  if (!UI_TAG || !st?.ui || st.ui === UI_TAG) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
  // offener Dialog, Tippen oder geoeffneter Editor (Spule/Sorte, evtl. ungespeichert): spaeter erneut versuchen
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
  try { set({ spools: (await get("/api/app/spools")).spools }); } catch { /* Anzeige behaelt alten Stand */ }
}
export async function loadJobs() {
  try { set({ jobs: (await get("/api/jobs?limit=60")).jobs }); } catch { /* s.o. */ }
}
export async function loadCatalog() {
  try { set({ catalog: await get("/api/app/catalog") }); } catch (e) { toast("Katalog: " + e.message, "bad"); }
}
export async function loadHealth() {
  try { set({ health: await get("/api/health") }); } catch { /* s.o. */ }
}
export async function reloadAll() {
  await Promise.all([loadState(), loadSpools()]);
}

/** Nach einer Aenderung: Zustand und Spulen neu holen. */
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

// ------------------------------------------------------------ Hilfen fuer Ansichten
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
/** Schreibende Aktion: ohne Kopplung erst zur Kopplungsseite. */
export function guard(fn) {
  return (...args) => {
    if (!canWrite()) { set({ pairing: true }); return; }
    return fn(...args);
  };
}
