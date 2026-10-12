// Shelf: list of all spools with search/filters and the detail view of a spool.

import { MoistureChip, SpoolMoisture } from "./humidity.js";
import { html, useEffect, useMemo, useRef, useState } from "../vendor/preact-htm.module.js";
import { get } from "./api.js";
import { Bar, Field, Spool, Swatch } from "./components.js";
import { FilamentEditor } from "./filaments.js";
import { lang, t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, openDialog, set, spoolById } from "./store.js";
import { cls, fileName, grams, meters, num, parseNum, tint, title, when } from "./util.js";

const LOW_G = 200;

export function spoolMenu(sp) {
  const slots = S.st?.slots || [];
  const go = (fn) => guard(() => import("./actions.js").then(fn));
  return [
    { label: t("Open"), icon: "spool", run: () => set({ sel: sp.spool_id }) },
    "-",
    ...slots.map((sl) => ({
      label: sl.spool ? t("Put into slot {slot} (instead of {name})", { slot: sl.slot, name: sl.spool.name }) : t("Put into slot {slot}", { slot: sl.slot }),
      icon: "play", disabled: sp.slot === sl.slot, run: go((a) => a.moveSpool(sp.spool_id, sl.slot)),
    })),
    { label: t("To the shelf"), icon: "shelf", disabled: !sp.slot, run: go((a) => a.moveSpool(sp.spool_id, null)) },
    "-",
    { label: t("Archive …"), icon: "archive", run: guard(() => confirmArchive(sp)) },
  ];
}

function confirmArchive(sp) {
  openDialog("confirm", {
    title: t("Archive spool #{id}?", { id: sp.spool_id }),
    text: t("{name} ({g} left) disappears from shelf and slots. In Spoolman it stays, archived.", { name: sp.display_name, g: grams(sp.remaining_weight) }),
    ok: t("Archive"), danger: true,
    action: () => import("./actions.js").then((a) => a.archiveSpool(sp.spool_id)),
  });
}

/** "· 2 NFC tags", or a hint when the tag of the second spool side is missing for the ACE 2 Pro. */
function tagsText(sp) {
  const n = (sp.nfc_uids || (sp.nfc_uid ? [sp.nfc_uid] : [])).length;
  return n >= 2 ? " · " + t("2 NFC tags") : n === 1 ? " · " + t("1 NFC tag (second side missing)") : "";
}

/** Spools by search and filter. */
export function useFilteredSpools() {
  const all = S.spools || [];
  const q = (S.q || "").trim().toLowerCase();
  const f = S.filter || "all";
  return useMemo(() => {
    let out = all.slice();
    if (q) out = out.filter((s) => `${s.display_name} ${s.material} ${s.location || ""} #${s.spool_id} ${s.tag_nr || ""}`.toLowerCase().includes(q));
    if (f === "ace") out = out.filter((s) => s.slot);
    else if (f === "low") out = out.filter((s) => (s.remaining_weight ?? 1e9) < LOW_G);
    else if (f === "damp") out = out.filter((s) => S.st?.moisture?.[String(s.spool_id)]?.needs_drying);
    else if (f !== "all") out = out.filter((s) => (s.material || "").toUpperCase() === f);
    out.sort((a, b) => (a.slot || 99) - (b.slot || 99) || a.material.localeCompare(b.material) || a.display_name.localeCompare(b.display_name) || a.spool_id - b.spool_id);
    return out;
  }, [all, q, f]);
}

export function SpoolList({ wideCols }) {
  const list = useFilteredSpools();
  const all = S.spools || [];
  const materials = [...new Set(all.map((s) => (s.material || "").toUpperCase()).filter(Boolean))].sort();
  const total = all.reduce((a, s) => a + (s.remaining_weight || 0), 0);
  const tableRef = useRef(null);
  useEffect(() => {
    const row = tableRef.current?.querySelector(".tr.sel");
    row?.scrollIntoView({ block: "nearest" });
  }, [S.sel]);
  const chip = (key, label) => html`<button class=${cls("chip", (S.filter || "all") === key && "on")} onClick=${() => set({ filter: key })}>${label}</button>`;
  return html`
  <section class="card listcard" aria-label=${t("Shelf")}>
    <div class="listbar">
      <span class="h2">${t("Spools")}</span><span class="m small muted">${t("{n} spools · {kg} kg", { n: all.length, kg: num(total / 1000) })}</span>
      <span class="grow"></span>
      ${chip("all", t("All"))}${materials.map((m) => chip(m, m))}
      ${chip("ace", t("in the ACE"))}${chip("low", t("almost empty"))}${chip("damp", t("to dry"))}
    </div>
    <div class="table" ref=${tableRef} role="listbox" aria-label=${t("Spools")}>
      <div class="tr th"><span></span><span class="hide-s">ID</span><span>${t("Filament")}</span><span class="hide-s">${t("Mat.")}</span><span>${t("Left")}</span><span class="hide-s">${t("Location")}</span>${wideCols && html`<span class="opt">${t("Tag")}</span>`}</div>
      ${S.spools == null && html`<div class="empty-state">${t("loading …")}</div>`}
      ${S.spools && !list.length && html`<div class="empty-state">${t("No spool matches.")}</div>`}
      ${list.map((s) => html`
        <div key=${s.spool_id} role="option" aria-selected=${S.sel === s.spool_id} class=${cls("tr", S.sel === s.spool_id && "sel")}
             onClick=${() => set({ sel: s.spool_id })}
             onContextMenu=${(e) => { e.preventDefault(); set({ sel: s.spool_id, menu: { x: e.clientX, y: e.clientY, items: spoolMenu(s) } }); }}>
          <${Swatch} color=${s.color} />
          <span class="m muted hide-s">#${s.spool_id}</span>
          <span class="ell"><b>${s.name}</b><span class="muted"> · ${s.vendor}</span> <${MoistureChip} id=${s.spool_id} /></span>
          <span class="hide-s">${s.material}</span>
          <span class="row" style="gap:8px"><${Bar} value=${s.remaining_weight} max=${s.initial_weight || 1000} warnBelow=${LOW_G} /><span class="m small" style="min-width:56px;text-align:right">${grams(s.remaining_weight)}</span></span>
          <span class="hide-s ell" style=${{ color: s.slot ? "var(--accent)" : "var(--text)" }}>${s.slot ? `ACE ${s.slot}` : s.location || "–"}</span>
          ${wideCols && html`<span class="opt m muted">${s.tag_nr || "–"}</span>`}
        </div>`)}
    </div>
  </section>`;
}

