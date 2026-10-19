// Direct feed: filament by hand straight in the toolhead (e.g. TPU), the ACE is passed by (bridge direct.py, Klipper
// kobra_direct). Red bar on every page while it is on, a card on the ACE page, the dialog to switch it on.

import { html, useEffect, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { Dialog, Swatch } from "./components.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, closeDialog, guard, loadState, openDialog, toast } from "./store.js";
import { cls, grams, title } from "./util.js";

const printing = () => ["printing", "paused"].includes(S.st?.printer?.state);

async function switchOff() {
  try { await post("/api/direct", { enable: false }); await loadState(); toast(t("Direct feed off – printing through the ACE again")); }
  catch (e) { if (e.status !== 401 && e.status !== 403) toast(e.message, "bad"); }
}

/** Red bar on every page while direct feed is on. */
export function DirectBanner() {
  const d = S.st?.direct;
  if (!d?.active) return null;
  return html`<div class="direct-bar" role="alert">
    <${Icon} name="warn" small />
    <span class="grow"><b>${t("Direct feed is on")}</b> – ${t("the ACE is passed by.")} ${t("Spool:")} <b>${d.label}</b>${d.material ? ` · ${d.material}` : ""}</span>
    <button class="btn small" disabled=${printing()} title=${printing() ? t("Not during a print") : ""}
      onClick=${guard(switchOff)}>${t("Switch off")}</button>
  </div>`;
}

/** Card on the ACE page: explanation and switch. */
export function DirectCard() {
  const d = S.st?.direct;
  if (!d?.available) return null;
  return html`<section class=${cls("card pad col", d.active && "direct-on")} aria-label=${t("Direct feed")}>
    <h2 class="h2">${t("Direct feed")}</h2>
    <div class="small muted">${t("For filament you insert by hand straight into the toolhead (e.g. TPU). The ACE stays on (drying, slots), the print passes it by. The consumption is booked on the spool you choose.")}</div>
    ${d.active
      ? html`<div class="note bad">${t("On – spool:")} <b>${d.label}</b>${d.material ? ` · ${d.material}` : ""}${d.tool != null ? ` · T${d.tool}` : ""}</div>
        <div class="row"><button class="btn" disabled=${printing()} onClick=${guard(switchOff)}>${t("Switch off")}</button></div>`
      : html`<div class="row"><button class="btn acc" disabled=${printing()} onClick=${guard(() => openDialog("directOn"))}>
          <${Icon} name="plus" small />${t("Switch on …")}</button></div>`}
  </section>`;
}

/** Dialog: choose the spool you inserted, unload the ACE filament first if one is in the head. */
export function DirectOn() {
  const [list, setList] = useState(null);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState(null);
  const loaded = (S.st?.slots || []).find((s) => s.ace?.active);
  const [unload, setUnload] = useState(!!loaded);
  const [busy, setBusy] = useState(false);
  useEffect(() => { get("/api/spools").then((r) => setList(r.spools)).catch((e) => toast(e.message, "bad")); }, []);
  const shown = (list || []).filter((s) => !q || `${s.display_name} ${s.material} ${s.vendor} #${s.spool_id}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (a.slot ? 1 : 0) - (b.slot ? 1 : 0) || a.display_name.localeCompare(b.display_name));
  const go = async () => {
    setBusy(true);
    try {
      await post("/api/direct", { enable: true, spool_id: pick, unload });
      await loadState();
      toast(t("Direct feed on – insert the filament into the toolhead"));
      closeDialog();
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  return html`<${Dialog} title=${t("Switch on direct feed")} wide footer=${html`<button class="btn ghost" onClick=${closeDialog}>${t("Cancel")}</button>
      <button class="btn acc" disabled=${!pick || busy} onClick=${go}>${busy ? "…" : t("Switch on")}</button>`}>
    <div class="col">
      <div class="note info">${t("Which spool do you insert into the toolhead? Its consumption, PA and Z offset are used. Direct feed stays on until you switch it off.")}</div>
      ${loaded && html`<label class="row" style="gap:8px"><input type="checkbox" checked=${unload} onChange=${(e) => setUnload(e.target.checked)} />
        <span>${t("Unload the ACE filament from slot {slot} first (heats up over the waste chute)", { slot: loaded.slot })}</span></label>`}
      <label class="search"><${Icon} name="search" small /><input aria-label=${t("Search spool")} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder=${t("Search spool")} /></label>
      ${!list && html`<div class="muted">${t("loading …")}</div>`}
      <div class="pick" role="listbox" style="max-height:46vh;overflow:auto">
        ${shown.map((s) => html`
          <button role="option" aria-selected=${pick === s.spool_id} class=${pick === s.spool_id ? "on" : ""} onClick=${() => setPick(s.spool_id)}>
            <${Swatch} color=${s.color} size=${26} />
            <span class="grow"><b>${title(s)}</b> <span class="muted">· ${s.vendor} · #${s.spool_id}</span>
              <span class="small muted" style="display:block">${s.material || ""} · ${grams(s.remaining_weight)} · ${s.slot ? t("is in slot {slot}", { slot: s.slot }) : s.location || t("Shelf")}</span></span>
          </button>`)}
      </div>
    </div></${Dialog}>`;
}
