// Print control: pause/resume, cancel (confirm), emergency stop (hold 2 s + confirm), tuning.
// Everything goes through the bridge (POST /api/print/...) and appears with its sender in the terminal.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { ApiError, post } from "./api.js";
import { Dialog } from "./components.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, closeDialog, guard, loadState, openDialog, toast } from "./store.js";
import { cls, fileName } from "./util.js";

const HOLD_MS = 2000;

/** Send an action; errors as a toast, then rethrow (so dialogs stay open). */
async function send(path, body = {}, okText) {
  try {
    await post(path, body);
    if (okText) toast(okText, "ok");
    loadState();
  } catch (e) {
    if (!(e instanceof ApiError && (e.status === 401 || e.status === 403))) toast(e.message, "bad");
    throw e;
  }
}

/** Button that fires only after being held for HOLD_MS (emergency stop). */
function HoldButton({ onHeld, children }) {
  const [p, setP] = useState(0);
  const timer = useRef(null);
  const start = useRef(0);
  const stop = () => { cancelAnimationFrame(timer.current); timer.current = null; setP(0); };
  const tick = () => {
    const v = Math.min(1, (performance.now() - start.current) / HOLD_MS);
    setP(v);
    if (v >= 1) { stop(); onHeld(); } else timer.current = requestAnimationFrame(tick);
  };
  const down = (e) => { e.preventDefault(); start.current = performance.now(); timer.current = requestAnimationFrame(tick); };
  useEffect(() => stop, []);
  return html`<button class="btn sm danger hold" style=${{ "--p": p }} title=${t("Hold for 2 seconds")}
    onPointerDown=${down} onPointerUp=${stop} onPointerLeave=${stop} onPointerCancel=${stop}
    onKeyDown=${(e) => (e.key === " " || e.key === "Enter") && !timer.current && down(e)} onKeyUp=${stop}>${children}</button>`;
}

export function ControlBar({ p }) {
  if (!S.me || !p) return null;
  if (p.state === "offline") {
    // Klipper off (emergency stop, error), Moonraker reachable: only the way back
    if (!p.moonraker_connected || p.klippy_ready) return null;
    // Rinkhals blocks reloading (GoKlipper would hang): only switching the printer off and on helps
    if (p.can_restart === false) return html`<div class="ctl row wrap"><span class="small muted grow">${t("The printer is not ready – switch it off and on.")}</span></div>`;
    const restart = () => openDialog("confirm", {
      title: t("Reload Klipper?"), ok: t("Reload"), back: t("Back"),
      text: t("Klipper is not ready (emergency stop or error). Reloading takes a few seconds; the axes must be homed again afterwards."),
      action: () => send("/api/print/firmware_restart", { confirm: true }, t("Klipper is reloading")),
    });
    return html`<div class="ctl row wrap"><span class="small muted grow">${t("Klipper is not ready.")}</span>
      <button class="btn sm acc" onClick=${guard(restart)}><${Icon} name="play" small />${t("Reload Klipper")}</button></div>`;
  }
  const printing = p.state === "printing", paused = p.state === "paused";
  const pct = p.progress != null ? ` · ${Math.round(p.progress * 100)} %` : "";
  const cancel = () => openDialog("confirm", {
    title: t("Cancel the print?"), ok: t("Cancel print"), back: t("Back"), danger: true,
    text: t("{file}{pct}. A cancelled print cannot be resumed.", { file: fileName(p.file) || t("Running print"), pct }),
    action: () => send("/api/print/cancel", { confirm: true }, t("Print cancelled")),
  });
  const estop = () => openDialog("confirm", {
    title: t("Trigger the emergency stop?"), ok: t("Emergency stop"), back: t("Back"), danger: true,
    text: p.can_restart === false ? t("Stops all motors and heaters at once. Afterwards switch the printer off and on.")
      : t("Stops all motors and heaters at once. Reload Klipper afterwards (the button appears here)."),
    action: () => send("/api/print/emergency_stop", { confirm: true }, t("Emergency stop triggered")),
  });
  return html`<div class="ctl row wrap">
    ${printing && html`<button class="btn sm" onClick=${guard(() => send("/api/print/pause", {}, t("Paused")).catch(() => {}))}><${Icon} name="pause" small />${t("Pause")}</button>`}
    ${paused && html`<button class="btn sm acc" onClick=${guard(() => send("/api/print/resume", {}, t("Continuing")).catch(() => {}))}><${Icon} name="play" small />${t("Continue")}</button>`}
    ${(printing || paused) && html`<button class="btn sm" onClick=${guard(cancel)}><${Icon} name="stop" small />${t("Cancel")}</button>`}
    <button class="btn sm" onClick=${guard(() => openDialog("tune"))}><${Icon} name="sliders" small />${t("Tune")}</button>
    <span class="grow"></span>
    <${HoldButton} onHeld=${estop}><${Icon} name="warn" small />${t("Emergency stop")}</${HoldButton}>
  </div>`;
}