// ------------------------------------------------------------ detail
function useSpoolDetail(id) {
  const [d, setD] = useState(null);
  const sp = spoolById(id);
  const stamp = sp ? `${sp.remaining_weight}|${sp.location}|${sp.lot_nr}|${sp.comment}` : "";
  useEffect(() => {
    let alive = true;
    if (id == null) { setD(null); return; }
    get(`/api/app/spool/${id}`).then((r) => alive && setD(r)).catch(() => alive && setD(null));
    return () => { alive = false; };
  }, [id, stamp]);
  return d;
}

const SPOOL_FIELDS = [
  ["remaining_weight", t("Remaining weight"), "g"], ["spool_weight", t("Empty spool"), "g"], ["initial_weight", t("Net when new"), "g"],
  ["price", t("Price"), null], ["lot_nr", t("Lot"), null],
];
/** Number for an input field in the page language ("0.5" / "0,5"). */
const inputNum = (v) => (lang === "de" ? String(v).replace(".", ",") : String(v));

function SpoolForm({ sp, readOnly }) {
  const init = () => Object.fromEntries([...SPOOL_FIELDS.map(([k]) => [k, sp[k] == null ? "" : typeof sp[k] === "number" ? inputNum(Math.round(sp[k] * 10) / 10) : String(sp[k])]),
    ["comment", sp.comment || ""], ["location", sp.slot ? "" : sp.location || ""]]);
  const [v, setV] = useState(init);
  useEffect(() => setV(init()), [sp.spool_id, sp.remaining_weight, sp.location, sp.lot_nr, sp.comment, sp.spool_weight, sp.price, sp.initial_weight]);
  const orig = init();
  const changed = Object.keys(v).filter((k) => v[k] !== orig[k]);
  const errors = {};
  for (const [k] of SPOOL_FIELDS) if (k !== "lot_nr" && Number.isNaN(parseNum(v[k]))) errors[k] = t("Number expected");
  const locations = [...new Set((S.spools || []).filter((s) => !s.slot && s.location).map((s) => s.location))];
  const save = guard(async () => {
    const body = {};
    for (const k of changed) {
      if (["comment", "lot_nr", "location"].includes(k)) body[k] = v[k].trim() || (k === "location" ? undefined : null);
      else body[k] = parseNum(v[k]);
    }
    if (body.location === undefined) delete body.location;
    const a = await import("./actions.js");
    await a.updateSpool(sp.spool_id, body);
  });
  const field = (k, label, unit) => html`
    <${Field} id=${"sp-" + k} label=${label + (unit ? ` (${unit})` : "")} changed=${changed.includes(k)} error=${errors[k]}>
      <input id=${"sp-" + k} inputmode=${k === "lot_nr" ? "text" : "decimal"} value=${v[k]} disabled=${readOnly}
             onInput=${(e) => setV({ ...v, [k]: e.target.value })} onKeyDown=${(e) => e.key === "Enter" && !Object.keys(errors).length && changed.length && save()} />
    </${Field}>`;
  return html`
  <div class="fgrid">${SPOOL_FIELDS.map(([k, l, u]) => field(k, l, u))}
    ${!sp.slot && html`<${Field} id="sp-location" label=${t("Storage location")} changed=${changed.includes("location")}>
      <input id="sp-location" list="sp-locations" value=${v.location} disabled=${readOnly} onInput=${(e) => setV({ ...v, location: e.target.value })} />
      <datalist id="sp-locations">${locations.map((l) => html`<option value=${l} />`)}</datalist>
    </${Field}>`}
  </div>
  <${Field} id="sp-comment" label=${t("Note")} changed=${changed.includes("comment")}>
    <input id="sp-comment" value=${v.comment} disabled=${readOnly} onInput=${(e) => setV({ ...v, comment: e.target.value })} />
  </${Field}>
  ${changed.length > 0 && html`<div class="row wrap">
    <button class="btn acc" disabled=${Object.keys(errors).length > 0} onClick=${save}>${t("Save")}</button>
    <button class="btn ghost" onClick=${() => setV(init())}>${t("Discard")}</button>
    <span class="small muted">${t("{n} changed", { n: changed.length })}</span>
  </div>`}`;
}

