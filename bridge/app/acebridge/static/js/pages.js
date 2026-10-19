// Pages. Which page is decided by the URL (#/filament ...); how much fits side by side, by the width.

import { HumidityCard } from "./humidity.js";
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, del, get, post } from "./api.js";
import { AceCard } from "./ace.js";
import { PaCard } from "./pa.js";
import { ClogCard, PowerlossCard, ResumeCard, UsbCard } from "./resume.js";
import { DirectCard } from "./direct.js";
import { HotendCard } from "./hotend.js";
import { DryerCard, JobCard, JobsList, OpenItemsCard, OrcaCard, PrinterCard, Slots, Swatch } from "./components.js";
import { NoticesCard } from "./notices.js";
import { FeaturesHint } from "./features.js";
import { FilamentEditor, FilamentList } from "./filaments.js";
import { LANGS, chosen, lang, setLang, t } from "./i18n.js";
import { Icon } from "./icons.js";
import { capability, quality, setQuality } from "./viewer3d.js";
import { cameraKey, cameraLink } from "./media.js";
import { SpoolDetail, SpoolList } from "./spools.js";
import { S, guard, loadCatalog, loadHealth, loadJobs, openDialog, set, toast } from "./store.js";
import { ago, cls, grams, num, when } from "./util.js";

// ------------------------------------------------------------ overview
// printer monitor: printer (camera) large, next to it messages & status, dryer, ACE; below the slots.
// Managing (spools, filaments, prints) has its own tabs.
export function Overview() {
  const open = (S.st?.usage?.open || []).length > 0;
  return html`
  <div class="ov2">
    <div class="ov2-printer"><${PrinterCard} /></div>
    <div class="ov2-side">
      <${ResumeCard} />
      <${FeaturesHint} />
      <div class="o-notices"><${NoticesCard} /></div>
      <div class="o-dryer"><${DryerCard} /></div>
      <div class="o-ace"><${AceCard} compact /></div>
      ${open && html`<div class="o-open"><${OpenItemsCard} /></div>`}
    </div>
    <div class="ov2-slots col" style="gap:14px">
      <div class="sec-head"><span class="lbl">${S.st?.ace_model || "ACE"} · Slots</span>
        <span class="small muted">${t("Assigning also gives material, colour and temperature to the ACE (spools without a tag)")}</span></div>
      <${Slots} />
    </div>
  </div>`;
}

/** 5120 px and more: printer large, slots + ACE, messages - everything at a glance, without management. */
export function Ultra() {
  const open = (S.st?.usage?.open || []).length > 0;
  return html`
  <div class="ultra">
    <div class="ucol"><${PrinterCard} tall /></div>
    <div class="ucol">
      <div class="sec-head"><span class="lbl">${S.st?.ace_model || "ACE"} · Slots</span><span class="small muted">${t("Assigning also gives the values to the ACE")}</span></div>
      <${Slots} />
      <div class="ugrid2"><${DryerCard} /><${AceCard} compact /></div>
    </div>
    <div class="ucol">
      <${NoticesCard} />
      ${open && html`<${OpenItemsCard} />`}
    </div>
  </div>`;
}

