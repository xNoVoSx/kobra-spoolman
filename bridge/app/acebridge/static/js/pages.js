// Seiten. Welche Seite, entscheidet die Adresse (#/filament ...); wie viel nebeneinander passt, die Breite.

import { HumidityCard } from "./humidity.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, del, get, post } from "./api.js";
import { AceCard } from "./ace.js";
import { DryerCard, JobCard, JobsList, OpenItemsCard, OrcaCard, PrinterCard, Slots, Swatch } from "./components.js";
import { NoticesCard } from "./notices.js";
import { FilamentEditor, FilamentList } from "./filaments.js";
import { Icon } from "./icons.js";
import { capability, quality, setQuality } from "./viewer3d.js";
import { cameraKey, cameraUrl } from "./media.js";
import { SpoolDetail, SpoolList } from "./spools.js";
import { S, guard, loadCatalog, loadHealth, loadJobs, openDialog, set, toast } from "./store.js";
import { ago, cls, grams, num, when } from "./util.js";

// ------------------------------------------------------------ Uebersicht
// Druckermonitor: Drucker (Kamera) gross, daneben Meldungen & Status, Trockner, ACE; darunter die Slots.
// Verwalten (Spulen, Sorten, Drucke) hat eigene Tabs.
export function Overview() {
  const open = (S.st?.usage?.open || []).length > 0;
  return html`
  <div class="ov2">
    <div class="ov2-printer"><${PrinterCard} /></div>
    <div class="ov2-side">
      <div class="o-notices"><${NoticesCard} /></div>
      <div class="o-dryer"><${DryerCard} /></div>
      <div class="o-ace"><${AceCard} compact /></div>
      ${open && html`<div class="o-open"><${OpenItemsCard} /></div>`}
    </div>
    <div class="ov2-slots col" style="gap:14px">
      <div class="sec-head"><span class="lbl">ACE 2 Pro · Slots</span>
        <span class="small muted">Zuordnen schreibt Material und Farbe auch ans Druckerdisplay (Spulen ohne Tag)</span></div>
      <${Slots} />
    </div>
  </div>`;
}

/** 5120 px und mehr: Drucker gross, Slots + ACE, Meldungen - alles auf einen Blick, ohne Verwaltung. */
export function Ultra() {
  const open = (S.st?.usage?.open || []).length > 0;
  return html`
  <div class="ultra">
    <div class="ucol"><${PrinterCard} tall /></div>
    <div class="ucol">
      <div class="sec-head"><span class="lbl">ACE 2 Pro · Slots</span><span class="small muted">Zuordnen schreibt auch ans Druckerdisplay</span></div>
      <${Slots} />
      <div class="ugrid2"><${DryerCard} /><${AceCard} compact /></div>
    </div>
    <div class="ucol">
      <${NoticesCard} />
      ${open && html`<${OpenItemsCard} />`}
    </div>
  </div>`;
}