export function SpoolDetail({ id, onBack }) {
  const sp = spoolById(id);
  const d = useSpoolDetail(id);
  const [tab, setTab] = useState("spool");
  useEffect(() => setTab((x) => x), [id]);
  if (id == null) {
    return html`<section class="card detail"><div class="empty-state" style="margin:auto">${t("Choose a spool in the list.")}<br /><span class="small faint">${t("↑ ↓ select · right click for a slot")}</span></div></section>`;
  }
  if (!sp) return html`<section class="card detail"><div class="empty-state" style="margin:auto">${t("Spool #{id} not found (archived?).", { id })}</div></section>`;
  const used = sp.used_weight;
  const tabBtn = (k, l) => html`<button role="tab" aria-selected=${tab === k} onClick=${() => setTab(k)}>${l}</button>`;
  const menu = (e) => set({ menu: { x: e.clientX, y: e.clientY + 8, items: spoolMenu(sp) } });
  return html`
  <section class="card detail" aria-label=${t("Spool #{id}", { id })}>
    <div class="dhead" style=${{ background: tint(sp.color) }}>
      ${onBack && html`<button class="btn icon ghost back" aria-label=${t("Back")} onClick=${onBack}><${Icon} name="back" /></button>`}
      <${Spool} color=${sp.color} size=${64} />
      <div class="grow">
        <div class="m small muted">${t("SPOOL #{id}", { id: sp.spool_id })} · ${sp.slot ? t("IN THE ACE, SLOT {slot}", { slot: sp.slot }) : (sp.location || t("no location")).toUpperCase()}</div>
        <div class="g ell" style="font-weight:700;font-size:24px">${title(sp)}</div>
        <div class="muted small">${sp.vendor}${sp.tag_nr ? " · " + t("Tag {nr}", { nr: sp.tag_nr }) : ""}${tagsText(sp)}</div>
      </div>
      <button class="btn" onClick=${(e) => { e.stopPropagation(); menu(e); }}>${sp.slot ? t("Change slot") : t("Put into a slot")}</button>
    </div>
    <div class="tabs" role="tablist">${tabBtn("spool", t("Spool"))}${tabBtn("filament", t("Filament"))}${tabBtn("usage", t("Consumption"))}${tabBtn("moisture", t("Moisture"))}</div>
    <div class="dbody">
      ${tab === "spool" && html`
        <div class="stats">
          <div class="stat"><div class="small muted">${t("Left")}</div><div class="v">${grams(sp.remaining_weight)}</div></div>
          <div class="stat"><div class="small muted">${t("Length")}</div><div class="v">${meters(sp.remaining_length)}</div></div>
          <div class="stat"><div class="small muted">${t("Used up")}</div><div class="v">${grams(used)}</div></div>
        </div>
        <${SpoolForm} sp=${sp} readOnly=${!S.me} />
        <hr class="sep" />
        <div class="row wrap">
          ${sp.slot ? html`<button class="btn ghost" onClick=${guard(() => import("./actions.js").then((a) => a.moveSpool(sp.spool_id, null)))}><${Icon} name="shelf" small />${t("To the shelf")}</button>` : null}
          <span class="grow"></span>
          <button class="btn danger" onClick=${guard(() => confirmArchive(sp))}><${Icon} name="archive" small />${t("Archive")}</button>
        </div>`}
      ${tab === "filament" && (sp.filament_id ? html`<${FilamentEditor} fid=${sp.filament_id} embedded />` : html`<div class="empty-state">${t("No filament.")}</div>`)}
      ${tab === "moisture" && html`<${SpoolMoisture} id=${sp.spool_id} />`}
      ${tab === "usage" && html`
        <div class="kv">
          <span>${t("First used")}</span><span>${when(sp.first_used)}</span>
          <span>${t("Last used")}</span><span>${when(sp.last_used)}</span>
          <span>${t("Created")}</span><span>${when(sp.registered)}</span>
          <span>${t("Used up in total")}</span><span class="m">${grams(used)}</span>
        </div>
        <div class="section-title">${t("Prints with this spool")}</div>
        ${!d && html`<div class="muted small">${t("loading …")}</div>`}
        ${d && !d.jobs.length && html`<div class="muted small">${t("No recorded print yet.")}</div>`}
        ${d && d.jobs.map((j) => html`<div class="row small"><span class="m ell grow">${fileName(j.file)}</span><span class="muted">${when(j.ended)}</span><span class="m" style="min-width:70px;text-align:right">${grams(j.g)}</span></div>`)}`}
    </div>
  </section>`;
}
