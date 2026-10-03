// Eigene Seite nur mit der 3D-Ansicht (/viewer) - fuer die App (WebView) und zum Teilen im Heimnetz.
// Liest nur /api/print/info und /api/print/geometry.bin (ohne Schluessel lesbar, wie das Vorschaubild).
// ?q=volume|lines|image|auto legt die Darstellung fest (die App reicht ihre Einstellung durch).

import { html, render, useEffect, useState } from "../vendor/preact-htm.module.js";
import { Model3D } from "./model3d.js";

const msg = { loading: "Druckdatei wird geladen …", too_big: "Datei zu groß für die 3D-Ansicht", error: "Druckdatei nicht lesbar", off: "Vorschau ist abgeschaltet" };

function Viewer() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let stop = false, timer = null;
    const tick = async () => {
      try { const r = await fetch("api/print/info", { cache: "no-store" }); if (r.ok && !stop) setInfo(await r.json()); } catch { /* Bridge weg */ }
      if (!stop) timer = setTimeout(tick, document.hidden ? 15000 : 3000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, []);
  const img = html`<div class="viewer-empty">${info?.thumbnail ? html`<img src=${"api/print/thumbnail.png?t=" + (info?.done || 0)} alt="Vorschaubild" style="max-width:100%;max-height:100%" />` : "Keine 3D-Ansicht"}</div>`;
  return html`<div class="viewer-page">
    ${info?.geometry ? html`<${Model3D} info=${info} fallback=${img} />`
      : html`<div class="viewer-empty">${info ? msg[info.status] || "Kein Druck – kein Modell" : "lädt …"}</div>`}
  </div>`;
}

render(html`<${Viewer} />`, document.getElementById("app"));