// ------------------------------------------------------------ filament: spools | filaments
/** Sub-page from the URL: #/filament/filaments (old: #/filament/sorten, #/filamente); else spools. */
export function filamentView() {
  const parts = location.hash.replace(/^#\/?/, "").split(/[/?]/);
  if (parts[0] === "filamente" || parts[1] === "sorten" || parts[1] === "filaments") return "filaments";
  return "spools";
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
    <div class="seg" role="tablist" aria-label=${t("Filament")}>
      ${tab("spools", t("Spools"), S.spools?.length)}${tab("filaments", t("Filaments"), S.catalog?.filaments?.length)}
    </div>
    ${view === "filaments" ? html`<${FilamentPage} />` : html`<${ShelfPage} />`}
  </div>`;
}

function ShelfPage() {
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
      ${S.selFil == null ? html`<div class="empty-state" style="margin:auto">${t("Choose a filament or create a new one.")}</div>`
        : html`<button class="btn ghost back" style="margin:12px 12px 0" onClick=${() => set({ selFil: null })}><${Icon} name="back" small />${t("Filaments")}</button>
               <${FilamentEditor} key=${S.selFil} fid=${S.selFil} />
               <${SpoolsOfFilament} fid=${S.selFil} />`}
    </section>
  </div>`;
}

/** Cross reference filament -> spools: tapping opens the spool under "Spools". */
function SpoolsOfFilament({ fid }) {
  const list = (S.spools || []).filter((s) => s.filament_id === fid);
  if (fid === "neu" || !list.length) return null;
  return html`<div class="dbody col" style="gap:8px;padding-top:0">
    <p class="section-title">${t("Spools of this filament")}</p>
    ${list.map((s) => html`<a class="row spool-link" href="#/filament/spools" onClick=${() => set({ sel: s.spool_id })}>
      <${Swatch} color=${s.color} size=${18} /><span class="grow">#${s.spool_id} · ${s.slot ? `ACE ${s.slot}` : s.location || t("Shelf")}</span>
      <span class="m small">${grams(s.remaining_weight)}</span></a>`)}
  </div>`;
}

// ------------------------------------------------------------ prints
export function JobsPage() {
  useEffect(() => { loadJobs(); }, []);
  const live = S.st?.usage?.live;
  const jobs = S.jobs || [];
  const totalG = jobs.reduce((a, j) => a + j.slots.reduce((b, s) => b + (s.g || 0), 0), 0);
  return html`<div class="col" style="max-width:1600px">
    <div class="row"><h1 class="h1">${t("Prints")}</h1><span class="m small muted">${t("{n} recorded · {kg} kg", { n: jobs.length, kg: num(totalG / 1000) })}</span></div>
    ${(S.st?.usage?.open || []).length > 0 && html`<${OpenItemsCard} />`}
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px">
      ${live && html`<${JobCard} job=${live} live />`}
      ${jobs.map((j) => html`<${JobCard} key=${j.job} job=${j} />`)}
    </div>
    ${!live && !jobs.length && html`<div class="empty-state">${t("No prints recorded yet.")}</div>`}
  </div>`;
}

// ------------------------------------------------------------ ACE page
export function AcePage() {
  const d = S.st?.dryer;
  const req = d?.required || {};
  // switched-off printer modules disappear here; they are switched on again on the Features page
  const off = (x) => !!x && x.present !== false && x.enabled === false;
  const hidden = [off(S.st?.resume) && t("Resume after a power loss"), off(S.st?.clog) && t("Clog detection"),
    off(S.st?.pa) && t("Auto PA")].filter(Boolean);
  return html`<div class="col" style="max-width:1100px">
    <h1 class="h1">ACE</h1>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px;align-items:start">
      <div class="col" style="gap:20px"><${DirectCard} /><${DryerCard} big />${!off(S.st?.resume) && html`<${PowerlossCard} />`}${!off(S.st?.clog) && html`<${ClogCard} />`}<${UsbCard} /></div>
      <div class="col" style="gap:20px"><${AceCard} /><${HotendCard} />${!off(S.st?.pa) && html`<${PaCard} />`}</div>
    </div>
    ${hidden.length > 0 && html`<div class="small muted">${t("Switched off: {names} –", { names: hidden.join(", ") })} <a href="#/features">${t("switch on under Features")}</a></div>`}
    ${d?.present && html`<section class="card pad col">
      <h2 class="h2">${t("Temperature limit")}</h2>
      <div class="kv">${(req.slots || []).map((p) => html`<span>${t("Slot {slot}", { slot: p.slot })} · ${p.name} <span class="faint">(${{ filament: t("on the filament"), vorlage: t("from the template"), standard: t("material value") }[p.source] || p.source})</span></span>
        <span class="m" style=${{ color: (req.limited_by || []).includes(p.slot) ? "var(--accent)" : "" }}>${p.temp} °C</span>`)}
        <span>${t("ACE at most")}</span><span class="m">${req.ace_max ?? "–"} °C</span></div>
      <div class="small muted">${t("Own limit per filament in the field “Drying max.” (Filaments → Temperatures).")}</div>
    </section>`}
    ${d?.present && html`<${HumidityCard} />`}
  </div>`;
}

// ------------------------------------------------------------ devices
export function DevicesPage() {
  const [list, setList] = useState(null);
  const load = () => get("/api/auth/devices").then((r) => setList(r.devices)).catch((e) => toast(e.message, "bad"));
  useEffect(() => { if (S.me) load(); }, [S.me]);
  useEffect(() => { if (!S.dialog && S.me) load(); }, [S.dialog]);
  const KIND = { app: [t("Phone app"), "phone"], web: [t("Browser"), "overview"], plugin: [t("Orca plugin"), "drop"], display: [t("Display"), "overview"],
    other: [t("Other"), "key"] };
  const remove = (d) => openDialog("confirm", {
    title: d.me ? t("Unpair this browser?") : t("Remove “{name}”?", { name: d.name }),
    text: d.me ? t("The browser forgets its key; to change anything it must be paired again.")
      : t("The device can no longer change anything until it is paired again."),
    ok: d.me ? t("Unpair") : t("Remove"), danger: true,
    action: async () => {
      await del(`/api/auth/devices/${d.id}`);
      if (d.me) { auth.clear(); set({ me: null, pairing: true }); } else load();
      toast(t("Removed"), "ok");
    },
  });
  if (!S.me) return html`<div class="col" style="max-width:900px"><h1 class="h1">${t("Devices")}</h1><div class="note">${t("This browser is not paired.")} <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>${t("Pair now")}</a></div></div>`;
  return html`<div class="col" style="max-width:900px">
    <div class="row"><h1 class="h1 grow">${t("Devices")}</h1><button class="btn acc" onClick=${() => openDialog("addDevice")}><${Icon} name="plus" small />${t("Add device")}</button></div>
    <div class="small muted">${t("Every device has its own key. Reading works without one, changing only when paired.")}</div>
    <section class="card">
      ${list == null && html`<div class="empty-state">${t("loading …")}</div>`}
      ${(list || []).map((d, i) => html`
        <div class="row" style=${{ padding: "14px 18px", borderTop: i ? "1px solid var(--line)" : "0" }}>
          <span style="color:var(--muted)"><${Icon} name=${(KIND[d.kind] || KIND.other)[1]} /></span>
          <div class="grow"><b>${d.name}</b>${d.me && html` <span class="chip on">${t("this browser")}</span>`}
            <div class="small muted">${t("{kind} · paired {when} · last seen {ago}", { kind: (KIND[d.kind] || KIND.other)[0], when: when(new Date(d.created * 1000).toISOString()), ago: ago(d.last_seen) })}</div></div>
          ${d.id !== "app_token" && html`<button class="btn sm danger" onClick=${() => remove(d)}>${d.me ? t("Unpair") : t("Remove")}</button>`}
        </div>`)}
    </section>
    <${CameraLinkCard} />
  </div>`;
}

/** Camera link for Mainsail & co.: everyone watches through the bridge, only one connection goes to the printer. */
function CameraLinkCard() {
  const [key, setKey] = useState(null);
  useEffect(() => { cameraKey(true).then(setKey).catch((e) => toast(e.message, "bad")); }, []);
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast(t("Copied"), "ok"); } catch { toast(t("Copying not possible – select the text"), "bad"); }
  };
  const rotate = () => openDialog("confirm", {
    title: t("Create a new camera link?"),
    text: t("The old link (e.g. entered in Mainsail) then shows no image any more and must be replaced."),
    ok: t("Create new"), danger: true,
    action: async () => { setKey((await post("/api/camera/link")).key); await cameraKey(true); toast(t("New camera link"), "ok"); },
  });
  const Line = ({ label, url }) => html`<span style="align-self:center">${label}</span><span class="row" style="gap:8px;min-width:0">
    <span class="m small grow" style="overflow-wrap:anywhere">${url}</span>
    <button class="btn sm icon ghost" aria-label=${t("Copy {label}", { label })} onClick=${() => copy(url)}><${Icon} name="copy" small /></button></span>`;
  return html`<section class="card pad col">
    <div class="row"><h2 class="h2 grow">${t("Camera link")}</h2><button class="btn sm" disabled=${!key} onClick=${rotate}>${t("Create new")}</button></div>
    <div class="small muted">${t("For Mainsail (Settings → Webcams, service “MJPEG-Streamer”) and other programs without pairing. All viewers go through the bridge, the printer delivers the stream only once. The link shows only the camera.")}</div>
    ${key ? html`<div class="kv"><${Line} label=${t("Stream")} url=${cameraLink(key)} /><${Line} label=${t("Snapshot")} url=${cameraLink(key, "snapshot.jpg")} /></div>`
          : html`<div class="small muted">${t("loading …")}</div>`}
  </section>`;
}

