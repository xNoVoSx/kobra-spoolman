// Karte "ACE": Einstellungen, die das Druckerdisplay versteckt - Spuel-Multiplikator mit Vorschau fuer die
// eingelegten Farben, automatisches Nachladen, Leer-Erkennung. Waehrend eines Drucks erst nach "Freischalten".

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { Swatch } from "./components.js";
import { Icon } from "./icons.js";
import { S, guard, loadState, toast } from "./store.js";
import { cls, fixed, num, parseNum, when } from "./util.js";

function usePurgePreview(multiplier) {
  const [data, setData] = useState(null);
  const timer = useRef(null);
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const q = multiplier != null && !Number.isNaN(multiplier) ? `?multiplier=${multiplier}` : "";
      get("/api/ace" + q).then((r) => setData(r.purge)).catch(() => {});
    }, 250);
    return () => clearTimeout(timer.current);
  }, [multiplier, S.st?.slots?.map((s) => s.ace?.color).join()]);
  return data;
}

export function Toggle({ label, hint, value, disabled, onChange }) {
  return html`<label class=${cls("toggle", disabled && "off")}>
    <span class="grow"><span>${label}</span>${hint && html`<span class="small muted" style="display:block">${hint}</span>`}</span>
    <input type="checkbox" role="switch" checked=${!!value} disabled=${disabled} onChange=${(e) => onChange(e.target.checked)} />
    <span class="knob" aria-hidden="true"></span>
  </label>`;
}

function PurgeSummary({ pairs }) {
  const sorted = [...pairs].sort((a, b) => a.mm - b.mm);
  const lo = sorted[0], hi = sorted[sorted.length - 1];
  const line = (p, label) => html`<div class="row small" style="gap:8px"><span class="muted" style="min-width:74px">${label}</span>
    <${Swatch} color=${p.from_color} size=${12} /><span class="muted">→</span><${Swatch} color=${p.to_color} size=${12} />
    <span class="ell grow">Slot ${p.from_slot} → ${p.to_slot}</span><span class="m">${num(p.mm, 0)} mm · ${fixed(p.g, 1)} g</span></div>`;
  return html`<div class="col" style="gap:4px">${line(hi, "teuerster")}${lo !== hi ? line(lo, "günstigster") : null}</div>`;
}

