// Filaments: list and editor with all Orca fields (same groups as the app's wizard, FilamentDraft.kt).
// Empty fields mean "from the template or the Orca base profile" - template values are shown only as placeholders.
// Labels of extra fields come from Spoolman (their names there).

import { html, useEffect, useMemo, useState } from "../vendor/preact-htm.module.js";
import { Field, Swatch } from "./components.js";
import { lang, t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, guard, loadCatalog, openDialog, set } from "./store.js";
import { cls, hex, parseNum, tint } from "./util.js";

const NATIVE = {
  settings_extruder_temp: [t("Nozzle"), "°C", "int"], settings_bed_temp: [t("Bed textured"), "°C", "int"],
  density: [t("Density"), "g/cm³", "float"], diameter: [t("Diameter"), "mm", "float"], weight: [t("Net per spool"), "g", "float"],
  spool_weight: [t("Empty spool"), "g", "float"], price: [t("Price per spool"), null, "float"],
  article_number: [t("Article number"), null, "text"], comment: [t("Note"), null, "text"],
};
const GROUPS = [
  [t("Physics"), ["diameter", "density", "weight", "spool_weight", "price"]],
  [t("Temperatures"), ["settings_extruder_temp", "nozzle_temp_first_layer", "settings_bed_temp", "bed_temp_first_layer",
    "bed_temp_smooth", "bed_temp_smooth_first_layer", "chamber_temp", "dry_temp"]],
  [t("Cooling"), ["fan_min", "fan_max", "fan_off_first_layers", "overhang_fan", "aux_fan", "air_filtration",
    "exhaust_fan_print", "exhaust_fan_done"]],
  [t("Extrusion"), ["flow_ratio", "pressure_advance", "max_volumetric_speed", "retraction_length", "retraction_speed", "z_hop"]],
  [t("Orca details"), ["orca_overrides"]],
];
const BASE = ["vorlage", "orca_basis", "article_number", "comment"];
const HANDLED = new Set([...GROUPS.flatMap(([, k]) => k), ...BASE]);

/** Field description: native Spoolman fields or extra fields from the catalog. */
function spec(key, cat) {
  const orcaOf = (k) => (cat.fields.find((f) => f.key === k) || cat.native_fields.find((f) => f.key === k) || {}).orca_key;
  if (NATIVE[key]) { const [label, unit, kind] = NATIVE[key]; return { key, label, unit, kind, native: true, orca: orcaOf(key) }; }
  const f = cat.fields.find((x) => x.key === key);
  if (!f) return null;
  const kind = { integer: "int", float: "float", boolean: "bool", choice: "choice" }[f.type] || (key === "orca_overrides" ? "multi" : "text");
  return { key, label: f.name || key, unit: f.unit, kind, native: false, orca: f.orca_key, choices: f.choices };
}

export function text(v) {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return lang === "de" ? String(v).replace(".", ",") : String(v);
  return String(v);
}

/** Which template applies - the same rule as the bridge (profiles.find_template). */
function templateFor(values, templates) {
  if ((values.orca_basis || "").trim()) return null;
  if (values.vorlage) { const hit = templates.find((x) => x.name === values.vorlage); if (hit) return hit; }
  const m = (values.material || "").trim().toUpperCase();
  if (!m) return null;
  const same = templates.filter((t) => (t.material || "").trim().toUpperCase() === m);
  return same.find((x) => (x.name || "").toUpperCase() === "VORLAGE " + m) || same.sort((a, b) => a.id - b.id)[0] || null;
}

function initial(fil) {
  if (!fil) return { vendor: "", name: "", material: "", color_hex: "" };
  const v = { vendor: fil.vendor_id != null ? String(fil.vendor_id) : "", name: fil.name || "", material: fil.material || "",
    color_hex: fil.color ? "#" + fil.color : "" };
  for (const [k, x] of Object.entries(fil.native || {})) if (!["name", "material", "color_hex"].includes(k)) v[k] = text(x);
  for (const [k, x] of Object.entries(fil.extra || {})) v[k] = text(x);
  return v;
}

function convert(sp, raw) {
  const s = String(raw ?? "").trim();
  if (!s) return null;
  if (sp.kind === "int") return Math.round(parseNum(s));
  if (sp.kind === "float") return parseNum(s);
  if (sp.kind === "bool") return s === "true";
  return s;
}

