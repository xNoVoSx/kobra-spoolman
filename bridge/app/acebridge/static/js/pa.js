// Card "Pressure advance": auto PA (Klipper module kobra_pa) - switches, PA per slot from Spoolman, measure / measure
// again. Klipper measures with the load cell when a filament in Spoolman has no PA yet; the bridge writes it back.

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Toggle } from "./ace.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";
import { fixed } from "./util.js";

const STATE = {
  table: [t("measured"), "ok"], manual: [t("by hand"), ""], needed: [t("measures at the next print"), "warn"],
  failed: [t("measurement failed"), "bad"], empty: ["", ""],
};
const k = (v) => (v == null ? "–" : fixed(v, 3));

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
    title: t("Measure PA for slot {slot}?", { slot: s.slot }), ok: t("Measure"), back: t("Back"),
    text: t("{name}: the printer moves to the purge position, heats to printing temperature and pushes about 120 mm into the waste chute (~2 minutes). The result goes to Spoolman.",
      { name: s.name || t("Filament") }),
    action: () => call("/api/pa/calibrate", { slot: s.slot }, t("Measuring – the result arrives in ~2 minutes")),
  });
  const forget = (s) => openDialog("confirm", {
    title: t("Discard PA?"), ok: t("Discard"), back: t("Back"),
    text: t("{name}: the PA value is deleted in Spoolman. At the next print with this filament the printer measures again (if “Measure automatically” is on).",
      { name: s.name }),
    action: () => call("/api/pa/forget", { filament_id: s.filament_id }, t("PA discarded")),
  });

  const printing = ["printing", "paused"].includes(S.st?.printer?.state);
  const ready = pa.present && pa.enabled && pa.patched && !pa.measuring && pa.calibrating == null && !printing;
  return html`
  <section class="card pad col" aria-label=${t("Pressure advance")}>
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">${t("Pressure advance")}</h2>
      ${(pa.measuring || pa.calibrating != null) && html`<span class="chip warn">${t("measuring …")}</span>`}</div>
    ${!pa.present ? html`<div class="small muted">${S.st?.ace?.variant === "rinkhals"
      ? t("Auto PA needs Klipper with the load cell module kobra_pa – not available with the Anycubic firmware. Orca's PA from the filament profile applies.")
      : t("Auto PA is not set up in Klipper (module kobra_pa) or Klipper is not ready.")}</div>` : html`
      <${Toggle} label=${t("Auto PA")} hint=${t("Apply PA per speed from Spoolman; off = Klipper takes the PA from Orca")}
                 value=${pa.enabled} disabled=${busy} onChange=${(v) => call("/api/pa/switch", { enabled: v })} />
      <${Toggle} label=${t("Measure automatically")} hint=${t("If a filament has no PA yet, the printer measures at print start or colour change (~2 min)")}
                 value=${pa.auto} disabled=${busy || !pa.enabled} onChange=${(v) => call("/api/pa/switch", { auto: v })} />
      ${!pa.patched && html`<div class="small" style="color:var(--accent-text)">${t("Klipper without the auto PA patch: fixed PA only, measuring does not work (kobra-klipper deploy).")}</div>`}
      ${!pa.sync && html`<div class="small" style="color:var(--accent-text)">${t("The connection to Spoolman is off (Settings → Pressure advance) – Klipper gets no values.")}</div>`}
      <div class="col" style="gap:8px">
        ${pa.slots.filter((s) => s.filament_id).map((s) => {
          const [label, cls] = STATE[s.source === "manual" ? "manual" : s.state] || [s.state, ""];
          return html`<div class="row wrap" style="gap:8px">
            <span class="grow"><b>${t("Slot {slot}", { slot: s.slot })}</b> · ${s.name}${s.active ? html` <span class="chip on">${t("active")}</span>` : ""}
              <span class="small faint" style="display:block">${s.k.length > 1
                ? t("{k} at {speeds} mm/s", { k: s.k.map(k).join(" / "), speeds: s.speeds.join(" / ") }) + (s.date ? ` · ${s.date}` : "")
                : s.k.length ? t("fixed {k}", { k: k(s.k[0]) }) : ""}</span></span>
            <span class="m">${k(s.k_ref)}</span>
            ${label && html`<span class=${`chip ${cls}`}>${label}</span>`}
            <button class="btn sm" disabled=${!ready || busy} title=${t("Measure now (only without a print)")} onClick=${() => measure(s)}>${t("Measure")}</button>
            ${s.k.length > 0 && html`<button class="btn sm" disabled=${busy} title=${t("Delete the value, measure again at the next print")} onClick=${() => forget(s)}>${t("Measure again")}</button>`}
          </div>`;
        })}
        ${!pa.slots.some((s) => s.filament_id) && html`<div class="small muted">${t("No spool assigned in the ACE.")}</div>`}
      </div>
      ${pa.last && html`<div class="small faint">${pa.last.kind === "error"
        ? t("Last measurement: slot {slot} · failed ({message})", { slot: pa.last.t + 1, message: pa.last.message })
        : t("Last measurement: slot {slot} · {k}", { slot: pa.last.t + 1, k: (pa.last.k || []).map(k).join(" / ") })}</div>`}
      <div class="small muted">${t("The value at 200 mm/s is also in Spoolman (pressure advance) and so in the Orca profile. PA changed by hand in Orca → the measurement no longer applies.")}</div>`}
  </section>`;
}
