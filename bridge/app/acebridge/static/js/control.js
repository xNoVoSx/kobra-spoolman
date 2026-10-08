// Drucksteuerung: Pause/Weiter, Abbrechen (Rueckfrage), Not-Aus (2 s halten + Rueckfrage), Nachjustieren.
// Alles geht ueber die Bridge (POST /api/print/...) und steht mit Absender im Terminal.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { ApiError, post } from "./api.js";
import { Dialog } from "./components.js";
import { Icon } from "./icons.js";
import { S, closeDialog, guard, loadState, openDialog, toast } from "./store.js";
import { cls, fileName } from "./util.js";

const HOLD_MS = 2000;

/** Aktion senden; Fehler als Meldung, dann weiterwerfen (damit Dialoge offen bleiben). */
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

/** Knopf, der erst nach HOLD_MS gedrueckt halten ausloest (Not-Aus). */
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
  return html`<button class="btn sm danger hold" style=${{ "--p": p }} title="2 Sekunden gedrückt halten"
    onPointerDown=${down} onPointerUp=${stop} onPointerLeave=${stop} onPointerCancel=${stop}
    onKeyDown=${(e) => (e.key === " " || e.key === "Enter") && !timer.current && down(e)} onKeyUp=${stop}>${children}</button>`;
}

export function ControlBar({ p }) {
  if (!S.me || !p) return null;
  if (p.state === "offline") {
    // Klipper aus (Not-Aus, Fehler), Moonraker aber erreichbar: nur der Weg zurueck
    if (!p.moonraker_connected || p.klippy_ready) return null;
    const restart = () => openDialog("confirm", {
      title: "Klipper neu laden?", ok: "Neu laden", back: "Zurück",
      text: "Klipper ist nicht bereit (Not-Aus oder Fehler). Neu laden dauert einige Sekunden; die Achsen müssen danach neu referenziert werden.",
      action: () => send("/api/print/firmware_restart", { confirm: true }, "Klipper wird neu geladen"),
    });
    return html`<div class="ctl row wrap"><span class="small muted grow">Klipper ist nicht bereit.</span>
      <button class="btn sm acc" onClick=${guard(restart)}><${Icon} name="play" small />Klipper neu laden</button></div>`;
  }
  const printing = p.state === "printing", paused = p.state === "paused";
  const pct = p.progress != null ? ` · ${Math.round(p.progress * 100)} %` : "";
  const cancel = () => openDialog("confirm", {
    title: "Druck abbrechen?", ok: "Druck abbrechen", back: "Zurück", danger: true,
    text: `${fileName(p.file) || "Laufender Druck"}${pct}. Ein abgebrochener Druck lässt sich nicht fortsetzen.`,
    action: () => send("/api/print/cancel", { confirm: true }, "Druck abgebrochen"),
  });
  const estop = () => openDialog("confirm", {
    title: "Not-Aus auslösen?", ok: "Not-Aus", back: "Zurück", danger: true,
    text: "Stoppt sofort alle Motoren und Heizungen. Danach Klipper neu laden (Knopf erscheint hier).",
    action: () => send("/api/print/emergency_stop", { confirm: true }, "Not-Aus ausgelöst"),
  });
  return html`<div class="ctl row wrap">
    ${printing && html`<button class="btn sm" onClick=${guard(() => send("/api/print/pause", {}, "Pausiert").catch(() => {}))}><${Icon} name="pause" small />Pause</button>`}
    ${paused && html`<button class="btn sm acc" onClick=${guard(() => send("/api/print/resume", {}, "Läuft weiter").catch(() => {}))}><${Icon} name="play" small />Weiter</button>`}
    ${(printing || paused) && html`<button class="btn sm" onClick=${guard(cancel)}><${Icon} name="stop" small />Abbrechen</button>`}
    <button class="btn sm" onClick=${guard(() => openDialog("tune"))}><${Icon} name="sliders" small />Nachjustieren</button>
    <span class="grow"></span>
    <${HoldButton} onHeld=${estop}><${Icon} name="warn" small />Not-Aus</${HoldButton}>
  </div>`;
}

// ------------------------------------------------------------ Nachjustieren
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
      await send("/api/print/tune", { ...body, confirm: !!warn }, "Übernommen");
      closeDialog();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setWarn(e.message);
    }
  };
  const temp = (k, label, max) => html`<label class="tune-temp"><span>${label} <span class="muted small">ist ${Math.round(p[k]?.temp ?? 0)} °C</span></span>
    <span class="row" style="gap:6px"><input class="inp m" inputmode="numeric" value=${v[k]} aria-label=${label + " Soll"} onInput=${(e) => upd(k)(e.target.value.replace(/[^0-9]/g, ""))} />
    <span class="muted">°C</span><button class="chip" onClick=${() => upd(k)("0")}>aus</button></span>
    <span class="small muted">0 bis ${max} °C</span></label>`;

  return html`<${Dialog} title="Nachjustieren" footer=${html`<button class="btn ghost" onClick=${closeDialog}>Schließen</button>
      <button class=${cls("btn", warn ? "danger" : "acc")} disabled=${empty || badTemp} onClick=${apply}>${warn ? "Trotzdem senden" : "Übernehmen"}</button>`}>
    <div class="col" style="gap:16px">
      <${Slider} label="Tempo" value=${v.speed} setValue=${upd("speed")} min=${50} max=${200} step=${5} presets=${[50, 100, 150]} />
      <${Slider} label="Fluss" value=${v.flow} setValue=${upd("flow")} min=${90} max=${110} presets=${[95, 100, 105]} />
      ${fans.part && html`<${Slider} label="Bauteillüfter" value=${v.part} setValue=${upd("part")} min=${0} max=${100} step=${5} />`}
      ${fans.box && html`<${Slider} label="Gehäuselüfter" value=${v.box} setValue=${upd("box")} min=${0} max=${100} step=${5} />`}
      ${fans.filter && html`<${Slider} label="Luftfilter" value=${v.filter} setValue=${upd("filter")} min=${0} max=${100} step=${5} />`}
      <div class="fgrid">${temp("nozzle", "Düse", 300)}${temp("bed", "Bett", 110)}</div>
      ${warn && html`<div class="note bad">${warn} – noch einmal drücken, um es trotzdem zu senden.</div>`}
      <div class="small muted">Gesendet wird nur, was du änderst. Tempo und Fluss gelten sofort, auch mitten im Druck; der Slicer setzt Lüfter und Temperaturen bei Schichtwechseln evtl. wieder.</div>
    </div></${Dialog}>`;
}
