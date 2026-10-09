// Karte "ACE": Einstellungen des ACE-Treibers (ACEPRO), die das Druckerdisplay nicht zeigt - Endlosspule und ihr
// Modus. Die Spuelmengen kommen aus Orca (Spuelmengen-Dialog, der Filamentwechsel-G-Code gibt sie an den Treiber).

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
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

const MODE_LABEL = { exact: "Gleiche Farbe", material: "Gleiches Material", next: "Nächste Spule" };

export function AceCard({ compact }) {
  const a = S.st?.ace;
  const [busy, setBusy] = useState(false);

  if (!a) return null;
  if (!a.present) {
    return html`<section class="card pad col" aria-label="ACE"><div class="row"><h2 class="h2 grow">ACE</h2><span class="chip">nicht verbunden</span></div>
      <div class="small muted">Der ACE-Treiber meldet keine verbundene ACE.</div></section>`;
  }

  const setOption = guard(async (k, v) => {
    setBusy(true);
    try {
      await post("/api/ace/options", { [k]: v });
      toast("ACE: gespeichert", "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const modes = a.endless_modes || {};

  return html`
  <section class="card pad col" aria-label="ACE-Einstellungen">
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">ACE</h2>
      <span class="small faint m">${a.firmware || ""}</span></div>
    <${Toggle} label="Endlosspule" hint="Ist eine Spule leer, lädt die ACE eine passende andere und druckt weiter"
               value=${a.endless_spool} disabled=${busy || a.endless_spool == null} onChange=${(v) => setOption("endless_spool", v)} />
    ${a.endless_spool && html`
      <div class="col" style="gap:6px">
        <div class="small muted">Welche Spule passt?</div>
        <div class="row wrap" style="gap:8px">
          ${Object.keys(modes).map((k) => html`
            <button class=${cls("chip", a.endless_mode === k && "on")} disabled=${busy} title=${modes[k]}
                    onClick=${() => a.endless_mode !== k && setOption("endless_mode", k)}>${MODE_LABEL[k] || k}</button>`)}
        </div>
      </div>`}
    ${!compact && html`
      <hr class="sep" />
      <div class="small muted">Spülmengen pro Farbwechsel stellst du in Orca ein (Spülmengen-Dialog neben „Filament“) –
        der Filamentwechsel-G-Code des Druckerprofils gibt sie an die ACE weiter. ${a.model ? html`<span class="faint">ACE: ${a.model}</span>` : null}</div>`}
    ${compact && html`<a href="#/ace" class="small">Mehr zur ACE →</a>`}
  </section>`;
}
