// Dialogs. Which one is open is in S.dialog ({kind, ...}).

import { html, useEffect, useMemo, useState } from "../vendor/preact-htm.module.js";
import { directBase, get, getText, post } from "./api.js";
import { Dialog, Field, Swatch } from "./components.js";
import { lang, t } from "./i18n.js";
import { Icon } from "./icons.js";
import { CameraDialog } from "./media.js";
import { TuneDialog } from "./control.js";
import { DirectOn } from "./direct.js";
import { S, closeDialog, loadCatalog, toast } from "./store.js";
import { cls, grams, hex, num, parseNum, title } from "./util.js";

const act = () => import("./actions.js");
/** Number for an input field in the page language ("0.5" / "0,5"). */
const inputNum = (v) => (lang === "de" ? String(v).replace(".", ",") : String(v));

/** Button that is locked during the action and closes the dialog only on success. */
function Run({ label, run, disabled, kind = "acc" }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await run(); closeDialog(); } catch { /* the message was shown already */ } finally { setBusy(false); }
  };
  return html`<button class=${cls("btn", kind)} disabled=${disabled || busy} onClick=${go}>${busy ? "…" : label}</button>`;
}
const Cancel = () => html`<button class="btn ghost" onClick=${closeDialog}>${t("Cancel")}</button>`;

function Confirm({ title: heading, text, ok, action, danger, back }) {
  const no = back ? html`<button class="btn ghost" onClick=${closeDialog}>${back}</button>` : html`<${Cancel} />`;
  return html`<${Dialog} title=${heading} footer=${html`${no}<${Run} label=${ok} run=${action} kind=${danger ? "danger" : "acc"} />`}>
    <p style="margin:0">${text}</p></${Dialog}>`;
}

