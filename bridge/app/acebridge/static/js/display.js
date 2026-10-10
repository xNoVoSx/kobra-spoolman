// Drucker-Display (800x480, Kiosk-Browser auf dem Klipper-Pi, ueber VNC auf dem Original-Display des Kobra S1).
// Start (Status, Slots, Trockner), Druck (kommt bei Druckstart von selbst: Vorschaubild, Fortschritt, Zeiten,
// Temperaturen, Steuerung), Schalter (alle Module, gespeichert im Drucker), Druck unterbrochen (nach Stromausfall).
// Liest ohne Schluessel; zum Schalten einmal koppeln (6-stelliger Code aus Web/App, "Geraet hinzufuegen").

import { html, render, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get, post } from "./api.js";
import { duration, fileName, finishAt, hex, printerLook } from "./util.js";

const POLL_MS = 2000;
const PAGES = [["start", "home", "Start"], ["print", "print", "Druck"], ["files", "files", "Dateien"],
  ["control", "control", "Steuerung"], ["switch", "switch", "Schalter"], ["system", "info", "System"]];
const PAGE_SIZE = 5;
const UI_TAG = document.querySelector('meta[name="ui-tag"]')?.content || null;   // neue Bridge -> neu laden
const PRINTING = new Set(["printing", "paused"]);

// ------------------------------------------------------------ Symbole (Linien, wie im Entwurf)
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

/** Kurze Dauer fuer die Kacheln: 1:31 (Stunden:Minuten), unter einer Stunde 0:42. */
const hm = (s) => (s == null ? "–" : (([h, m]) => `${h}:${String(m).padStart(2, "0")}`)([Math.floor(Math.round(s / 60) / 60), Math.round(s / 60) % 60]));
const pct = (v) => Math.round(100 * (v || 0));
const deg = (v) => (v == null ? "–" : Math.round(v));
const clock = () => new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });

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

  /** Schreibender Aufruf: ohne Schluessel erst koppeln, danach genau diesen Aufruf wiederholen. */
  async function act(fn) {
    if (!auth.key) { setDlg({ kind: "pair", then: fn }); return; }
    setBusy(true);
    try { await fn(); await load(); }
    catch (e) {
      if (e.status === 401 || e.status === 403) { auth.clear(); setDlg({ kind: "pair", then: fn }); }
      else if (e.status === 409 && fn.retry) setDlg({ kind: "confirm", title: "Wirklich?", text: e.message, ok: "Ja", action: fn.retry });
      else setDlg({ kind: "info", title: "Nicht ausgeführt", text: e.message });
    } finally { setBusy(false); }
  }
  const confirm = (o) => setDlg({ kind: "confirm", ...o });
  const flip = (key, value) => act(() => post("/api/switch", { key, value }));

  if (down && !st) return html`<div class="disp"><div class="disp-empty">Bridge nicht erreichbar …</div></div>`;
  if (!st) return html`<div class="disp"><div class="disp-empty">Lade …</div></div>`;

  const p = st.printer || {};
  const look = printerLook(p.moonraker_connected === false ? null : p);
  const items = sw?.items || [];
  const light = items.find((i) => i.key === "light");
  const errors = (st.notices?.messages || []).filter((m) => m.level === "error" && m.key !== "resume");
  const ctx = { st, sw, items, busy, act, confirm, flip, setDlg, page, setPage };

  return html`<div class="disp">
    <nav class="disp-rail" aria-label="Bereiche">
      ${PAGES.map(([k, i, l]) =>
        html`<button type="button" class=${"disp-nav" + (page === k ? " on" : "")} aria-label=${l} onClick=${() => setPage(k)}><${Icon} name=${i} /></button>`)}
      <div class="grow"></div>
      ${light && html`<button type="button" class=${"disp-nav lit" + (light.on ? " on" : "")} aria-label=${light.on ? "Licht aus" : "Licht an"}
        disabled=${!light.sensitive || busy} onClick=${() => flip("light", !light.on)}><${Icon} name="light" /></button>`}
    </nav>
    <main class="disp-main">
      <header class="disp-head">
        <h1>${["start", "print"].includes(page) ? "Kobra S1" : PAGES.find((x) => x[0] === page)[2]}</h1>
        <span class="disp-chip" style=${`color:${look.fg};background:${look.bg};border-color:${look.line}`}>${look.label}</span>
        ${down && html`<span class="disp-chip" style="color:var(--danger-text);border-color:var(--danger-line)">Bridge weg</span>`}
        <div class="grow"></div>
        <span class="disp-clock">${now}</span>
      </header>
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
    <section class="disp-grid3" aria-label="Temperaturen">
      <div class="disp-tile"><div class="disp-lbl">Düse</div><div class="disp-val">${deg(p.nozzle?.temp)}<small> / ${deg(p.nozzle?.target)} °C</small></div></div>
      <div class="disp-tile"><div class="disp-lbl">Bett</div><div class="disp-val">${deg(p.bed?.temp)}<small> / ${deg(p.bed?.target)} °C</small></div></div>
      <div class="disp-tile"><div class="disp-lbl">ACE-Feuchte</div><div class="disp-val">${d.humidity ?? "–"}<small> %</small></div></div>
    </section>
    <section class="disp-grid4 disp-slots" aria-label="ACE-Slots">${(st.slots || []).map((s) => html`<${Slot} s=${s} />`)}</section>
    ${d.present && html`<section class="disp-tile disp-row" aria-label="Trockner">
      <div class="grow"><b>${d.drying ? `Trocknet · ${d.target_temp ?? "?"} °C` : "Trockner aus"}</b>
        <div class="muted">${d.drying ? `noch ${duration((d.remaining_min || 0) * 60)} · ${d.temp ?? "–"} °C im ACE`
          : (d.config?.enabled ? "Automatik an" : "Automatik aus") + (d.required?.temp ? ` · höchstens ${d.required.temp} °C für die eingelegten Spulen` : "")}</div></div>
      ${d.drying
        ? html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => confirm({ title: "Trocknen stoppen?", ok: "Stoppen",
            action: () => post("/api/dryer/stop") })}>Stoppen</button>`
        : html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => confirm({ title: "Trocknen starten?", ok: "Starten",
            text: `Temperatur und Dauer nach den eingelegten Spulen${d.required?.temp ? ` (höchstens ${d.required.temp} °C)` : ""}.`,
            action: () => post("/api/dryer/start", {}) })}>Trocknen …</button>`}
    </section>`}`;
}