export function FilamentEditor({ fid, embedded }) {
  const cat = S.catalog;
  useEffect(() => { if (!cat) loadCatalog(); }, []);
  const isNew = fid === "neu";
  const fil = !isNew && cat ? cat.filaments.find((f) => f.filament_id === fid) : null;
  const [v, setV] = useState(() => initial(fil));
  const [newVendor, setNewVendor] = useState("");
  const [busy, setBusy] = useState(false);
  const origKey = fil ? JSON.stringify(initial(fil)) : "neu";
  useEffect(() => { setV(initial(fil)); setNewVendor(""); }, [fid, origKey]);

  const specs = useMemo(() => {
    if (!cat) return [];
    const groups = GROUPS.map(([title, keys]) => [title, keys.map((k) => spec(k, cat)).filter(Boolean)]);
    const others = cat.fields.filter((f) => !HANDLED.has(f.key)).map((f) => spec(f.key, cat)).filter(Boolean);
    if (others.length) groups.push([t("More"), others]);
    return groups;
  }, [cat]);
  if (!cat) return html`<div class="empty-state">${t("loading the catalog …")}</div>`;
  if (!isNew && !fil) return html`<div class="empty-state">${t("Filament #{id} not found.", { id: fid })}</div>`;

  const orig = initial(fil);
  const all = [...specs.flatMap(([, s]) => s), ...BASE.map((k) => spec(k, cat)).filter(Boolean)];
  const changed = new Set(Object.keys({ ...orig, ...v }).filter((k) => (v[k] || "") !== (orig[k] || "")));
  if (newVendor) changed.add("vendor");
  const tpl = templateFor(v, cat.templates);
  const ph = (sp) => { const x = tpl && (sp.native ? tpl.native[sp.key] : tpl.extra[sp.key]); return x == null ? "" : text(x); };

  const errors = {};
  if (!v.name.trim()) errors.name = t("Name missing");
  if (!v.material.trim()) errors.material = t("Material missing");
  if (isNew && !v.vendor && !newVendor.trim()) errors.vendor = t("Choose a vendor");
  if (v.vendor === "+" && !newVendor.trim()) errors.vendor = t("Enter a name");
  if (v.color_hex && !hex(v.color_hex)) errors.color_hex = t("Colour as #RRGGBB");
  for (const sp of all) if ((sp.kind === "int" || sp.kind === "float") && Number.isNaN(parseNum(v[sp.key]))) errors[sp.key] = t("Number expected");
  const valid = !Object.keys(errors).length;

  const save = guard(async () => {
    setBusy(true);
    try {
      const a = await import("./actions.js");
      let vendorId = v.vendor && v.vendor !== "+" ? Number(v.vendor) : null;
      if (v.vendor === "+") vendorId = (await a.createVendor(newVendor.trim())).id;
      const body = {};
      const extra = {};
      const put = (sp) => {
        const val = convert(sp, v[sp.key]);
        if (isNew && val == null) return;
        if (sp.native) body[sp.key] = val; else extra[sp.key] = val;
      };
      if (isNew || changed.has("name")) body.name = v.name.trim();
      if (isNew || changed.has("material")) body.material = v.material.trim();
      if ((isNew && v.color_hex) || (!isNew && changed.has("color_hex"))) body.color_hex = v.color_hex ? hex(v.color_hex).slice(1) : null;
      if (isNew || changed.has("vendor")) body.vendor_id = vendorId;
      for (const sp of all) if (isNew || changed.has(sp.key)) put(sp);
      if (Object.keys(extra).length) body.extra = extra;
      if (isNew) {
        const f = await a.createFilament(body);
        set({ selFil: f?.filament_id ?? null });
      } else {
        await a.updateFilament(fid, body);
      }
    } finally { setBusy(false); }
  });

  const input = (sp) => {
    const id = "fil-" + sp.key;
    const val = v[sp.key] || "";
    const on = (e) => setV({ ...v, [sp.key]: e.target.value });
    let control;
    if (sp.kind === "bool") {
      const p = ph(sp);
      control = html`<select id=${id} value=${val} onChange=${on}><option value="">${p ? (p === "true" ? t("from the template (yes)") : t("from the template (no)")) : t("not set")}</option><option value="true">${t("yes")}</option><option value="false">${t("no")}</option></select>`;
    } else if (sp.kind === "choice") {
      control = html`<select id=${id} value=${val} onChange=${on}><option value="">${sp.key === "vorlage" ? t("automatic by material") : "–"}</option>${(sp.choices || []).map((c) => html`<option value=${c}>${c}</option>`)}</select>`;
    } else if (sp.kind === "multi") {
      control = html`<textarea id=${id} value=${val} placeholder=${ph(sp) || t("key = value (one line per value)")} onInput=${on}></textarea>`;
    } else if (sp.key === "orca_basis") {
      control = html`<input id=${id} list="orca-bases" value=${val} placeholder=${t("empty = template")} onInput=${on} />
        <datalist id="orca-bases">${(cat.orca_bases || []).map((n) => html`<option value=${n} />`)}</datalist>`;
    } else {
      control = html`<input id=${id} value=${val} inputmode=${sp.kind === "text" ? "text" : "decimal"} placeholder=${ph(sp)} onInput=${on} />`;
    }
    return html`<${Field} key=${sp.key} id=${id} label=${sp.label + (sp.unit ? ` (${sp.unit})` : "")} orca=${sp.orca} changed=${changed.has(sp.key)} error=${errors[sp.key]}>${control}</${Field}>`;
  };

  const materials = [...new Set([...cat.templates, ...cat.filaments].map((f) => f.material).filter(Boolean))].sort();
  const color = hex(v.color_hex);
  const head = !embedded && html`
    <div class="dhead" style=${{ background: color ? tint(color) : "var(--surface)" }}>
      <${Swatch} color=${color} size=${56} />
      <div class="grow">
        <div class="m small muted">${isNew ? t("NEW FILAMENT") : (fil.spools === 1 ? t("FILAMENT · 1 SPOOL · {orca}", { orca: fil.orca_id }) : t("FILAMENT · {n} SPOOLS · {orca}", { n: fil.spools, orca: fil.orca_id }))}</div>
        <div class="g ell" style="font-weight:700;font-size:24px">${isNew ? (v.name || t("New filament")) : fil.display_name}</div>
        <div class="small muted">${tpl ? t("Empty fields from “{name}”", { name: tpl.name }) : v.orca_basis ? t("Empty fields from Orca “{name}”", { name: v.orca_basis }) : t("No template found")}</div>
      </div>
      ${!isNew && html`<button class="btn ghost" onClick=${guard(() => openDialog("copyFilament", { fil }))}><${Icon} name="copy" small />${t("New colour")}</button>`}
    </div>`;
  return html`
  ${head}
  <div class=${embedded ? "col" : "dbody"} style=${embedded ? "gap:18px" : ""}>
    ${embedded && html`<div class="small muted">${fil.display_name} · ${fil.orca_id} · ${fil.spools === 1 ? t("1 spool") : t("{n} spools", { n: fil.spools })} · ${tpl ? t("empty fields from “{name}”", { name: tpl.name }) : v.orca_basis ? t("empty fields from Orca “{name}”", { name: v.orca_basis }) : t("no template")}</div>`}
    <p class="section-title">${t("Basics")}</p>
    <div class="fgrid">
      <${Field} id="fil-vendor" label=${t("Vendor")} changed=${changed.has("vendor")} error=${errors.vendor}>
        <select id="fil-vendor" value=${v.vendor} onChange=${(e) => setV({ ...v, vendor: e.target.value })}>
          <option value="">${isNew ? t("choose …") : t("none")}</option>
          ${cat.vendors.map((x) => html`<option value=${String(x.id)}>${x.name}</option>`)}
          <option value="+">${t("+ new vendor …")}</option>
        </select>
      </${Field}>
      ${v.vendor === "+" && html`<${Field} id="fil-newvendor" label=${t("New vendor")}><input id="fil-newvendor" value=${newVendor} onInput=${(e) => setNewVendor(e.target.value)} /></${Field}>`}
      <${Field} id="fil-name" label=${t("Name")} changed=${changed.has("name")} error=${errors.name} hint=${t("e.g. PETG 2.0 Mint green")}>
        <input id="fil-name" value=${v.name} onInput=${(e) => setV({ ...v, name: e.target.value })} />
      </${Field}>
      <${Field} id="fil-material" label=${t("Material")} orca="filament_type" changed=${changed.has("material")} error=${errors.material}>
        <input id="fil-material" list="materials" value=${v.material} onInput=${(e) => setV({ ...v, material: e.target.value })} />
        <datalist id="materials">${materials.map((m) => html`<option value=${m} />`)}</datalist>
      </${Field}>
      <${Field} id="fil-color" label=${t("Colour")} orca="default_filament_colour" changed=${changed.has("color_hex")} error=${errors.color_hex}>
        <div class="colorrow"><input type="color" aria-label=${t("Choose a colour")} value=${color || "#888888"} onInput=${(e) => setV({ ...v, color_hex: e.target.value.toUpperCase() })} />
        <input id="fil-color" value=${v.color_hex} placeholder="#RRGGBB" onInput=${(e) => setV({ ...v, color_hex: e.target.value })} /></div>
      </${Field}>
      ${BASE.slice(0, 3).map((k) => spec(k, cat)).filter(Boolean).map(input)}
    </div>
    ${specs.map(([title, list]) => list.length > 0 && html`<p class="section-title">${title}</p><div class="fgrid">${list.map(input)}</div>`)}
    ${spec("comment", cat) && html`<div class="fgrid">${input(spec("comment", cat))}</div>`}
  </div>
  ${(changed.size > 0 || isNew) && html`
  <div class=${embedded ? "col" : "dfoot"} style=${embedded ? "gap:10px" : ""}>
    ${!isNew && html`<div class="note" style="width:100%">${t("Changed: {fields}. After saving, “Update profiles” in Orca, then Orca's sync button.", { fields: [...changed].map((k) => (all.find((s) => s.key === k)?.label) || { name: t("Name"), material: t("Material"), color_hex: t("Colour"), vendor: t("Vendor") }[k] || k).join(", ") })}</div>`}
    <div class="row wrap">
      <button class="btn acc" disabled=${!valid || busy} onClick=${save}>${isNew ? t("Create filament") : t("Save")}</button>
      ${!isNew && html`<button class="btn ghost" onClick=${() => { setV(initial(fil)); setNewVendor(""); }}>${t("Discard")}</button>`}
      ${!valid && html`<span class="small" style="color:var(--danger-text)">${Object.values(errors)[0]}</span>`}
    </div>
  </div>`}`;
}

