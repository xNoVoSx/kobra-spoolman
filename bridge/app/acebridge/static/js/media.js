// Druckansicht: Modell (von der Bridge gerechnetes Bild der Druckdatei) und Kamera (Einzelbilder ueber die
// Bridge, nur gekoppelt). Die Bilder werden nur geholt, solange sie sichtbar sind.

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

/** Kamerabild per fetch (mit Schluessel) als Blob-URL, alle `every` ms neu. */
export function useCamera(active, every = 1000) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!active) return;
    let stop = false, last = null, timer = null;
    const tick = async () => {
      if (stop) return;
      if (!document.hidden) {
        try {
          const r = await fetch("api/camera/snapshot.jpg", { headers: { Authorization: "Bearer " + auth.key }, cache: "no-store" });
          if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Kamera ${r.status}`);
          const u = URL.createObjectURL(await r.blob());
          if (last) URL.revokeObjectURL(last);
          last = u; setUrl(u); setErr(null);
        } catch (e) { setErr(e.message); }
      }
      timer = setTimeout(tick, every);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); if (last) URL.revokeObjectURL(last); };
  }, [active, every]);
  return [url, err];
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
  const [cam, camErr] = useCamera(visible && tab === "camera" && !!S.me);
  const hasModel = info && (info.status === "ready" || info.thumbnail);
  const src = info?.status === "ready" ? `api/print/preview.png?t=${stamp}` : info?.thumbnail ? `api/print/thumbnail.png?t=${stamp}` : null;

  let body;
  if (tab === "camera") {
    if (!S.me) body = html`<div class="media-empty">Die Kamera sehen nur gekoppelte Geräte. <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>Koppeln</a></div>`;
    else if (cam) body = html`<img src=${cam} alt="Kamera" onClick=${() => openDialog("camera")} />`;
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

/** Vollbild: Kamera live (1/s) oder das Modellbild gross. */
export function CameraDialog({ view, src }) {
  const [cam, camErr] = useCamera(view !== "model" && !!S.me);
  const close = () => set({ dialog: null });
  return html`<div class="scrim viewer" onClick=${close}>
    <button class="btn icon ghost viewer-close" aria-label="Schließen" onClick=${close}><${Icon} name="close" /></button>
    ${view === "model" ? html`<img src=${src} alt="Vorschau der Druckdatei" />`
      : cam ? html`<img src=${cam} alt="Kamera" />` : html`<div class="media-empty">${camErr || "Kamera lädt …"}</div>`}
  </div>`;
}