// ------------------------------------------------------------ tuning
const pctOf = (v) => (v == null ? null : Math.round(v * 100));

function Slider({ label, value, setValue, min, max, step = 1, unit = "%", presets = [] }) {
  return html`<div class="tune-row">
    <div class="row"><span class="grow">${label}</span><b class="m">${value}${unit}</b></div>
    <input type="range" min=${min} max=${max} step=${step} value=${value} aria-label=${label} onInput=${(e) => setValue(Number(e.target.value))} />
    ${presets.length > 0 && html`<div class="row wrap" style="gap:6px">${presets.map((v) => html`<button class=${cls("chip", value === v && "on")} onClick=${() => setValue(v)}>${v}${unit}</button>`)}</div>`}
  </div>`;
}

export function TuneDialog() {
  const p = S.st?.printer || {};
  const fans = Object.fromEntries((p.fans || []).map((f) => [f.key, f]));
  const init = {
    speed: pctOf(p.speed_factor) ?? 100, flow: pctOf(p.flow_factor) ?? 100,
    part: pctOf(fans.part?.speed) ?? 0, box: pctOf(fans.box?.speed) ?? 0, filter: pctOf(fans.filter?.speed) ?? 0,
    nozzle: String(Math.round(p.nozzle?.target ?? 0)), bed: String(Math.round(p.bed?.target ?? 0)),
  };
  const [v, setV] = useState(init);
  const [warn, setWarn] = useState(null);
  const upd = (k) => (x) => { setV({ ...v, [k]: x }); setWarn(null); };
  const body = {};
  if (v.speed !== init.speed) body.speed = v.speed;
  if (v.flow !== init.flow) body.flow = v.flow;
  const fanBody = {};
  for (const k of ["part", "box", "filter"]) if (fans[k] && v[k] !== init[k]) fanBody[k] = v[k];
  if (Object.keys(fanBody).length) body.fans = fanBody;
  const n = Number(v.nozzle), b = Number(v.bed);
  const badTemp = !Number.isFinite(n) || n < 0 || n > 300 || !Number.isFinite(b) || b < 0 || b > 110;
  if (!badTemp && v.nozzle !== init.nozzle) body.nozzle = n;
  if (!badTemp && v.bed !== init.bed) body.bed = b;
  const empty = !Object.keys(body).length;

  const apply = async () => {
    try {
      await send("/api/print/tune", { ...body, confirm: !!warn }, t("Applied"));
      closeDialog();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setWarn(e.message);
    }
  };
  const temp = (k, label, max) => html`<label class="tune-temp"><span>${label} <span class="muted small">${t("is {t} °C", { t: Math.round(p[k]?.temp ?? 0) })}</span></span>
    <span class="row" style="gap:6px"><input class="inp m" inputmode="numeric" value=${v[k]} aria-label=${t("{label} target", { label })} onInput=${(e) => upd(k)(e.target.value.replace(/[^0-9]/g, ""))} />
    <span class="muted">°C</span><button class="chip" onClick=${() => upd(k)("0")}>${t("off")}</button></span>
    <span class="small muted">${t("0 to {max} °C", { max })}</span></label>`;

  return html`<${Dialog} title=${t("Tune")} footer=${html`<button class="btn ghost" onClick=${closeDialog}>${t("Close")}</button>
      <button class=${cls("btn", warn ? "danger" : "acc")} disabled=${empty || badTemp} onClick=${apply}>${warn ? t("Send anyway") : t("Apply")}</button>`}>
    <div class="col" style="gap:16px">
      <${Slider} label=${t("Speed")} value=${v.speed} setValue=${upd("speed")} min=${50} max=${200} step=${5} presets=${[50, 100, 150]} />
      <${Slider} label=${t("Flow")} value=${v.flow} setValue=${upd("flow")} min=${90} max=${110} presets=${[95, 100, 105]} />
      ${fans.part && html`<${Slider} label=${t("Part cooling fan")} value=${v.part} setValue=${upd("part")} min=${0} max=${100} step=${5} />`}
      ${fans.box && html`<${Slider} label=${t("Enclosure fan")} value=${v.box} setValue=${upd("box")} min=${0} max=${100} step=${5} />`}
      ${fans.filter && html`<${Slider} label=${t("Air filter")} value=${v.filter} setValue=${upd("filter")} min=${0} max=${100} step=${5} />`}
      <div class="fgrid">${temp("nozzle", t("Nozzle"), 300)}${temp("bed", t("Bed"), 110)}</div>
      ${warn && html`<div class="note bad">${t("{warning} – press again to send it anyway.", { warning: warn })}</div>`}
      <div class="small muted">${t("Only what you change is sent. Speed and flow apply at once, also in the middle of a print; the slicer may set fans and temperatures again at layer changes.")}</div>
    </div></${Dialog}>`;
}