// ------------------------------------------------------------ settings / info
/** Number for an input field in the page language ("0.5" / "0,5"). */
const inputNum = (v) => (lang === "de" ? String(v).replace(".", ",") : String(v));
/** A number: saved only on Enter or when leaving the field; range and unit next to it. */
function NumSetting({ it, save }) {
  const [v, setV] = useState(inputNum(it.value));
  useEffect(() => setV(inputNum(it.value)), [it.value]);
  const commit = () => { const n = Number(v.replace(",", ".")); if (v.trim() !== "" && n !== it.value) save(it.key, n); };
  return html`<label class="row small" style="gap:6px">
    <input class="inp set-num" inputmode="decimal" value=${v} onInput=${(e) => setV(e.target.value)} onBlur=${commit}
      onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); }} aria-label=${it.label} />
    <span class="muted">${it.unit}</span></label>`;
}

/** Text: saved only on Enter or when leaving the field. */
function TextSetting({ it, save }) {
  const [v, setV] = useState(it.value || "");
  useEffect(() => setV(it.value || ""), [it.value]);
  return html`<input class="inp set-text" value=${v} placeholder=${t("Drybox=15")} onInput=${(e) => setV(e.target.value)}
    onBlur=${() => { if (v !== (it.value || "")) save(it.key, v); }} onKeyDown=${(e) => { if (e.key === "Enter") e.target.blur(); }} aria-label=${it.label} />`;
}

