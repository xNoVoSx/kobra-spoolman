// Druckansicht: Modell (von der Bridge gerechnetes Bild der Druckdatei) und Kamera (Restream der Bridge: eine
// Verbindung zum Drucker fuer alle Zuschauer, nur gekoppelt). Bilder laufen nur, solange sie sichtbar sind.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get } from "./api.js";
import { Icon } from "./icons.js";
import { S, openDialog, set } from "./store.js";
import { cls } from "./util.js";
import { Model3D } from "./model3d.js";
import { effectiveQuality } from "./viewer3d.js";

const TAB_KEY = "kobra.mediaTab";
function savedTab() { try { return localStorage.getItem(TAB_KEY) || "camera"; } catch { return "camera"; } }

/** Sichtbar und Fenster im Vordergrund? Dann laufen die Abfragen. */
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

/** Kamera-Schluessel (nur gekoppelt): ein <img> kann keinen Authorization-Header schicken. */
let camKey = null;
export async function cameraKey(force = false) {
  if (!camKey || force) camKey = (await get("/api/camera/link")).key;
  return camKey;
}
export const cameraUrl = (key, what = "stream.mjpg") => new URL(`api/camera/${what}?key=${encodeURIComponent(key)}`, location.href).href;

/** Seite im Vordergrund? Im Hintergrund wird der Stream getrennt, damit die Bridge ihn schliessen kann. */
function usePageVisible() {
  const [vis, setVis] = useState(!document.hidden);
  useEffect(() => {
    const on = () => setVis(!document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return vis;
}

/** Live-Bild ueber den Restream der Bridge (MJPEG im <img>). Liefert [src, Fehler, onError, fps]. */
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
  useEffect(() => {          // Bildrate in der Ecke: so schnell liefert der Drucker (gemessen in der Bridge)
    if (!on) return;
    let stop = false, timer = null;
    const tick = async () => {
      try { const c = await get("/api/camera"); if (!stop) { setFps(c.fps == null ? null : { fps: c.fps }); if (c.error && !c.fps) setErr(c.error); } } catch { /* egal */ }
      if (!stop) timer = setTimeout(tick, 2000);
    };
    timer = setTimeout(tick, 1500);
    return () => { stop = true; clearTimeout(timer); setFps(null); };
  }, [on]);
  const onError = () => { setErr("Kamera nicht erreichbar – neuer Versuch …"); setTimeout(() => setRetry((r) => r + 1), 5000); };
  const src = on && key ? cameraUrl(key) + `&v=${retry}` : null;
  return [src, err, onError, fps];
}

/** Kleine Bildrate oben rechts im Kamerabild. */
export function Fps({ fps }) {
  if (fps == null) return null;
  const v = fps.fps;
  return html`<span class="media-fps m">${v < 10 ? v.toFixed(1) : Math.round(v)} fps</span>`;
}

/** Fundstellen der KI als Rahmen ueber dem Kamerabild. Das SVG hat das Seitenverhaeltnis des ausgewerteten
 *  Bildes und "meet" wie object-fit: contain - die Rahmen sitzen so ohne Messen genau auf dem Bild. */
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
const share = (v) => (v > 0 ? `${Math.round(v * 100)} %` : "aus");

/** Druckerdaten unter dem Bild: Temperaturen, Luefter, Tempo, Fluss, Schicht (nur was der Drucker meldet). */
export function MachineBar({ p }) {
  if (!p || (!p.nozzle && !p.bed && !(p.fans || []).length)) return null;
  const items = [];
  if (p.nozzle) items.push(["Düse", temp(p.nozzle), p.nozzle.target > 0]);
  if (p.bed) items.push(["Bett", temp(p.bed), p.bed.target > 0]);
  for (const f of p.fans || []) items.push([f.name, share(f.speed)]);
  if (p.speed_factor != null) items.push(["Tempo", `${Math.round(p.speed_factor * 100)} %`, p.speed_factor !== 1]);
  if (p.flow_factor != null) items.push(["Fluss", `${Math.round(p.flow_factor * 100)} %`, p.flow_factor !== 1]);
  if (p.layer != null && p.layers) items.push(["Schicht", `${p.layer} / ${p.layers}`]);
  return html`<div class="machine">${items.map(([l, v, hot]) => html`<div><span>${l}</span><b class=${cls("m", hot && "hot")}>${v}</b></div>`)}</div>`;
}

/** Gerechnetes Modellbild; neu laden, wenn sich der Druck bewegt (alle 10 s). */
function useModel(active) {
  const [info, setInfo] = useState(null);
  const [stamp, setStamp] = useState(0);
  useEffect(() => {
    if (!active) return;
    let stop = false, timer = null;
    const tick = async () => {
      try { const i = await get("/api/print/info"); if (!stop) { setInfo(i); setStamp(Date.now()); } } catch { /* Bridge weg */ }
      // 3D zeigt den Fortschritt live (nur eine Zahl), das Bild der Bridge wird hoechstens alle 15 s neu gerechnet
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
  const choose = (t) => { setTab(t); try { localStorage.setItem(TAB_KEY, t); } catch { /* egal */ } };
  // Kamera ist die Hauptansicht; das Modell gibt es nur, solange gedruckt wird
  const running = ["printing", "paused"].includes(S.st?.printer?.state);
  const tab = running ? chosen : "camera";
  const [info, stamp] = useModel(visible && tab === "model");
  const [cam, camErr, camFail, fps] = useCamera(visible && tab === "camera" && !!S.me && S.dialog?.kind !== "camera");
  const hasModel = info && (info.status === "ready" || info.thumbnail);
  const src = info?.status === "ready" ? `api/print/preview.png?t=${stamp}` : info?.thumbnail ? `api/print/thumbnail.png?t=${stamp}` : null;

  let body;
  if (tab === "camera") {
    if (!S.me) body = html`<div class="media-empty">Die Kamera sehen nur gekoppelte Geräte. <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>Koppeln</a></div>`;
    else if (cam) body = html`<img src=${cam} alt="Kamera" onError=${camFail} onClick=${() => openDialog("camera")} /><${AiBoxes} /><${Fps} fps=${fps} />`;
    else body = html`<div class="media-empty">${camErr || "Kamera lädt …"}</div>`;
  } else if (src) {
    const img = html`<img src=${src} alt="Vorschau der Druckdatei" onClick=${() => openDialog("camera", { view: "model", src })} />`;
    body = info?.geometry && effectiveQuality() !== "image" ? html`<${Model3D} info=${info} fallback=${img} />` : img;
  } else {
    const msg = { loading: "Druckdatei wird geladen …", too_big: "Datei zu groß für die Vorschau", error: "Vorschau nicht möglich", off: "Vorschau ist abgeschaltet" };
    body = html`<div class="media-empty">${info ? msg[info.status] || "Kein Druck – keine Vorschau" : "lädt …"}</div>`;
  }
  return html`
  <div class=${cls("media", tall && "tall")} ref=${ref}>
    <div class="media-tabs" role="tablist">
      <button role="tab" aria-selected=${tab === "camera"} onClick=${() => choose("camera")}><${Icon} name="overview" small />Kamera</button>
      ${running && html`<button role="tab" aria-selected=${tab === "model"} onClick=${() => choose("model")}><${Icon} name="spool" small />Modell</button>`}
      ${tab === "model" && S.st?.printer?.layer == null && info?.layer && info?.layers ? html`<span class="media-meta m">Schicht ${info.layer} / ${info.layers}</span>` : null}
    </div>
    <div class="media-body">${body}</div>
    <${MachineBar} p=${S.st?.printer} />
  </div>`;
}

/** Vollbild: Kamera live (Restream) oder das Modellbild gross. */
export function CameraDialog({ view, src }) {
  const [cam, camErr, camFail, fps] = useCamera(view !== "model" && !!S.me);
  const close = () => set({ dialog: null });
  return html`<div class="scrim viewer" onClick=${close}>
    <button class="btn icon ghost viewer-close" aria-label="Schließen" onClick=${close}><${Icon} name="close" /></button>
    ${view === "model" ? html`<img src=${src} alt="Vorschau der Druckdatei" />`
      : cam ? html`<div class="viewer-cam"><img src=${cam} alt="Kamera" onError=${camFail} /><${Fps} fps=${fps} />
          <div class="viewer-machine"><${MachineBar} p=${S.st?.printer} /></div></div>`
        : html`<div class="media-empty">${camErr || "Kamera lädt …"}</div>`}
  </div>`;
}
