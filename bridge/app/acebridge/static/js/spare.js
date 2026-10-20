// Card "Spool empty": a spool ran out and the endless spool found no matching one (Klipper kobra_spare, bridge
// spare.py). The print waits over the waste chute; one tap = continue with that slot for the rest of the print.

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Swatch } from "./components.js";
import { t } from "./i18n.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";
import { grams } from "./util.js";

const name = (x) => x.spool?.name || x.material || "?";
const colour = (x) => x.spool?.color || x.color;

export function note(c) {
  if (!c.same_material) return c.sticks ? t("other material") : t("other material – may not stick");
  return c.same_color ? "" : t("other colour");
}

// the slot the printer would take by itself (same order as kobra_spare: material, color, any)
export function autoPick(sp) {
  for (const kind of sp.auto_order || []) {
    const c = (sp.candidates || []).find((x) => kind === "any" || (kind === "material" && x.same_material)
      || (kind === "color" && x.same_color));
    if (c) return c;
  }
  return null;
}

export function SpareCard() {
  const sp = S.st?.spare;
  const [busy, setBusy] = useState(false);
  if (!sp?.available || !(sp.waiting || sp.busy)) return null;
  const w = sp.waiting;
  const working = busy || sp.busy;

  const go = guard(async (tool) => {
    setBusy(true);
    try {
      await post("/api/spare", { tool });
      toast(t("Changing to slot {slot} – the print continues afterwards", { slot: tool + 1 }), "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const pick = (c) => c.same_material ? go(c.tool) : openDialog("confirm", {
    title: t("Continue with {name}?", { name: name(c) }), ok: t("Continue"), back: t("Back"), danger: !c.sticks,
    text: t("Slot {slot} holds {material}, the print so far is {was}. The nozzle switches to the temperature of the new spool; the bed and the fans stay as the file sets them.",
      { slot: c.slot, material: c.material, was: w.material }) + (c.sticks ? "" : " " + t("These two materials usually do not stick to each other well.")),
    action: () => go(c.tool),
  });
  const auto = sp.auto_in != null && autoPick(sp);

  return html`<section class="card pad col" aria-label=${t("Spool empty")} style="border-color:var(--danger-line)">
    <h2 class="h2">${working ? t("Changing the spool …") : t("Spool empty – which one now?")}</h2>
    ${w && html`<div class="row" style="gap:8px"><${Swatch} color=${colour(w)} />
      <span class="small">${t("Slot {slot} · {name} is empty. No matching spool is loaded; the print waits over the waste chute.",
        { slot: w.slot, name: name(w) })}</span></div>`}
    ${sp.error && html`<div class="note bad">${t("Change to another spool failed: {error}", { error: sp.error })}</div>`}
    ${w && !working && html`
      <div class="pick" role="group" aria-label=${t("Continue with")}>
        ${sp.candidates.map((c) => html`<button class=${c.sticks ? "" : "warn"} onClick=${() => pick(c)}>
          <${Swatch} color=${colour(c)} />
          <span class="grow"><b>${t("Slot {slot}", { slot: c.slot })} · ${name(c)}</b>
            <span class="small muted" style="display:block">${[c.material, note(c),
              c.spool?.remaining_weight != null && t("{g} left", { g: grams(c.spool.remaining_weight) })].filter(Boolean).join(" · ")}</span></span>
        </button>`)}
      </div>
      ${!sp.candidates.length && html`<div class="small muted">${t("No other spool is ready – refill the slot.")}</div>`}
      <div class="row wrap" style="gap:8px">
        <button class="btn sm" onClick=${() => go(w.tool)}>${t("Slot {slot} refilled – load and continue", { slot: w.slot })}</button>
      </div>
      ${auto && html`<div class="small faint">${t("Without an answer the printer takes slot {slot} in {min} min.",
        { slot: auto.slot, min: Math.max(1, Math.ceil(sp.auto_in / 60)) })}</div>`}`}
  </section>`;
}
