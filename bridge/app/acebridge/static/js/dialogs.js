// Dialoge. Welcher offen ist, steht in S.dialog ({kind, ...}).

import { html, useEffect, useMemo, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { Dialog, Field, Swatch } from "./components.js";
import { Icon } from "./icons.js";
import { CameraDialog } from "./media.js";
import { TuneDialog } from "./control.js";
import { S, closeDialog, loadCatalog, toast } from "./store.js";
import { cls, grams, hex, num, parseNum, title } from "./util.js";

const act = () => import("./actions.js");

/** Knopf, der waehrend der Aktion gesperrt ist und den Dialog nur bei Erfolg schliesst. */
function Run({ label, run, disabled, kind = "acc" }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await run(); closeDialog(); } catch { /* Meldung kam schon */ } finally { setBusy(false); }
  };
  return html`<button class=${cls("btn", kind)} disabled=${disabled || busy} onClick=${go}>${busy ? "…" : label}</button>`;
}
const Cancel = () => html`<button class="btn ghost" onClick=${closeDialog}>Abbrechen</button>`;

function Confirm({ title, text, ok, action, danger, back }) {
  const no = back ? html`<button class="btn ghost" onClick=${closeDialog}>${back}</button>` : html`<${Cancel} />`;
  return html`<${Dialog} title=${title} footer=${html`${no}<${Run} label=${ok} run=${action} kind=${danger ? "danger" : "acc"} />`}>
    <p style="margin:0">${text}</p></${Dialog}>`;
}

