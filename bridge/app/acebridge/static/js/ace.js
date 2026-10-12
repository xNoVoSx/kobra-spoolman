// Card "ACE": settings of the ACE driver (ACEPRO) the printer display does not show - endless spool and its mode.
// Purge lengths come from Orca (flushing volumes dialog, the change-filament G-code gives them to the driver).

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, toast } from "./store.js";
import { cls } from "./util.js";

export function Toggle({ label, hint, value, disabled, onChange }) {
  return html`<label class=${cls("toggle", disabled && "off")}>
    <span class="grow"><span>${label}</span>${hint && html`<span class="small muted" style="display:block">${hint}</span>`}</span>
    <input type="checkbox" role="switch" checked=${!!value} disabled=${disabled} onChange=${(e) => onChange(e.target.checked)} />
    <span class="knob" aria-hidden="true"></span>
  </label>`;
}

const MODE_LABEL = { exact: t("Same colour"), material: t("Same material"), next: t("Next spool") };

export function AceCard({ compact }) {
  const a = S.st?.ace;
  const [busy, setBusy] = useState(false);

  if (!a) return null;
  if (!a.present) {
    return html`<section class="card pad col" aria-label="ACE"><div class="row"><h2 class="h2 grow">ACE</h2><span class="chip">${t("not connected")}</span></div>
      <div class="small muted">${t("The ACE driver reports no connected ACE.")}</div></section>`;
  }

  const setOption = guard(async (k, v) => {
    setBusy(true);
    try {
      await post("/api/ace/options", { [k]: v });
      toast(t("ACE: saved"), "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const modes = a.endless_modes || {};

  return html`
  <section class="card pad col" aria-label=${t("ACE settings")}>
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">ACE</h2>
      <span class="small faint m">${a.firmware || ""}</span></div>
    <${Toggle} label=${t("Endless spool")} hint=${t("If a spool runs empty, the ACE loads a matching other one and keeps printing")}
               value=${a.endless_spool} disabled=${busy || a.endless_spool == null} onChange=${(v) => setOption("endless_spool", v)} />
    ${a.endless_spool && html`
      <div class="col" style="gap:6px">
        <div class="small muted">${t("Which spool matches?")}</div>
        <div class="row wrap" style="gap:8px">
          ${Object.keys(modes).map((k) => html`
            <button class=${cls("chip", a.endless_mode === k && "on")} disabled=${busy} title=${modes[k]}
                    onClick=${() => a.endless_mode !== k && setOption("endless_mode", k)}>${MODE_LABEL[k] || k}</button>`)}
        </div>
      </div>`}
    ${!compact && html`
      <hr class="sep" />
      <div class="small muted">${t("Purge lengths per colour change are set in Orca (flushing volumes dialog next to “Filament”) – the printer profile's change-filament G-code passes them to the ACE.")}
        ${a.model ? html`<span class="faint">ACE: ${a.model}</span>` : null}</div>`}
    ${compact && html`<a href="#/ace" class="small">${t("More about the ACE →")}</a>`}
  </section>`;
}
