// Filamente: Liste und Editor mit allen Orca-Feldern (gleiche Gruppen wie der Assistent der App, FilamentDraft.kt).
// Leere Felder bedeuten "aus der Vorlage bzw. dem Orca-Basisprofil" - die Vorlagenwerte stehen nur als Platzhalter da.

import { html, useEffect, useMemo, useState } from "../vendor/preact-htm.module.js";
import { Field, Swatch } from "./components.js";
import { Icon } from "./icons.js";
import { S, guard, loadCatalog, openDialog, set } from "./store.js";
import { cls, hex, parseNum, tint } from "./util.js";

const NATIVE = {
  settings_extruder_temp: ["Düse", "°C", "int"], settings_bed_temp: ["Bett texturiert", "°C", "int"],
  density: ["Dichte", "g/cm³", "float"], diameter: ["Durchmesser", "mm", "float"], weight: ["Netto je Spule", "g", "float"],
  spool_weight: ["Leerspule", "g", "float"], price: ["Preis je Spule", "€", "float"],
  article_number: ["Artikelnummer", null, "text"], comment: ["Notiz", null, "text"],
};
const GROUPS = [
  ["Physik", ["diameter", "density", "weight", "spool_weight", "price"]],
  ["Temperaturen", ["settings_extruder_temp", "nozzle_temp_first_layer", "settings_bed_temp", "bed_temp_first_layer",
    "bed_temp_smooth", "bed_temp_smooth_first_layer", "chamber_temp", "dry_temp"]],
  ["Kühlung", ["fan_min", "fan_max", "fan_off_first_layers", "overhang_fan", "aux_fan", "air_filtration",
    "exhaust_fan_print", "exhaust_fan_done"]],
  ["Extrusion", ["flow_ratio", "pressure_advance", "max_volumetric_speed", "retraction_length", "retraction_speed", "z_hop"]],
  ["Orca-Feinheiten", ["orca_overrides"]],
];
const BASE = ["vorlage", "orca_basis", "article_number", "comment"];
const HANDLED = new Set([...GROUPS.flatMap(([, k]) => k), ...BASE]);

/** Feldbeschreibung: native Spoolman-Felder oder Zusatzfelder aus dem Katalog. */
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
  if (typeof v === "number") return String(v).replace(".", ",");
  return String(v);
}

/** Welche Vorlage gilt - dieselbe Regel wie die Bridge (profiles.find_template). */
function templateFor(values, templates) {
  if ((values.orca_basis || "").trim()) return null;
  if (values.vorlage) { const t = templates.find((t) => t.name === values.vorlage); if (t) return t; }
  const m = (values.material || "").trim().toUpperCase();
  if (!m) return null;
  const same = templates.filter((t) => (t.material || "").trim().toUpperCase() === m);
  return same.find((t) => (t.name || "").toUpperCase() === "VORLAGE " + m) || same.sort((a, b) => a.id - b.id)[0] || null;
}

function initial(fil) {
  if (!fil) return { vendor: "", name: "", material: "", color_hex: "" };
  const v = { vendor: fil.vendor_id != null ? String(fil.vendor_id) : "", name: fil.name || "", material: fil.material || "",
    color_hex: fil.color ? "#" + fil.color : "" };
  for (const [k, x] of Object.entries(fil.native || {})) if (!["name", "material", "color_hex"].includes(k)) v[k] = text(x);
  for (const [k, x] of Object.entries(fil.extra || {})) v[k] = text(x);
  return v;
}