/** Settings of the bridge, changeable at runtime (stored in the bridge; environment = start value). */
function BridgeSettings() {
  const [v, setV] = useState(null);
  useEffect(() => { get("/api/settings").then(setV).catch((e) => toast(e.message, "bad")); }, []);
  if (!v) return null;
  const save = guard(async (key, value) => { setV(await post("/api/settings", { [key]: value })); toast(t("Saved"), "ok"); });
  const reset = guard(async (key) => { setV(await post("/api/settings/reset", { key })); toast(t("Default restored"), "ok"); });
  const fmt = (it, x) => (it.kind === "bool" ? (x ? t("on") : t("off")) : it.kind === "choice" ? (it.options.find((o) => o[0] === x)?.[1] || x)
    : it.kind === "text" ? (x || t("empty")) : `${inputNum(x)} ${it.unit}`.trim());
  return html`
    ${v.groups.map((g) => html`<section class="card pad col">
      <h2 class="h2">${g.name}</h2>
      ${g.items.map((it) => html`<div class="set-row">
        <div class="grow"><div>${it.label}</div>
          ${it.help && html`<div class="small muted">${it.help}</div>`}
          ${it.kind !== "bool" && it.min != null && html`<div class="small faint">${t("allowed {min}–{max} {unit}", { min: inputNum(it.min), max: inputNum(it.max), unit: it.unit })}</div>`}
          ${it.changed && html`<div class="small" style="color:var(--accent-text)">${t("changed · default {value}", { value: fmt(it, it.default) })} <button class="linkbtn" onClick=${() => reset(it.key)}>${t("reset")}</button></div>`}</div>
        ${it.kind === "bool" ? html`<label class="toggle"><input type="checkbox" role="switch" checked=${!!it.value} onChange=${(e) => save(it.key, e.target.checked)} aria-label=${it.label} /><span class="knob" aria-hidden="true"></span></label>`
          : it.kind === "choice" ? html`<select class="inp set-text" value=${it.value} onChange=${(e) => save(it.key, e.target.value)} aria-label=${it.label}>${it.options.map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select>`
          : it.kind === "text" ? html`<${TextSetting} it=${it} save=${save} />`
          : html`<${NumSetting} it=${it} save=${save} />`}
      </div>`)}
    </section>`)}
    <section class="card pad col">
      <h2 class="h2">${t("More settings")}</h2>
      <div class="row wrap"><a class="btn sm" href="#/features">${t("Features")}</a><a class="btn sm" href="#/ace">${t("Dryer rules (ACE)")}</a><a class="btn sm" href="#/ai">${t("AI")}</a><a class="btn sm" href="#/devices">${t("Devices")}</a></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">${t("Connections")}</h2>
      <div class="kv">${v.readonly.map((r) => html`<span>${r.label}</span><span class="m">${r.value === "" || r.value == null ? "–" : String(r.value)}</span>`)}</div>
      <div class="small muted">${t("These need a restart of the bridge: change them in the stack (environment variables) and redeploy.")}</div>
    </section>`;
}

/** Settings that apply only in this browser (localStorage): language and 3D model. */
function DeviceCard() {
  const [q, setQ] = useState(quality());
  const found = { volume: t("volume"), lines: t("lines"), image: t("image") }[capability()];
  const opts = [["auto", t("Automatic (here: {mode})", { mode: found })], ["volume", t("Volume – shaded strands")],
    ["lines", t("Lines – saves graphics power")], ["image", t("Bridge image – for weak devices")]];
  const bridgeLang = LANGS[S.health?.settings?.language] || "";
  return html`<section class="card pad col">
    <h2 class="h2">${t("This device")}</h2>
    <div class="row wrap"><span class="grow">${t("Language")}</span>
      <select class="inp set-text" value=${chosen} onChange=${(e) => setLang(e.target.value)} aria-label=${t("Language")}>
        <option value="">${bridgeLang ? t("Bridge default ({lang})", { lang: bridgeLang }) : t("Bridge default")}</option>
        ${Object.entries(LANGS).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <div class="row wrap"><span class="grow">${t("3D model")}</span>
      <select class="inp set-text" value=${q} onChange=${(e) => { setQuality(e.target.value); setQ(e.target.value); toast(t("Applies from the next time the model view opens"), "ok"); }} aria-label=${t("3D model")}>
        ${opts.map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select></div>
    <div class="small muted">${t("Applies only in this browser. The bridge default language is under “General” below; the app has its own settings.")}</div>
  </section>`;
}

export function SettingsPage() {
  useEffect(() => { loadHealth(); }, []);
  const h = S.health;
  return html`<div class="col" style="max-width:1100px">
    <h1 class="h1">${t("Settings")}</h1>
    <section class="card pad col">
      <h2 class="h2">${t("This browser")}</h2>
      ${S.me ? html`<div class="row"><span class="grow">${t("Paired as")} <b>${S.me.name}</b></span><a class="btn sm" href="#/devices">${t("Manage devices")}</a></div>`
             : html`<div class="row"><span class="grow muted">${t("Not paired – view only.")}</span><button class="btn sm acc" onClick=${() => set({ pairing: true })}>${t("Pair")}</button></div>`}
    </section>
    <${DeviceCard} />
    <${OrcaCard} />
    ${h && html`
    <section class="card pad col">
      <h2 class="h2">Bridge ${h.version}</h2>
      <div class="kv">
        <span>${t("Running since")}</span><span>${when(h.started)}</span>
        <span>${t("Printer")}</span><span class="m">${h.moonraker.url}</span>
        <span>Spoolman</span><span><a href=${h.links?.spoolman || h.spoolman.url} target="_blank" rel="noopener">${h.links?.spoolman || h.spoolman.url}</a></span>
        ${h.links?.printer_ui && html`<span>${t("Printer UI")}</span><span><a href=${h.links.printer_ui} target="_blank" rel="noopener">${h.links.printer_ui}</a></span>`}
      </div>
    </section>
    <${BridgeSettings} />
    <section class="card pad col">
      <h2 class="h2">${t("New in the bridge")}</h2>
      ${h.changelog.map((c) => html`<div><b class="m">${c.version}</b> <span class="muted small">${c.date}</span><ul style="margin:6px 0 0;padding-left:20px">${c.items.map((i) => html`<li class="small">${i}</li>`)}</ul></div>`)}
    </section>`}
    <div class="small faint">${t("Fonts: Space Grotesk, IBM Plex (SIL OFL) · Preact, htm, qrcode-generator – licence texts are in the bridge under static/licenses.")}</div>
  </div>`;
}

// ------------------------------------------------------------ pairing (first start)
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
    if (clean.length === 2 && digits[i]) clean = clean.replace(digits[i], "") || clean.slice(-1);   // field overwritten
    if (clean.length > 1) {          // pasted
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
      toast(t("Paired as “{name}”", { name: r.device.name }), "ok");
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
      <div><h1 class="h1" style="font-size:28px;margin-bottom:8px">${t("Pair this browser")}</h1>
        <p class="muted" style="margin:0">${reason || t("Once. Afterwards the browser remembers its key and does not ask again.")}</p></div>
      ${!useLong ? html`
        <fieldset style="border:0;margin:0;padding:0">
          <legend class="small muted" style="margin-bottom:10px">${t("Pairing code (6 digits)")}</legend>
          <div class="digits">${digits.map((d, i) => html`${i === 3 && html`<span class="gap"></span>`}<input ref=${(el) => (refs.current[i] = el)} aria-label=${t("Digit {n}", { n: i + 1 })}
            inputmode="numeric" autocomplete="one-time-code" maxlength="6" value=${d} onInput=${(e) => setAt(i, e.target.value)} onKeyDown=${(e) => key(i, e)} />`)}</div>
        </fieldset>` : html`
        <div class="f"><label for="pair-long">${t("Key (APP_TOKEN)")}</label><input id="pair-long" value=${long} onInput=${(e) => setLong(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && pair()} /></div>`}
      <div class="f"><label for="pair-name">${t("Name of this device")}</label><input id="pair-name" value=${name} onInput=${(e) => setName(e.target.value)} /></div>
      ${err && html`<div class="note bad">${err}</div>`}
      <button class="btn acc" style="min-height:52px" disabled=${busy} onClick=${pair}>${busy ? "…" : t("Pair")}</button>
      <div class="note info" style="line-height:1.55">
        <b style="color:var(--text)">${t("Where does the code come from?")}</b><br />
        ${t("In the app or a paired browser under")} <b style="color:var(--text)">${t("Devices → Add device")}</b>.<br />
        ${S.setupRequired ? t("Nothing paired yet: the setup code is in the bridge's log (e.g. Portainer → container → logs).")
          : t("First device? The setup code is in the bridge's log (e.g. Portainer → logs).")}
      </div>
      <div class="row wrap small">
        <a href="#" onClick=${(e) => { e.preventDefault(); setUseLong(!useLong); setErr(""); }}>${useLong ? t("Pair with a 6-digit code") : t("Pair with the old APP_TOKEN")}</a>
        <span class="grow"></span>
        <a href="#" onClick=${(e) => { e.preventDefault(); later(); }}>${t("View only")}</a>
      </div>
    </div>
  </div>`;
}