// ------------------------------------------------------------ Filament: Spulen | Sorten
/** Unterseite aus der Adresse: #/filament/sorten, alt #/filamente; sonst Spulen. */
export function filamentView() {
  const parts = location.hash.replace(/^#\/?/, "").split(/[/?]/);
  if (parts[0] === "filamente" || parts[1] === "sorten") return "sorten";
  return "spulen";
}

export function FilamentHub() {
  const [view, setView] = useState(filamentView());
  useEffect(() => {
    const on = () => setView(filamentView());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const tab = (k, label, n) => html`<a href=${"#/filament/" + k} role="tab" aria-selected=${view === k} class=${cls("seg-btn", view === k && "on")}>${label}${n != null && html` <span class="m muted">${n}</span>`}</a>`;
  return html`<div class="hub">
    <div class="seg" role="tablist" aria-label="Filament">
      ${tab("spulen", "Spulen", S.spools?.length)}${tab("sorten", "Sorten", S.catalog?.filaments?.length)}
    </div>
    ${view === "sorten" ? html`<${FilamentPage} />` : html`<${RegalPage} />`}
  </div>`;
}

function RegalPage() {
  return html`<div class=${cls("split", S.sel != null && "has-sel")}>
    <${SpoolList} wideCols=${window.innerWidth > 1500} />
    <${SpoolDetail} id=${S.sel} onBack=${() => set({ sel: null })} />
  </div>`;
}

function FilamentPage() {
  useEffect(() => { loadCatalog(); }, []);
  return html`<div class=${cls("split", S.selFil != null && "has-sel")}>
    <${FilamentList} />
    <section class="card detail">
      ${S.selFil == null ? html`<div class="empty-state" style="margin:auto">Filament wählen oder neu anlegen.</div>`
        : html`<button class="btn ghost back" style="margin:12px 12px 0" onClick=${() => set({ selFil: null })}><${Icon} name="back" small />Filamente</button>
               <${FilamentEditor} key=${S.selFil} fid=${S.selFil} />
               <${SpoolsOfFilament} fid=${S.selFil} />`}
    </section>
  </div>`;
}

/** Querverweis Sorte -> Spulen: Tippen oeffnet die Spule unter "Spulen". */
function SpoolsOfFilament({ fid }) {
  const list = (S.spools || []).filter((s) => s.filament_id === fid);
  if (fid === "neu" || !list.length) return null;
  return html`<div class="dbody col" style="gap:8px;padding-top:0">
    <p class="section-title">Spulen dieser Sorte</p>
    ${list.map((s) => html`<a class="row spool-link" href="#/filament/spulen" onClick=${() => set({ sel: s.spool_id })}>
      <${Swatch} color=${s.color} size=${18} /><span class="grow">#${s.spool_id} · ${s.slot ? `ACE ${s.slot}` : s.location || "Regal"}</span>
      <span class="m small">${grams(s.remaining_weight)}</span></a>`)}
  </div>`;
}

// ------------------------------------------------------------ Drucke
export function JobsPage() {
  useEffect(() => { loadJobs(); }, []);
  const live = S.st?.usage?.live;
  const jobs = S.jobs || [];
  const totalG = jobs.reduce((a, j) => a + j.slots.reduce((b, s) => b + (s.g || 0), 0), 0);
  return html`<div class="col" style="max-width:1600px">
    <div class="row"><h1 class="h1">Drucke</h1><span class="m small muted">${jobs.length} aufgezeichnet · ${num(totalG / 1000)} kg</span></div>
    ${(S.st?.usage?.open || []).length > 0 && html`<${OpenItemsCard} />`}
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px">
      ${live && html`<${JobCard} job=${live} live />`}
      ${jobs.map((j) => html`<${JobCard} key=${j.job} job=${j} />`)}
    </div>
    ${!live && !jobs.length && html`<div class="empty-state">Noch keine Drucke aufgezeichnet.</div>`}
  </div>`;
}

// ------------------------------------------------------------ Trockner
export function AcePage() {
  const d = S.st?.dryer;
  const req = d?.required || {};
  return html`<div class="col" style="max-width:1100px">
    <h1 class="h1">ACE</h1>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px;align-items:start">
      <${DryerCard} big />
      <${AceCard} />
    </div>
    ${d?.present && html`<section class="card pad col">
      <h2 class="h2">Temperaturgrenze</h2>
      <div class="kv">${(req.slots || []).map((p) => html`<span>Slot ${p.slot} · ${p.name} <span class="faint">(${{ filament: "am Filament", vorlage: "aus Vorlage", standard: "Materialwert" }[p.source] || p.source})</span></span>
        <span class="m" style=${{ color: (req.limited_by || []).includes(p.slot) ? "var(--accent)" : "" }}>${p.temp} °C</span>`)}
        <span>ACE höchstens</span><span class="m">${req.ace_max ?? "–"} °C</span></div>
      <div class="small muted">Eigene Grenze pro Filament im Feld „Trocknen max.“ (Filamente → Temperaturen).</div>
    </section>`}
    ${d?.present && html`<${HumidityCard} />`}
  </div>`;
}

// ------------------------------------------------------------ Geraete
export function DevicesPage() {
  const [list, setList] = useState(null);
  const load = () => get("/api/auth/devices").then((r) => setList(r.devices)).catch((e) => toast(e.message, "bad"));
  useEffect(() => { if (S.me) load(); }, [S.me]);
  useEffect(() => { if (!S.dialog && S.me) load(); }, [S.dialog]);
  const KIND = { app: ["Handy-App", "phone"], web: ["Browser", "overview"], plugin: ["Orca-Plugin", "drop"], other: ["Sonstiges", "key"] };
  const remove = (d) => openDialog("confirm", {
    title: d.me ? "Diesen Browser entkoppeln?" : `„${d.name}“ entfernen?`,
    text: d.me ? "Der Browser vergisst seinen Schlüssel; zum Ändern muss er neu gekoppelt werden." : "Das Gerät kann danach nichts mehr ändern, bis es neu gekoppelt ist.",
    ok: d.me ? "Entkoppeln" : "Entfernen", danger: true,
    action: async () => {
      await del(`/api/auth/devices/${d.id}`);
      if (d.me) { auth.clear(); set({ me: null, pairing: true }); } else load();
      toast("Entfernt", "ok");
    },
  });
  if (!S.me) return html`<div class="col" style="max-width:900px"><h1 class="h1">Geräte</h1><div class="note">Dieser Browser ist nicht gekoppelt. <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>Jetzt koppeln</a></div></div>`;
  return html`<div class="col" style="max-width:900px">
    <div class="row"><h1 class="h1 grow">Geräte</h1><button class="btn acc" onClick=${() => openDialog("addDevice")}><${Icon} name="plus" small />Gerät hinzufügen</button></div>
    <div class="small muted">Jedes Gerät hat einen eigenen Schlüssel. Lesen geht ohne, ändern nur gekoppelt.</div>
    <section class="card">
      ${list == null && html`<div class="empty-state">lade …</div>`}
      ${(list || []).map((d, i) => html`
        <div class="row" style=${{ padding: "14px 18px", borderTop: i ? "1px solid var(--line)" : "0" }}>
          <span style="color:var(--muted)"><${Icon} name=${(KIND[d.kind] || KIND.other)[1]} /></span>
          <div class="grow"><b>${d.name}</b>${d.me && html` <span class="chip on">dieser Browser</span>`}
            <div class="small muted">${(KIND[d.kind] || KIND.other)[0]} · gekoppelt ${when(new Date(d.created * 1000).toISOString())} · zuletzt ${ago(d.last_seen)}</div></div>
          ${d.id !== "app_token" && html`<button class="btn sm danger" onClick=${() => remove(d)}>${d.me ? "Entkoppeln" : "Entfernen"}</button>`}
        </div>`)}
    </section>
    <${CameraLinkCard} />
  </div>`;
}

/** Kamera-Link fuer Mainsail & Co.: alle schauen ueber die Bridge, zum Drucker geht nur eine Verbindung. */
function CameraLinkCard() {
  const [key, setKey] = useState(null);
  useEffect(() => { cameraKey(true).then(setKey).catch((e) => toast(e.message, "bad")); }, []);
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast("Kopiert", "ok"); } catch { toast("Kopieren nicht möglich – Text markieren", "bad"); }
  };
  const rotate = () => openDialog("confirm", {
    title: "Neuen Kamera-Link erzeugen?",
    text: "Der alte Link (z. B. in Mainsail eingetragen) zeigt danach kein Bild mehr und muss ersetzt werden.",
    ok: "Neu erzeugen", danger: true,
    action: async () => { setKey((await post("/api/camera/link")).key); await cameraKey(true); toast("Neuer Kamera-Link", "ok"); },
  });
  const Line = ({ label, url }) => html`<span style="align-self:center">${label}</span><span class="row" style="gap:8px;min-width:0">
    <span class="m small grow" style="overflow-wrap:anywhere">${url}</span>
    <button class="btn sm icon ghost" aria-label=${label + " kopieren"} onClick=${() => copy(url)}><${Icon} name="copy" small /></button></span>`;
  return html`<section class="card pad col">
    <div class="row"><h2 class="h2 grow">Kamera-Link</h2><button class="btn sm" disabled=${!key} onClick=${rotate}>Neu erzeugen</button></div>
    <div class="small muted">Für Mainsail (Einstellungen → Webcams, Dienst „MJPEG-Streamer“) und andere Programme ohne Kopplung.
      Alle Zuschauer laufen über die Bridge, der Drucker liefert den Stream nur einmal. Der Link zeigt nur die Kamera.</div>
    ${key ? html`<div class="kv"><${Line} label="Stream" url=${cameraUrl(key)} /><${Line} label="Einzelbild" url=${cameraUrl(key, "snapshot.jpg")} /></div>`
          : html`<div class="small muted">lade …</div>`}
  </section>`;
}

// ------------------------------------------------------------ Einstellungen / Info
/** Eine Zahl: erst bei Enter oder Verlassen des Feldes speichern; Bereich und Einheit daneben. */
function NumSetting({ it, save }) {
  const [v, setV] = useState(String(it.value).replace(".", ","));
  useEffect(() => setV(String(it.value).replace(".", ",")), [it.value]);
  const commit = () => { const n = Number(v.replace(",", ".")); if (v.trim() !== "" && n !== it.value) save(it.key, n); };
  return html`<label class="row small" style="gap:6px">
    <input class="set-num" inputmode="decimal" value=${v} onInput=${(e) => setV(e.target.value)} onBlur=${commit}
      onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); }} aria-label=${it.label} />
    <span class="muted">${it.unit}</span></label>`;
}

/** Text: erst bei Enter oder Verlassen des Feldes speichern. */
function TextSetting({ it, save }) {
  const [v, setV] = useState(it.value || "");
  useEffect(() => setV(it.value || ""), [it.value]);
  return html`<input class="set-text" value=${v} placeholder="Trockenbox=15" onInput=${(e) => setV(e.target.value)}
    onBlur=${() => { if (v !== (it.value || "")) save(it.key, v); }} onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); }} aria-label=${it.label} />`;
}

/** Einstellungen der Bridge, im Betrieb aenderbar (gespeichert in der Bridge; Umgebung = Startwert). */
function BridgeSettings() {
  const [v, setV] = useState(null);
  useEffect(() => { get("/api/settings").then(setV).catch((e) => toast(e.message, "bad")); }, []);
  if (!v) return null;
  const save = guard(async (key, value) => { setV(await post("/api/settings", { [key]: value })); toast("Gespeichert", "ok"); });
  const reset = guard(async (key) => { setV(await post("/api/settings/reset", { key })); toast("Standard wiederhergestellt", "ok"); });
  const fmt = (it, x) => (it.kind === "bool" ? (x ? "an" : "aus") : it.kind === "choice" ? (it.options.find((o) => o[0] === x)?.[1] || x)
    : it.kind === "text" ? (x || "leer") : `${String(x).replace(".", ",")} ${it.unit}`.trim());
  return html`
    ${v.groups.map((g) => html`<section class="card pad col">
      <h2 class="h2">${g.name}</h2>
      ${g.items.map((it) => html`<div class="set-row">
        <div class="grow"><div>${it.label}</div>
          ${it.help && html`<div class="small muted">${it.help}</div>`}
          ${it.kind !== "bool" && it.min != null && html`<div class="small faint">erlaubt ${String(it.min).replace(".", ",")}–${String(it.max).replace(".", ",")} ${it.unit}</div>`}
          ${it.changed && html`<div class="small" style="color:var(--accent-text)">geändert · Standard ${fmt(it, it.default)} <button class="linkbtn" onClick=${() => reset(it.key)}>zurücksetzen</button></div>`}</div>
        ${it.kind === "bool" ? html`<label class="toggle"><input type="checkbox" role="switch" checked=${!!it.value} onChange=${(e) => save(it.key, e.target.checked)} aria-label=${it.label} /><span class="knob" aria-hidden="true"></span></label>`
          : it.kind === "choice" ? html`<select value=${it.value} onChange=${(e) => save(it.key, e.target.value)} aria-label=${it.label}>${it.options.map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select>`
          : it.kind === "text" ? html`<${TextSetting} it=${it} save=${save} />`
          : html`<${NumSetting} it=${it} save=${save} />`}
      </div>`)}
    </section>`)}
    <section class="card pad col">
      <h2 class="h2">Weitere Einstellungen</h2>
      <div class="row wrap"><a class="btn sm" href="#/ace">Trockner-Regeln (ACE)</a><a class="btn sm" href="#/ki">KI</a><a class="btn sm" href="#/geraete">Geräte</a></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">Verbindungen</h2>
      <div class="kv">${v.readonly.map((r) => html`<span>${r.label}</span><span class="m">${r.value === "" || r.value == null ? "–" : String(r.value)}</span>`)}</div>
      <div class="small muted">Diese brauchen einen Neustart der Bridge: im Stack (Umgebungsvariablen) ändern und neu ausrollen.</div>
    </section>`;
}

/** Einstellungen, die nur in diesem Browser gelten (localStorage). */
function DeviceCard() {
  const [q, setQ] = useState(quality());
  const found = { volume: "Volumen", lines: "Linien", image: "Bild" }[capability()];
  const opts = [["auto", `Automatisch (hier: ${found})`], ["volume", "Volumen – schattierte Stränge"], ["lines", "Linien – spart Grafikleistung"], ["image", "Bild der Bridge – für schwache Geräte"]];
  return html`<section class="card pad col">
    <h2 class="h2">Dieses Gerät</h2>
    <div class="row wrap"><span class="grow">3D-Modell</span>
      <select value=${q} onChange=${(e) => { setQuality(e.target.value); setQ(e.target.value); toast("Gilt ab dem nächsten Öffnen der Modell-Ansicht", "ok"); }} aria-label="3D-Modell">
        ${opts.map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <div class="small muted">Gilt nur in diesem Browser. Die App hat dieselbe Einstellung unter Einstellungen.</div>
  </section>`;
}

export function SettingsPage() {
  useEffect(() => { loadHealth(); }, []);
  const h = S.health;
  return html`<div class="col" style="max-width:1100px">
    <h1 class="h1">Einstellungen</h1>
    <section class="card pad col">
      <h2 class="h2">Dieser Browser</h2>
      ${S.me ? html`<div class="row"><span class="grow">Gekoppelt als <b>${S.me.name}</b></span><a class="btn sm" href="#/geraete">Geräte verwalten</a></div>`
             : html`<div class="row"><span class="grow muted">Nicht gekoppelt – nur Ansehen.</span><button class="btn sm acc" onClick=${() => set({ pairing: true })}>Koppeln</button></div>`}
    </section>
    <${DeviceCard} />
    <${OrcaCard} />
    ${h && html`
    <section class="card pad col">
      <h2 class="h2">Bridge ${h.version}</h2>
      <div class="kv">
        <span>Läuft seit</span><span>${when(h.started)}</span>
        <span>Drucker</span><span class="m">${h.moonraker.url}</span>
        <span>Spoolman</span><span><a href=${h.links?.spoolman || h.spoolman.url} target="_blank" rel="noopener">${h.links?.spoolman || h.spoolman.url}</a></span>
        ${h.links?.printer_ui && html`<span>Drucker-Oberfläche</span><span><a href=${h.links.printer_ui} target="_blank" rel="noopener">${h.links.printer_ui}</a></span>`}
        <span>Firmware-Spoolman</span><span>${h.firmware_spoolman_support ? html`<span class="chip bad">an – doppelte Buchung!</span>` : "aus"}</span>
      </div>
    </section>
    <${BridgeSettings} />
    <section class="card pad col">
      <h2 class="h2">Neu in der Bridge</h2>
      ${h.changelog.map((c) => html`<div><b class="m">${c.version}</b> <span class="muted small">${c.date}</span><ul style="margin:6px 0 0;padding-left:20px">${c.items.map((i) => html`<li class="small">${i}</li>`)}</ul></div>`)}
    </section>`}
    <div class="small faint">Schriften: Space Grotesk, IBM Plex (SIL OFL) · Preact, htm, qrcode-generator – Lizenztexte liegen in der Bridge unter static/licenses.</div>
  </div>`;
}

// ------------------------------------------------------------ Koppeln (erster Start)
function deviceName() {
  const ua = navigator.userAgent;
  const browser = /Firefox\//.test(ua) ? "Firefox" : /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return `${browser}${os ? " · " + os : ""}`;
}

export function PairPage({ reason }) {
  const [digits, setDigits] = useState(["", "", "", "", "", ""]);
  const [long, setLong] = useState("");
  const [useLong, setUseLong] = useState(false);
  const [name, setName] = useState(deviceName());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const refs = useRef([]);
  const code = useLong ? long.trim() : digits.join("");
  useEffect(() => { refs.current[0]?.focus(); }, []);
  const setAt = (i, val) => {
    let clean = val.replace(/\D/g, "");
    if (clean.length === 2 && digits[i]) clean = clean.replace(digits[i], "") || clean.slice(-1);   // Feld ueberschrieben
    if (clean.length > 1) {          // eingefuegt
      const next = clean.slice(0, 6).split("");
      setDigits([...next, ...Array(6 - next.length).fill("")]);
      refs.current[Math.min(5, next.length)]?.focus();
      return;
    }
    const d = digits.slice(); d[i] = clean; setDigits(d);
    if (clean && i < 5) refs.current[i + 1]?.focus();
  };
  const key = (i, e) => {
    if (e.key === "Backspace" && !digits[i] && i > 0) refs.current[i - 1]?.focus();
    if (e.key === "Enter") pair();
  };
  const pair = async () => {
    if (busy || !(useLong ? code.length > 3 : code.length === 6)) return;
    setBusy(true); setErr("");
    try {
      const r = await post("/api/auth/pair", { code, name: name.trim() || "Browser", kind: "web" });
      auth.save(r.token);
      set({ me: r.device, pairing: false, setupRequired: false });
      toast(`Gekoppelt als „${r.device.name}“`, "ok");
      location.hash = "#/";
    } catch (e) {
      setErr(e.message);
    } finally { setBusy(false); }
  };
  const later = () => { auth.setViewOnly(true); set({ pairing: false }); };
  return html`
  <div class="pair">
    <div class="card box">
      <div class="row"><span class="logo"><${Icon} name="spool" /></span><span class="g" style="font-weight:700;font-size:20px">Kobra Spoolman</span></div>
      <div><h1 class="h1" style="font-size:28px;margin-bottom:8px">Diesen Browser koppeln</h1>
        <p class="muted" style="margin:0">${reason || "Einmalig. Danach merkt sich der Browser seinen Schlüssel und fragt nicht wieder."}</p></div>
      ${!useLong ? html`
        <fieldset style="border:0;margin:0;padding:0">
          <legend class="small muted" style="margin-bottom:10px">Kopplungscode (6 Ziffern)</legend>
          <div class="digits">${digits.map((d, i) => html`${i === 3 && html`<span class="gap"></span>`}<input ref=${(el) => (refs.current[i] = el)} aria-label=${"Ziffer " + (i + 1)}
            inputmode="numeric" autocomplete="one-time-code" maxlength="6" value=${d} onInput=${(e) => setAt(i, e.target.value)} onKeyDown=${(e) => key(i, e)} />`)}</div>
        </fieldset>` : html`
        <div class="f"><label for="pair-long">Schlüssel (APP_TOKEN)</label><input id="pair-long" value=${long} onInput=${(e) => setLong(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && pair()} /></div>`}
      <div class="f"><label for="pair-name">Name dieses Geräts</label><input id="pair-name" value=${name} onInput=${(e) => setName(e.target.value)} /></div>
      ${err && html`<div class="note bad">${err}</div>`}
      <button class="btn acc" style="min-height:52px" disabled=${busy} onClick=${pair}>${busy ? "…" : "Koppeln"}</button>
      <div class="note info" style="line-height:1.55">
        <b style="color:var(--text)">Woher kommt der Code?</b><br />
        In der App oder einem gekoppelten Browser unter <b style="color:var(--text)">Geräte → Gerät hinzufügen</b>.<br />
        ${S.setupRequired ? html`Noch nichts gekoppelt: Der Einrichtungscode steht im Log der Bridge (Portainer → Container → Logs).` : html`Erstes Gerät? Der Einrichtungscode steht im Log der Bridge (Portainer → Logs).`}
      </div>
      <div class="row wrap small">
        <a href="#" onClick=${(e) => { e.preventDefault(); setUseLong(!useLong); setErr(""); }}>${useLong ? "Mit 6-stelligem Code koppeln" : "Mit altem APP_TOKEN koppeln"}</a>
        <span class="grow"></span>
        <a href="#" onClick=${(e) => { e.preventDefault(); later(); }}>Nur ansehen</a>
      </div>
    </div>
  </div>`;
}
