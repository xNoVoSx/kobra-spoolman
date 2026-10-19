// Card "Hotend": swappable hotends (bridge nozzle.py, Klipper kobra_nozzle) - which hotend is in, PID per hotend
// (measure once), Z correction, print start check. Klipper sets PID and nozzle at once; Auto PA keeps values per nozzle.

import { html, useEffect, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Toggle } from "./ace.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";
import { cls, fixed, nozzleMm as mm } from "./util.js";

const zText = (z) => `${z > 0 ? "+" : ""}${fixed(z || 0, 3)} mm`;

export function HotendCard() {
  const n = S.st?.nozzle;
  const [busy, setBusy] = useState(false);
  const [z, setZ] = useState("");
  useEffect(() => { setZ(n ? fixed(n.z || 0, 3) : ""); }, [n?.active, n?.z]);
  if (!n?.available) return null;

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
  const printing = ["printing", "paused"].includes(S.st?.printer?.state);
  const locked = busy || printing || n.measuring || !n.enabled;
  const measure = () => openDialog("confirm", {
    title: t("Measure the PID of {name}?", { name: n.name }), ok: t("Measure"), back: t("Back"),
    text: t("The printer homes if needed, moves over the waste chute and heats the nozzle to {temp} °C several times (a few minutes). Stay near the printer. The values apply at once and are saved for this hotend.",
      { temp: 250 }),
    action: () => call("/api/nozzle/pid", {}, t("Measuring the PID – a few minutes")),
  });
  const zNum = Number(String(z).replace(",", "."));
  const zValid = String(z).trim() !== "" && Number.isFinite(zNum) && Math.abs(zNum) <= 0.5;

  return html`<section class="card pad col" aria-label=${t("Hotend")}>
    <div class="row"><span style="color:var(--accent)"><${Icon} name="nozzle" /></span><h2 class="h2 grow">${t("Hotend")}</h2>
      ${n.measuring && html`<span class="chip warn">${t("measuring PID …")}</span>`}
      ${n.enabled && !n.measuring && html`<span class="chip">${mm(n.diameter)}</span>`}</div>
    ${!n.enabled ? html`<div class="small muted">${t("Swappable hotends are off – Klipper heats with the PID of its configuration.")} <a href="#/features">${t("Switch on under Features")}</a></div>` : html`
      <div class="small muted">${t("Which hotend is in the printer? Klipper takes its PID, nozzle size and Z correction at once; Auto PA keeps its values per nozzle.")}</div>
      <div class="pick" role="radiogroup" aria-label=${t("Hotend in use")}>
        ${n.hotends.map((h) => html`<button role="radio" aria-checked=${h.id === n.active} class=${cls(h.id === n.active && "on")}
            disabled=${locked && h.id !== n.active} title=${printing ? t("Not during a print") : ""}
            onClick=${() => h.id !== n.active && call("/api/nozzle", { hotend: h.id }, t("Hotend: {name}", { name: h.name }))}>
          <span class="grow"><b>${h.name}</b> <span class="muted">· ${mm(h.diameter)}</span>
            <span class="small muted" style="display:block">${h.pid ? t("PID measured") : h.default ? t("PID from the Klipper configuration") : t("PID not measured")}${h.z ? ` · Z ${zText(h.z)}` : ""}</span></span>
          ${h.id === n.active && html`<span class="chip on">${t("in use")}</span>`}
        </button>`)}
      </div>
      ${n.warning && html`<div class="note warn">${n.warning}</div>`}
      ${n.error && html`<div class="note bad">${t("PID measurement failed: {error}", { error: n.error })}</div>`}
      <div class="row wrap" style="gap:8px">
        <span class="grow small">${t("PID")}: ${n.pid.length ? html`<span class="m">${n.pid.map((v) => fixed(v, 3)).join(" / ")}</span>` : "–"}
          <span class="faint"> · ${n.pid_measured ? t("measured for this hotend") : t("from the Klipper configuration")}</span></span>
        <button class="btn sm" disabled=${locked} title=${printing ? t("Not during a print") : ""} onClick=${measure}>
          ${n.pid_measured ? t("Measure again") : t("Measure PID")}</button>
      </div>
      <div class="row wrap" style="gap:8px">
        <label class="grow small" for="hotend-z">${t("Z correction of this hotend (+ = further from the bed)")}</label>
        <input id="hotend-z" class="inp m" style="width:7em" inputmode="decimal" value=${z} onInput=${(e) => setZ(e.target.value)} />
        <button class="btn sm" disabled=${busy || !zValid || zNum === (n.z || 0)}
          onClick=${() => call("/api/nozzle", { z: zNum }, t("Z correction saved"))}>${t("Save")}</button>
      </div>
      <${Toggle} label=${t("Check the nozzle at print start")} hint=${t("Stops a print that was sliced for another nozzle, before anything heats up")}
                 value=${n.check} disabled=${busy} onChange=${(v) => call("/api/nozzle", { check: v })} />
      ${n.last?.ok && html`<div class="small faint">${t("Last PID measurement: {name} · {pid}", {
        name: (n.hotends.find((h) => h.id === n.last.hotend) || {}).name || n.last.hotend, pid: n.last.pid.map((v) => fixed(v, 3)).join(" / ") })}</div>`}`}
  </section>`;
}
