// Print view: model (image of the print file rendered by the bridge) and camera (restream of the bridge: one
// connection to the printer for all viewers, paired only). Images only run while they are visible.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get } from "./api.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { S, openDialog, set } from "./store.js";
import { cls } from "./util.js";
import { Model3D } from "./model3d.js";
import { effectiveQuality } from "./viewer3d.js";

const TAB_KEY = "kobra.mediaTab";
function savedTab() { try { return localStorage.getItem(TAB_KEY) || "camera"; } catch { return "camera"; } }

/** Visible and window in the foreground? Then the requests run. */
function useVisible(ref) {
  const [vis, setVis] = useState(true);
  useEffect(() => {
    if (!ref.current || !window.IntersectionObserver) return;
    const io = new IntersectionObserver(([e]) => setVis(e.isIntersecting));
    io.observe(ref.current);
    return () => io.disconnect();
  }, []);
  return vis;
}

/** Camera key (paired only): an <img> cannot send an Authorization header. */
let camKey = null;
export async function cameraKey(force = false) {
  if (!camKey || force) camKey = (await get("/api/camera/link")).key;
  return camKey;
}
export const cameraUrl = (key, what = "stream.mjpg") => new URL(`api/camera/${what}?key=${encodeURIComponent(key)}`, location.href).href;