// ------------------------------------------------------------ Slot zuordnen
function Assign({ slot }) {
  const [list, setList] = useState(null);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState(null);
  useEffect(() => { get(`/api/spools?slot=${slot}`).then((r) => setList(r.spools)).catch((e) => toast(e.message, "bad")); }, [slot]);
  const sl = S.st?.slots.find((s) => s.slot === slot);
  const shown = (list || []).filter((s) => !q || `${s.display_name} ${s.material} #${s.spool_id}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.match?.material === true) - (a.match?.material === true) || (a.slot ? 1 : 0) - (b.slot ? 1 : 0) || a.display_name.localeCompare(b.display_name));
  return html`<${Dialog} title=${`Spule für Slot ${slot}`} wide footer=${html`<${Cancel} /><${Run} label="Zuordnen" disabled=${!pick} run=${() => act().then((a) => a.assignSlot(slot, pick))} />`}>
    <div class="col">
      ${sl?.ace?.present && html`<div class="note info">ACE meldet in Slot ${slot}: <b>${sl.ace.material || "kein Material"}</b>${sl.ace.color ? html` <${Swatch} color=${sl.ace.color} size=${12} />` : ""} – passende Spulen stehen oben.</div>`}
      <label class="search"><${Icon} name="search" small /><input aria-label="Spule suchen" value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Spule suchen" /></label>
      ${!list && html`<div class="muted">lade …</div>`}
      <div class="pick" role="listbox" style="max-height:52vh;overflow:auto">
        ${shown.map((s) => html`
          <button role="option" aria-selected=${pick === s.spool_id} class=${pick === s.spool_id ? "on" : ""} onClick=${() => setPick(s.spool_id)} onDblClick=${() => setPick(s.spool_id)}>
            <${Swatch} color=${s.color} size=${26} />
            <span class="grow"><b>${title(s)}</b> <span class="muted">· ${s.vendor} · #${s.spool_id}</span>
              <span class="small muted" style="display:block">${grams(s.remaining_weight)} · ${s.slot ? `liegt in Slot ${s.slot}` : s.location || "Regal"}</span></span>
            ${s.match?.material === true && html`<span class="chip ok">passt</span>`}
            ${s.match?.material === false && html`<span class="chip warn">ACE: anderes Material</span>`}
          </button>`)}
      </div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ Neue Spule
function NewSpool({ slot: preSlot }) {
  const cat = S.catalog;
  useEffect(() => { if (!cat) loadCatalog(); }, []);
  const [q, setQ] = useState("");
  const [fid, setFid] = useState(null);
  const [v, setV] = useState({ initial_weight: "", spool_weight: "", price: "", lot_nr: "", comment: "", slot: preSlot ? String(preSlot) : "" });
  const fil = cat?.filaments.find((f) => f.filament_id === fid);
  const list = (cat?.filaments || []).filter((f) => !q || `${f.display_name} ${f.material}`.toLowerCase().includes(q.toLowerCase()));
  const bad = ["initial_weight", "spool_weight", "price"].some((k) => Number.isNaN(parseNum(v[k])));
  const run = () => act().then((a) => {
    const body = { filament_id: fid };
    for (const k of ["initial_weight", "spool_weight", "price"]) if (parseNum(v[k]) != null) body[k] = parseNum(v[k]);
    for (const k of ["lot_nr", "comment"]) if (v[k].trim()) body[k] = v[k].trim();
    if (v.slot) body.slot = Number(v.slot);
    return a.createSpool(body);
  });
  const f = (k, label, ph) => html`<${Field} id=${"ns-" + k} label=${label}><input id=${"ns-" + k} value=${v[k]} placeholder=${ph ?? ""} inputmode=${["lot_nr", "comment"].includes(k) ? "text" : "decimal"} onInput=${(e) => setV({ ...v, [k]: e.target.value })} /></${Field}>`;
  return html`<${Dialog} title="Neue Spule" wide footer=${html`<${Cancel} /><${Run} label="Spule anlegen" disabled=${!fid || bad} run=${run} />`}>
    <div class="col">
      ${!fil && html`
        <label class="search"><${Icon} name="search" small /><input aria-label="Filament suchen" value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Filament suchen" /></label>
        <div class="pick" style="max-height:46vh;overflow:auto">
          ${!cat && html`<div class="muted">lade …</div>`}
          ${list.map((x) => html`<button onClick=${() => setFid(x.filament_id)}><${Swatch} color=${x.color} size=${24} /><span class="grow"><b>${x.name}</b> <span class="muted">· ${x.vendor} · ${x.material}</span></span><span class="small muted">${x.spools} ${x.spools === 1 ? "Spule" : "Spulen"}</span></button>`)}
        </div>
        <div class="small muted">Filament fehlt? Unter <a href="#/filament/sorten" onClick=${closeDialog}>Filament → Sorten</a> anlegen.</div>`}
      ${fil && html`
        <div class="row"><${Swatch} color=${fil.color} size=${32} /><div class="grow"><b>${fil.display_name}</b><div class="small muted">${fil.material} · ${fil.orca_id}</div></div><button class="btn sm ghost" onClick=${() => setFid(null)}>Ändern</button></div>
        <div class="fgrid">
          ${f("initial_weight", "Netto (g)", fil.weight ? num(fil.weight, 0) : "")}
          ${f("spool_weight", "Leerspule (g)", fil.spool_weight ? num(fil.spool_weight, 0) : "")}
          ${f("price", "Preis (€)", fil.price ? num(fil.price) : "")}
          ${f("lot_nr", "Charge")}
          <${Field} id="ns-slot" label="Gleich einlegen"><select id="ns-slot" value=${v.slot} onChange=${(e) => setV({ ...v, slot: e.target.value })}>
            <option value="">nein, ins Regal</option>${(S.st?.slots || []).map((s) => html`<option value=${String(s.slot)}>Slot ${s.slot}${s.spool ? ` (statt ${s.spool.name})` : ""}</option>`)}</select></${Field}>
        </div>
        ${f("comment", "Notiz")}`}
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ Trockner
function DryerStart() {
  const d = S.st?.dryer || {};
  const req = d.required || {};
  const cap = req.temp ?? req.ace_max ?? 55;
  const [temp, setTemp] = useState(String(cap));
  const [hours, setHours] = useState(String(d.config?.max_hours ?? 6).replace(".", ","));
  const t = parseNum(temp), h = parseNum(hours);
  const bad = !t || Number.isNaN(t) || !h || Number.isNaN(h) || h < 0.5 || h > 24;
  return html`<${Dialog} title="Trocknen starten" footer=${html`<${Cancel} /><${Run} label="Starten" disabled=${bad} run=${() => act().then((a) => a.dryerStart(Math.min(t, cap), h))} />`}>
    <div class="col">
      <div class="fgrid">
        <${Field} id="dr-t" label="Temperatur (°C)" hint=${`höchstens ${cap} °C`}><input id="dr-t" inputmode="numeric" value=${temp} onInput=${(e) => setTemp(e.target.value)} /></${Field}>
        <${Field} id="dr-h" label="Dauer (h)" hint="0,5 bis 24"><input id="dr-h" inputmode="decimal" value=${hours} onInput=${(e) => setHours(e.target.value)} /></${Field}>
      </div>
      ${(req.slots || []).length > 0 && html`<div class="kv">${req.slots.map((p) => html`<span>Slot ${p.slot} · ${p.name}</span><span class="m" style=${{ color: (req.limited_by || []).includes(p.slot) ? "var(--accent)" : "" }}>${p.temp} °C</span>`)}</div>`}
      <div class="small muted">Die Bridge nimmt nie mehr als das empfindlichste eingelegte Filament verträgt (Feld „Trocknen max.“, sonst Vorlage bzw. Materialwert) und nie mehr als die ACE kann (${req.ace_max ?? "?"} °C).</div>
    </div></${Dialog}>`;
}

function DryerRules() {
  const c = S.st?.dryer?.config || {};
  const [v, setV] = useState({ enabled: !!c.enabled, while_printing: !!c.while_printing,
    start_above: String(c.start_above ?? 20), stop_below: String(c.stop_below ?? 10),
    max_hours: String(c.max_hours ?? 6).replace(".", ","), pause_minutes: String(c.pause_minutes ?? 60),
    start_delay_minutes: String(c.start_delay_minutes ?? 15) });
  const nums = ["start_above", "stop_below", "max_hours", "pause_minutes", "start_delay_minutes"];
  const bad = nums.some((k) => parseNum(v[k]) == null || Number.isNaN(parseNum(v[k]))) || parseNum(v.stop_below) >= parseNum(v.start_above);
  const run = () => act().then((a) => a.dryerConfig({ enabled: v.enabled, while_printing: v.while_printing, ...Object.fromEntries(nums.map((k) => [k, parseNum(v[k])])) }));
  const n = (k, label, hint) => html`<${Field} id=${"rule-" + k} label=${label} hint=${hint}><input id=${"rule-" + k} inputmode="decimal" value=${v[k]} onInput=${(e) => setV({ ...v, [k]: e.target.value })} /></${Field}>`;
  return html`<${Dialog} title="Trockner-Automatik" footer=${html`<${Cancel} /><${Run} label="Speichern" disabled=${bad} run=${run} />`}>
    <div class="col">
      <label class="check"><input type="checkbox" checked=${v.enabled} onChange=${(e) => setV({ ...v, enabled: e.target.checked })} />Automatik an</label>
      <div class="fgrid">
        ${n("start_above", "Start ab Feuchte (%)")}${n("stop_below", "Stopp unter Feuchte (%)")}
        ${n("max_hours", "Längstens (h)", "pro Durchgang")}${n("pause_minutes", "Pause danach (min)", "gegen An/Aus-Flattern")}
        ${n("start_delay_minutes", "Erst starten nach (min)", "so lange am Stück über „Start ab“ – Deckel auf zählt nicht")}
      </div>
      <div class="small muted">Gilt nur für die Automatik. Von Hand, geplant oder nach dem Einlegen gestartet läuft der Trockner bis zur gewählten Zeit.</div>
      <label class="check"><input type="checkbox" checked=${v.while_printing} onChange=${(e) => setV({ ...v, while_printing: e.target.checked })} />Auch während eines Drucks trocknen</label>
      ${bad && html`<div class="small" style="color:var(--danger-text)">Stopp-Feuchte muss unter der Start-Feuchte liegen.</div>`}
    </div></${Dialog}>`;
}

function DryerPlan() {
  const d = S.st?.dryer || {};
  const req = d.required || {};
  const pad = (n) => String(n).padStart(2, "0");
  const local = (t) => `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(t.getHours())}:${pad(t.getMinutes())}`;
  const tonight = new Date(); tonight.setHours(22, 0, 0, 0);
  if (tonight < new Date()) tonight.setDate(tonight.getDate() + 1);
  const [at, setAt] = useState(d.schedule ? local(new Date(d.schedule.at * 1000)) : local(tonight));
  const [temp, setTemp] = useState(d.schedule?.temp ? String(d.schedule.temp) : "");
  const [hours, setHours] = useState(String(d.schedule?.hours ?? d.config?.max_hours ?? 6).replace(".", ","));
  const t = parseNum(temp), h = parseNum(hours);
  const when_ = new Date(at);
  const bad = Number.isNaN(when_.getTime()) || when_ <= new Date() || Number.isNaN(t) || h == null || Number.isNaN(h) || h < 0.5 || h > 24;
  const run = () => act().then(async () => {
    await post("/api/dryer/schedule", { at: when_.getTime() / 1000, temp: t, hours: h });
    toast("Trocknen geplant", "ok");
    (await import("./store.js")).loadState();
  });
  const remove = async () => {
    try { await (await import("./api.js")).del("/api/dryer/schedule"); toast("Plan gelöscht", "ok"); (await import("./store.js")).loadState(); closeDialog(); }
    catch (e) { toast(e.message, "bad"); }
  };
  return html`<${Dialog} title="Trocknen planen" footer=${html`${d.schedule && html`<button class="btn danger" onClick=${remove}>Plan löschen</button><span class="grow"></span>`}<${Cancel} /><${Run} label="Planen" disabled=${bad} run=${run} />`}>
    <div class="col">
      <div class="fgrid">
        <${Field} id="pl-at" label="Start"><input id="pl-at" type="datetime-local" value=${at} onInput=${(e) => setAt(e.target.value)} /></${Field}>
        <${Field} id="pl-t" label="Temperatur (°C)" hint=${`leer = automatisch, höchstens ${req.temp ?? req.ace_max ?? "?"} °C`}><input id="pl-t" inputmode="numeric" value=${temp} onInput=${(e) => setTemp(e.target.value)} /></${Field}>
        <${Field} id="pl-h" label="Dauer (h)" hint="0,5 bis 24"><input id="pl-h" inputmode="decimal" value=${hours} onInput=${(e) => setHours(e.target.value)} /></${Field}>
      </div>
      <div class="small muted">Einmaliger Start, z.B. nachts. Die Temperatur richtet sich beim Start nach den dann eingelegten Spulen.</div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ Offenen Posten buchen
function BookOpen({ item }) {
  const spools = S.spools || [];
  const [pick, setPick] = useState(item.spool_id || S.st?.slots.find((s) => s.slot === item.slot)?.spool?.spool_id || null);
  return html`<${Dialog} title="Offene Buchung" wide footer=${html`
      <button class="btn danger" onClick=${async () => { try { await (await act()).discardOpen(item.id); closeDialog(); } catch { /* s.o. */ } }}>Verwerfen</button>
      <span class="grow"></span><${Cancel} /><${Run} label=${pick ? `Auf #${pick} buchen` : "Buchen"} disabled=${!pick} run=${() => act().then((a) => a.bookOpen(item.id, pick))} />`}>
    <div class="col">
      <div class="note info">${num(item.mm, 0)} mm ≈ ${grams(item.g_est)} aus „${item.file}“, ${item.slot > 0 ? `Slot ${item.slot}` : "ohne Slot"}.</div>
      <div class="pick" style="max-height:48vh;overflow:auto">
        ${spools.map((s) => html`<button class=${pick === s.spool_id ? "on" : ""} onClick=${() => setPick(s.spool_id)}><${Swatch} color=${s.color} size=${24} /><span class="grow"><b>${title(s)}</b> <span class="muted">· ${s.vendor} · #${s.spool_id}</span></span><span class="small muted">${s.slot ? `Slot ${s.slot}` : grams(s.remaining_weight)}</span></button>`)}
      </div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ Neue Farbe einer Produktreihe
function CopyFilament({ fil }) {
  const [name, setName] = useState(fil.name);
  const [color, setColor] = useState("");
  const c = hex(color);
  const run = () => act().then(async (a) => {
    const f = await a.copyFilament(fil.filament_id, { name: name.trim(), ...(c ? { color_hex: c.slice(1) } : {}) });
    if (f?.filament_id) (await import("./store.js")).set({ selFil: f.filament_id });
  });
  return html`<${Dialog} title="Neue Farbe anlegen" footer=${html`<${Cancel} /><${Run} label="Anlegen" disabled=${!name.trim() || name.trim() === fil.name || (color && !c)} run=${run} />`}>
    <div class="col">
      <div class="small muted">Übernimmt alle Werte von „${fil.display_name}“ außer Name und Farbe.</div>
      <${Field} id="cp-name" label="Name"><input id="cp-name" value=${name} onInput=${(e) => setName(e.target.value)} /></${Field}>
      <${Field} id="cp-color" label="Farbe"><div class="colorrow"><input type="color" aria-label="Farbe wählen" value=${c || "#888888"} onInput=${(e) => setColor(e.target.value.toUpperCase())} /><input id="cp-color" value=${color} placeholder="#RRGGBB" onInput=${(e) => setColor(e.target.value)} /></div></${Field}>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ Geraet hinzufuegen
export function qrSvg(text) {
  if (!window.qrcode) return null;
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
}

function AddDevice() {
  const [code, setCode] = useState(null);
  const [left, setLeft] = useState(0);
  const fetchCode = async () => {
    try {
      const r = await post("/api/auth/code");
      setCode(r.code);
      setLeft(r.expires_in);
    } catch (e) { toast(e.message, "bad"); }
  };
  useEffect(() => { fetchCode(); }, []);
  useEffect(() => {
    if (!code) return;
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [code]);
  const link = code ? `kobraspoolman://pair?b=${encodeURIComponent(location.origin)}&c=${code}` : "";
  const svg = useMemo(() => (link ? qrSvg(link) : null), [link]);
  const pretty = code ? code.slice(0, 3) + " " + code.slice(3) : "…";
  return html`<${Dialog} title="Gerät hinzufügen" footer=${html`<button class="btn" onClick=${fetchCode}><${Icon} name="refresh" small />Neuer Code</button><button class="btn acc" onClick=${closeDialog}>Fertig</button>`}>
    <div class="row wrap" style="gap:24px;align-items:flex-start">
      ${svg ? html`<div class="qr" dangerouslySetInnerHTML=${{ __html: svg }}></div>` : null}
      <div class="col grow" style="min-width:200px">
        <div class="lbl">Kopplungscode</div>
        <div class="code-big">${pretty}</div>
        <div class="small muted">${left > 0 ? `gültig noch ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} min, einmal verwendbar` : "abgelaufen – neuen Code holen"}</div>
        <div class="small muted">App: <b>Einstellungen → Koppeln</b> und den QR-Code scannen.<br />Browser oder Orca-Plugin: den Code dort eingeben.</div>
      </div>
    </div></${Dialog}>`;
}

const KINDS = { confirm: Confirm, assign: Assign, newSpool: NewSpool, dryerStart: DryerStart, dryerRules: DryerRules, dryerPlan: DryerPlan,
  bookOpen: BookOpen, copyFilament: CopyFilament, addDevice: AddDevice, camera: CameraDialog, tune: TuneDialog };

export function Dialogs() {
  const d = S.dialog;
  if (!d) return null;
  const C = KINDS[d.kind];
  return C ? html`<${C} ...${d} />` : null;
}