// ------------------------------------------------------------ list
export function FilamentList() {
  const cat = S.catalog;
  const [q, setQ] = useState("");
  if (!cat) return html`<section class="card listcard"><div class="empty-state">${t("loading …")}</div></section>`;
  const list = cat.filaments.filter((f) => !q || `${f.display_name} ${f.material} ${f.orca_id}`.toLowerCase().includes(q.toLowerCase()));
  return html`
  <section class="card listcard" aria-label=${t("Filaments")}>
    <div class="listbar">
      <span class="h2">${t("Filaments")}</span><span class="m small muted">${cat.filaments.length}</span>
      <span class="grow"></span>
      <label class="search" style="min-height:38px"><${Icon} name="search" small /><input aria-label=${t("Search filaments")} value=${q} onInput=${(e) => setQ(e.target.value)} placeholder=${t("search")} /></label>
      <button class="btn sm acc" onClick=${guard(() => set({ selFil: "neu" }))}><${Icon} name="plus" small />${t("New")}</button>
    </div>
    <div class="table" role="listbox" aria-label=${t("Filaments")}>
      <div class="tr th fil"><span></span><span>${t("Filament")}</span><span>${t("Material")}</span><span class="hide-s">Orca</span><span class="hide-s">${t("Spools")}</span></div>
      ${list.map((f) => html`
        <div key=${f.filament_id} role="option" aria-selected=${S.selFil === f.filament_id} class=${cls("tr fil", S.selFil === f.filament_id && "sel")} onClick=${() => set({ selFil: f.filament_id })}>
          <${Swatch} color=${f.color} />
          <span class="ell"><b>${f.name}</b><span class="muted"> · ${f.vendor}</span></span>
          <span>${f.material}</span>
          <span class="m small muted hide-s">${f.orca_id}</span>
          <span class="m hide-s">${f.spools}</span>
        </div>`)}
    </div>
  </section>`;
}