function convert(sp, t) {
  const s = String(t ?? "").trim();
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
    if (others.length) groups.push(["Weitere", others]);
    return groups;
  }, [cat]);
  if (!cat) return html`<div class="empty-state">lade Katalog …</div>`;
  if (!isNew && !fil) return html`<div class="empty-state">Filament #${fid} nicht gefunden.</div>`;

  const orig = initial(fil);
  const all = [...specs.flatMap(([, s]) => s), ...BASE.map((k) => spec(k, cat)).filter(Boolean)];
  const changed = new Set(Object.keys({ ...orig, ...v }).filter((k) => (v[k] || "") !== (orig[k] || "")));
  if (newVendor) changed.add("vendor");
  const tpl = templateFor(v, cat.templates);
  const ph = (sp) => { const x = tpl && (sp.native ? tpl.native[sp.key] : tpl.extra[sp.key]); return x == null ? "" : text(x); };

  const errors = {};
  if (!v.name.trim()) errors.name = "Name fehlt";
  if (!v.material.trim()) errors.material = "Material fehlt";
  if (isNew && !v.vendor && !newVendor.trim()) errors.vendor = "Hersteller wählen";
  if (v.vendor === "+" && !newVendor.trim()) errors.vendor = "Namen eingeben";
  if (v.color_hex && !hex(v.color_hex)) errors.color_hex = "Farbe als #RRGGBB";
  for (const sp of all) if ((sp.kind === "int" || sp.kind === "float") && Number.isNaN(parseNum(v[sp.key]))) errors[sp.key] = "Zahl erwartet";
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
      control = html`<select id=${id} value=${val} onChange=${on}><option value="">${p ? `aus Vorlage (${p === "true" ? "ja" : "nein"})` : "nicht gesetzt"}</option><option value="true">ja</option><option value="false">nein</option></select>`;
    } else if (sp.kind === "choice") {
      control = html`<select id=${id} value=${val} onChange=${on}><option value="">${sp.key === "vorlage" ? "automatisch nach Material" : "–"}</option>${(sp.choices || []).map((c) => html`<option value=${c}>${c}</option>`)}</select>`;
    } else if (sp.kind === "multi") {
      control = html`<textarea id=${id} value=${val} placeholder=${ph(sp) || "schluessel = wert (eine Zeile je Wert)"} onInput=${on}></textarea>`;
    } else if (sp.key === "orca_basis") {
      control = html`<input id=${id} list="orca-bases" value=${val} placeholder="leer = Vorlage" onInput=${on} />
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
        <div class="m small muted">${isNew ? "NEUES FILAMENT" : `FILAMENT · ${fil.spools} SPULE${fil.spools === 1 ? "" : "N"} · ${fil.orca_id}`}</div>
        <div class="g ell" style="font-weight:700;font-size:24px">${isNew ? (v.name || "Neues Filament") : fil.display_name}</div>
        <div class="small muted">${tpl ? `Leere Felder aus „${tpl.name}“` : v.orca_basis ? `Leere Felder aus Orca „${v.orca_basis}“` : "Keine Vorlage gefunden"}</div>
      </div>
      ${!isNew && html`<button class="btn ghost" onClick=${guard(() => openDialog("copyFilament", { fil }))}><${Icon} name="copy" small />Neue Farbe</button>`}
    </div>`;
  return html`
  ${head}
  <div class=${embedded ? "col" : "dbody"} style=${embedded ? "gap:18px" : ""}>
    ${embedded && html`<div class="small muted">${fil.display_name} · ${fil.orca_id} · ${fil.spools} Spule${fil.spools === 1 ? "" : "n"} · ${tpl ? `leere Felder aus „${tpl.name}“` : v.orca_basis ? `leere Felder aus Orca „${v.orca_basis}“` : "keine Vorlage"}</div>`}
    <p class="section-title">Grunddaten</p>
    <div class="fgrid">
      <${Field} id="fil-vendor" label="Hersteller" changed=${changed.has("vendor")} error=${errors.vendor}>
        <select id="fil-vendor" value=${v.vendor} onChange=${(e) => setV({ ...v, vendor: e.target.value })}>
          <option value="">${isNew ? "wählen …" : "ohne"}</option>
          ${cat.vendors.map((x) => html`<option value=${String(x.id)}>${x.name}</option>`)}
          <option value="+">+ neuer Hersteller …</option>
        </select>
      </${Field}>
      ${v.vendor === "+" && html`<${Field} id="fil-newvendor" label="Neuer Hersteller"><input id="fil-newvendor" value=${newVendor} onInput=${(e) => setNewVendor(e.target.value)} /></${Field}>`}
      <${Field} id="fil-name" label="Name" changed=${changed.has("name")} error=${errors.name} hint="z.B. PETG 2.0 Mintgrün">
        <input id="fil-name" value=${v.name} onInput=${(e) => setV({ ...v, name: e.target.value })} />
      </${Field}>
      <${Field} id="fil-material" label="Material" orca="filament_type" changed=${changed.has("material")} error=${errors.material}>
        <input id="fil-material" list="materials" value=${v.material} onInput=${(e) => setV({ ...v, material: e.target.value })} />
        <datalist id="materials">${materials.map((m) => html`<option value=${m} />`)}</datalist>
      </${Field}>
      <${Field} id="fil-color" label="Farbe" orca="default_filament_colour" changed=${changed.has("color_hex")} error=${errors.color_hex}>
        <div class="colorrow"><input type="color" aria-label="Farbe wählen" value=${color || "#888888"} onInput=${(e) => setV({ ...v, color_hex: e.target.value.toUpperCase() })} />
        <input id="fil-color" value=${v.color_hex} placeholder="#RRGGBB" onInput=${(e) => setV({ ...v, color_hex: e.target.value })} /></div>
      </${Field}>
      ${BASE.slice(0, 3).map((k) => spec(k, cat)).filter(Boolean).map(input)}
    </div>
    ${specs.map(([title, list]) => list.length > 0 && html`<p class="section-title">${title}</p><div class="fgrid">${list.map(input)}</div>`)}
    ${spec("comment", cat) && html`<div class="fgrid">${input(spec("comment", cat))}</div>`}
  </div>
  ${(changed.size > 0 || isNew) && html`
  <div class=${embedded ? "col" : "dfoot"} style=${embedded ? "gap:10px" : ""}>
    ${!isNew && html`<div class="note" style="width:100%">Geändert: ${[...changed].map((k) => (all.find((s) => s.key === k)?.label) || { name: "Name", material: "Material", color_hex: "Farbe", vendor: "Hersteller" }[k] || k).join(", ")}. Nach dem Speichern in Orca „Profile aktualisieren“, dann Orcas Sync-Knopf.</div>`}
    <div class="row wrap">
      <button class="btn acc" disabled=${!valid || busy} onClick=${save}>${isNew ? "Filament anlegen" : "Speichern"}</button>
      ${!isNew && html`<button class="btn ghost" onClick=${() => { setV(initial(fil)); setNewVendor(""); }}>Verwerfen</button>`}
      ${!valid && html`<span class="small" style="color:var(--danger-text)">${Object.values(errors)[0]}</span>`}
    </div>
  </div>`}`;
}

// ------------------------------------------------------------ Liste
export function FilamentList() {
  const cat = S.catalog;
  const [q, setQ] = useState("");
  if (!cat) return html`<section class="card listcard"><div class="empty-state">lade …</div></section>`;
  const list = cat.filaments.filter((f) => !q || `${f.display_name} ${f.material} ${f.orca_id}`.toLowerCase().includes(q.toLowerCase()));
  return html`
  <section class="card listcard" aria-label="Filamente">
    <div class="listbar">
      <span class="h2">Filamente</span><span class="m small muted">${cat.filaments.length}</span>
      <span class="grow"></span>
      <label class="search" style="min-height:38px"><${Icon} name="search" small /><input aria-label="Filamente suchen" value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="suchen" /></label>
      <button class="btn sm acc" onClick=${guard(() => set({ selFil: "neu" }))}><${Icon} name="plus" small />Neu</button>
    </div>
    <div class="table" role="listbox" aria-label="Filamente">
      <div class="tr th fil"><span></span><span>Filament</span><span>Material</span><span class="hide-s">Orca</span><span class="hide-s">Spulen</span></div>
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
