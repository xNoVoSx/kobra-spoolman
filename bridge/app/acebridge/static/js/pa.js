// Karte "Pressure Advance": Auto-PA (Klipper-Modul kobra_pa) - Schalter, PA je Slot aus Spoolman, messen/neu messen.
// Klipper misst mit der Wiegezelle, wenn ein Filament in Spoolman noch kein PA hat; die Bridge schreibt es zurueck.

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Toggle } from "./ace.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";

const STATE = {
  table: ["gemessen", "ok"], manual: ["von Hand", ""], needed: ["misst beim nächsten Druck", "warn"],
  failed: ["Messung gescheitert", "bad"], empty: ["", ""],
};
const k = (v) => (v == null ? "–" : v.toFixed(3).replace(".", ","));

export function PaCard() {
  const pa = S.st?.pa;
  const [busy, setBusy] = useState(false);
  if (!pa) return null;

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
  const measure = (s) => openDialog("confirm", {
    title: `PA für Slot ${s.slot} messen?`, ok: "Messen", back: "Zurück",
    text: `${s.name || "Filament"}: Der Drucker fährt zur Wurfposition, heizt auf Drucktemperatur und drückt etwa 120 mm ` +
      "in den Abfallschacht (~2 Minuten). Das Ergebnis landet in Spoolman.",
    action: () => call("/api/pa/calibrate", { slot: s.slot }, "Messung läuft – Ergebnis kommt in ~2 Minuten"),
  });
  const forget = (s) => openDialog("confirm", {
    title: "PA verwerfen?", ok: "Verwerfen", back: "Zurück",
    text: `${s.name}: Der PA-Wert wird in Spoolman gelöscht. Beim nächsten Druck mit diesem Filament misst der Drucker neu ` +
      "(wenn „Automatisch messen“ an ist).",
    action: () => call("/api/pa/forget", { filament_id: s.filament_id }, "PA verworfen"),
  });

  const printing = ["printing", "paused"].includes(S.st?.printer?.state);
  const ready = pa.present && pa.enabled && pa.patched && !pa.measuring && pa.calibrating == null && !printing;
  return html`
  <section class="card pad col" aria-label="Pressure Advance">
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">Pressure Advance</h2>
      ${(pa.measuring || pa.calibrating != null) && html`<span class="chip warn">misst …</span>`}</div>
    ${!pa.present ? html`<div class="small muted">Auto-PA ist in Klipper nicht eingerichtet (Modul kobra_pa) oder Klipper ist nicht bereit.</div>` : html`
      <${Toggle} label="Auto-PA" hint="PA je Geschwindigkeit aus Spoolman anwenden; aus = Klipper nimmt das PA aus Orca"
                 value=${pa.enabled} disabled=${busy} onChange=${(v) => call("/api/pa/switch", { enabled: v })} />
      <${Toggle} label="Automatisch messen" hint="Hat ein Filament noch kein PA, misst der Drucker beim Druckstart bzw. Farbwechsel (~2 min)"
                 value=${pa.auto} disabled=${busy || !pa.enabled} onChange=${(v) => call("/api/pa/switch", { auto: v })} />
      ${!pa.patched && html`<div class="small" style="color:var(--accent-text)">Klipper ohne Auto-PA-Patch: nur festes PA, messen geht nicht (kobra-klipper deploy).</div>`}
      ${!pa.sync && html`<div class="small" style="color:var(--accent-text)">Verbindung zu Spoolman ist aus (Einstellungen → Pressure Advance) – Klipper bekommt keine Werte.</div>`}
      <div class="col" style="gap:8px">
        ${pa.slots.filter((s) => s.filament_id).map((s) => {
          const [label, cls] = STATE[s.source === "manual" ? "manual" : s.state] || [s.state, ""];
          return html`<div class="row wrap" style="gap:8px">
            <span class="grow"><b>Slot ${s.slot}</b> · ${s.name}${s.active ? html` <span class="chip on">aktiv</span>` : ""}
              <span class="small faint" style="display:block">${s.k.length > 1
                ? `${s.k.map(k).join(" / ")} bei ${s.speeds.join(" / ")} mm/s${s.date ? ` · ${s.date}` : ""}`
                : s.k.length ? `fest ${k(s.k[0])}` : ""}</span></span>
            <span class="m">${k(s.k_ref)}</span>
            ${label && html`<span class=${`chip ${cls}`}>${label}</span>`}
            <button class="btn sm" disabled=${!ready || busy} title="Jetzt messen (nur ohne Druck)" onClick=${() => measure(s)}>Messen</button>
            ${s.k.length > 0 && html`<button class="btn sm" disabled=${busy} title="Wert löschen, beim nächsten Druck neu messen" onClick=${() => forget(s)}>Neu messen</button>`}
          </div>`;
        })}
        ${!pa.slots.some((s) => s.filament_id) && html`<div class="small muted">Keine Spule in der ACE zugeordnet.</div>`}
      </div>
      ${pa.last && html`<div class="small faint">Letzte Messung: Slot ${pa.last.t + 1} · ${pa.last.kind === "error" ? `gescheitert (${pa.last.message})`
        : `${(pa.last.k || []).map(k).join(" / ")}`}</div>`}
      <div class="small muted">Wert bei 200 mm/s steht auch in Spoolman (Pressure Advance) und damit im Orca-Profil.
        PA in Orca von Hand geändert → die Messung gilt nicht mehr.</div>`}
  </section>`;
}