// ------------------------------------------------------------ assign a slot
function Assign({ slot }) {
  const [list, setList] = useState(null);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState(null);
  useEffect(() => { get(`/api/spools?slot=${slot}`).then((r) => setList(r.spools)).catch((e) => toast(e.message, "bad")); }, [slot]);
  const sl = S.st?.slots.find((s) => s.slot === slot);
  const shown = (list || []).filter((s) => !q || `${s.display_name} ${s.material} #${s.spool_id}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (b.match?.material === true) - (a.match?.material === true) || (a.slot ? 1 : 0) - (b.slot ? 1 : 0) || a.display_name.localeCompare(b.display_name));
  return html`<${Dialog} title=${t("Spool for slot {slot}", { slot })} wide footer=${html`<${Cancel} /><${Run} label=${t("Assign")} disabled=${!pick} run=${() => act().then((a) => a.assignSlot(slot, pick))} />`}>
    <div class="col">
      ${sl?.ace?.present && html`<div class="note info">${t("ACE reports in slot {slot}:", { slot })} <b>${sl.ace.material || t("no material")}</b>${sl.ace.color ? html` <${Swatch} color=${sl.ace.color} size=${12} />` : ""} – ${t("matching spools are at the top.")}</div>`}
      <label class="search"><${Icon} name="search" small /><input aria-label=${t("Search spool")} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder=${t("Search spool")} /></label>
      ${!list && html`<div class="muted">${t("loading …")}</div>`}
      <div class="pick" role="listbox" style="max-height:52vh;overflow:auto">
        ${shown.map((s) => html`
          <button role="option" aria-selected=${pick === s.spool_id} class=${pick === s.spool_id ? "on" : ""} onClick=${() => setPick(s.spool_id)} onDblClick=${() => setPick(s.spool_id)}>
            <${Swatch} color=${s.color} size=${26} />
            <span class="grow"><b>${title(s)}</b> <span class="muted">· ${s.vendor} · #${s.spool_id}</span>
              <span class="small muted" style="display:block">${grams(s.remaining_weight)} · ${s.slot ? t("is in slot {slot}", { slot: s.slot }) : s.location || t("Shelf")}</span></span>
            ${s.match?.material === true && html`<span class="chip ok">${t("matches")}</span>`}
            ${s.match?.material === false && html`<span class="chip warn">${t("ACE: other material")}</span>`}
          </button>`)}
      </div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ new spool
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
  return html`<${Dialog} title=${t("New spool")} wide footer=${html`<${Cancel} /><${Run} label=${t("Create spool")} disabled=${!fid || bad} run=${run} />`}>
    <div class="col">
      ${!fil && html`
        <label class="search"><${Icon} name="search" small /><input aria-label=${t("Search filament")} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder=${t("Search filament")} /></label>
        <div class="pick" style="max-height:46vh;overflow:auto">
          ${!cat && html`<div class="muted">${t("loading …")}</div>`}
          ${list.map((x) => html`<button onClick=${() => setFid(x.filament_id)}><${Swatch} color=${x.color} size=${24} /><span class="grow"><b>${x.name}</b> <span class="muted">· ${x.vendor} · ${x.material}</span></span><span class="small muted">${x.spools === 1 ? t("1 spool") : t("{n} spools", { n: x.spools })}</span></button>`)}
        </div>
        <div class="small muted">${t("Filament missing? Create it under")} <a href="#/filament/filaments" onClick=${closeDialog}>${t("Filament → Filaments")}</a>.</div>`}
      ${fil && html`
        <div class="row"><${Swatch} color=${fil.color} size=${32} /><div class="grow"><b>${fil.display_name}</b><div class="small muted">${fil.material} · ${fil.orca_id}</div></div><button class="btn sm ghost" onClick=${() => setFid(null)}>${t("Change")}</button></div>
        <div class="fgrid">
          ${f("initial_weight", t("Net (g)"), fil.weight ? num(fil.weight, 0) : "")}
          ${f("spool_weight", t("Empty spool (g)"), fil.spool_weight ? num(fil.spool_weight, 0) : "")}
          ${f("price", t("Price"), fil.price ? num(fil.price) : "")}
          ${f("lot_nr", t("Lot"))}
          <${Field} id="ns-slot" label=${t("Insert right away")}><select id="ns-slot" value=${v.slot} onChange=${(e) => setV({ ...v, slot: e.target.value })}>
            <option value="">${t("no, to the shelf")}</option>${(S.st?.slots || []).map((s) => html`<option value=${String(s.slot)}>${s.spool ? t("Slot {slot} (instead of {name})", { slot: s.slot, name: s.spool.name }) : t("Slot {slot}", { slot: s.slot })}</option>`)}</select></${Field}>
        </div>
        ${f("comment", t("Note"))}`}
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ dryer
function DryerStart() {
  const d = S.st?.dryer || {};
  const req = d.required || {};
  const cap = req.temp ?? req.ace_max ?? 55;
  const [temp, setTemp] = useState(String(cap));
  const [hours, setHours] = useState(inputNum(d.config?.max_hours ?? 6));
  const tv = parseNum(temp), h = parseNum(hours);
  const bad = !tv || Number.isNaN(tv) || !h || Number.isNaN(h) || h < 0.5 || h > 24;
  return html`<${Dialog} title=${t("Start drying")} footer=${html`<${Cancel} /><${Run} label=${t("Start")} disabled=${bad} run=${() => act().then((a) => a.dryerStart(Math.min(tv, cap), h))} />`}>
    <div class="col">
      <div class="fgrid">
        <${Field} id="dr-t" label=${t("Temperature (°C)")} hint=${t("at most {t} °C", { t: cap })}><input id="dr-t" inputmode="numeric" value=${temp} onInput=${(e) => setTemp(e.target.value)} /></${Field}>
        <${Field} id="dr-h" label=${t("Duration (h)")} hint=${t("0.5 to 24")}><input id="dr-h" inputmode="decimal" value=${hours} onInput=${(e) => setHours(e.target.value)} /></${Field}>
      </div>
      ${(req.slots || []).length > 0 && html`<div class="kv">${req.slots.map((p) => html`<span>${t("Slot {slot}", { slot: p.slot })} · ${p.name}</span><span class="m" style=${{ color: (req.limited_by || []).includes(p.slot) ? "var(--accent)" : "" }}>${p.temp} °C</span>`)}</div>`}
      <div class="small muted">${t("The bridge never uses more than the most sensitive loaded filament tolerates (field “Drying max.”, else template or material value) and never more than the ACE can do ({max} °C).", { max: req.ace_max ?? "?" })}</div>
    </div></${Dialog}>`;
}

function DryerRules() {
  const c = S.st?.dryer?.config || {};
  const [v, setV] = useState({ enabled: !!c.enabled, while_printing: !!c.while_printing,
    start_above: String(c.start_above ?? 20), stop_below: String(c.stop_below ?? 10),
    max_hours: inputNum(c.max_hours ?? 6), pause_minutes: String(c.pause_minutes ?? 60),
    start_delay_minutes: String(c.start_delay_minutes ?? 15) });
  const nums = ["start_above", "stop_below", "max_hours", "pause_minutes", "start_delay_minutes"];
  const bad = nums.some((k) => parseNum(v[k]) == null || Number.isNaN(parseNum(v[k]))) || parseNum(v.stop_below) >= parseNum(v.start_above);
  const run = () => act().then((a) => a.dryerConfig({ enabled: v.enabled, while_printing: v.while_printing, ...Object.fromEntries(nums.map((k) => [k, parseNum(v[k])])) }));
  const n = (k, label, hint) => html`<${Field} id=${"rule-" + k} label=${label} hint=${hint}><input id=${"rule-" + k} inputmode="decimal" value=${v[k]} onInput=${(e) => setV({ ...v, [k]: e.target.value })} /></${Field}>`;
  return html`<${Dialog} title=${t("Dryer automation")} footer=${html`<${Cancel} /><${Run} label=${t("Save")} disabled=${bad} run=${run} />`}>
    <div class="col">
      <label class="check"><input type="checkbox" checked=${v.enabled} onChange=${(e) => setV({ ...v, enabled: e.target.checked })} />${t("Automation on")}</label>
      <div class="fgrid">
        ${n("start_above", t("Start from humidity (%)"))}${n("stop_below", t("Stop below humidity (%)"))}
        ${n("max_hours", t("At most (h)"), t("per run"))}${n("pause_minutes", t("Pause afterwards (min)"), t("against on/off flapping"))}
        ${n("start_delay_minutes", t("Start only after (min)"), t("this long in a row above “Start from” – an open lid does not count"))}
      </div>
      <div class="small muted">${t("Applies only to the automation. Started by hand, scheduled or after inserting, the dryer runs until the chosen time.")}</div>
      <label class="check"><input type="checkbox" checked=${v.while_printing} onChange=${(e) => setV({ ...v, while_printing: e.target.checked })} />${t("Dry during a print too")}</label>
      ${bad && html`<div class="small" style="color:var(--danger-text)">${t("The stop humidity must be below the start humidity.")}</div>`}
    </div></${Dialog}>`;
}

function DryerPlan() {
  const d = S.st?.dryer || {};
  const req = d.required || {};
  const pad = (n) => String(n).padStart(2, "0");
  const local = (x) => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}T${pad(x.getHours())}:${pad(x.getMinutes())}`;
  const tonight = new Date(); tonight.setHours(22, 0, 0, 0);
  if (tonight < new Date()) tonight.setDate(tonight.getDate() + 1);
  const [at, setAt] = useState(d.schedule ? local(new Date(d.schedule.at * 1000)) : local(tonight));
  const [temp, setTemp] = useState(d.schedule?.temp ? String(d.schedule.temp) : "");
  const [hours, setHours] = useState(inputNum(d.schedule?.hours ?? d.config?.max_hours ?? 6));
  const tv = parseNum(temp), h = parseNum(hours);
  const when_ = new Date(at);
  const bad = Number.isNaN(when_.getTime()) || when_ <= new Date() || Number.isNaN(tv) || h == null || Number.isNaN(h) || h < 0.5 || h > 24;
  const run = () => act().then(async () => {
    await post("/api/dryer/schedule", { at: when_.getTime() / 1000, temp: tv, hours: h });
    toast(t("Drying scheduled"), "ok");
    (await import("./store.js")).loadState();
  });
  const remove = async () => {
    try { await (await import("./api.js")).del("/api/dryer/schedule"); toast(t("Schedule deleted"), "ok"); (await import("./store.js")).loadState(); closeDialog(); }
    catch (e) { toast(e.message, "bad"); }
  };
  return html`<${Dialog} title=${t("Schedule drying")} footer=${html`${d.schedule && html`<button class="btn danger" onClick=${remove}>${t("Delete schedule")}</button><span class="grow"></span>`}<${Cancel} /><${Run} label=${t("Schedule")} disabled=${bad} run=${run} />`}>
    <div class="col">
      <div class="fgrid">
        <${Field} id="pl-at" label=${t("Start")}><input id="pl-at" type="datetime-local" value=${at} onInput=${(e) => setAt(e.target.value)} /></${Field}>
        <${Field} id="pl-t" label=${t("Temperature (°C)")} hint=${t("empty = automatic, at most {t} °C", { t: req.temp ?? req.ace_max ?? "?" })}><input id="pl-t" inputmode="numeric" value=${temp} onInput=${(e) => setTemp(e.target.value)} /></${Field}>
        <${Field} id="pl-h" label=${t("Duration (h)")} hint=${t("0.5 to 24")}><input id="pl-h" inputmode="decimal" value=${hours} onInput=${(e) => setHours(e.target.value)} /></${Field}>
      </div>
      <div class="small muted">${t("A one-off start, e.g. at night. The temperature follows the spools loaded at that time.")}</div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ book an open item
function BookOpen({ item }) {
  const spools = S.spools || [];
  const [pick, setPick] = useState(item.spool_id || S.st?.slots.find((s) => s.slot === item.slot)?.spool?.spool_id || null);
  return html`<${Dialog} title=${t("Open booking")} wide footer=${html`
      <button class="btn danger" onClick=${async () => { try { await (await act()).discardOpen(item.id); closeDialog(); } catch { /* see above */ } }}>${t("Discard")}</button>
      <span class="grow"></span><${Cancel} /><${Run} label=${pick ? t("Book on #{id}", { id: pick }) : t("Book")} disabled=${!pick} run=${() => act().then((a) => a.bookOpen(item.id, pick))} />`}>
    <div class="col">
      <div class="note info">${t("{mm} mm ≈ {g} from “{file}”, {slot}.", { mm: num(item.mm, 0), g: grams(item.g_est), file: item.file, slot: item.slot > 0 ? t("Slot {slot}", { slot: item.slot }) : t("without a slot") })}</div>
      <div class="pick" style="max-height:48vh;overflow:auto">
        ${spools.map((s) => html`<button class=${pick === s.spool_id ? "on" : ""} onClick=${() => setPick(s.spool_id)}><${Swatch} color=${s.color} size=${24} /><span class="grow"><b>${title(s)}</b> <span class="muted">· ${s.vendor} · #${s.spool_id}</span></span><span class="small muted">${s.slot ? t("Slot {slot}", { slot: s.slot }) : grams(s.remaining_weight)}</span></button>`)}
      </div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ new colour of a product line
function CopyFilament({ fil }) {
  const [name, setName] = useState(fil.name);
  const [color, setColor] = useState("");
  const c = hex(color);
  const run = () => act().then(async (a) => {
    const f = await a.copyFilament(fil.filament_id, { name: name.trim(), ...(c ? { color_hex: c.slice(1) } : {}) });
    if (f?.filament_id) (await import("./store.js")).set({ selFil: f.filament_id });
  });
  return html`<${Dialog} title=${t("Create a new colour")} footer=${html`<${Cancel} /><${Run} label=${t("Create")} disabled=${!name.trim() || name.trim() === fil.name || (color && !c)} run=${run} />`}>
    <div class="col">
      <div class="small muted">${t("Takes over all values of “{name}” except name and colour.", { name: fil.display_name })}</div>
      <${Field} id="cp-name" label=${t("Name")}><input id="cp-name" value=${name} onInput=${(e) => setName(e.target.value)} /></${Field}>
      <${Field} id="cp-color" label=${t("Colour")}><div class="colorrow"><input type="color" aria-label=${t("Choose a colour")} value=${c || "#888888"} onInput=${(e) => setColor(e.target.value.toUpperCase())} /><input id="cp-color" value=${color} placeholder="#RRGGBB" onInput=${(e) => setColor(e.target.value)} /></div></${Field}>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ add a device
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
    const timer = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [code]);
  const link = code ? `kobraspoolman://pair?b=${encodeURIComponent(directBase())}&c=${code}` : "";
  const svg = useMemo(() => (link ? qrSvg(link) : null), [link]);
  const pretty = code ? code.slice(0, 3) + " " + code.slice(3) : "…";
  return html`<${Dialog} title=${t("Add device")} footer=${html`<button class="btn" onClick=${fetchCode}><${Icon} name="refresh" small />${t("New code")}</button><button class="btn acc" onClick=${closeDialog}>${t("Done")}</button>`}>
    <div class="row wrap" style="gap:24px;align-items:flex-start">
      ${svg ? html`<div class="qr" dangerouslySetInnerHTML=${{ __html: svg }}></div>` : null}
      <div class="col grow" style="min-width:200px">
        <div class="lbl">${t("Pairing code")}</div>
        <div class="code-big">${pretty}</div>
        <div class="small muted">${left > 0 ? t("valid for {time} min, usable once", { time: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` }) : t("expired – get a new code")}</div>
        <div class="small muted">${t("App:")} <b>${t("Settings → Scan QR code")}</b><br />${t("Browser or Orca plugin: enter the code there.")}</div>
      </div>
    </div></${Dialog}>`;
}

// ------------------------------------------------------------ report a bug
const REPO = "https://github.com/xNoVoSx/kobra-spoolman";

/** Diagnostics for a bug report (bridge diagnostics.py: versions, setup, slots, settings, log – without hosts and
 *  secrets), copied for the GitHub form, which asks for exactly this. */
function BugReport() {
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { getText("/api/diagnostics").then(setText).catch((e) => setErr(e.message)); }, []);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); toast(t("Copied"), "ok"); return; } catch { /* http: no clipboard API */ }
    const area = document.getElementById("diag-text");
    area.select();
    try { if (document.execCommand("copy")) { toast(t("Copied"), "ok"); return; } } catch { /* see below */ }
    toast(t("Copying not possible – select the text"), "bad");
  };
  const version = S.health?.version || "";
  const form = `${REPO}/issues/new?template=bug_report.yml&bridge_version=${encodeURIComponent(version)}`;
  return html`<${Dialog} title=${t("Report a bug")} footer=${html`<button class="btn" onClick=${closeDialog}>${t("Close")}</button>
      <button class="btn" disabled=${!text} onClick=${copy}><${Icon} name="copy" small />${t("Copy diagnostics")}</button>
      <a class="btn acc" href=${form} target="_blank" rel="noopener">${t("Open the form on GitHub")}</a>`}>
    <div class="col">
      <div class="small muted">${t("1. Copy the diagnostics. 2. Open the form on GitHub and paste them into “Diagnostics”. 3. Describe what you did, what happened and what you expected. Host names, IP addresses and keys are already removed – have a look before you post.")}</div>
      ${err ? html`<div class="bad small">${err}</div>`
            : html`<textarea id="diag-text" class="m small" rows="14" readonly value=${text || t("Loading …")}></textarea>`}
    </div></${Dialog}>`;
}

const KINDS = { bugReport: BugReport, confirm: Confirm, assign: Assign, directOn: DirectOn, newSpool: NewSpool, dryerStart: DryerStart, dryerRules: DryerRules, dryerPlan: DryerPlan,
  bookOpen: BookOpen, copyFilament: CopyFilament, addDevice: AddDevice, camera: CameraDialog, tune: TuneDialog };

export function Dialogs() {
  const d = S.dialog;
  if (!d) return null;
  const C = KINDS[d.kind];
  return C ? html`<${C} ...${d} />` : null;
}
