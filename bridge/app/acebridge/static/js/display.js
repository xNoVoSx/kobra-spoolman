// Drucker-Display (800x480, Kiosk-Browser auf dem Klipper-Pi, ueber VNC auf dem Original-Display des Kobra S1).
// Start (Status, Slots, Trockner), Druck (kommt bei Druckstart von selbst: Vorschaubild, Fortschritt, Zeiten,
// Temperaturen, Steuerung), Schalter (alle Module, gespeichert im Drucker), Druck unterbrochen (nach Stromausfall).
// Liest ohne Schluessel; zum Schalten einmal koppeln (6-stelliger Code aus Web/App, "Geraet hinzufuegen").

import { html, render, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get, post } from "./api.js";
import { duration, fileName, finishAt, hex, printerLook } from "./util.js";

const POLL_MS = 2000;
const PRINTING = new Set(["printing", "paused"]);

// ------------------------------------------------------------ Symbole (Linien, wie im Entwurf)
const ICONS = {
  home: html`<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>`,
  print: html`<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 17v4h10v-4"/>`,
  switch: html`<rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="16" cy="12" r="3"/>`,
  light: html`<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>`,
  power: html`<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>`,
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
      ${[["start", "home", "Start"], ["print", "print", "Druck"], ["switch", "switch", "Schalter"]].map(([k, i, l]) =>
        html`<button type="button" class=${"disp-nav" + (page === k ? " on" : "")} aria-label=${l} onClick=${() => setPage(k)}><${Icon} name=${i} /></button>`)}
      <div class="grow"></div>
      ${light && html`<button type="button" class=${"disp-nav lit" + (light.on ? " on" : "")} aria-label=${light.on ? "Licht aus" : "Licht an"}
        disabled=${!light.sensitive || busy} onClick=${() => flip("light", !light.on)}><${Icon} name="light" /></button>`}
    </nav>
    <main class="disp-main">
      <header class="disp-head">
        <h1>${page === "switch" ? "Schalter" : "Kobra S1"}</h1>
        <span class="disp-chip" style=${`color:${look.fg};background:${look.bg};border-color:${look.line}`}>${look.label}</span>
        ${down && html`<span class="disp-chip" style="color:var(--danger-text);border-color:var(--danger-line)">Bridge weg</span>`}
        <div class="grow"></div>
        <span class="disp-clock">${now}</span>
      </header>
      ${page !== "switch" && errors.slice(0, 1).map((m) => html`<div class="disp-alert">${m.text}</div>`)}
      ${page === "start" && html`<${Start} ...${ctx} />`}
      ${page === "print" && html`<${Print} ...${ctx} />`}
      ${page === "switch" && html`<${Switches} ...${ctx} />`}
    </main>
    <${Resume} ...${ctx} />
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
    <div class="name">${sp ? `${sp.material || ""} ${sp.name?.replace(sp.material || "", "").trim() || ""}`.trim()
      : ace.present ? (ace.material || "Unbekannt") : "leer"}</div>
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
    return html`<div class="disp-empty">Kein Druck. Gestartet wird in Orca oder Mainsail –<br/>die Druckansicht kommt dann von selbst.</div>`;
  }
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
          ? html`<button type="button" class="disp-btn acc" disabled=${busy} onClick=${() => act(() => post("/api/print/resume", {}))}>Weiter</button>`
          : html`<button type="button" class="disp-btn" disabled=${busy} onClick=${() => act(() => post("/api/print/pause", {}))}>Pause</button>`}
        <button type="button" class="disp-btn" disabled=${busy} onClick=${() => setDlg({ kind: "tune" })}>Nachjustieren</button>
        <button type="button" class="disp-btn danger" disabled=${busy} onClick=${() => confirm({ title: "Druck abbrechen?", ok: "Abbrechen", danger: true,
          text: `${fileName(file)} wird abgebrochen. Das lässt sich nicht rückgängig machen.`,
          action: () => post("/api/print/cancel", { confirm: true }) })}>Abbrechen</button>
      </div>`}
    </div>
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

function Tune({ close, act, p }) {
  const [speed, setSpeed] = useState(pct(p.speed_factor || 1));
  const [flow, setFlow] = useState(pct(p.flow_factor || 1));
  const step = (v, set, d, lo, hi) => set(Math.max(lo, Math.min(hi, v + d)));
  const row = (label, v, set, lo, hi) => html`<div class="disp-row"><b class="grow">${label}</b><div class="disp-step">
    <button type="button" class="disp-btn" onClick=${() => step(v, set, -5, lo, hi)}>−5</button>
    <span class="v">${v} %</span>
    <button type="button" class="disp-btn" onClick=${() => step(v, set, 5, lo, hi)}>+5</button></div></div>`;
  return html`<div class="disp-over" role="dialog" aria-label="Nachjustieren">
    <section class="disp-dialog">
      <h2>Nachjustieren</h2>
      ${row("Tempo", speed, setSpeed, 10, 300)}
      ${row("Fluss", flow, setFlow, 50, 150)}
      <div class="disp-btns">
        <button type="button" class="disp-btn acc" onClick=${() => { close(); act(() => post("/api/print/tune", { speed, flow })); }}>Übernehmen</button>
        <button type="button" class="disp-btn" onClick=${close}>Zurück</button>
      </div>
    </section>
  </div>`;
}

render(html`<${Display} />`, document.getElementById("app"));
