// Druckansicht: Modell (von der Bridge gerechnetes Bild der Druckdatei) und Kamera (Restream der Bridge: eine
// Verbindung zum Drucker fuer alle Zuschauer, nur gekoppelt). Bilder laufen nur, solange sie sichtbar sind.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, get } from "./api.js";
import { Icon } from "./icons.js";
import { S, openDialog, set } from "./store.js";
import { cls } from "./util.js";

const TAB_KEY = "kobra.mediaTab";
function savedTab() { try { return localStorage.getItem(TAB_KEY) || "model"; } catch { return "model"; } }

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
      try { const c = await get("/api/camera"); if (!stop) { setFps(c.fps); if (c.error && !c.fps) setErr(c.error); } } catch { /* egal */ }
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
  return fps == null ? null : html`<span class="media-fps m">${fps < 10 ? fps.toFixed(1) : Math.round(fps)} fps</span>`;
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
      if (!stop) timer = setTimeout(tick, 10000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [active]);
  return [info, stamp];
}

export function PrintMedia({ tall }) {
  const ref = useRef(null);
  const visible = useVisible(ref);
  const [tab, setTab] = useState(savedTab());
  const choose = (t) => { setTab(t); try { localStorage.setItem(TAB_KEY, t); } catch { /* egal */ } };
  const [info, stamp] = useModel(visible && tab === "model");
  const [cam, camErr, camFail, fps] = useCamera(visible && tab === "camera" && !!S.me && S.dialog?.kind !== "camera");
  const hasModel = info && (info.status === "ready" || info.thumbnail);
  const src = info?.status === "ready" ? `api/print/preview.png?t=${stamp}` : info?.thumbnail ? `api/print/thumbnail.png?t=${stamp}` : null;

  let body;
  if (tab === "camera") {
    if (!S.me) body = html`<div class="media-empty">Die Kamera sehen nur gekoppelte Geräte. <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>Koppeln</a></div>`;
    else if (cam) body = html`<img src=${cam} alt="Kamera" onError=${camFail} onClick=${() => openDialog("camera")} /><${Fps} fps=${fps} />`;
    else body = html`<div class="media-empty">${camErr || "Kamera lädt …"}</div>`;
  } else if (src) {
    body = html`<img src=${src} alt="Vorschau der Druckdatei" onClick=${() => openDialog("camera", { view: "model", src })} />`;
  } else {
    const msg = { loading: "Druckdatei wird geladen …", too_big: "Datei zu groß für die Vorschau", error: "Vorschau nicht möglich", off: "Vorschau ist abgeschaltet" };
    body = html`<div class="media-empty">${info ? msg[info.status] || "Kein Druck – keine Vorschau" : "lädt …"}</div>`;
  }
  return html`
  <div class=${cls("media", tall && "tall")} ref=${ref}>
    <div class="media-tabs" role="tablist">
      <button role="tab" aria-selected=${tab === "model"} onClick=${() => choose("model")}><${Icon} name="spool" small />Modell</button>
      <button role="tab" aria-selected=${tab === "camera"} onClick=${() => choose("camera")}><${Icon} name="overview" small />Kamera</button>
      ${tab === "model" && info?.layer && info?.layers ? html`<span class="media-meta m">Schicht ${info.layer} / ${info.layers}</span>` : null}
    </div>
    <div class="media-body">${body}</div>
  </div>`;
}

/** Vollbild: Kamera live (Restream) oder das Modellbild gross. */
export function CameraDialog({ view, src }) {
  const [cam, camErr, camFail, fps] = useCamera(view !== "model" && !!S.me);
  const close = () => set({ dialog: null });
  return html`<div class="scrim viewer" onClick=${close}>
    <button class="btn icon ghost viewer-close" aria-label="Schließen" onClick=${close}><${Icon} name="close" /></button>
    ${view === "model" ? html`<img src=${src} alt="Vorschau der Druckdatei" />`
      : cam ? html`<div class="viewer-cam"><img src=${cam} alt="Kamera" onError=${camFail} /><${Fps} fps=${fps} /></div>`
        : html`<div class="media-empty">${camErr || "Kamera lädt …"}</div>`}
  </div>`;
}