function Slot({ s }) {
  const sp = s.spool, ace = s.ace || {};
  const color = hex(sp?.color || ace.color);
  const rest = sp?.remaining_weight;
  const low = rest != null && rest < 200;
  return html`<div class=${"disp-slot" + (ace.active ? " on" : "")}>
    <div class="hd"><span>Slot ${s.slot}</span>${ace.active && html`<span class="disp-tag">geladen</span>`}</div>
    <div class=${"disp-swatch" + (color ? "" : " empty")} style=${color ? `background:${color}` : ""}></div>
    <div class="name">${sp ? (sp.name || sp.material || "Spule") : ace.present ? (ace.material || "Unbekannt") : "leer"}</div>
    <div class=${"sub" + (low ? " warn" : "")}>${sp ? `${rest != null ? Math.round(rest) + " g" : "–"} · ${low ? "fast leer" : sp.vendor || ""}` : ace.present ? "ohne Spule" : ""}</div>
  </div>`;
}

// ------------------------------------------------------------ Druck
function Print({ st, busy, act, confirm, setDlg }) {
  const p = st.printer || {};
  const [img, setImg] = useState(0);              // 0 Vorschaubild der Datei, 1 Bild der Bridge, 2 keins
  const file = p.file || "";
  useEffect(() => setImg(0), [file]);
  if (!PRINTING.has(p.state) && !["complete", "cancelled", "error"].includes(p.state)) {
    return html`<div class="disp-empty">Kein Druck. Starten unter „Dateien“, in Orca oder Mainsail –<br/>die Druckansicht kommt dann von selbst.</div>`;
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
    <section class="disp-thumb" aria-label="Vorschau">
      <div class="img">${img < 2 ? html`<img src=${src} alt="Vorschaubild" onError=${() => setImg(img + 1)} />`
        : html`<span class="muted">Kein Vorschaubild</span>`}</div>
      <div class="file">${fileName(file)}</div>
      ${uses.length > 0 && html`<div class="disp-uses"><span class="disp-lbl">Benutzt</span>
        ${uses.map((u) => html`<span class=${"disp-dot" + (u.slot === active ? " on" : "")} style=${`background:${hex(u.color) || "var(--surface2)"}`} title=${"Slot " + u.slot}></span>`)}
        <span class="disp-note m">Slot ${uses.map((u) => u.slot).join(" · ")}</span></div>`}
    </section>
    <div class="disp-pcol">
      <div class="disp-note">${p.changing_filament ? "Wechselt Filament …" : active ? `Slot ${active}` : ""}${active && st.slots?.[active - 1]?.spool ? " · " + st.slots[active - 1].spool.name : ""}</div>
      <div class="disp-big"><span class="pct">${pct(p.progress)} %</span>${p.layers ? html`<span class="lay">Schicht ${p.layer ?? "?"} / ${p.layers}</span>` : ""}</div>
      <div class="disp-bar"><div style=${`width:${pct(p.progress)}%`}></div></div>
      <div class="disp-grid3" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">Läuft</div><div class="disp-val">${hm(p.print_duration_s)}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Rest</div><div class="disp-val">${running ? hm(p.eta_s) : "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Fertig</div><div class="disp-val">${running ? finishAt(p.eta_s).replace("~", "") : "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Düse</div><div class="disp-val">${deg(p.nozzle?.temp)}<small> / ${deg(p.nozzle?.target)}</small></div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Bett</div><div class="disp-val">${deg(p.bed?.temp)}<small> / ${deg(p.bed?.target)}</small></div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Tempo · Fluss</div><div class="disp-val">${pct(p.speed_factor)}<small> · ${pct(p.flow_factor)} %</small></div></div>
      </div>
      <div class="disp-note">${[pa?.k_ref != null ? `Auto-PA K ${String(pa.k_ref.toFixed(3)).replace(".", ",")}` : null,
        clog != null ? `Filament läuft (${pct(clog)} %)` : null].filter(Boolean).join(" · ")}</div>
      <div class="grow" style="flex:1"></div>
      ${running && html`<div class="disp-btns">
        ${paused
          ? html`<button type="button" class="disp-btn acc" disabled=${busy} onClick=${() => act(() => post("/api/print/resume", {}))}>Weiter</button>
            <button type="button" class="disp-btn danger" disabled=${busy} onClick=${() => confirm({ title: "Druck abbrechen?", ok: "Abbrechen", danger: true,
              text: `${fileName(file)} wird abgebrochen. Das lässt sich nicht rückgängig machen.`,
              action: () => post("/api/print/cancel", { confirm: true }) })}>Abbrechen</button>`
          : html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => act(() => post("/api/print/pause", {}))}>Pause</button>
            <button type="button" class="disp-btn" disabled=${busy} onClick=${() => setDlg({ kind: "tune" })}>Nachjustieren</button>`}
        <${EStop} confirm=${confirm} />
      </div>`}
    </div>
  </div>`;
}

// ------------------------------------------------------------ Steuerung
/** Aufruf, der bei einer Rueckfrage der Bridge (409 + confirm) nach Bestaetigung mit confirm: true wiederholt wird. */
function withConfirm(path, body) {
  const fn = () => post(path, body);
  fn.retry = () => post(path, { ...body, confirm: true });
  return fn;
}

function Control(ctx) {
  const [tab, setTab] = useState("temp");
  const [m, setM] = useState(null);
  async function loadM() { try { setM(await get("/api/machine")); } catch { /* Anzeige bleibt */ } }
  useEffect(() => { loadM(); const t = setInterval(loadM, POLL_MS); return () => clearInterval(t); }, []);
  const act = (fn) => ctx.act(async () => { await fn(); await loadM(); });
  const tabs = [["temp", "Temperatur"], ["move", "Bewegen"], ["fil", "Filament"], ["more", "Mehr"]];
  const sub = { ...ctx, m, act };
  return html`
    <div class="disp-tabs" role="tablist" aria-label="Steuerung">
      ${tabs.map(([k, l]) => html`<button type="button" role="tab" aria-selected=${tab === k} class=${tab === k ? "on" : ""}
        onClick=${() => setTab(k)}>${l}</button>`)}
    </div>
    ${m?.running && html`<div class="disp-alert warn">Läuft: ${m.running} …</div>`}
    ${m?.error && !m.running && html`<div class="disp-alert">${m.error}</div>`}
    ${tab === "temp" && html`<${Temps} ...${sub} />`}
    ${tab === "move" && html`<${Move} ...${sub} />`}
    ${tab === "fil" && html`<${Filament} ...${sub} />`}
    ${tab === "more" && html`<${More} ...${sub} />`}`;
}

function Temps({ st, busy, act, setDlg }) {
  const p = st.printer || {};
  const tune = (body) => act(withConfirm("/api/print/tune", body));
  // Schnellwahl aus den eingelegten Spulen (Spoolman), jede Kombination einmal
  const seen = new Set();
  const presets = (st.slots || []).map((s) => s.spool).filter((sp) => sp?.nozzle_temp)
    .filter((sp) => { const k = `${sp.nozzle_temp}/${sp.bed_temp}`; if (seen.has(k)) return false; seen.add(k); return true; });
  const ask = (label, key, cur, max) => setDlg({ kind: "number", title: label, value: cur || 0, max,
    action: (v) => tune({ [key]: v }) });
  const card = (label, key, t, max) => html`<div class="disp-tile disp-temp">
    <button type="button" class="disp-tempbtn" disabled=${busy} onClick=${() => ask(`${label}: Soll (°C)`, key, t?.target, max)}>
      <div class="disp-lbl">${label} · antippen zum Einstellen</div>
      <div class="disp-val" style="font-size:34px">${deg(t?.temp)}<small> / ${deg(t?.target)} °C</small></div></button>
    <button type="button" class="disp-btn danger disp-off" disabled=${busy || !t?.target} aria-label=${label + " aus"}
      onClick=${() => tune({ [key]: 0 })}>Aus</button></div>`;
  return html`
    <div class="disp-grid2">${card("Düse", "nozzle", p.nozzle, 300)}${card("Bett", "bed", p.bed, 120)}</div>
    <div class="disp-lbl">Aus den eingelegten Spulen</div>
    <div class="disp-presets">
      ${presets.map((sp) => html`<button type="button" class="disp-btn" disabled=${busy}
        onClick=${() => tune({ nozzle: sp.nozzle_temp, bed: sp.bed_temp || 0 })}>
        <span class="disp-dot" style=${`width:16px;height:16px;display:inline-block;vertical-align:-2px;margin-right:8px;background:${hex(sp.color) || "var(--surface2)"}`}></span>
        ${sp.material} ${sp.nozzle_temp}/${sp.bed_temp ?? "–"}</button>`)}
      <button type="button" class="disp-btn danger" disabled=${busy} onClick=${() => tune({ nozzle: 0, bed: 0 })}>Alles aus</button>
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
      <div class="disp-tile"><div class="disp-lbl">Position${homed.length < 3 ? " · nicht alles gehomt" : ""}</div>
        <div class="disp-val" style="font-size:18px">${pos ? `X ${pos[0]}  Y ${pos[1]}  Z ${pos[2]}` : "–"}</div></div>
      <div class="disp-lbl">Schritt (mm)</div>
      <div class="disp-steps">${(m?.steps || [0.1, 1, 10, 50]).map((s) => html`<button type="button"
        class=${"disp-btn" + (s === step ? " acc" : "")} onClick=${() => setStep(s)}>${String(s).replace(".", ",")}</button>`)}</div>
      <div class="disp-btns">
        <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/home", { axes: "all" }))}>Alle homen</button>
        <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/motors_off", {}))}>Motoren aus</button>
      </div>
      ${!m?.move_allowed && html`<div class="disp-note">Während des Drucks gesperrt.</div>`}
    </div>
  </div>`;
}

function Filament({ st, m, busy, act }) {
  const p = st.printer || {};
  const ok = m?.move_allowed && !busy && !m?.running;
  const okE = m?.extrude_allowed && !busy && !m?.running;
  const cold = (p.nozzle?.temp ?? 0) < 170;
  return html`
    <div class="disp-lbl">Slot laden (wechselt über die ACE, heizt selbst)</div>
    <div class="disp-grid4">${(st.slots || []).map((s) => {
      const sp = s.spool, color = hex(sp?.color || s.ace?.color);
      return html`<button type="button" class=${"disp-slot" + (s.ace?.active ? " on" : "")} style="min-height:118px"
        disabled=${!ok || !s.ace?.present} onClick=${() => act(() => post("/api/machine/load", { slot: s.slot }))}>
        <div class="hd"><span>Slot ${s.slot}</span>${s.ace?.active && html`<span class="disp-tag">geladen</span>`}</div>
        <div class=${"disp-swatch" + (color ? "" : " empty")} style=${(color ? `background:${color};` : "") + "width:36px;height:36px"}></div>
        <div class="name">${sp?.name || (s.ace?.present ? s.ace.material : "leer")}</div></button>`;
    })}</div>
    <div class="disp-btns">
      <button type="button" class="disp-btn" disabled=${!ok} onClick=${() => act(() => post("/api/machine/unload", {}))}>Entladen</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: -10 }))}>10 mm zurück</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: 10 }))}>10 mm vor</button>
      <button type="button" class="disp-btn" disabled=${!okE || cold} onClick=${() => act(() => post("/api/machine/extrude", { mm: 50 }))}>50 mm vor</button>
    </div>
    ${cold && html`<div class="disp-note">Extrudieren erst ab 170 °C Düse (Reiter Temperatur).</div>`}`;
}

function More({ st, m, busy, act, confirm }) {
  const p = st.printer || {};
  const ok = m?.move_allowed && !busy && !m?.running;
  const fan = (f) => html`<div class="disp-tile disp-fan"><b>${f.name}</b><span class="disp-val" style="font-size:22px">${pct(f.speed)}<small> %</small></span>
    <div class="disp-fanbtns">${[0, 50, 100].map((v) => html`<button type="button" class="disp-btn" disabled=${busy}
      onClick=${() => act(() => post("/api/print/tune", { fans: { [f.key]: v } }))}>${v}</button>`)}</div></div>`;
  return html`
    <div class="disp-lbl">Lüfter (%)</div>
    <div class="disp-grid3">${(p.fans || []).map(fan)}</div>
    <div style="flex:1"></div>
    <div class="disp-btns">
      ${(m?.macros || []).map((mc) => html`<button type="button" class="disp-btn"
        disabled=${!ok} onClick=${() => confirm({ title: mc.label + "?", text: mc.confirm, ok: "Starten",
          action: () => post("/api/machine/macro", { key: mc.key, confirm: true }) })}>${mc.label}</button>`)}
      <button type="button" class="disp-btn" disabled=${busy || p.state === "printing"}
        onClick=${() => confirm({ title: "Klipper neu laden?", text: "Dauert einige Sekunden; die Achsen müssen danach neu gehomt werden.",
          ok: "Neu laden", action: () => post("/api/print/firmware_restart", { confirm: true }) })}>Klipper neu laden</button>
      <${EStop} confirm=${confirm} />
    </div>`;
}

// ------------------------------------------------------------ Schalter
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
    <div class="disp-tabs" role="tablist" aria-label="Gruppe">
      ${groups.map((g) => html`<button type="button" role="tab" aria-selected=${tab === g.key} class=${tab === g.key ? "on" : ""}
        onClick=${() => setTab(g.key)}>${g.title}</button>`)}
    </div>
    <div class="disp-scroll">
      <div class="disp-toggles">
        ${toggles.map((i) => html`<${Toggle} title=${i.title} hint=${i.hint} on=${i.on} disabled=${!i.sensitive || busy}
          onClick=${() => flip(i.key, !i.on)} />`)}
        ${tab === GROUP_KI && v?.configured && html`<${Toggle} title="KI-Überwachung" hint="Fehldruck-Erkennung mit der Kamera"
          on=${v.enabled} disabled=${busy} onClick=${() => act(() => post("/api/vision/settings", { enabled: !v.enabled }))} />`}
        ${tab === GROUP_KI && v?.configured && v.enabled && printing && html`<${Toggle} title="Diesen Druck nicht überwachen"
          hint="KI bis zum nächsten Druck still" on=${v.muted} disabled=${busy}
          onClick=${() => act(() => post("/api/vision/mute", { on: !v.muted }))} />`}
      </div>
      ${choices.map((c) => html`<div class="disp-choice"><b>${c.title}</b><div class="opts">
        ${c.options.map((o) => html`<button type="button" class=${o.value === c.current ? "on" : ""} disabled=${!c.sensitive || busy}
          aria-pressed=${o.value === c.current} onClick=${() => o.value !== c.current && flip(c.key, o.value)}>${o.label}</button>`)}
      </div></div>`)}
      ${tab === "print" && st.pa?.slots?.length > 0 && html`<div class="disp-tile disp-grid4" aria-label="PA je Slot">
        ${st.pa.slots.map((s) => html`<div class="disp-row" style="gap:8px">
          <span class="disp-dot" style=${`width:18px;height:18px;background:${hex(st.slots?.[s.slot - 1]?.spool?.color) || "var(--surface2)"}`}></span>
          <span class="disp-note">${s.state === "table" || s.k_ref != null ? `K ${String((s.k_ref ?? 0).toFixed(3)).replace(".", ",")}`
            : s.state === "needed" ? "misst beim Druck" : s.state === "failed" ? "gescheitert" : "–"}</span></div>`)}
      </div>`}
      ${items.length === 0 && html`<div class="disp-empty">Klipper ist nicht bereit</div>`}
      <div class="disp-note">Alle Schalter gelten auch in Web, App und Mainsail – gespeichert im Drucker.</div>
    </div>`;
}

/** Not-Aus: immer bedienbar (auch wenn gerade etwas laeuft), mit Rueckfrage. */
function EStop({ confirm }) {
  return html`<button type="button" class="disp-btn danger" onClick=${() => confirm({ title: "Not-Aus?", ok: "Not-Aus", danger: true,
    text: "Alles stoppt sofort: Motoren, Heizungen, Druck. Der Druck ist verloren; danach Klipper neu laden.",
    action: () => post("/api/print/emergency_stop", { confirm: true }) })}>Not-Aus …</button>`;
}

const Toggle = ({ title, hint, on, disabled, onClick }) => html`<button type="button" class="disp-toggle" aria-pressed=${!!on}
  disabled=${disabled} onClick=${onClick}><span class="t"><b>${title}</b>${hint && html`<span>${hint}</span>`}</span>
  <span class=${"disp-knob" + (on ? " on" : "")} aria-hidden="true"></span></button>`;

// ------------------------------------------------------------ Druck unterbrochen (Stromausfall)
function Resume({ st, busy, confirm }) {
  const r = st.resume;
  if (!r || !(r.pending || r.running)) return null;
  const p = r.pending || {};
  const file = p.file || "";
  return html`<div class="disp-over" role="alertdialog" aria-label="Druck unterbrochen">
    <section class="disp-dialog danger" style="height:100%">
      <div class="disp-split">
        <div class="disp-thumb" style="width:210px">
          <div class="img" style="height:210px"><img src=${`/api/print/thumbnail.png?f=${encodeURIComponent(file)}`} alt="Vorschaubild"
            onError=${(e) => { e.target.style.display = "none"; }} /></div>
          <div class="file">${fileName(file)}</div>
          <div class="disp-note m">Schicht ${p.layer ?? "?"}${p.layers ? " / " + p.layers : ""} · ${pct(p.progress)} %</div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;gap:12px;min-width:0">
          <div class="disp-row" style="gap:10px;color:var(--danger)"><${Icon} name="power" /><h2 style="color:var(--text)">
            ${r.running ? "Druck wird fortgesetzt …" : "Druck unterbrochen"}</h2></div>
          ${r.running ? html`<p class="muted">Heizen, anheben, Höhe antasten, spülen – das dauert einige Minuten.</p>` : html`
            <p>Der Strom war weg. Ist das Teil noch fest auf dem Bett?</p>
            <p class="muted">Beim Fortsetzen heizt der Drucker erst auf Drucktemperatur, hebt die Düse langsam an, tastet die
              Höhe auf dem Teil an und druckt an der Stelle weiter. Passt die Höhe nicht, bricht er ab statt zu raten.</p>`}
          ${r.error && html`<div class="disp-alert">Fortsetzen abgebrochen: ${r.error}</div>`}
          <div style="flex:1"></div>
          ${!r.running && html`<div class="disp-btns">
            <button type="button" class="disp-btn acc" style="flex:2;min-height:60px" disabled=${busy}
              onClick=${() => confirm({ title: "Druck fortsetzen?", ok: "Fortsetzen",
                text: "Teil geprüft? Der Drucker heizt, fährt X/Y nach Hause, tastet die Höhe auf dem Teil an und druckt weiter.",
                action: () => post("/api/resume", { confirm: true }) })}>Fortsetzen …</button>
            <button type="button" class="disp-btn danger" style="min-height:60px" disabled=${busy}
              onClick=${() => confirm({ title: "Druck verwerfen?", ok: "Verwerfen", danger: true,
                text: `${fileName(file)} wird nicht fortgesetzt, die Sicherung wird gelöscht.`,
                action: () => post("/api/resume/discard", {}) })}>Verwerfen …</button>
          </div>`}
        </div>
      </div>
    </section>
  </div>`;
}

// ------------------------------------------------------------ Dialoge
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
        <button type="button" class="disp-btn" onClick=${close}>${dlg.action ? "Zurück" : "OK"}</button>
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
      const res = await post("/api/auth/pair", { code, name: "Drucker-Display", kind: "display" });
      auth.save(res.key || res.token);
      close();
      if (then) act(then);
    } catch (e) { setErr(e.message); setCode(""); } finally { setBusy(false); }
  }
  return html`<div class="disp-over" role="dialog" aria-label="Display koppeln">
    <section class="disp-dialog" style="height:100%">
      <div class="disp-split">
        <div style="flex:1;display:flex;flex-direction:column;gap:12px">
          <h2>Display koppeln</h2>
          <p class="muted">Zum Schalten braucht das Display einmal einen Code: in der Weboberfläche oder App unter
            Geräte → Gerät hinzufügen erzeugen und hier eintippen.</p>
          <div class="disp-code" aria-live="polite">${code.padEnd(6, "·")}</div>
          ${err && html`<div class="disp-alert">${err}</div>`}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class="disp-btn acc" disabled=${code.length !== 6 || busy} onClick=${pair}>Koppeln</button>
            <button type="button" class="disp-btn" onClick=${close}>Zurück</button>
          </div>
        </div>
        <div class="disp-keys" aria-label="Ziffern">
          ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "<"].map((k) => html`<button type="button"
            aria-label=${k === "<" ? "Löschen" : k === "C" ? "Alles löschen" : k} onClick=${() => press(k)}>${k === "<" ? "⌫" : k}</button>`)}
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
          ${bad && html`<div class="disp-alert">Höchstens ${dlg.max} °C</div>`}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class="disp-btn acc" disabled=${bad} onClick=${() => { close(); dlg.action(n); }}>Übernehmen</button>
            <button type="button" class="disp-btn" onClick=${close}>Zurück</button>
          </div>
        </div>
        <div class="disp-keys" aria-label="Ziffern">
          ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "<"].map((k) => html`<button type="button"
            aria-label=${k === "<" ? "Löschen" : k === "C" ? "Alles löschen" : k} onClick=${() => press(k)}>${k === "<" ? "⌫" : k}</button>`)}
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
  async function loadM() { try { setM(await get("/api/machine")); } catch { /* bleibt */ } }
  useEffect(() => { loadM(); const t = setInterval(loadM, POLL_MS); return () => clearInterval(t); }, []);
  const step = (v, set, d, lo, hi) => set(Math.max(lo, Math.min(hi, v + d)));
  const row = (label, v, set, lo, hi) => html`<div class="disp-row"><b class="grow">${label}</b><div class="disp-step">
    <button type="button" class="disp-btn" onClick=${() => step(v, set, -5, lo, hi)}>−5</button>
    <span class="v">${v} %</span>
    <button type="button" class="disp-btn" onClick=${() => step(v, set, 5, lo, hi)}>+5</button></div></div>`;
  const z = (d) => act(async () => { await post("/api/machine/zadjust", { delta: d }); await loadM(); });
  const fmt = (v) => (v == null ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3).replace(".", ",")}`);
  const objects = m?.objects || [];
  const tabs = [["speed", "Tempo & Fluss"], ["z", "Erste Schicht (Z)"], ["obj", `Objekte${objects.length ? ` (${objects.length})` : ""}`]];
  return html`<div class="disp-over" role="dialog" aria-label="Nachjustieren">
    <section class="disp-dialog" style="height:100%">
      <div class="disp-tabs" role="tablist">${tabs.map(([k, l]) => html`<button type="button" role="tab" aria-selected=${tab === k}
        class=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</div>
      ${tab === "speed" && html`${row("Tempo", speed, setSpeed, 10, 300)}${row("Fluss", flow, setFlow, 50, 150)}
        <div style="flex:1"></div>
        <div class="disp-btns">
          <button type="button" class="disp-btn acc" onClick=${() => { close(); act(() => post("/api/print/tune", { speed, flow })); }}>Übernehmen</button>
          <button type="button" class="disp-btn" onClick=${close}>Zurück</button>
        </div>`}
      ${tab === "z" && html`
        <div class="disp-row"><div class="grow"><div class="disp-lbl">Z-Versatz jetzt</div>
          <div class="disp-val">${fmt(m?.z_offset)}<small> mm</small></div></div>
          <div class="grow"><div class="disp-lbl">in diesem Druck nachgestellt</div>
          <div class="disp-val">${fmt(m?.z_session)}<small> mm</small></div></div></div>
        <div class="disp-zsteps">
          ${[...(m?.z_steps || [0.01, 0.025, 0.05])].reverse().map((d) => html`<button type="button" class="disp-btn"
            onClick=${() => z(-d)}>−${String(d).replace(".", ",")}<small> näher</small></button>`)}
          ${(m?.z_steps || [0.01, 0.025, 0.05]).map((d) => html`<button type="button" class="disp-btn"
            onClick=${() => z(d)}>+${String(d).replace(".", ",")}<small> weiter weg</small></button>`)}
        </div>
        ${msg && html`<div class="disp-alert warn">${msg}</div>`}
        <div style="flex:1"></div>
        <div class="disp-btns">
          <button type="button" class="disp-btn acc" disabled=${!m?.z_filament || !m?.z_session}
            onClick=${() => act(async () => { const r = await post("/api/machine-z/save", {});
              setMsg(`${r.filament}: Z-Versatz ${fmt(r.old)} → ${fmt(r.new)} mm (gilt ab dem nächsten Druck)`); await loadM(); })}>
            ${m?.z_filament ? `Für ${m.z_filament.name} übernehmen` : "Kein Filament geladen"}</button>
          <button type="button" class="disp-btn" onClick=${close}>Fertig</button>
        </div>`}
      ${tab === "obj" && html`
        ${objects.length === 0 ? html`<div class="disp-empty">Die Datei hat keine benannten Objekte<br/>(in Orca „Objekte beschriften“ einschalten).</div>`
          : html`<div class="disp-objs">${objects.map((o) => html`<button type="button" class=${"disp-btn" + (o.current ? " acc" : "")}
            disabled=${o.excluded} onClick=${() => act(withConfirm("/api/machine/exclude", { name: o.name }))}>
            ${o.excluded ? "✕ " : ""}${o.name}${o.current ? " · druckt gerade" : ""}</button>`)}</div>`}
        <div style="flex:1"></div>
        <div class="disp-btns"><button type="button" class="disp-btn" onClick=${close}>Fertig</button></div>`}
    </section>
  </div>`;
}

// ------------------------------------------------------------ Druck fertig
function Done({ st, busy, setDlg }) {
  const p = st.printer || {};
  const ok = p.state === "complete";
  const file = p.file || "";
  const used = (st.uses || []).filter((u) => u.total_g);
  return html`<div class="disp-print">
    <section class="disp-thumb" aria-label="Vorschau">
      <div class="img"><img src=${`/api/print/thumbnail.png?f=${encodeURIComponent(file)}`} alt="Vorschaubild"
        onError=${(e) => { e.target.style.display = "none"; }} /></div>
      <div class="file">${fileName(file)}</div>
    </section>
    <div class="disp-pcol">
      <h2 class="disp-done" style=${`color:${ok ? "var(--ok-text)" : "var(--danger-text)"}`}>${ok ? "Druck fertig" : p.state === "cancelled" ? "Druck abgebrochen" : "Druck mit Fehler beendet"}</h2>
      <div class="disp-grid2" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">Druckzeit</div><div class="disp-val">${hm(p.print_duration_s)}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Fortschritt</div><div class="disp-val">${pct(p.progress)} %</div></div>
      </div>
      ${used.length > 0 && html`<div class="disp-lbl">Verbraucht</div>
        ${used.map((u) => html`<div class="disp-row" style="gap:10px"><span class="disp-dot" style=${`background:${hex(u.color) || "var(--surface2)"}`}></span>
          <span class="grow">Slot ${u.slot} · ${u.name}</span><b class="m">${String(u.total_g).replace(".", ",")} g</b></div>`)}`}
      <div style="flex:1"></div>
      <div class="disp-btns">
        <button type="button" class="disp-btn acc" disabled=${busy || !file} onClick=${() => setDlg({ kind: "start", path: file })}>Erneut drucken …</button>
      </div>
    </div>
  </div>`;
}

// ------------------------------------------------------------ Dateien
function Files({ busy, setDlg }) {
  const [files, setFiles] = useState(null);
  const [err, setErr] = useState(null);
  const [pageNo, setPageNo] = useState(0);
  useEffect(() => { get("/api/files").then((r) => setFiles(r.files)).catch((e) => setErr(e.message)); }, []);
  if (err) return html`<div class="disp-empty">${err}</div>`;
  if (!files) return html`<div class="disp-empty">Lade Dateien …</div>`;
  if (!files.length) return html`<div class="disp-empty">Keine Druckdateien am Drucker.</div>`;
  const pages = Math.ceil(files.length / PAGE_SIZE);
  const shown = files.slice(pageNo * PAGE_SIZE, pageNo * PAGE_SIZE + PAGE_SIZE);
  return html`<div class="disp-files">
    <div class="disp-flist">${shown.map((f) => html`<button type="button" class="disp-file" disabled=${busy}
      onClick=${() => setDlg({ kind: "start", path: f.path })}>
      <span class="th">${f.thumb && html`<img src=${`/api/files/thumb?path=${encodeURIComponent(f.path)}`} alt="" />`}</span>
      <span class="t"><b>${fileName(f.path)}</b><span>${[f.est_s ? hm(f.est_s) + " h" : null, f.weight_g ? Math.round(f.weight_g) + " g" : null,
        f.modified ? new Date(f.modified * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) : null].filter(Boolean).join(" · ")}</span></span>
      <span class="dots">${f.tools.map((t) => html`<span class="disp-dot" style=${`width:18px;height:18px;background:${hex(t.color) || "var(--surface2)"}`}></span>`)}</span>
    </button>`)}</div>
    <div class="disp-pager">
      <button type="button" class="disp-btn" disabled=${pageNo === 0} aria-label="Seite zurück" onClick=${() => setPageNo(pageNo - 1)}>▲</button>
      <span class="disp-note m">${pageNo + 1}/${pages}</span>
      <button type="button" class="disp-btn" disabled=${pageNo >= pages - 1} aria-label="Seite vor" onClick=${() => setPageNo(pageNo + 1)}>▼</button>
    </div>
  </div>`;
}

function StartPrint({ path, close, act }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { get("/api/files/check?path=" + encodeURIComponent(path)).then(setC).catch((e) => setErr(e.message)); }, [path]);
  return html`<div class="disp-over" role="dialog" aria-label="Druck starten">
    <section class="disp-dialog" style="height:100%">
      <div class="disp-split">
        <div class="disp-thumb" style="width:200px">
          <div class="img" style="height:200px"><img src=${`/api/files/thumb?path=${encodeURIComponent(path)}`} alt="Vorschaubild"
            onError=${(e) => { e.target.style.display = "none"; }} /></div>
          <div class="file">${fileName(path)}</div>
          ${c && html`<div class="disp-note m">${[c.est_s ? hm(c.est_s) + " h" : null, c.weight_g ? Math.round(c.weight_g) + " g" : null].filter(Boolean).join(" · ")}</div>`}
        </div>
        <div style="flex:1;display:flex;flex-direction:column;gap:8px;min-width:0">
          <h2>Drucken?</h2>
          ${err && html`<div class="disp-alert">${err}</div>`}
          ${!c && !err && html`<div class="disp-note">Prüfe Slots …</div>`}
          ${c && c.tools.map((t) => html`<div class="disp-tile disp-row" style="gap:10px;padding:8px 12px">
            <span class="disp-dot" style=${`background:${hex(t.color) || "var(--surface2)"}`} title="Datei"></span>
            <span class="disp-note">→</span>
            <span class="disp-dot" style=${`background:${hex(t.have_color) || "var(--surface2)"}`} title="Slot"></span>
            <span class="grow disp-tool"><span><b>Slot ${t.slot}</b> · ${t.have_name || "keine Spule"}</span>
              <span class=${t.hints.length ? "warn" : "ok"}>${t.hints.length ? t.hints.join(" · ") : `passt${t.type ? ` (Datei: ${t.type})` : ""}`}</span></span></div>`)}
          <div style="flex:1"></div>
          <div class="disp-btns">
            <button type="button" class=${"disp-btn " + (c && !c.ok ? "danger" : "acc")} disabled=${!c}
              onClick=${() => { close(); act(() => post("/api/files/start", { path, confirm: true })); }}>${c && !c.ok ? "Trotzdem drucken" : "Drucken"}</button>
            <button type="button" class="disp-btn" onClick=${close}>Zurück</button>
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
  useEffect(() => { get("/api/system").then(setInfo).catch(() => setInfo({})); }, []);
  const msgs = st.notices?.messages || [];
  const printing = PRINTING.has(st.printer?.state);
  const colour = { error: "var(--danger-text)", warn: "var(--accent-text)" };
  return html`
    <div class="disp-tabs" role="tablist">${[["msg", `Meldungen${msgs.length ? ` (${msgs.length})` : ""}`], ["info", "Info & Neustart"]].map(([k, l]) =>
      html`<button type="button" role="tab" aria-selected=${tab === k} class=${tab === k ? "on" : ""} onClick=${() => setTab(k)}>${l}</button>`)}</div>
    ${tab === "msg" && html`<div class="disp-msgs">${msgs.length === 0 ? html`<div class="disp-empty">Keine Meldungen.</div>`
      : msgs.slice(0, 7).map((m) => html`<div class="disp-tile" style=${`padding:7px 12px;color:${colour[m.level] || "var(--text)"}`}>${m.text}</div>`)}
      ${msgs.length > 7 && html`<div class="disp-note">… und ${msgs.length - 7} weitere (Web/App)</div>`}</div>`}
    ${tab === "info" && html`
      <div class="disp-grid2" style="gap:8px">
        <div class="disp-tile disp-mini"><div class="disp-lbl">IP des Pi</div><div class="disp-val" style="font-size:17px">${(info?.ips || []).join(", ") || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Klipper</div><div class="disp-val" style="font-size:17px">${info?.klippy_state || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Bridge</div><div class="disp-val" style="font-size:17px">${info?.bridge || st.version || "–"}</div></div>
        <div class="disp-tile disp-mini"><div class="disp-lbl">Klipper-Version</div><div class="disp-val" style="font-size:13px">${info?.klipper || "–"}</div></div>
      </div>
      <div style="flex:1"></div>
      <div class="disp-btns">
        <button type="button" class="disp-btn" disabled=${busy || printing} onClick=${() => confirm({ title: "Klipper neu laden?", ok: "Neu laden",
          text: "Dauert einige Sekunden; die Achsen müssen danach neu gehomt werden.", action: () => post("/api/print/firmware_restart", { confirm: true }) })}>Klipper neu laden</button>
        <button type="button" class="disp-btn" disabled=${busy || printing} onClick=${() => confirm({ title: "Pi neu starten?", ok: "Neu starten",
          text: "Klipper und das Display sind etwa eine Minute weg.", action: () => post("/api/system/reboot", { confirm: true }) })}>Pi neu starten</button>
        <button type="button" class="disp-btn danger" disabled=${busy || printing} onClick=${() => confirm({ title: "Pi herunterfahren?", ok: "Herunterfahren", danger: true,
          text: "Danach erst den Strom trennen. Wieder an geht nur über Strom aus/an am Pi.", action: () => post("/api/system/shutdown", { confirm: true }) })}>Pi herunterfahren</button>
      </div>
      ${printing && html`<div class="disp-note">Während eines Drucks gesperrt.</div>`}`}`;
}

// ------------------------------------------------------------ Ueberlagerungen: Rueckfrage eines Makros, Klipper-Fehler
function Prompt({ st, busy, act }) {
  const q = st.prompt;
  const answer = (id) => act(() => post("/api/prompt", { id }));
  const style = (s) => (s === "error" ? " danger" : s === "primary" || s === "warning" ? " acc" : "");
  return html`<div class="disp-over" role="alertdialog" aria-label=${q.title}>
    <section class="disp-dialog">
      <div class="disp-row"><h2 class="grow">${q.title}</h2>
        <button type="button" class="disp-btn" aria-label="Schließen" style="min-width:56px" onClick=${() => act(() => post("/api/prompt/close", {}))}>✕</button></div>
      ${q.text.map((t) => html`<p>${t}</p>`)}
      ${q.rows.map((row) => html`<div class="disp-btns">${row.map((b) => html`<button type="button" class=${"disp-btn" + style(b.style)}
        disabled=${busy} onClick=${() => answer(b.id)}>${b.label}</button>`)}</div>`)}
      ${q.footer.length > 0 && html`<div class="disp-btns">${q.footer.map((b) => html`<button type="button" class=${"disp-btn" + style(b.style)}
        disabled=${busy} onClick=${() => answer(b.id)}>${b.label}</button>`)}</div>`}
    </section>
  </div>`;
}

function KlippyDown({ busy, confirm }) {
  const [info, setInfo] = useState(null);
  useEffect(() => { get("/api/system").then(setInfo).catch(() => setInfo(null)); }, []);
  return html`<div class="disp-over" role="alertdialog" aria-label="Klipper nicht bereit">
    <section class="disp-dialog danger">
      <h2>Klipper ist nicht bereit</h2>
      <p class="muted" style="white-space:pre-line;max-height:190px;overflow:hidden">${info?.klippy_message || "Not-Aus, Fehler oder Verbindung zu den Platinen weg."}</p>
      <div class="disp-btns">
        <button type="button" class="disp-btn acc" disabled=${busy} onClick=${() => confirm({ title: "Klipper neu laden?", ok: "Neu laden",
          text: "Die Achsen müssen danach neu gehomt werden.", action: () => post("/api/print/firmware_restart", { confirm: true }) })}>Klipper neu laden</button>
      </div>
    </section>
  </div>`;
}

render(html`<${Display} />`, document.getElementById("app"));
