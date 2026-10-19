// Printer display (800x480, kiosk browser on the Klipper Pi, via VNC on the original display of the Kobra S1).
// Start (status, slots, dryer), print (opens by itself at print start: preview, progress, times, temperatures,
// controls), switches (all modules, stored in the printer), print interrupted (after a power loss).
// Reads without a key; to switch things, pair once (6-digit code from web/app, "Add device").

import { html, render, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get, post } from "./api.js";
import { locale, t } from "./i18n.js";
import { duration, fileName, finishAt, fixed, hex, nozzleMm, num, printerLook } from "./util.js";

const POLL_MS = 2000;
const PAGES = [["start", "home", t("Home")], ["print", "print", t("Print")], ["files", "files", t("Files")],
  ["control", "control", t("Control")], ["switch", "switch", t("Switches")], ["system", "info", t("System")]];
const PAGE_SIZE = 5;
const UI_TAG = document.querySelector('meta[name="ui-tag"]')?.content || null;   // new bridge -> reload
const PRINTING = new Set(["printing", "paused"]);

// ------------------------------------------------------------ icons (lines, as in the design)
const ICONS = {
  home: html`<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>`,
  print: html`<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 17v4h10v-4"/>`,
  switch: html`<rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="16" cy="12" r="3"/>`,
  light: html`<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>`,
  power: html`<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>`,
  control: html`<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>`,
  files: html`<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>`,
  info: html`<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>`,
};
const Icon = ({ name, size = 28 }) => html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

/** Short duration for the tiles: 1:31 (hours:minutes), under an hour 0:42. */
const hm = (s) => (s == null ? "–" : (([h, m]) => `${h}:${String(m).padStart(2, "0")}`)([Math.floor(Math.round(s / 60) / 60), Math.round(s / 60) % 60]));
const pct = (v) => Math.round(100 * (v || 0));
const deg = (v) => (v == null ? "–" : Math.round(v));
const clock = () => new Date().toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });

// ------------------------------------------------------------ App
function Display() {
  const [st, setSt] = useState(null);
  const [sw, setSw] = useState(null);
  const [down, setDown] = useState(false);
  const [page, setPage] = useState("start");
  const [dlg, setDlg] = useState(null);           // {kind: "confirm"|"pair"|"tune", ...}
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(clock());
  const prevState = useRef(null);

  async function load() {
    try {
      const [s, w] = await Promise.all([get("/api/app/state"), get("/api/switches")]);
      if (UI_TAG && s.ui && s.ui !== UI_TAG) { location.reload(); return; }
      setSt(s); setSw(w); setDown(false);
      const ps = s.printer?.state;
      if (ps === "printing" && prevState.current && !PRINTING.has(prevState.current)) setPage("print");
      prevState.current = ps;
    } catch { setDown(true); }
  }
  useEffect(() => {
    load();
    const a = setInterval(load, POLL_MS), b = setInterval(() => setNow(clock()), 10000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);

  /** Writing call: without a key pair first, then repeat exactly this call. */
  async function act(fn) {
    if (!auth.key) { setDlg({ kind: "pair", then: fn }); return; }
    setBusy(true);
    try { await fn(); await load(); }
    catch (e) {
      if (e.status === 401 || e.status === 403) { auth.clear(); setDlg({ kind: "pair", then: fn }); }
      else if (e.status === 409 && fn.retry) setDlg({ kind: "confirm", title: t("Really?"), text: e.message, ok: t("Yes"), action: fn.retry });
      else setDlg({ kind: "info", title: t("Not carried out"), text: e.message });
    } finally { setBusy(false); }
  }
  const confirm = (o) => setDlg({ kind: "confirm", ...o });
  const flip = (key, value) => act(() => post("/api/switch", { key, value }));

  if (down && !st) return html`<div class="disp"><div class="disp-empty">${t("Bridge not reachable …")}</div></div>`;
  if (!st) return html`<div class="disp"><div class="disp-empty">${t("Loading …")}</div></div>`;

  const p = st.printer || {};
  const look = printerLook(p.moonraker_connected === false ? null : p);
  const items = sw?.items || [];
  const light = items.find((i) => i.key === "light");
  const errors = (st.notices?.messages || []).filter((m) => m.level === "error" && m.key !== "resume");
  const ctx = { st, sw, items, busy, act, confirm, flip, setDlg, page, setPage };

  return html`<div class="disp">
    <nav class="disp-rail" aria-label=${t("Sections")}>
      <!-- The top left corner (60x60 px) belongs to the viewer app on the printer: touches there are swallowed for
           "hold 5 s = quit" (fb-vnc-viewer, VIEWER_EXIT_CORNER_PX). So nothing to press there. -->
      <div class="disp-corner" aria-hidden="true"><span class="dot" style=${`background:${look.dot}`}></span></div>
      ${PAGES.map(([k, i, l]) =>
        html`<button type="button" class=${"disp-nav" + (page === k ? " on" : "")} aria-label=${l} onClick=${() => setPage(k)}><${Icon} name=${i} /></button>`)}
    </nav>
    <main class="disp-main">
      <header class="disp-head">
        <h1>${["start", "print"].includes(page) ? (st.printer_name || t("Printer")) : PAGES.find((x) => x[0] === page)[2]}</h1>
        <span class="disp-chip disp-chip-phase" style=${`color:${look.fg};background:${look.bg};border-color:${look.line}`}>${p.phase || look.label}</span>
        ${down && html`<span class="disp-chip" style="color:var(--danger-text);border-color:var(--danger-line)">${t("Bridge gone")}</span>`}
        <div class="grow"></div>
        ${light && html`<button type="button" class=${"disp-hbtn" + (light.on ? " on" : "")} aria-label=${light.on ? t("Light off") : t("Light on")}
          disabled=${!light.sensitive || busy} onClick=${() => flip("light", !light.on)}><${Icon} name="light" /></button>`}
        <span class="disp-clock">${now}</span>
      </header>
      ${st.direct?.active && html`<div class="disp-alert disp-direct"><span class="grow">${t("Direct feed is on")} – ${t("the ACE is passed by.")} ${st.direct.label}</span>
        ${!PRINTING.has(st.printer?.state) && html`<button type="button" class="disp-btn" disabled=${busy}
          onClick=${() => act(() => post("/api/direct", { enable: false }))}>${t("Switch off")}</button>`}</div>`}
      ${!["switch", "system"].includes(page) && errors.slice(0, 1).map((m) => html`<div class="disp-alert">${m.text}</div>`)}
      ${page === "start" && html`<${Start} ...${ctx} />`}
      ${page === "print" && html`<${Print} ...${ctx} />`}
      ${page === "switch" && html`<${Switches} ...${ctx} />`}
      ${page === "control" && html`<${Control} ...${ctx} />`}
      ${page === "files" && html`<${Files} ...${ctx} />`}
      ${page === "system" && html`<${System} ...${ctx} />`}
    </main>
    <${Resume} ...${ctx} />
    ${!st.resume?.pending && !st.resume?.running && st.prompt && html`<${Prompt} ...${ctx} />`}
    ${p.moonraker_connected !== false && p.klippy_ready === false && !dlg && html`<${KlippyDown} ...${ctx} />`}
    ${dlg && html`<${Dialog} dlg=${dlg} close=${() => setDlg(null)} act=${act} st=${st} />`}
  </div>`;
}

// ------------------------------------------------------------ Start
function Start({ st, busy, act, confirm }) {
  const p = st.printer || {}, d = st.dryer || {};
  return html`
    <section class="disp-grid3" aria-label=${t("Temperatures")}>
      <div class="disp-tile"><div class="disp-lbl">${t("Nozzle")}</div><div class="disp-val">${deg(p.nozzle?.temp)}<small> / ${deg(p.nozzle?.target)} °C</small></div></div>
      <div class="disp-tile"><div class="disp-lbl">${t("Bed")}</div><div class="disp-val">${deg(p.bed?.temp)}<small> / ${deg(p.bed?.target)} °C</small></div></div>
      <div class="disp-tile"><div class="disp-lbl">${t("ACE humidity")}</div><div class="disp-val">${d.humidity ?? "–"}<small> %</small></div></div>
    </section>
    <section class="disp-grid4 disp-slots" aria-label=${t("ACE slots")}>${(st.slots || []).map((s) => html`<${Slot} s=${s} />`)}</section>
    ${d.present && html`<section class="disp-tile disp-row" aria-label=${t("Dryer")}>
      <div class="grow"><b>${d.drying ? t("Drying · {temp} °C", { temp: d.target_temp ?? "?" }) : t("Dryer off")}</b>
        <div class="muted">${d.drying ? t("{left} left · {temp} °C in the ACE", { left: duration((d.remaining_min || 0) * 60), temp: d.temp ?? "–" })
          : (d.config?.enabled ? t("Automatic on") : t("Automatic off")) + (d.required?.temp ? " · " + t("at most {temp} °C for the loaded spools", { temp: d.required.temp }) : "")}</div></div>
      ${d.drying
        ? html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => confirm({ title: t("Stop drying?"), ok: t("Stop"),
            action: () => post("/api/dryer/stop") })}>${t("Stop")}</button>`
        : html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => confirm({ title: t("Start drying?"), ok: t("Start"),
            text: d.required?.temp ? t("Temperature and duration from the loaded spools (at most {temp} °C).", { temp: d.required.temp }) : t("Temperature and duration from the loaded spools."),
            action: () => post("/api/dryer/start", {}) })}>${t("Dry …")}</button>`}
    </section>`}`;
}

function Slot({ s }) {
  const sp = s.spool, ace = s.ace || {};
  const color = hex(sp?.color || ace.color);
  const rest = sp?.remaining_weight;
  const low = rest != null && rest < 200;
  const offline = s.live === false && !!sp;      // printer or ACE off: Spoolman's last known assignment
  return html`<div class=${"disp-slot" + (ace.active ? " on" : "") + (offline ? " offline" : "")}>
    <div class="hd"><span>${t("Slot {slot}", { slot: s.slot })}</span>${ace.active && html`<span class="disp-tag">${t("loaded")}</span>`}${offline && html`<span class="disp-tag">${t("offline")}</span>`}</div>
    <div class=${"disp-swatch" + (color ? "" : " empty")} style=${color ? `background:${color}` : ""}></div>
    <div class="name">${sp ? (sp.name || sp.material || t("Spool")) : ace.present ? (ace.material || t("Unknown")) : t("empty")}</div>
    <div class=${"sub" + (low ? " warn" : "")}>${sp ? `${rest != null ? Math.round(rest) + " g" : "–"} · ${low ? t("almost empty") : sp.vendor || ""}` : ace.present ? t("no spool") : ""}</div>
  </div>`;
}

// ------------------------------------------------------------ print
function Print({ st, busy, act, confirm, setDlg }) {
  const p = st.printer || {};
  const [img, setImg] = useState(0);              // 0 thumbnail of the file, 1 bridge image, 2 none
  const file = p.file || "";
  useEffect(() => setImg(0), [file]);
  if (!PRINTING.has(p.state) && !["complete", "cancelled", "error"].includes(p.state)) {
    return html`<div class="disp-empty">${t("No print. Start one under “Files”, in Orca or Mainsail –")}<br/>${t("the print view then opens by itself.")}</div>`;
  }
  if (!PRINTING.has(p.state)) return html`<${Done} st=${st} busy=${busy} setDlg=${setDlg} />`;
  const src = img === 0 ? `/api/print/thumbnail.png?f=${encodeURIComponent(file)}` : `/api/print/preview.png?f=${encodeURIComponent(file)}`;
  const active = p.active_slot;
  const uses = st.uses || [];
  const pa = st.pa?.slots?.find((s) => s.slot === active);
  const clog = st.clog?.enabled ? st.clog.last_ratio : null;
  const paused = p.state === "paused";
  const running = PRINTING.has(p.state);
  return html`<div class="disp-print">
    <section class="disp-thumb" aria-label=${t("Preview")}>
      <div class="img">${img < 2 ? html`<img src=${src} alt=${t("Preview image")} onError=${() => setImg(img + 1)} />`
        : html`<span class="muted">${t("No preview image")}</span>`}</div>
      <div class="file">${fileName(file)}</div>
      ${uses.length > 0 && html`<div class="disp-uses"><span class="disp-lbl">${t("Used")}</span>
        ${uses.map((u) => html`<span class=${"disp-dot" + (u.slot === active ? " on" : "")} style=${`background:${hex(u.color) || "var(--surface2)"}`} title=${t("Slot {slot}", { slot: u.slot })}></span>`)}
        <span class="disp-note m">${t("Slot {slot}", { slot: uses.map((u) => u.slot).join(" · ") })}</span></div>`}
    </section>
    <div class="disp-pcol">
      <div class="disp-note">${p.changing_filament && !p.phase ? t("Changing filament …") : active ? t("Slot {slot}", { slot: active }) : ""}${active && st.slots?.[active - 1]?.spool ? " · " + st.slots[active - 1].spool.name : ""}</div>
      <div class="disp-big"><span class="pct">${pct(p.progress)} %</span>${p.layers ? html`<span class="lay">${t("Layer {layer} / {layers}", { layer: p.layer ?? "?", layers: p.layers })}</span>` : ""}</div>
      <div class="disp-bar"><div style=${`width:${pct(p.progress)}%`}></div></div>
      <div class="disp-grid3" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Elapsed")}</div><div class="disp-val">${hm(p.print_duration_s)}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Remaining")}</div><div class="disp-val">${running ? hm(p.eta_s) : "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Finish")}</div><div class="disp-val">${running ? finishAt(p.eta_s).replace("~", "") : "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Nozzle")}</div><div class="disp-val">${deg(p.nozzle?.temp)}<small> / ${deg(p.nozzle?.target)}</small></div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Bed")}</div><div class="disp-val">${deg(p.bed?.temp)}<small> / ${deg(p.bed?.target)}</small></div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Speed · flow")}</div><div class="disp-val">${pct(p.speed_factor)}<small> · ${pct(p.flow_factor)} %</small></div></div>
      </div>
      <div class="disp-note">${[pa?.k_ref != null ? `Auto-PA K ${fixed(pa.k_ref, 3)}` : null,
        clog != null ? t("Filament flowing ({pct} %)", { pct: pct(clog) }) : null].filter(Boolean).join(" · ")}</div>
      <div class="grow" style="flex:1"></div>
      ${running && html`<div class="disp-btns">
        ${paused
          ? html`<button type="button" class="disp-btn acc" disabled=${busy} onClick=${() => act(() => post("/api/print/resume", {}))}>${t("Resume")}</button>
            <button type="button" class="disp-btn danger" disabled=${busy} onClick=${() => confirm({ title: t("Cancel the print?"), ok: t("Cancel print"), danger: true,
              text: t("{file} is cancelled. This cannot be undone.", { file: fileName(file) }),
              action: () => post("/api/print/cancel", { confirm: true }) })}>${t("Cancel print")}</button>`
          : html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => act(() => post("/api/print/pause", {}))}>${t("Pause")}</button>
            <button type="button" class="disp-btn" disabled=${busy} onClick=${() => setDlg({ kind: "tune" })}>${t("Tune")}</button>`}
        <${EStop} confirm=${confirm} />
      </div>`}
    </div>
  </div>`;
}

// ------------------------------------------------------------ control
/** Call that is repeated with confirm: true after confirmation when the bridge asks back (409 + confirm). */
function withConfirm(path, body) {
  const fn = () => post(path, body);
  fn.retry = () => post(path, { ...body, confirm: true });
  return fn;
}

function Control(ctx) {
  const [tab, setTab] = useState("temp");
  const [m, setM] = useState(null);
  async function loadM() { try { setM(await get("/api/machine")); } catch { /* display stays */ } }
  useEffect(() => { loadM(); const timer = setInterval(loadM, POLL_MS); return () => clearInterval(timer); }, []);
  const act = (fn) => ctx.act(async () => { await fn(); await loadM(); });
  const hot = ctx.st.nozzle?.available && ctx.st.nozzle.enabled;
  const tabs = [["temp", t("Temperature")], ["move", t("Move")], ["fil", t("Filament")], ...(hot ? [["hotend", t("Hotend")]] : []),
    ["more", t("More")]];
  const sub = { ...ctx, m, act };
  return html`
    <div class="disp-tabs" role="tablist" aria-label=${t("Control")}>
      ${tabs.map(([k, l]) => html`<button type="button" role="tab" aria-selected=${tab === k} class=${tab === k ? "on" : ""}
        onClick=${() => setTab(k)}>${l}</button>`)}
    </div>
    ${m?.running && html`<div class="disp-alert warn">${t("Running: {what} …", { what: m.running })}</div>`}
    ${m?.error && !m.running && html`<div class="disp-alert">${m.error}</div>`}
    ${tab === "temp" && html`<${Temps} ...${sub} />`}
    ${tab === "move" && html`<${Move} ...${sub} />`}
    ${tab === "fil" && html`<${Filament} ...${sub} />`}
    ${tab === "hotend" && hot && html`<${Hotend} ...${sub} />`}
    ${tab === "more" && html`<${More} ...${sub} />`}`;
}

// swappable hotends (bridge nozzle.py, Klipper kobra_nozzle): which hotend is in, PID per hotend
function Hotend({ st, m, busy, act, confirm }) {
  const n = st.nozzle;
  const ok = m?.move_allowed && !busy && !m?.running && !n.measuring;
  return html`
    <div class="disp-lbl">${t("Hotend in use – Klipper takes its PID and nozzle at once")}</div>
    <div class="disp-grid4">${n.hotends.map((h) => html`<button type="button" class=${"disp-slot" + (h.id === n.active ? " on" : "")}
        style="min-height:104px" disabled=${!ok && h.id !== n.active}
        onClick=${() => h.id !== n.active && act(() => post("/api/nozzle", { hotend: h.id }))}>
      <div class="hd"><span>${nozzleMm(h.diameter)}</span>${h.id === n.active && html`<span class="disp-tag">${t("in use")}</span>`}</div>
      <div class="name">${h.name}</div>
      <div class="disp-note" style="margin:0">${h.pid ? t("PID measured") : h.default ? t("PID from the Klipper configuration") : t("PID not measured")}</div></button>`)}</div>
    ${n.warning && html`<div class="disp-alert warn">${n.warning}</div>`}
    ${n.error && html`<div class="disp-alert">${t("PID measurement failed: {error}", { error: n.error })}</div>`}
    <div class="disp-tile"><div class="disp-lbl">${t("PID")} · ${n.pid_measured ? t("measured for this hotend") : t("from the Klipper configuration")}</div>
      <div class="disp-val" style="font-size:20px">${n.measuring ? t("measuring PID …") : n.pid.length ? n.pid.map((v) => fixed(v, 3)).join(" / ") : "–"}</div></div>
    <div class="disp-btns">
      <button type="button" class="disp-btn" disabled=${!ok}
        onClick=${() => confirm({ title: t("Measure the PID of {name}?", { name: n.name }),
          text: t("The printer homes if needed, moves over the waste chute and heats the nozzle to {temp} °C several times (a few minutes). Stay near the printer. The values apply at once and are saved for this hotend.", { temp: 250 }),
          ok: t("Measure"), action: () => post("/api/nozzle/pid", {}) })}>${n.pid_measured ? t("Measure again") : t("Measure PID")}</button>
    </div>
    ${!m?.move_allowed && html`<div class="disp-note">${t("Locked while printing.")}</div>`}`;
}

function Temps({ st, busy, act, setDlg }) {
  const p = st.printer || {};
  const tune = (body) => act(withConfirm("/api/print/tune", body));
  // quick choice from the loaded spools (Spoolman), every combination once
  const seen = new Set();
  const presets = (st.slots || []).map((s) => s.spool).filter((sp) => sp?.nozzle_temp)
    .filter((sp) => { const k = `${sp.nozzle_temp}/${sp.bed_temp}`; if (seen.has(k)) return false; seen.add(k); return true; });
  const ask = (label, key, cur, max) => setDlg({ kind: "number", title: label, value: cur || 0, max,
    action: (v) => tune({ [key]: v }) });
  const card = (label, key, h, max) => html`<div class="disp-tile disp-temp">
    <button type="button" class="disp-tempbtn" disabled=${busy} onClick=${() => ask(t("{label}: target (°C)", { label }), key, h?.target, max)}>
      <div class="disp-lbl">${t("{label} · tap to set", { label })}</div>
      <div class="disp-val" style="font-size:34px">${deg(h?.temp)}<small> / ${deg(h?.target)} °C</small></div></button>
    <button type="button" class="disp-btn danger disp-off" disabled=${busy || !h?.target} aria-label=${t("{label} off", { label })}
      onClick=${() => tune({ [key]: 0 })}>${t("Off")}</button></div>`;
  return html`
    <div class="disp-grid2">${card(t("Nozzle"), "nozzle", p.nozzle, 300)}${card(t("Bed"), "bed", p.bed, 120)}</div>
    <div class="disp-lbl">${t("From the loaded spools")}</div>
    <div class="disp-presets">
      ${presets.map((sp) => html`<button type="button" class="disp-btn" disabled=${busy}
        onClick=${() => tune({ nozzle: sp.nozzle_temp, bed: sp.bed_temp || 0 })}>
        <span class="disp-dot" style=${`width:16px;height:16px;display:inline-block;vertical-align:-2px;margin-right:8px;background:${hex(sp.color) || "var(--surface2)"}`}></span>
        ${sp.material} ${sp.nozzle_temp}/${sp.bed_temp ?? "–"}</button>`)}
      <button type="button" class="disp-btn danger" disabled=${busy} onClick=${() => tune({ nozzle: 0, bed: 0 })}>${t("All off")}</button>
    </div>`;
}

function Move({ m, busy, act }) {
  const [step, setStep] = useState(10);
  const ok = m?.move_allowed && !busy && !m?.running;
  const jog = (axis, sign) => act(() => post("/api/machine/jog", { axis, dist: sign * (axis === "z" ? Math.min(step, 10) : step) }));
  const pos = m?.position;
  const homed = m?.homed || "";
  const key = (label, axis, sign, extra = "") => html`<button type="button" class=${"disp-btn disp-jog " + extra}
    disabled=${!ok || !homed.includes(axis)} aria-label=${label} onClick=${() => jog(axis, sign)}>${label}</button>`;
  return html`<div class="disp-move">
    <div class="disp-pad">
      <span></span>${key("Y+", "y", 1)}<span></span>
      ${key("X−", "x", -1)}<button type="button" class="disp-btn disp-jog" disabled=${!ok} onClick=${() => act(() => post("/api/machine/home", { axes: "xy" }))}>⌂ XY</button>${key("X+", "x", 1)}
      <span></span>${key("Y−", "y", -1)}<span></span>
    </div>
    <div class="disp-zcol">${key("Z+", "z", 1)}<button type="button" class="disp-btn disp-jog" disabled=${!ok}
      onClick=${() => act(() => post("/api/machine/home", { axes: "z" }))}>⌂ Z</button>${key("Z−", "z", -1)}</div>
    <div class="disp-mside">
      <div class="disp-tile"><div class="disp-lbl">${t("Position")}${homed.length < 3 ? " · " + t("not all homed") : ""}</div>
        <div class="disp-val" style="font-size:18px">${pos ? `X ${pos[0]}  Y ${pos[1]}  Z ${pos[2]}` : "–"}</div></div>
      <div class="disp-lbl">${t("Step (mm)")}</div>
      <div class="disp-steps">${(m?.steps || [0.1, 1, 10, 50]).map((s) => html`<button type="button"
        class=${"disp-btn" + (s === step ? " acc" : "")} onClick=${() => setStep(s)}>${num(s, 1)}</button>`)}</div>
      <div class="disp-btns">
        <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/home", { axes: "all" }))}>${t("Home all")}</button>
        <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/motors_off", {}))}>${t("Motors off")}</button>
      </div>
      ${!m?.move_allowed && html`<div class="disp-note">${t("Locked while printing.")}</div>`}
    </div>
  </div>`;
}

function Filament({ st, m, busy, act }) {
  const p = st.printer || {};
  const ok = m?.move_allowed && !busy && !m?.running;
  const okE = m?.extrude_allowed && !busy && !m?.running;
  const cold = (p.nozzle?.temp ?? 0) < 170;
  return html`
    <div class="disp-lbl">${t("Load a slot (changes via the ACE, heats by itself)")}</div>
    <div class="disp-grid4">${(st.slots || []).map((s) => {
      const sp = s.spool, color = hex(sp?.color || s.ace?.color);
      return html`<button type="button" class=${"disp-slot" + (s.ace?.active ? " on" : "")} style="min-height:118px"
        disabled=${!ok || !s.ace?.present} onClick=${() => act(() => post("/api/machine/load", { slot: s.slot }))}>
        <div class="hd"><span>${t("Slot {slot}", { slot: s.slot })}</span>${s.ace?.active && html`<span class="disp-tag">${t("loaded")}</span>`}</div>
        <div class=${"disp-swatch" + (color ? "" : " empty")} style=${(color ? `background:${color};` : "") + "width:36px;height:36px"}></div>
        <div class="name">${sp?.name || (s.ace?.present ? s.ace.material : t("empty"))}</div></button>`;
    })}</div>
    <div class="disp-btns">
      <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/unload", {}))}>${t("Unload")}</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: -10 }))}>${t("{mm} mm back", { mm: 10 })}</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: 10 }))}>${t("{mm} mm forward", { mm: 10 })}</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: 50 }))}>${t("{mm} mm forward", { mm: 50 })}</button>
    </div>
    ${cold && html`<div class="disp-note">${t("Extruding only from 170 °C nozzle (tab Temperature).")}</div>`}`;
}

function More({ st, m, busy, act, confirm }) {
  const p = st.printer || {};
  const ok = m?.move_allowed && !busy && !m?.running;
  const fan = (f) => html`<div class="disp-tile disp-fan"><b>${f.name}</b><span class="disp-val" style="font-size:22px">${pct(f.speed)}<small> %</small></span>
    <div class="disp-fanbtns">${[0, 50, 100].map((v) => html`<button type="button" class="disp-btn" disabled=${busy}
      onClick=${() => act(() => post("/api/print/tune", { fans: { [f.key]: v } }))}>${v}</button>`)}</div></div>`;
  return html`
    <div class="disp-lbl">${t("Fans (%)")}</div>
    <div class="disp-grid3">${(p.fans || []).map(fan)}</div>
    <div style="flex:1"></div>
    <div class="disp-btns">
      ${(m?.macros || []).map((mc) => html`<button type="button" class="disp-btn"
        disabled=${!ok} onClick=${() => confirm({ title: mc.label + "?", text: mc.confirm, ok: t("Start"),
          action: () => post("/api/machine/macro", { key: mc.key, confirm: true }) })}>${mc.label}</button>`)}
      <button type="button" class="disp-btn" disabled=${busy || p.state === "printing"}
        onClick=${() => confirm({ title: t("Reload Klipper?"), text: t("Takes a few seconds; the axes must be homed again afterwards."),
          ok: t("Reload"), action: () => post("/api/print/firmware_restart", { confirm: true }) })}>${t("Reload Klipper")}</button>
      <${EStop} confirm=${confirm} />
    </div>`;
}

// ------------------------------------------------------------ switches
const GROUP_KI = "watch";

function Switches({ st, sw, items, busy, act, flip }) {
  const groups = sw?.groups || [];
  const [tab, setTab] = useState(groups[0]?.key || "print");
  const v = st.vision;
  const printing = PRINTING.has(st.printer?.state);
  const list = items.filter((i) => i.group === tab);
  const toggles = list.filter((i) => i.kind === "switch");
  const choices = list.filter((i) => i.kind === "choice");
  return html`
    <div class="disp-tabs" role="tablist" aria-label=${t("Group")}>
      ${groups.map((g) => html`<button type="button" role="tab" aria-selected=${tab === g.key} class=${tab === g.key ? "on" : ""}
        onClick=${() => setTab(g.key)}>${g.title}</button>`)}
    </div>
    <div class="disp-scroll">
      <div class="disp-toggles">
        ${toggles.map((i) => html`<${Toggle} title=${i.title} hint=${i.hint} on=${i.on} disabled=${!i.sensitive || busy}
          onClick=${() => flip(i.key, !i.on)} />`)}
        ${tab === GROUP_KI && v?.configured && html`<${Toggle} title=${t("AI monitoring")} hint=${t("Failure detection with the camera")}
          on=${v.enabled} disabled=${busy} onClick=${() => act(() => post("/api/vision/settings", { enabled: !v.enabled }))} />`}
        ${tab === GROUP_KI && v?.configured && v.enabled && printing && html`<${Toggle} title=${t("Don't watch this print")}
          hint=${t("AI quiet until the next print")} on=${v.muted} disabled=${busy}
          onClick=${() => act(() => post("/api/vision/mute", { on: !v.muted }))} />`}
      </div>
      ${choices.map((c) => html`<div class="disp-choice"><b>${c.title}</b><div class="opts">
        ${c.options.map((o) => html`<button type="button" class=${o.value === c.current ? "on" : ""} disabled=${!c.sensitive || busy}
          aria-pressed=${o.value === c.current} onClick=${() => o.value !== c.current && flip(c.key, o.value)}>${o.label}</button>`)}
      </div></div>`)}
      ${tab === "print" && st.pa?.slots?.length > 0 && html`<div class="disp-tile disp-grid4" aria-label=${t("PA per slot")}>
        ${st.pa.slots.map((s) => html`<div class="disp-row" style="gap:8px">
          <span class="disp-dot" style=${`width:18px;height:18px;background:${hex(st.slots?.[s.slot - 1]?.spool?.color) || "var(--surface2)"}`}></span>
          <span class="disp-note">${s.state === "table" || s.k_ref != null ? `K ${fixed(s.k_ref ?? 0, 3)}`
            : s.state === "needed" ? t("measures at the print") : s.state === "failed" ? t("failed") : "–"}</span></div>`)}
      </div>`}
      ${items.length === 0 && html`<div class="disp-empty">${t("Klipper is not ready")}</div>`}
      <div class="disp-note">${t("All switches also apply in web, app and Mainsail – stored in the printer.")}</div>
    </div>`;
}

/** Emergency stop: always usable (even while something runs), with a confirmation. */
function EStop({ confirm }) {
  return html`<button type="button" class="disp-btn danger" onClick=${() => confirm({ title: t("Emergency stop?"), ok: t("Emergency stop"), danger: true,
    text: t("Everything stops at once: motors, heaters, print. The print is lost; reload Klipper afterwards."),
    action: () => post("/api/print/emergency_stop", { confirm: true }) })}>${t("Emergency stop …")}</button>`;
}

const Toggle = ({ title, hint, on, disabled, onClick }) => html`<button type="button" class="disp-toggle" aria-pressed=${!!on}
  disabled=${disabled} onClick=${onClick}><span class="t"><b>${title}</b>${hint && html`<span>${hint}</span>`}</span>
  <span class=${"disp-knob" + (on ? " on" : "")} aria-hidden="true"></span></button>`;

// ------------------------------------------------------------ print interrupted (power loss)
function Resume({ st, busy, confirm }) {
  const r = st.resume;
  if (!r || !(r.pending || r.running)) return null;
  const p = r.pending || {};
  const file = p.file || "";
  return html`<div class="disp-over" role="alertdialog" aria-label=${t("Print interrupted")}>
    <section class="disp-dialog danger" style="height:100%">
      <div class="disp-split">
        <div class="disp-thumb" style="width:210px">
          <div class="img" style="height:210px"><img src=${`api/print/thumbnail.png?f=${encodeURIComponent(file)}`} alt=${t("Preview image")}
            onError=${(e) => { e.target.style.display = "none"; }} /></div>
          <div class="file">${fileName(file)}</div>
          <div class="disp-note m">${p.layers ? t("Layer {layer} / {layers}", { layer: p.layer ?? "?", layers: p.layers }) : t("Layer {layer}", { layer: p.layer ?? "?" })} · ${pct(p.progress)} %</div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;gap:12px;min-width:0">
          <div class="disp-row" style="gap:10px;color:var(--danger)"><${Icon} name="power" /><h2 style="color:var(--text)">
            ${r.running ? t("Resuming the print …") : t("Print interrupted")}</h2></div>
          ${r.running ? html`<p class="muted">${t("Heating, lifting, probing the height, purging – this takes a few minutes.")}</p>` : html`
            <p>${t("The power was gone. Is the part still stuck to the bed?")}</p>
            <p class="muted">${t("When resuming, the printer first heats to printing temperature, lifts the nozzle slowly, probes the height on the part and continues printing there. If the height does not fit, it stops instead of guessing.")}</p>`}
          ${r.error && html`<div class="disp-alert">${t("Resume cancelled: {error}", { error: r.error })}</div>`}
          <div style="flex:1"></div>
          ${!r.running && html`<div class="disp-btns">
            <button type="button" class="disp-btn acc" style="flex:2;min-height:60px" disabled=${busy}
              onClick=${() => confirm({ title: t("Resume the print?"), ok: t("Resume"),
                text: t("Part checked? The printer heats, homes X/Y, probes the height on the part and continues printing."),
                action: () => post("/api/resume", { confirm: true }) })}>${t("Resume …")}</button>
            <button type="button" class="disp-btn danger" style="min-height:60px" disabled=${busy}
              onClick=${() => confirm({ title: t("Discard the interrupted print?"), ok: t("Discard"), danger: true,
                text: t("{file} is not resumed; the saved state is deleted.", { file: fileName(file) }),
                action: () => post("/api/resume/discard", {}) })}>${t("Discard …")}</button>
          </div>`}
        </div>
      </div>
    </section>
  </div>`;
}

// ------------------------------------------------------------ dialogs
function Dialog({ dlg, close, act, st }) {
  if (dlg.kind === "pair") return html`<${Pair} then=${dlg.then} close=${close} act=${act} />`;
  if (dlg.kind === "tune") return html`<${Tune} close=${close} act=${act} p=${st.printer || {}} />`;
  if (dlg.kind === "number") return html`<${NumberPad} dlg=${dlg} close=${close} />`;
  if (dlg.kind === "start") return html`<${StartPrint} path=${dlg.path} close=${close} act=${act} />`;
  const ok = () => { close(); if (dlg.action) act(dlg.action); };
  return html`<div class="disp-over" role="dialog" aria-label=${dlg.title}>
    <section class=${"disp-dialog" + (dlg.danger ? " danger" : "")}>
      <h2>${dlg.title}</h2>
      ${dlg.text && html`<p>${dlg.text}</p>`}
      <div class="disp-btns">
        ${dlg.action && html`<button type="button" class=${"disp-btn " + (dlg.danger ? "danger" : "acc")} onClick=${ok}>${dlg.ok || "OK"}</button>`}
        <button type="button" class="disp-btn" onClick=${close}>${dlg.action ? t("Back") : "OK"}</button>
      </div>
    </section>
  </div>`;
}

function Pair({ then, close, act }) {
  const [code, setCode] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const press = (k) => setCode((c) => (k === "<" ? c.slice(0, -1) : k === "C" ? "" : (c + k).slice(0, 6)));
  async function pair() {
    setBusy(true); setErr(null);
    try {
      const res = await post("/api/auth/pair", { code, name: t("Printer display"), kind: "display" });
      auth.save(res.key || res.token);
      close();
      if (then) act(then);
    } catch (e) { setErr(e.message); setCode(""); } finally { setBusy(false); }
  }
  return html`<div class="disp-over" role="dialog" aria-label=${t("Pair the display")}>
    <section class="disp-dialog" style="height:100%">
      <div class="disp-split">
        <div style="flex:1;display:flex;flex-direction:column;gap:12px">
          <h2>${t("Pair the display")}</h2>
          <p class="muted">${t("To switch things the display needs a code once: create it in the web UI or app under Devices → Add device and type it here.")}</p>
          <div class="disp-code" aria-live="polite">${code.padEnd(6, "·")}</div>
          ${err && html`<div class="disp-alert">${err}</div>`}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class="disp-btn acc" disabled=${code.length !== 6 || busy} onClick=${pair}>${t("Pair")}</button>
            <button type="button" class="disp-btn" onClick=${close}>${t("Back")}</button>
          </div>
        </div>
        <div class="disp-keys" aria-label=${t("Digits")}>
          ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "<"].map((k) => html`<button type="button"
            aria-label=${k === "<" ? t("Delete") : k === "C" ? t("Clear all") : k} onClick=${() => press(k)}>${k === "<" ? "⌫" : k}</button>`)}
        </div>
      </div>
    </section>
  </div>`;
}

function NumberPad({ dlg, close }) {
  const [v, setV] = useState(String(Math.round(dlg.value || 0)));
  const press = (k) => setV((c) => (k === "<" ? c.slice(0, -1) : k === "C" ? "" : (c === "0" ? k : c + k).slice(0, 3)));
  const n = parseInt(v || "0", 10);
  const bad = n > dlg.max;
  return html`<div class="disp-over" role="dialog" aria-label=${dlg.title}>
    <section class="disp-dialog" style="height:100%">
      <div class="disp-split">
        <div style="flex:1;display:flex;flex-direction:column;gap:12px">
          <h2>${dlg.title}</h2>
          <div class="disp-code">${v || "0"} °C</div>
          ${bad && html`<div class="disp-alert">${t("At most {max} °C", { max: dlg.max })}</div>`}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class="disp-btn acc" disabled=${bad} onClick=${() => { close(); dlg.action(n); }}>${t("Apply")}</button>
            <button type="button" class="disp-btn" onClick=${close}>${t("Back")}</button>
          </div>
        </div>
        <div class="disp-keys" aria-label=${t("Digits")}>
          ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "<"].map((k) => html`<button type="button"
            aria-label=${k === "<" ? t("Delete") : k === "C" ? t("Clear all") : k} onClick=${() => press(k)}>${k === "<" ? "⌫" : k}</button>`)}
        </div>
      </div>
    </section>
  </div>`;
}

function Tune({ close, act, p }) {
  const [tab, setTab] = useState("speed");
  const [speed, setSpeed] = useState(pct(p.speed_factor || 1));
  const [flow, setFlow] = useState(pct(p.flow_factor || 1));
  const [m, setM] = useState(null);
  const [msg, setMsg] = useState(null);
  async function loadM() { try { setM(await get("/api/machine")); } catch { /* stays */ } }
  useEffect(() => { loadM(); const timer = setInterval(loadM, POLL_MS); return () => clearInterval(timer); }, []);
  const step = (v, set, d, lo, hi) => set(Math.max(lo, Math.min(hi, v + d)));
  const row = (label, v, set, lo, hi) => html`<div class="disp-row"><b class="grow">${label}</b><div class="disp-step">
    <button type="button" class="disp-btn" onClick=${() => step(v, set, -5, lo, hi)}>−5</button>
    <span class="v">${v} %</span>
    <button type="button" class="disp-btn" onClick=${() => step(v, set, 5, lo, hi)}>+5</button></div></div>`;
  const z = (d) => act(async () => { await post("/api/machine/zadjust", { delta: d }); await loadM(); });
  const fmt = (v) => (v == null ? "–" : `${v >= 0 ? "+" : "−"}${fixed(Math.abs(v), 3)}`);
  const objects = m?.objects || [];
  const tabs = [["speed", t("Speed & flow")], ["z", t("First layer (Z)")], ["obj", objects.length ? t("Objects ({n})", { n: objects.length }) : t("Objects")]];
  return html`<div class="disp-over" role="dialog" aria-label=${t("Tune")}>
    <section class="disp-dialog" style="height:100%">
      <div class="disp-tabs" role="tablist">${tabs.map(([k, l]) => html`<button type="button" role="tab" aria-selected=${tab === k}
        class=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</div>
      ${tab === "speed" && html`${row(t("Speed"), speed, setSpeed, 10, 300)}${row(t("Flow"), flow, setFlow, 50, 150)}
        <div style="flex:1"></div>
        <div class="disp-btns">
          <button type="button" class="disp-btn acc" onClick=${() => { close(); act(() => post("/api/print/tune", { speed, flow })); }}>${t("Apply")}</button>
          <button type="button" class="disp-btn" onClick=${close}>${t("Back")}</button>
        </div>`}
      ${tab === "z" && html`
        <div class="disp-row"><div class="grow"><div class="disp-lbl">${t("Z offset now")}</div>
          <div class="disp-val">${fmt(m?.z_offset)}<small> mm</small></div></div>
          <div class="grow"><div class="disp-lbl">${t("adjusted in this print")}</div>
          <div class="disp-val">${fmt(m?.z_session)}<small> mm</small></div></div></div>
        <div class="disp-zsteps">
          ${[...(m?.z_steps || [0.01, 0.025, 0.05])].reverse().map((d) => html`<button type="button" class="disp-btn"
            onClick=${() => z(-d)}>−${num(d, 3)}<small> ${t("closer")}</small></button>`)}
          ${(m?.z_steps || [0.01, 0.025, 0.05]).map((d) => html`<button type="button" class="disp-btn"
            onClick=${() => z(d)}>+${num(d, 3)}<small> ${t("further away")}</small></button>`)}
        </div>
        ${msg && html`<div class="disp-alert warn">${msg}</div>`}
        <div style="flex:1"></div>
        <div class="disp-btns">
          <button type="button" class="disp-btn acc" disabled=${!m?.z_filament || !m?.z_session}
            onClick=${() => act(async () => { const r = await post("/api/machine-z/save", {});
              setMsg(t("{filament}: Z offset {old} → {new} mm (applies from the next print)", { filament: r.filament, old: fmt(r.old), new: fmt(r.new) })); await loadM(); })}>
            ${m?.z_filament ? t("Apply for {name}", { name: m.z_filament.name }) : t("No filament loaded")}</button>
          <button type="button" class="disp-btn" onClick=${close}>${t("Done")}</button>
        </div>`}
      ${tab === "obj" && html`
        ${objects.length === 0 ? html`<div class="disp-empty">${t("The file has no named objects")}<br/>${t("(switch on “Label objects” in Orca).")}</div>`
          : html`<div class="disp-objs">${objects.map((o) => html`<button type="button" class=${"disp-btn" + (o.current ? " acc" : "")}
            disabled=${o.excluded} onClick=${() => act(withConfirm("/api/machine/exclude", { name: o.name }))}>
            ${o.excluded ? "✕ " : ""}${o.name}${o.current ? " · " + t("printing now") : ""}</button>`)}</div>`}
        <div style="flex:1"></div>
        <div class="disp-btns"><button type="button" class="disp-btn" onClick=${close}>${t("Done")}</button></div>`}
    </section>
  </div>`;
}

// ------------------------------------------------------------ print finished
function Done({ st, busy, setDlg }) {
  const p = st.printer || {};
  const ok = p.state === "complete";
  const file = p.file || "";
  const used = (st.uses || []).filter((u) => u.total_g);
  return html`<div class="disp-print">
    <section class="disp-thumb" aria-label=${t("Preview")}>
      <div class="img"><img src=${`api/print/thumbnail.png?f=${encodeURIComponent(file)}`} alt=${t("Preview image")}
        onError=${(e) => { e.target.style.display = "none"; }} /></div>
      <div class="file">${fileName(file)}</div>
    </section>
    <div class="disp-pcol">
      <h2 class="disp-done" style=${`color:${ok ? "var(--ok-text)" : "var(--danger-text)"}`}>${ok ? t("Print finished") : p.state === "cancelled" ? t("Print cancelled") : t("Print ended with an error")}</h2>
      <div class="disp-grid2" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Print time")}</div><div class="disp-val">${hm(p.print_duration_s)}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Progress")}</div><div class="disp-val">${pct(p.progress)} %</div></div>
      </div>
      ${used.length > 0 && html`<div class="disp-lbl">${t("Used up")}</div>
        ${used.map((u) => html`<div class="disp-row" style="gap:10px"><span class="disp-dot" style=${`background:${hex(u.color) || "var(--surface2)"}`}></span>
          <span class="grow">${t("Slot {slot}", { slot: u.slot })} · ${u.name}</span><b class="m">${num(u.total_g, 1)} g</b></div>`)}`}
      <div style="flex:1"></div>
      <div class="disp-btns">
        <button type="button" class="disp-btn acc" disabled=${busy || !file} onClick=${() => setDlg({ kind: "start", path: file })}>${t("Print again …")}</button>
      </div>
    </div>
  </div>`;
}

// ------------------------------------------------------------ files
function Files({ busy, setDlg }) {
  const [files, setFiles] = useState(null);
  const [err, setErr] = useState(null);
  const [pageNo, setPageNo] = useState(0);
  useEffect(() => { get("/api/files").then((r) => setFiles(r.files)).catch((e) => setErr(e.message)); }, []);
  if (err) return html`<div class="disp-empty">${err}</div>`;
  if (!files) return html`<div class="disp-empty">${t("Loading files …")}</div>`;
  if (!files.length) return html`<div class="disp-empty">${t("No print files on the printer.")}</div>`;
  const pages = Math.ceil(files.length / PAGE_SIZE);
  const shown = files.slice(pageNo * PAGE_SIZE, pageNo * PAGE_SIZE + PAGE_SIZE);
  return html`<div class="disp-files">
    <div class="disp-flist">${shown.map((f) => html`<button type="button" class="disp-file" disabled=${busy}
      onClick=${() => setDlg({ kind: "start", path: f.path })}>
      <span class="th">${f.thumb && html`<img src=${`api/files/thumb?path=${encodeURIComponent(f.path)}`} alt="" />`}</span>
      <span class="t"><b>${fileName(f.path)}</b><span>${[f.est_s ? hm(f.est_s) + " h" : null, f.weight_g ? Math.round(f.weight_g) + " g" : null,
        f.modified ? new Date(f.modified * 1000).toLocaleDateString(locale, { day: "2-digit", month: "2-digit" }) : null].filter(Boolean).join(" · ")}</span></span>
      <span class="dots">${f.tools.map((tool) => html`<span class="disp-dot" style=${`width:18px;height:18px;background:${hex(tool.color) || "var(--surface2)"}`}></span>`)}</span>
    </button>`)}</div>
    <div class="disp-pager">
      <button type="button" class="disp-btn" disabled=${pageNo === 0} aria-label=${t("Previous page")} onClick=${() => setPageNo(pageNo - 1)}>▲</button>
      <span class="disp-note m">${pageNo + 1}/${pages}</span>
      <button type="button" class="disp-btn" disabled=${pageNo >= pages - 1} aria-label=${t("Next page")} onClick=${() => setPageNo(pageNo + 1)}>▼</button>
    </div>
  </div>`;
}

function StartPrint({ path, close, act }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { get("/api/files/check?path=" + encodeURIComponent(path)).then(setC).catch((e) => setErr(e.message)); }, [path]);
  return html`<div class="disp-over" role="dialog" aria-label=${t("Start print")}>
    <section class="disp-dialog" style="height:100%">
      <div class="disp-split">
        <div class="disp-thumb" style="width:200px">
          <div class="img" style="height:200px"><img src=${`api/files/thumb?path=${encodeURIComponent(path)}`} alt=${t("Preview image")}
            onError=${(e) => { e.target.style.display = "none"; }} /></div>
          <div class="file">${fileName(path)}</div>
          ${c && html`<div class="disp-note m">${[c.est_s ? hm(c.est_s) + " h" : null, c.weight_g ? Math.round(c.weight_g) + " g" : null].filter(Boolean).join(" · ")}</div>`}
        </div>
        <div style="flex:1;display:flex;flex-direction:column;gap:8px;min-width:0">
          <h2>${t("Print?")}</h2>
          ${err && html`<div class="disp-alert">${err}</div>`}
          ${!c && !err && html`<div class="disp-note">${t("Checking slots …")}</div>`}
          ${c && c.tools.map((tool) => html`<div class="disp-tile disp-row" style="gap:10px;padding:8px 12px">
            <span class="disp-dot" style=${`background:${hex(tool.color) || "var(--surface2)"}`} title=${t("File")}></span>
            <span class="disp-note">→</span>
            <span class="disp-dot" style=${`background:${hex(tool.have_color) || "var(--surface2)"}`} title="Slot"></span>
            <span class="grow disp-tool"><span><b>${t("Slot {slot}", { slot: tool.slot })}</b> · ${tool.have_name || t("no spool")}</span>
              <span class=${tool.hints.length ? "warn" : "ok"}>${tool.hints.length ? tool.hints.join(" · ") : tool.type ? t("fits (file: {type})", { type: tool.type }) : t("fits")}</span></span></div>`)}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class=${"disp-btn " + (c && !c.ok ? "danger" : "acc")} disabled=${!c}
              onClick=${() => { close(); act(() => post("/api/files/start", { path, confirm: true })); }}>${c && !c.ok ? t("Print anyway") : t("Print")}</button>
            <button type="button" class="disp-btn" onClick=${close}>${t("Back")}</button>
          </div>
        </div>
      </div>
    </section>
  </div>`;
}

