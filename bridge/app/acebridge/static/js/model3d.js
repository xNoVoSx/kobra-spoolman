// Model view: 3D (viewer3d.js) with layer slider and views - or the bridge image, depending on the device or the
// setting (Settings -> This device). The paths are loaded once per print.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { t } from "./i18n.js";
import { cls } from "./util.js";
import { PrintView, effectiveQuality, parseGeometry } from "./viewer3d.js";

const REST_KEY = "kobra.render3d.rest";
const RESTS = [["glass", t("See-through")], ["full", t("Solid")], ["off", t("Hidden")]];
const loadRest = () => { try { const v = localStorage.getItem(REST_KEY); return RESTS.some(([k]) => k === v) ? v : "glass"; } catch { return "glass"; } };

export function Model3D({ info, fallback }) {
  const canvas = useRef(null);
  const view = useRef(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [layer, setLayer] = useState(null);          // null = everything (live)
  const [single, setSingle] = useState(false);
  const [rest, setRestState] = useState(loadRest);          // remembered per device
  const setRest = (v) => { setRestState(v); try { localStorage.setItem(REST_KEY, v); } catch { /* ignore */ } };
  const [geoKey, setGeoKey] = useState(null);
  const mode = effectiveQuality();
  const total = info?.layers || 0;

  useEffect(() => {
    if (mode === "image" || !canvas.current) return;
    try { view.current = new PrintView(canvas.current, () => setErr(t("Graphics lost – reload the page"))); }
    catch (e) { setErr(e.message); }
    return () => { view.current?.dispose(); view.current = null; };
  }, [mode]);

  // load the paths when the print file changes
  useEffect(() => {
    const key = info?.geometry;
    if (!key || key === geoKey || !view.current) return;
    let stop = false;
    setLoading(true);
    fetch("api/print/geometry.bin", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(t("Paths could not be loaded ({status})", { status: r.status })); return r.arrayBuffer(); })
      .then((buf) => { if (stop) return; const g = parseGeometry(buf); view.current.load(g); view.current.step = g.step; setGeoKey(key); setErr(null); })
      .catch((e) => { if (!stop) setErr(e.message); })
      .finally(() => { if (!stop) setLoading(false); });
    return () => { stop = true; };
  }, [info?.geometry, !!view.current]);

  // progress, colours, layer
  useEffect(() => {
    const v = view.current; if (!v || !v.geo) return;
    v.set({ mode, done: Math.floor((info?.done || 0) / (v.step || 1)), maxLayer: layer == null ? total - 1 : layer - 1, single: single && layer != null, rest });
    v.setColors(info?.filament_colours?.length ? info.filament_colours : info?.colours);     // original colours as in Orca
  }, [info?.done, info?.filament_colours?.join(), info?.colours?.join(), layer, single, rest, mode, geoKey, total]);

  if (mode === "image" || err) return html`${fallback}${err && html`<span class="media-meta m">3D: ${err}</span>`}`;
  const cur = info?.layer || 0;
  return html`<div class="m3d">
    <canvas ref=${canvas} class="m3d-canvas" aria-label=${t("3D view of the print file")}></canvas>
    ${loading && html`<div class="m3d-loading">${t("Loading paths …")}</div>`}
    <div class="m3d-bar">
      <div class="seg">${[["iso", "3D"], ["top", t("Top")], ["front", t("Front")]].map(([k, l]) => html`<button class="seg-btn" onClick=${() => view.current?.view(k)}>${l}</button>`)}</div>
      <span class="m3d-chk">${t("Rest")}</span>
      <div class="seg" role="group" aria-label=${t("Part not printed yet")}>${RESTS.map(([k, l]) => html`<button class=${cls("seg-btn", rest === k && "on")} aria-pressed=${rest === k} onClick=${() => setRest(k)}>${l}</button>`)}</div>
      <label class="m3d-chk"><input type="checkbox" checked=${single} disabled=${layer == null} onChange=${(e) => setSingle(e.target.checked)} />${t("layer only")}</label>
      <input class="grow" type="range" min="1" max=${Math.max(1, total)} value=${layer ?? total} aria-label=${t("Layer")}
        onInput=${(e) => setLayer(Number(e.target.value) >= total ? null : Number(e.target.value))} />
      <span class="m small">${layer == null ? t("all · now {cur}/{total}", { cur, total }) : `${layer}/${total}`}</span>
      ${layer != null && html`<button class=${cls("btn sm")} onClick=${() => { setLayer(null); setSingle(false); }}>Live</button>`}
    </div>
  </div>`;
}
