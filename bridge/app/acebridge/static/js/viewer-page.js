// Separate page with only the 3D view (/viewer) - for the app (WebView) and for sharing in the home network.
// Reads only /api/print/info and /api/print/geometry.bin (readable without a key, like the preview image).
// ?q=volume|lines|image|auto sets the rendering (the app passes its setting through), ?lang=de|en the language.

import { html, render, useEffect, useState } from "../vendor/preact-htm.module.js";
import { t } from "./i18n.js";
import { Model3D } from "./model3d.js";

const msg = { loading: t("Loading the print file …"), too_big: t("File too big for the 3D view"), error: t("Print file not readable"), off: t("Preview is switched off") };

function Viewer() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let stop = false, timer = null;
    const tick = async () => {
      try { const r = await fetch("api/print/info", { cache: "no-store" }); if (r.ok && !stop) setInfo(await r.json()); } catch { /* bridge gone */ }
      if (!stop) timer = setTimeout(tick, document.hidden ? 15000 : 3000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, []);
  const img = html`<div class="viewer-empty">${info?.thumbnail ? html`<img src=${"api/print/thumbnail.png?t=" + (info?.done || 0)} alt=${t("Preview image")} style="max-width:100%;max-height:100%" />` : t("No 3D view")}</div>`;
  return html`<div class="viewer-page">
    ${info?.geometry ? html`<${Model3D} info=${info} fallback=${img} />`
      : html`<div class="viewer-empty">${info ? msg[info.status] || t("No print – no model") : t("loading …")}</div>`}
  </div>`;
}

render(html`<${Viewer} />`, document.getElementById("app"));