// ------------------------------------------------------------ System
function System({ st, busy, act, confirm }) {
  const [tab, setTab] = useState("msg");
  const [info, setInfo] = useState(null);
  const usb = useUsb();
  useEffect(() => { get("/api/system").then(setInfo).catch(() => setInfo({})); }, []);
  const msgs = st.notices?.messages || [];
  const printing = PRINTING.has(st.printer?.state);
  const colour = { error: "var(--danger-text)", warn: "var(--accent-text)" };
  return html`
    <div class="disp-tabs" role="tablist">${[["msg", msgs.length ? t("Messages ({n})", { n: msgs.length }) : t("Messages")], ["info", t("Info & restart")]].map(([k, l]) =>
      html`<button type="button" role="tab" aria-selected=${tab === k} class=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</div>
    ${tab === "msg" && html`<div class="disp-msgs">${msgs.length === 0 ? html`<div class="disp-empty">${t("No messages.")}</div>`
      : msgs.slice(0, 7).map((m) => html`<div class="disp-tile" style=${`padding:7px 12px;color:${colour[m.level] || "var(--text)"}`}>${m.text}</div>`)}
      ${msgs.length > 7 && html`<div class="disp-note">${t("… and {n} more (web/app)", { n: msgs.length - 7 })}</div>`}</div>`}
    ${tab === "info" && html`
      <div class="disp-grid2" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("IP of the Pi")}</div><div class="disp-val" style="font-size:17px">${(info?.ips || []).join(", ") || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Klipper</div><div class="disp-val" style="font-size:17px">${info?.klippy_state || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Bridge</div><div class="disp-val" style="font-size:17px">${info?.bridge || st.version || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">${t("Klipper version")}</div><div class="disp-val" style="font-size:13px">${info?.klipper || "–"}</div></div>
        ${st.printer?.printer_cpu != null && html`<div class="disp-tile disp-mini"><div class="disp-lbl">${t("Printer CPU")}</div>
          <div class="disp-val" style=${`font-size:17px;color:${st.printer.printer_cpu >= 90 ? "var(--danger-text)" : "var(--text)"}`}>${st.printer.printer_cpu} %</div></div>`}
      </div>
      ${usb?.available && html`<${UsbTile} usb=${usb} />`}
      <div style="flex:1"></div>
      <div class="disp-btns">
        <button type="button" class="disp-btn" disabled=${busy || printing} onClick=${() => confirm({ title: t("Reload Klipper?"), ok: t("Reload"),
          text: t("Takes a few seconds; the axes must be homed again afterwards."), action: () => post("/api/print/firmware_restart", { confirm: true }) })}>${t("Reload Klipper")}</button>
        <button type="button" class="disp-btn" disabled=${busy || printing} onClick=${() => confirm({ title: t("Restart the Pi?"), ok: t("Restart"),
          text: t("Klipper and the display are gone for about a minute."), action: () => post("/api/system/reboot", { confirm: true }) })}>${t("Restart the Pi")}</button>
        <button type="button" class="disp-btn danger" disabled=${busy || printing} onClick=${() => confirm({ title: t("Shut down the Pi?"), ok: t("Shut down"), danger: true,
          text: t("Only cut the power afterwards. It only comes back on by power off/on at the Pi."), action: () => post("/api/system/shutdown", { confirm: true }) })}>${t("Shut down the Pi")}</button>
      </div>
      ${printing && html`<div class="disp-note">${t("Locked during a print.")}</div>`}`}`;
}

// ------------------------------------------------------------ overlays: macro prompt, Klipper error
function Prompt({ st, busy, act }) {
  const q = st.prompt;
  const answer = (id) => act(() => post("/api/prompt", { id }));
  const style = (s) => (s === "error" ? " danger" : s === "primary" || s === "warning" ? " acc" : "");
  return html`<div class="disp-over" role="alertdialog" aria-label=${q.title}>
    <section class="disp-dialog">
      <div class="disp-row"><h2 class="grow">${q.title}</h2>
        <button type="button" class="disp-btn" aria-label=${t("Close")} style="min-width:56px" onClick=${() => act(() => post("/api/prompt/close", {}))}>✕</button></div>
      ${q.text.map((line) => html`<p>${line}</p>`)}
      ${q.rows.map((row) => html`<div class="disp-btns">${row.map((b) => html`<button type="button" class=${"disp-btn" + style(b.style)}
        disabled=${busy} onClick=${() => answer(b.id)}>${b.label}</button>`)}</div>`)}
      ${q.footer.length > 0 && html`<div class="disp-btns">${q.footer.map((b) => html`<button type="button" class=${"disp-btn" + style(b.style)}
        disabled=${busy} onClick=${() => answer(b.id)}>${b.label}</button>`)}</div>`}
    </section>
  </div>`;
}

// USB tunnel printer <-> Pi (watchdog kobra-usb-watch): state every 10 s while the page is open
function useUsb() {
  const [usb, setUsb] = useState(null);
  useEffect(() => {
    const load = () => get("/api/usb").then(setUsb).catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);
  return usb;
}

const USB_COLOUR = { ok: "var(--ok-text)", warn: "var(--accent-text)", bad: "var(--danger-text)", off: "var(--muted)" };

function UsbTile({ usb }) {
  const last = usb.events?.length ? usb.events[usb.events.length - 1] : null;
  const at = last ? new Date(last.at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }) : "";
  return html`<div class="disp-tile disp-mini" style="margin-top:8px">
    <div class="disp-lbl">${t("USB tunnel printer ↔ Pi")}</div>
    <div class="disp-val" style=${`font-size:17px;color:${USB_COLOUR[usb.state] || "var(--text)"}`}>${usb.detail}</div>
    ${last && html`<div class="disp-note" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${at} · ${last.text}</div>`}
  </div>`;
}

function KlippyDown({ busy, confirm }) {
  const [info, setInfo] = useState(null);
  const usb = useUsb();
  useEffect(() => { get("/api/system").then(setInfo).catch(() => setInfo(null)); }, []);
  return html`<div class="disp-over" role="alertdialog" aria-label=${t("Klipper not ready")}>
    <section class="disp-dialog danger">
      <h2>${t("Klipper is not ready")}</h2>
      <p class="muted" style="white-space:pre-line;max-height:150px;overflow:hidden">${info?.klippy_message || t("Emergency stop, error or connection to the boards lost.")}</p>
      ${usb?.available && html`<p style=${`color:${USB_COLOUR[usb.state] || "var(--text)"}`}>${t("USB tunnel: {detail}", { detail: usb.detail })}${usb.state === "warn" && usb.switches?.auto_restart ? " – " + t("Klipper is reloaded by itself afterwards") : ""}</p>`}
      <div class="disp-btns">
        <button type="button" class="disp-btn acc" disabled=${busy} onClick=${() => confirm({ title: t("Reload Klipper?"), ok: t("Reload"),
          text: t("The axes must be homed again afterwards."), action: () => post("/api/print/firmware_restart", { confirm: true }) })}>${t("Reload Klipper")}</button>
      </div>
    </section>
  </div>`;
}

render(html`<${Display} />`, document.getElementById("app"));
