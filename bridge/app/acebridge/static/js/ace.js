// Card "ACE": settings of the ACE the printer display does not show - per driver (settings.variant).
// Klipper + ACEPRO: endless spool and its mode. Purge lengths come from Orca (flushing volumes dialog, the change-filament
// G-code gives them to the driver).
// Rinkhals: endless spool (auto refill), runout detection and the firmware's purge multiplier with a preview per colour
// pair (the firmware purges by itself, Orca's matrix does not apply). Changes during a print need a confirmation.

import { html, useEffect, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { Swatch } from "./components.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";
import { cls, num } from "./util.js";

export function Toggle({ label, hint, value, disabled, onChange }) {
  return html`<label class=${cls("toggle", disabled && "off")}>
    <span class="grow"><span>${label}</span>${hint && html`<span class="small muted" style="display:block">${hint}</span>`}</span>
    <input type="checkbox" role="switch" checked=${!!value} disabled=${disabled} onChange=${(e) => onChange(e.target.checked)} />
    <span class="knob" aria-hidden="true"></span>
  </label>`;
}

const MODE_LABEL = { exact: t("Same colour"), material: t("Same material"), next: t("Next spool") };
const PRESET_LABEL = { minimal: t("Minimal"), normal: t("Normal"), maximum: t("Maximum") };

export function AceCard({ compact }) {
  const a = S.st?.ace;
  const [busy, setBusy] = useState(false);

  if (!a) return null;
  if (!a.present) {
    return html`<section class="card pad col" aria-label="ACE"><div class="row"><h2 class="h2 grow">ACE</h2><span class="chip">${t("not connected")}</span></div>
      <div class="small muted">${t("The ACE driver reports no connected ACE.")}</div></section>`;
  }
  const rinkhals = a.variant === "rinkhals";

  const send = async (changes, confirmPrinting) => {
    setBusy(true);
    try {
      await post("/api/ace/options", confirmPrinting ? { ...changes, confirm_printing: true } : changes);
      toast(t("ACE: saved"), "ok");
      await loadState();
    } catch (e) {
      if (e.status === 409 && rinkhals && a.printing && !confirmPrinting) {
        openDialog("confirm", {
          title: t("Change during the print?"),
          text: t("The printer applies it from the next colour change on."),
          ok: t("Change"), action: () => send(changes, true),
        });
      } else if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  };
  const setOption = guard((k, v) => send({ [k]: v }, false));
  const modes = a.endless_modes || {};

  return html`
  <section class="card pad col" aria-label=${t("ACE settings")}>
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">ACE</h2>
      <span class="small faint m">${a.firmware || ""}</span></div>
    <${Toggle} label=${t("Endless spool")} hint=${t("If a spool runs empty, the ACE loads a matching other one and keeps printing")}
               value=${a.endless_spool} disabled=${busy || a.endless_spool == null} onChange=${(v) => setOption("endless_spool", v)} />
    ${a.endless_spool && Object.keys(modes).length > 0 && html`
      <div class="col" style="gap:6px">
        <div class="small muted">${t("Which spool matches?")}</div>
        <div class="row wrap" style="gap:8px">
          ${Object.keys(modes).map((k) => html`
            <button class=${cls("chip", a.endless_mode === k && "on")} disabled=${busy} title=${modes[k]}
                    onClick=${() => a.endless_mode !== k && setOption("endless_mode", k)}>${MODE_LABEL[k] || k}</button>`)}
        </div>
      </div>`}
    ${rinkhals && html`
      <${Toggle} label=${t("Runout detection")} hint=${t("The printer pauses when the filament runs out")}
                 value=${a.runout_detect} disabled=${busy || a.runout_detect == null} onChange=${(v) => setOption("runout_detect", v)} />`}
    ${rinkhals && compact && a.flush_multiplier != null && html`
      <div class="row small"><span class="grow muted">${t("Purge multiplier")}</span><b>${num(a.flush_multiplier, 1)}×</b></div>`}
    ${rinkhals && !compact && html`<${PurgeSection} a=${a} busy=${busy} send=${(m) => send({ flush_multiplier: m }, false)} />`}
    ${!rinkhals && !compact && html`
      <hr class="sep" />
      <div class="small muted">${t("Purge lengths per colour change are set in Orca (flushing volumes dialog next to “Filament”) – the printer profile's change-filament G-code passes them to the ACE.")}
        ${a.model ? html`<span class="faint">ACE: ${a.model}</span>` : null}</div>`}
    ${compact && html`<a href="#/ace" class="small">${t("More about the ACE →")}</a>`}
  </section>`;
}

// Rinkhals: the firmware's purge multiplier with a "what if" preview of the purge per colour pair.
function PurgeSection({ a, busy, send }) {
  const current = a.flush_multiplier;
  const [lo, hi] = a.limits?.flush_multiplier || [0.1, 3];
  const [want, setWant] = useState(current);
  const [preview, setPreview] = useState(null);
  useEffect(() => { setWant(current); }, [current]);
  useEffect(() => {
    if (want == null) return undefined;
    const id = setTimeout(() => {
      get(`/api/ace?multiplier=${encodeURIComponent(want)}`).then((r) => setPreview(r.purge)).catch(() => setPreview(null));
    }, 250);
    return () => clearTimeout(id);
  }, [want, S.st?.slots]);
  const changed = want != null && current != null && Math.abs(want - current) > 0.001;
  const editable = a.flush_multiplier_editable !== false && current != null;

  return html`
    <hr class="sep" />
    <div class="col" style="gap:8px">
      <div class="row"><b class="grow">${t("Purge per colour change")}</b>
        <span class="small muted">${current == null ? t("not read yet") : t("now {m}×", { m: num(current, 1) })}</span></div>
      <div class="small muted">${t("Under Rinkhals the printer purges by itself at every colour change – Orca's flushing volumes do not apply. The amount follows the colour difference times this multiplier.")}</div>
      <div class="row wrap" style="gap:8px">
        ${Object.entries(a.presets || {}).map(([k, v]) => html`
          <button class=${cls("chip", Math.abs((want ?? -1) - v) < 0.001 && "on")} disabled=${busy || !editable}
                  onClick=${() => setWant(v)}>${PRESET_LABEL[k] || k} ${num(v, 1)}×</button>`)}
      </div>
      <div class="row" style="gap:10px">
        <input class="grow" type="range" min=${lo} max=${hi} step="0.1" value=${want ?? 1} disabled=${busy || !editable}
               aria-label=${t("Purge multiplier")} onInput=${(e) => setWant(Number(e.target.value))} />
        <b style="min-width:3.5em;text-align:right">${want == null ? "–" : num(want, 1) + "×"}</b>
      </div>
      ${!editable && current != null && html`<div class="small muted">${t("The firmware does not allow changing the multiplier right now")}</div>`}
      ${changed && html`<div class="row" style="gap:8px">
        <button class="btn acc" disabled=${busy} onClick=${() => send(want)}>${t("Apply {m}×", { m: num(want, 1) })}</button>
        <button class="btn ghost" disabled=${busy} onClick=${() => setWant(current)}>${t("Reset")}</button></div>`}
      <${PurgePairs} p=${preview} />
      ${a.model ? html`<div class="small faint">ACE: ${a.model}</div>` : null}
    </div>`;
}

function PurgePairs({ p }) {
  if (!p) return null;
  if (!p.pairs?.length) return html`<div class="small muted">${t("Load at least two colours to see the purge per change.")}</div>`;
  return html`
    <div class="small muted">${t("First load of a print: about {mm} mm.", { mm: num(p.first_load_mm, 0) })}</div>
    <div style="overflow:auto"><table class="tbl small">
      <thead><tr><th>${t("From")}</th><th>${t("To")}</th><th class="r">mm</th><th class="r">g</th></tr></thead>
      <tbody>${p.pairs.map((x) => html`<tr>
        <td class="n" title=${x.from_name}><${Swatch} color=${x.from_color} size=${12} /> ${x.from_slot} · ${x.from_name}</td>
        <td class="n" title=${x.to_name}><${Swatch} color=${x.to_color} size=${12} /> ${x.to_slot} · ${x.to_name}</td>
        <td class="r">${num(x.mm, 0)}</td><td class="r">${num(x.g, 1)}</td></tr>`)}</tbody>
    </table></div>`;
}