/** Page in the foreground? In the background the stream is dropped so the bridge can close it. */
function usePageVisible() {
  const [vis, setVis] = useState(!document.hidden);
  useEffect(() => {
    const on = () => setVis(!document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return vis;
}

/** Live image via the bridge restream (MJPEG in the <img>). Returns [src, error, onError, fps]. */
export function useCamera(active) {
  const page = usePageVisible();
  const on = active && page;
  const [key, setKey] = useState(camKey);
  const [err, setErr] = useState(null);
  const [retry, setRetry] = useState(0);
  const [fps, setFps] = useState(null);
  useEffect(() => {
    if (!on) return;
    cameraKey(retry > 0).then((k) => { setKey(k); setErr(null); }).catch((e) => setErr(e.message));
  }, [on, retry]);
  useEffect(() => {          // frame rate in the corner: how fast the printer delivers (measured in the bridge)
    if (!on) return;
    let stop = false, timer = null;
    const tick = async () => {
      try { const c = await get("/api/camera"); if (!stop) { setFps(c.fps == null ? null : { fps: c.fps, throttled: !!c.throttled }); if (c.error && !c.fps) setErr(c.error); } } catch { /* ignore */ }
      if (!stop) timer = setTimeout(tick, 2000);
    };
    timer = setTimeout(tick, 1500);
    return () => { stop = true; clearTimeout(timer); setFps(null); };
  }, [on]);
  const onError = () => { setErr(t("Camera not reachable – trying again …")); setTimeout(() => setRetry((r) => r + 1), 5000); };
  const src = on && key ? cameraUrl(key) + `&v=${retry}` : null;
  return [src, err, onError, fps];
}

/** Small frame rate at the top right of the camera image. */
export function Fps({ fps }) {
  if (fps == null) return null;
  const v = fps.fps;
  // Rinkhals: the bridge holds the rate back while the printer's CPU is busy printing
  return html`<span class="media-fps m" title=${fps.throttled ? t("The printer's CPU is busy – the bridge fetches fewer images") : ""}>${v < 10 ? v.toFixed(1) : Math.round(v)} fps${fps.throttled ? " · " + t("throttled") : ""}</span>`;
}

/** AI detections as boxes over the camera image. The SVG has the aspect ratio of the analysed image and "meet"
 *  like object-fit: contain - so the boxes sit exactly on the image without measuring. */
export function AiBoxes() {
  const v = S.st?.vision;
  const [w, h] = v?.size || [];
  if (!v?.detections?.length || !w || !h) return null;
  const color = v.level === "fail" ? "var(--danger)" : "var(--accent)";
  return html`<svg class="ai-boxes" viewBox=${`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
    ${v.detections.filter((d) => d[1] >= 0.2).map(([, c, [xc, yc, bw, bh]]) => html`<g>
      <rect x=${(xc - bw / 2) * w} y=${(yc - bh / 2) * h} width=${bw * w} height=${bh * h} fill="none" stroke=${color}
        stroke-width=${Math.max(2, w / 400)} vector-effect="non-scaling-stroke" />
      <text x=${(xc - bw / 2) * w + 4} y=${(yc - bh / 2) * h + Math.max(14, h / 40)} fill=${color}
        font-size=${Math.max(12, h / 45)}>${Math.round(c * 100)} %</text></g>`)}
  </svg>`;
}

const temp = (h) => (h.target > 0 ? `${Math.round(h.temp)}/${Math.round(h.target)}°` : `${Math.round(h.temp)}°`);
const share = (v) => (v > 0 ? `${Math.round(v * 100)} %` : t("off"));

/** Printer data below the image: temperatures, fans, speed, flow, layer (only what the printer reports). */
export function MachineBar({ p }) {
  if (!p || (!p.nozzle && !p.bed && !(p.fans || []).length)) return null;
  const items = [];
  if (p.nozzle) items.push([t("Nozzle"), temp(p.nozzle), p.nozzle.target > 0]);
  if (p.bed) items.push([t("Bed"), temp(p.bed), p.bed.target > 0]);
  for (const f of p.fans || []) items.push([f.name, share(f.speed)]);
  if (p.speed_factor != null) items.push([t("Speed"), `${Math.round(p.speed_factor * 100)} %`, p.speed_factor !== 1]);
  if (p.flow_factor != null) items.push([t("Flow"), `${Math.round(p.flow_factor * 100)} %`, p.flow_factor !== 1]);
  if (p.layer != null && p.layers) items.push([t("Layer"), `${p.layer} / ${p.layers}`]);
  return html`<div class="machine">${items.map(([l, v, hot]) => html`<div><span>${l}</span><b class=${cls("m", hot && "hot")}>${v}</b></div>`)}</div>`;
}

/** Rendered model image; reload while the print moves (every 10 s). */
function useModel(active) {
  const [info, setInfo] = useState(null);
  const [stamp, setStamp] = useState(0);
  useEffect(() => {
    if (!active) return;
    let stop = false, timer = null;
    const tick = async () => {
      try { const i = await get("/api/print/info"); if (!stop) { setInfo(i); setStamp(Date.now()); } } catch { /* bridge gone */ }
      // 3D shows the progress live (just a number), the bridge renders its image at most every 15 s
      if (!stop) timer = setTimeout(tick, effectiveQuality() === "image" ? 10000 : 3000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [active]);
  return [info, stamp];
}

export function PrintMedia({ tall }) {
  const ref = useRef(null);
  const visible = useVisible(ref);
  const [chosen, setTab] = useState(savedTab());
  const choose = (v) => { setTab(v); try { localStorage.setItem(TAB_KEY, v); } catch { /* ignore */ } };
  // the camera is the main view; the model exists only while printing
  const running = ["printing", "paused"].includes(S.st?.printer?.state);
  const tab = running ? chosen : "camera";
  const [info, stamp] = useModel(visible && tab === "model");
  const [cam, camErr, camFail, fps] = useCamera(visible && tab === "camera" && !!S.me && S.dialog?.kind !== "camera");
  const hasModel = info && (info.status === "ready" || info.thumbnail);
  const src = info?.status === "ready" ? `api/print/preview.png?t=${stamp}` : info?.thumbnail ? `api/print/thumbnail.png?t=${stamp}` : null;

  let body;
  if (tab === "camera") {
    if (!S.me) body = html`<div class="media-empty">${t("Only paired devices see the camera.")} <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>${t("Pair")}</a></div>`;
    else if (cam) body = html`<img src=${cam} alt=${t("Camera")} onError=${camFail} onClick=${() => openDialog("camera")} /><${AiBoxes} /><${Fps} fps=${fps} />`;
    else body = html`<div class="media-empty">${camErr || t("Camera loading …")}</div>`;
  } else if (src) {
    const img = html`<img src=${src} alt=${t("Preview of the print file")} onClick=${() => openDialog("camera", { view: "model", src })} />`;
    body = info?.geometry && effectiveQuality() !== "image" ? html`<${Model3D} info=${info} fallback=${img} />` : img;
  } else {
    const msg = { loading: t("Loading the print file …"), too_big: t("File too big for the preview"), error: t("Preview not possible"), off: t("Preview is switched off") };
    body = html`<div class="media-empty">${info ? msg[info.status] || t("No print – no preview") : t("loading …")}</div>`;
  }
  return html`
  <div class=${cls("media", tall && "tall")} ref=${ref}>
    <div class="media-tabs" role="tablist">
      <button role="tab" aria-selected=${tab === "camera"} onClick=${() => choose("camera")}><${Icon} name="overview" small />${t("Camera")}</button>
      ${running && html`<button role="tab" aria-selected=${tab === "model"} onClick=${() => choose("model")}><${Icon} name="spool" small />${t("Model")}</button>`}
      ${tab === "model" && S.st?.printer?.layer == null && info?.layer && info?.layers ? html`<span class="media-meta m">${t("Layer {layer} / {layers}", { layer: info.layer, layers: info.layers })}</span>` : null}
    </div>
    <div class="media-body">${body}</div>
    <${MachineBar} p=${S.st?.printer} />
  </div>`;
}

/** Full screen: live camera (restream) or the model image large. */
export function CameraDialog({ view, src }) {
  const [cam, camErr, camFail, fps] = useCamera(view !== "model" && !!S.me);
  const close = () => set({ dialog: null });
  return html`<div class="scrim viewer" onClick=${close}>
    <button class="btn icon ghost viewer-close" aria-label=${t("Close")} onClick=${close}><${Icon} name="close" /></button>
    ${view === "model" ? html`<img src=${src} alt=${t("Preview of the print file")} />`
      : cam ? html`<div class="viewer-cam"><img src=${cam} alt=${t("Camera")} onError=${camFail} /><${Fps} fps=${fps} />
          <div class="viewer-machine"><${MachineBar} p=${S.st?.printer} /></div></div>`
        : html`<div class="media-empty">${camErr || t("Camera loading …")}</div>`}
  </div>`;
}
