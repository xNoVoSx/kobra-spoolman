// Karte "Druck fortsetzen?": nach einem Stromausfall (Klipper-Modul kobra_resume). Live-Bild zum Pruefen des Teils,
// Fortsetzen nur mit Rueckfrage - Klipper heizt, tastet Z auf das Teil an und druckt an der Stelle weiter.

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Toggle } from "./ace.js";
import { useCamera } from "./media.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";

export function ResumeCard() {
  const r = S.st?.resume;
  const [busy, setBusy] = useState(false);
  const show = r && (r.pending || r.running || r.error);
  const [src, err, onError] = useCamera(!!show);
  if (!show) return null;
  const p = r.pending || {};

  const call = guard(async (path, body, ok) => {
    setBusy(true);
    try {
      await post(path, body);
      if (ok) toast(ok, "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const resume = () => openDialog("confirm", {
    title: "Druck fortsetzen?", ok: "Fortsetzen", back: "Zurück",
    text: `${p.file}, Schicht ${p.layer ?? "?"}: Ist das Teil noch fest auf dem Bett? Der Drucker heizt das Bett, ` +
      "fährt X/Y nach Hause, tastet die Höhe auf dem Teil an und druckt an der Stelle weiter (dauert einige Minuten). " +
      "Passt die Höhe nicht, bricht er ab statt zu raten.",
    action: () => call("/api/resume", { confirm: true }, "Fortsetzen gestartet"),
  });
  const discard = () => openDialog("confirm", {
    title: "Unterbrochenen Druck verwerfen?", ok: "Verwerfen", back: "Zurück", danger: true,
    text: `${p.file} wird nicht fortgesetzt; die Sicherung wird gelöscht.`,
    action: () => call("/api/resume/discard", {}, "Verworfen"),
  });
  return html`
  <section class="card pad col" aria-label="Druck fortsetzen" style="border-color:var(--danger-line)">
    <h2 class="h2">${r.running ? "Druck wird fortgesetzt …" : "Druck unterbrochen"}</h2>
    ${r.pending && html`<div class="small">${p.file} · Schicht ${p.layer ?? "?"}${p.layers ? ` von ${p.layers}` : ""}
      · ${Math.round(100 * (p.progress || 0))} %</div>`}
    ${src && html`<img src=${src} onError=${onError} alt="Kamera" style="width:100%;border-radius:10px" />`}
    ${err && html`<div class="small faint">${err}</div>`}
    ${r.error && html`<div class="small" style="color:var(--danger-text)">Fortsetzen abgebrochen: ${r.error}</div>`}
    ${r.pending && !r.running && html`<div class="row wrap" style="gap:8px">
      <button class="btn acc" disabled=${busy} onClick=${resume}>Fortsetzen …</button>
      <button class="btn" disabled=${busy} onClick=${discard}>Verwerfen</button></div>`}
  </section>`;
}

/** Schalter auf der ACE-Seite: Fortsetzen nach Stromausfall an/aus (im Drucker gespeichert). */
export function PowerlossCard() {
  const r = S.st?.resume;
  const [busy, setBusy] = useState(false);
  if (!r || !r.present) return null;
  const set = guard(async (v) => {
    setBusy(true);
    try { await post("/api/resume/switch", { enabled: v }); await loadState(); }
    catch (e) { if (e.status !== 401 && e.status !== 403) toast(e.message, "bad"); }
    finally { setBusy(false); }
  });
  return html`<section class="card pad col" aria-label="Stromausfall">
    <${Toggle} label="Fortsetzen nach Stromausfall"
      hint="Der Drucker sichert im Druck laufend die Stelle; nach dem Einschalten fragt er, ob er weitermachen soll"
      value=${r.enabled} disabled=${busy} onChange=${set} /></section>`;
}
