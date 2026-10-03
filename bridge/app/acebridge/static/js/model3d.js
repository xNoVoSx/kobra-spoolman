// Modell-Ansicht: 3D (viewer3d.js) mit Schicht-Regler und Ansichten - oder das Bild der Bridge, je nach Geraet
// bzw. Einstellung (Einstellungen -> Dieses Geraet). Die Bahnen werden einmal je Druck geladen.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { PrintView, effectiveQuality, parseGeometry } from "./viewer3d.js";
import { cls } from "./util.js";

export function Model3D({ info, fallback }) {
  const canvas = useRef(null);
  const view = useRef(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  const [layer, setLayer] = useState(null);          // null = alles (live)
  const [single, setSingle] = useState(false);
  const [ghost, setGhost] = useState(true);
  const [geoKey, setGeoKey] = useState(null);
  const mode = effectiveQuality();
  const total = info?.layers || 0;

  useEffect(() => {
    if (mode === "image" || !canvas.current) return;
    try { view.current = new PrintView(canvas.current, () => setErr("Grafik verloren – Seite neu laden")); }
    catch (e) { setErr(e.message); }
    return () => { view.current?.dispose(); view.current = null; };
  }, [mode]);

  // Bahnen laden, wenn sich die Druckdatei aendert
  useEffect(() => {
    const key = info?.geometry;
    if (!key || key === geoKey || !view.current) return;
    let stop = false;
    setLoading(true);
    fetch("api/print/geometry.bin", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(`Bahnen nicht ladbar (${r.status})`); return r.arrayBuffer(); })
      .then((buf) => { if (stop) return; const g = parseGeometry(buf); view.current.load(g); view.current.step = g.step; setGeoKey(key); setErr(null); })
      .catch((e) => { if (!stop) setErr(e.message); })
      .finally(() => { if (!stop) setLoading(false); });
    return () => { stop = true; };
  }, [info?.geometry, !!view.current]);

  // Fortschritt, Farben, Schicht
  useEffect(() => {
    const v = view.current; if (!v || !v.geo) return;
    v.set({ mode, done: Math.floor((info?.done || 0) / (v.step || 1)), maxLayer: layer == null ? total - 1 : layer - 1, single: single && layer != null, ghost });
    v.setColors(info?.filament_colours?.length ? info.filament_colours : info?.colours);     // Originalfarben wie in Orca
  }, [info?.done, info?.filament_colours?.join(), info?.colours?.join(), layer, single, ghost, mode, geoKey, total]);

  if (mode === "image" || err) return html`${fallback}${err && html`<span class="media-meta m">3D: ${err}</span>`}`;
  const cur = info?.layer || 0;
  return html`<div class="m3d">
    <canvas ref=${canvas} class="m3d-canvas" aria-label="3D-Ansicht der Druckdatei"></canvas>
    ${loading && html`<div class="m3d-loading">Bahnen werden geladen …</div>`}
    <div class="m3d-bar">
      <div class="seg">${[["iso", "3D"], ["top", "Oben"], ["front", "Vorne"]].map(([k, l]) => html`<button class="seg-btn" onClick=${() => view.current?.view(k)}>${l}</button>`)}</div>
      <label class="m3d-chk"><input type="checkbox" checked=${ghost} onChange=${(e) => setGhost(e.target.checked)} />Rest</label>
      <label class="m3d-chk"><input type="checkbox" checked=${single} disabled=${layer == null} onChange=${(e) => setSingle(e.target.checked)} />nur Schicht</label>
      <input class="grow" type="range" min="1" max=${Math.max(1, total)} value=${layer ?? total} aria-label="Schicht"
        onInput=${(e) => setLayer(Number(e.target.value) >= total ? null : Number(e.target.value))} />
      <span class="m small">${layer == null ? `alle · jetzt ${cur}/${total}` : `${layer}/${total}`}</span>
      ${layer != null && html`<button class=${cls("btn sm")} onClick=${() => { setLayer(null); setSingle(false); }}>Live</button>`}
    </div>
  </div>`;
}
