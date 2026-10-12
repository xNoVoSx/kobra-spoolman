// Writing actions. Each fetches the bridge's state again afterwards and reports success or failure.

import { del, patch, post } from "./api.js";
import { t } from "./i18n.js";
import { S, after, loadCatalog, loadJobs, set } from "./store.js";

export const assignSlot = (slot, spoolId) =>
  after(post(`/api/slots/${slot}`, { spool_id: spoolId }), spoolId == null ? t("Slot {slot} emptied", { slot })
    : t("Spool #{id} in slot {slot}", { id: spoolId, slot }));

export const moveSpool = (spoolId, slot) =>
  after(post(`/api/app/spool/${spoolId}/location`, { slot }), slot == null ? t("Put on the shelf") : t("Moved into slot {slot}", { slot }));

export const updateSpool = (spoolId, changes) =>
  after(patch(`/api/app/spool/${spoolId}`, changes), t("Spool saved"));

export async function archiveSpool(spoolId) {
  await after(post(`/api/app/spool/${spoolId}/archive`), t("Spool #{id} archived", { id: spoolId }));
  if (S.sel === spoolId) set({ sel: null });
}

export async function createSpool(body) {
  const res = await after(post("/api/app/spool", body), t("Spool created"));
  set({ sel: res.spool?.spool_id ?? null });
  return res;
}

export async function createVendor(name) {
  const res = await after(post("/api/app/vendor", { name }), t("Vendor “{name}” created", { name }));
  await loadCatalog();
  return res.vendor;
}

export async function createFilament(body) {
  const res = await after(post("/api/app/filament", body), t("Filament created"));
  await loadCatalog();
  return res.filament;
}
export async function updateFilament(fid, body) {
  const res = await after(patch(`/api/app/filament/${fid}`, body), t("Filament saved – in Orca “Update profiles”"));
  await loadCatalog();
  return res.filament;
}
export async function copyFilament(fid, body) {
  const res = await after(post(`/api/app/filament/${fid}/copy`, body), t("New colour created"));
  await loadCatalog();
  return res.filament;
}

export const dryerStart = (temp, hours) => after(post("/api/dryer/start", { temp, hours }), t("Dryer started"));
export const dryerStop = () => after(post("/api/dryer/stop"), t("Dryer stopped"));
export const dryerConfig = (cfg) => after(post("/api/dryer/config", cfg), t("Rules saved"));

export async function bookOpen(itemId, spoolId) {
  await after(post(`/api/open/${itemId}`, { spool_id: spoolId }), t("Booked on spool #{id}", { id: spoolId }));
  loadJobs();
}
export const visionFeedback = (id, verdict) =>
  after(post("/api/vision/feedback", { id, verdict }), verdict === "false_alarm"
    ? t("Noted as a false alarm – AI muted for this print") : t("Thanks – noted as a failed print"));
export const discardOpen = (itemId) => after(del(`/api/open/${itemId}`), t("Item discarded"));
