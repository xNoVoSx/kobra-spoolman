// Schreibende Aktionen. Jede holt danach den Stand der Bridge neu und meldet Erfolg oder Fehler.

import { del, patch, post } from "./api.js";
import { S, after, loadCatalog, loadJobs, set } from "./store.js";

export const assignSlot = (slot, spoolId) =>
  after(post(`/api/slots/${slot}`, { spool_id: spoolId }), spoolId == null ? `Slot ${slot} geleert` : `Spule #${spoolId} in Slot ${slot}`);

export const moveSpool = (spoolId, slot) =>
  after(post(`/api/app/spool/${spoolId}/location`, { slot }), slot == null ? "Ins Regal gelegt" : `In Slot ${slot} gelegt`);

export const updateSpool = (spoolId, changes) =>
  after(patch(`/api/app/spool/${spoolId}`, changes), "Spule gespeichert");

export async function archiveSpool(spoolId) {
  await after(post(`/api/app/spool/${spoolId}/archive`), `Spule #${spoolId} archiviert`);
  if (S.sel === spoolId) set({ sel: null });
}

export async function createSpool(body) {
  const res = await after(post("/api/app/spool", body), "Spule angelegt");
  set({ sel: res.spool?.spool_id ?? null });
  return res;
}

export async function createVendor(name) {
  const res = await after(post("/api/app/vendor", { name }), `Hersteller „${name}“ angelegt`);
  await loadCatalog();
  return res.vendor;
}

export async function createFilament(body) {
  const res = await after(post("/api/app/filament", body), "Filament angelegt");
  await loadCatalog();
  return res.filament;
}
export async function updateFilament(fid, body) {
  const res = await after(patch(`/api/app/filament/${fid}`, body), "Filament gespeichert – in Orca „Profile aktualisieren“");
  await loadCatalog();
  return res.filament;
}
export async function copyFilament(fid, body) {
  const res = await after(post(`/api/app/filament/${fid}/copy`, body), "Neue Farbe angelegt");
  await loadCatalog();
  return res.filament;
}

export const dryerStart = (temp, hours) => after(post("/api/dryer/start", { temp, hours }), "Trockner gestartet");
export const dryerStop = () => after(post("/api/dryer/stop"), "Trockner gestoppt");
export const dryerConfig = (cfg) => after(post("/api/dryer/config", cfg), "Regeln gespeichert");

export async function bookOpen(itemId, spoolId) {
  await after(post(`/api/open/${itemId}`, { spool_id: spoolId }), `Auf Spule #${spoolId} gebucht`);
  loadJobs();
}
export const visionFeedback = (id, verdict) =>
  after(post("/api/vision/feedback", { id, verdict }), verdict === "false_alarm" ? "Als Fehlalarm gemerkt – KI für diesen Druck still" : "Danke – als Fehldruck gemerkt");
export const discardOpen = (itemId) => after(del(`/api/open/${itemId}`), "Posten verworfen");