export function AceCard({ compact }) {
  const a = S.st?.ace;
  const printing = !!a?.printing;
  const [unlocked, setUnlocked] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const current = a?.flush_multiplier;
  useEffect(() => { if (!printing) setUnlocked(false); }, [printing]);
  useEffect(() => { if (current != null && !busy) setText(fixed(current, 1)); }, [current]);
  const wanted = parseNum(text);
  const valid = wanted != null && !Number.isNaN(wanted) && wanted >= 0.1 && wanted <= 3;
  const changed = valid && current != null && Math.abs(wanted - current) > 0.001;
  const preview = usePurgePreview(!compact && valid ? wanted : null);
  const nowPreview = usePurgePreview(null);
  const locked = printing && !unlocked;

  if (!a) return null;
  if (!a.present) {
    return html`<section class="card pad col" aria-label="ACE"><div class="row"><h2 class="h2 grow">ACE</h2><span class="chip">keine Daten</span></div>
      <div class="small muted">Die Bridge konnte die ACE-Einstellungen noch nicht vom Drucker lesen.</div></section>`;
  }

  const send = guard(async (path, body) => {
    setBusy(true);
    try {
      await post(path, { ...body, confirm_printing: printing && unlocked });
      toast("Am Drucker gespeichert", "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const setFlush = (v) => send("/api/ace/flush", { multiplier: v });
  const setOption = (k, v) => send("/api/ace/options", { [k]: v });
  const nowBy = Object.fromEntries((nowPreview?.pairs || []).map((p) => [`${p.from_slot}-${p.to_slot}`, p]));

  return html`
  <section class="card pad col" aria-label="ACE-Einstellungen">
    <div class="row"><span style="color:var(--accent)"><${Icon} name="sliders" /></span><h2 class="h2 grow">ACE</h2>
      <span class="small faint">vom Drucker ${a.read_at ? when(a.read_at) : "–"}</span></div>

    <div class="row wrap" style="gap:12px;align-items:flex-end">
      <div><div class="small muted">Spülen (Multiplikator)</div><div class="m" style="font-size:32px;font-weight:600;line-height:1.1">× ${fixed(current, 1)}</div></div>
      <span class="grow"></span>
      ${printing && !unlocked && html`<button class="btn sm" onClick=${guard(() => setUnlocked(true))}><${Icon} name="key" small />Freischalten</button>`}
    </div>
    ${printing && unlocked && html`<div class="note">Druck läuft: Der neue Wert gilt ab dem nächsten Farbwechsel. Weniger Spülen spart Filament, kann aber Farben vermischen.</div>`}
    <div class="row wrap" style="gap:8px">
      ${Object.entries(a.presets || {}).map(([k, v]) => html`
        <button class=${cls("chip", Math.abs((current ?? -1) - v) < 0.001 && "on")} disabled=${locked || busy}
                onClick=${() => setFlush(v)}>${{ minimal: "Minimal", normal: "Normal", maximum: "Maximum" }[k] || k} ${fixed(v, 1)}</button>`)}
    </div>
    <div class="row" style="gap:8px">
      <input class="inp" style="max-width:120px" inputmode="decimal" aria-label="Multiplikator" value=${text} disabled=${locked}
             aria-invalid=${!valid && !!text} onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && changed && setFlush(wanted)} />
      <button class="btn sm acc" disabled=${!changed || locked || busy} onClick=${() => setFlush(wanted)}>Übernehmen</button>
      ${!valid && text && html`<span class="small" style="color:var(--danger-text)">erlaubt 0,1 bis 3,0</span>`}
    </div>
    ${!compact && html`
    ${preview && preview.pairs.length > 0 && html`
      <div class="col" style="gap:6px">
        <${PurgeSummary} pairs=${preview.pairs} />
        <details class="small"><summary class="muted" style="cursor:pointer">Alle ${preview.pairs.length} Farbwechsel${changed ? " (jetzt → neu)" : ""}</summary>
        <div class="col" style="gap:6px;margin-top:8px">
        ${preview.pairs.map((p) => {
          const before = nowBy[`${p.from_slot}-${p.to_slot}`];
          return html`<div class="row small" style="gap:8px">
            <${Swatch} color=${p.from_color} size=${12} /><span class="muted">→</span><${Swatch} color=${p.to_color} size=${12} />
            <span class="ell grow">Slot ${p.from_slot} → ${p.to_slot}<span class="muted"> · ${p.to_name}</span></span>
            ${changed && before ? html`<span class="m muted">${num(before.mm, 0)} →</span>` : null}
            <span class="m" style="min-width:110px;text-align:right">${num(p.mm, 0)} mm · ${fixed(p.g, 1)} g</span>
          </div>`;
        })}
        </div></details>
        <div class="small faint">Erster Ladevorgang eines Drucks ≈ ${num(preview.first_load_mm, 0)} mm. Gerechnet wie die Firmware (Farbformel × Multiplikator).</div>
      </div>`}
    <hr class="sep" />
    <${Toggle} label="Automatisch nachladen" hint="Ist eine Spule leer, lädt die ACE eine passende Ersatzspule"
               value=${a.auto_refill} disabled=${locked || busy || a.auto_refill == null} onChange=${(v) => setOption("auto_refill", v)} />
    <${Toggle} label="Leer-Erkennung" hint="Die ACE erkennt, wenn eine Spule zu Ende ist"
               value=${a.runout_detect} disabled=${locked || busy || a.runout_detect == null} onChange=${(v) => setOption("runout_detect", v)} />`}
    ${compact && html`<a href="#/ace" class="small">Vorschau und weitere Einstellungen →</a>`}
  </section>`;
}
