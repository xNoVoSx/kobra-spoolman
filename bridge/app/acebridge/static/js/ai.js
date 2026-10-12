// AI tab: see and control failure detection (kobra-vision via the bridge).
// Live (camera with detections, history, check now), settings, ignored areas, memory (baseline, events) and image
// collection (label, delete, ZIP).

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, del, get, post } from "./api.js";
import { Toggle } from "./ace.js";
import { locale, t } from "./i18n.js";
import { Icon } from "./icons.js";
import { cameraKey, cameraUrl } from "./media.js";
import { S, guard, toast } from "./store.js";
import { ago, cls, num } from "./util.js";

const LEVEL = { ok: [t("normal"), "ok"], warn: [t("suspicious"), "warn"], fail: [t("Failure?"), "bad"] };
const KIND = { start: t("print start"), periodic: t("periodic"), suspect: t("suspicious"), event: t("Alarm"), end: t("End"), test: t("Test") };
const abs = (p) => new URL(p.replace(/^\//, ""), location.href).href;
const time = (ts) => new Date(ts * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** State of the AI, refreshed every 3 s while the tab is open. */
function useVision() {
  const [v, setV] = useState(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let stop = false, timer = null;
    const tick = async () => {
      if (!document.hidden) { try { const r = await get("/api/vision"); if (!stop) setV(r); } catch (e) { if (!stop) setV((o) => o || { error: e.message }); } }
      if (!stop) timer = setTimeout(tick, 3000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [n]);
  return [v, () => setN((x) => x + 1)];
}

function useKey() {
  const [key, setKey] = useState(null);
  useEffect(() => { if (S.me) cameraKey().then(setKey).catch(() => {}); }, [S.me]);
  return key;
}

/** Two-step button for delete/reset: tap first, then confirm. */
function Confirm({ label, sure = t("Really?"), onYes, small = true, danger = true }) {
  const [arm, setArm] = useState(false);
  useEffect(() => { if (!arm) return; const timer = setTimeout(() => setArm(false), 4000); return () => clearTimeout(timer); }, [arm]);
  return html`<button class=${cls("btn", small && "sm", arm && danger && "danger")} onClick=${guard(async () => { if (!arm) { setArm(true); return; } setArm(false); await onYes(); })}>${arm ? sure : label}</button>`;
}

/** Image with boxes: detections (red/yellow), ignored detections (grey dashed), ignored areas (blue). */
function Boxed({ src, size, dets = [], ignored = [], zones = [], level = "warn", children, onPointer }) {
  const [w, h] = size && size[0] ? size : [1280, 720];
  const color = level === "fail" ? "var(--danger)" : "var(--accent)";
  const [gone, setGone] = useState(false);              // image deleted (e.g. print removed from the collection)
  useEffect(() => setGone(false), [src]);
  const rect = (b, stroke, dash, label) => {
    const [xc, yc, bw, bh] = b;
    return html`<g><rect x=${(xc - bw / 2) * w} y=${(yc - bh / 2) * h} width=${bw * w} height=${bh * h} fill="none" stroke=${stroke}
      stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray=${dash || null} />
      ${label && html`<text x=${(xc - bw / 2) * w + 4} y=${(yc - bh / 2) * h + Math.max(14, h / 40)} fill=${stroke} font-size=${Math.max(12, h / 45)}>${label}</text>`}</g>`;
  };
  return html`<div class="ai-img" style=${{ aspectRatio: `${w} / ${h}` }}>
    ${src && !gone ? html`<img src=${src} alt=${t("Camera image")} onError=${() => setGone(true)} />`
      : html`<div class="media-empty">${src ? t("Image deleted") : t("no image")}</div>`}
    <svg class="ai-boxes" viewBox=${`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true"
      onPointerDown=${onPointer?.down} onPointerMove=${onPointer?.move} onPointerUp=${onPointer?.up} style=${onPointer ? { pointerEvents: "auto", cursor: "crosshair", touchAction: "none" } : null}>
      ${zones.map((z) => html`<rect x=${z.x * w} y=${z.y * h} width=${z.w * w} height=${z.h * h} fill="rgba(80,140,255,.18)" stroke="#5a8cff" stroke-width="2" vector-effect="non-scaling-stroke" />`)}
      ${ignored.map((d) => rect(d[2], "#9aa0a6", "6 4", t("{pct} % ignored", { pct: Math.round(d[1] * 100) })))}
      ${dets.map((d) => rect(d[2], color, null, `${Math.round(d[1] * 100)} %`))}
      ${children}
    </svg>
  </div>`;
}

/** History of the score in the running print: 0..1, bands for suspicious (1/3) and failure (2/3). */
function Chart({ history }) {
  if (!history?.length) return html`<div class="small muted">${t("No history yet – it starts with the next print.")}</div>`;
  const W = 600, H = 120, t0 = history[0][0], t1 = Math.max(history[history.length - 1][0], t0 + 60);
  const x = (ts) => ((ts - t0) / (t1 - t0)) * W, y = (s) => H - s * H;
  const pts = history.map(([ts, , s]) => `${x(ts).toFixed(1)},${y(s).toFixed(1)}`).join(" ");
  const last = history[history.length - 1];
  return html`<svg class="ai-chart" viewBox=${`0 0 ${W} ${H + 18}`} preserveAspectRatio="none" role="img" aria-label=${t("History of the AI score")}>
    <rect x="0" y=${y(1)} width=${W} height=${H / 3} fill="var(--danger-soft)" />
    <rect x="0" y=${y(2 / 3)} width=${W} height=${H / 3} fill="var(--accent-soft)" />
    <line x1="0" x2=${W} y1=${y(1 / 3)} y2=${y(1 / 3)} stroke="var(--line-strong)" stroke-dasharray="4 4" />
    <line x1="0" x2=${W} y1=${y(2 / 3)} y2=${y(2 / 3)} stroke="var(--line-strong)" stroke-dasharray="4 4" />
    <polyline points=${pts} fill="none" stroke="var(--text)" stroke-width="2" vector-effect="non-scaling-stroke" />
    <circle cx=${x(last[0])} cy=${y(last[2])} r="4" fill="var(--accent)" />
    <text x="4" y=${H + 14} font-size="11" fill="var(--muted)">${time(t0)}</text>
    <text x=${W - 4} y=${H + 14} font-size="11" fill="var(--muted)" text-anchor="end">${time(last[0])}</text>
    <text x=${W - 4} y=${y(2 / 3) - 4} font-size="11" fill="var(--danger-text)" text-anchor="end">${t("Failure")}</text>
    <text x=${W - 4} y=${y(1 / 3) - 4} font-size="11" fill="var(--accent-text)" text-anchor="end">${t("suspicious")}</text>
  </svg>`;
}

// ------------------------------------------------------------ Live
async function upload(file) {
  // any image -> JPEG (the service expects JPEG)
  const bmp = await createImageBitmap(file);
  const c = document.createElement("canvas");
  c.width = bmp.width; c.height = bmp.height;
  c.getContext("2d").drawImage(bmp, 0, 0);
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.9));
  const resp = await fetch("/api/vision/test", { method: "POST", body: blob, headers: { "Content-Type": "image/jpeg", Authorization: "Bearer " + auth.key } });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || t("Error {status}", { status: resp.status }));
  return { ...data, src: URL.createObjectURL(blob) };
}

function Live({ v, key_, reload }) {
  const [test, setTest] = useState(null);
  const fileRef = useRef(null);
  const p = v.prediction || {};
  const [word, chip] = LEVEL[v.level] || LEVEL.ok;
  const learning = v.printing && p.frames < v.safe_frames;
  const prov = (v.health?.model?.provider || "").replace("ExecutionProvider", "");
  const runTest = guard(async () => {
    const r = await post("/api/vision/test");
    setTest({ ...r, src: cameraUrl(key_, "snapshot.jpg") + `&t=${Date.now()}` });
  });
  return html`<div class="ai-grid">
    <section class="card pad col">
      <div class="row wrap"><h2 class="h2 grow">${t("Now")}</h2>
        ${v.printing ? html`<span class=${cls("chip", v.muted ? "" : chip)}>${v.muted ? t("muted") : learning ? t("learning") : word}</span>` : html`<span class="chip">${t("no print")}</span>`}</div>
      <div class="kv ai-kv">
        <span>${t("Score")}</span><span class="m">${v.score == null ? "–" : num(v.score, 2)} <span class="muted small">${t("(0–1; suspicious from {low}, failure from {high})", { low: num(0.33, 2), high: num(0.67, 2) })}</span></span>
        <span>${t("Last image")}</span><span class="m">${p.p == null ? "–" : num(p.p, 2)} <span class="muted small">${t("sum of detections")} · ${t("{n} detections", { n: (v.detections || []).length })}${(v.ignored || []).length ? ", " + t("{n} ignored", { n: v.ignored.length }) : ""}</span></span>
        <span>${t("This print")}</span><span>${v.printing ? t("{n} images", { n: p.frames }) + (learning ? " · " + t("still learning {n}", { n: v.safe_frames - p.frames }) : "") : "–"}</span>
        <span>${t("Service")}</span><span>${v.error ? html`<span class="err-text">${v.error}</span>` : `${prov === "CUDA" ? t("graphics card") : prov || t("ready")}${v.ms ? " · " + t("{ms} ms per image", { ms: num(v.ms, 0) }) : ""} · ${v.health?.model?.loaded ? t("model loaded") : t("model unloaded")}`}</span>
        <span>${t("Applies now")}</span><span>${v.action_now === "pause" ? t("pause on failure") : t("notify only")}${v.quiet_now ? " " + t("(quiet hours)") : ""}</span>
      </div>
      <div class="row wrap">
        <button class="btn sm" onClick=${runTest}><${Icon} name="refresh" small />${t("Check now")}</button>
        <button class="btn sm" onClick=${() => fileRef.current?.click()}><${Icon} name="plus" small />${t("Test an image")}</button>
        <input ref=${fileRef} type="file" accept="image/*" hidden onChange=${guard(async (e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setTest(await upload(f)); })} />
        ${v.printing && html`<button class="btn sm" onClick=${guard(async () => { await post("/api/vision/mute", { on: !v.muted }); toast(v.muted ? t("The AI is watching again") : t("This print is not watched"), "ok"); reload(); })}>
          ${v.muted ? t("Watch again") : t("Don't watch this print")}</button>`}
      </div>
      <div class="lbl">${t("History of this print")}</div>
      <${Chart} history=${v.history} />
    </section>
    <section class="card pad col">
      <h2 class="h2">${test ? t("Test: {verdict}", { verdict: test.verdict }) : t("Camera with detections")}</h2>
      ${test
        ? html`<${Boxed} src=${test.src} size=${test.size} dets=${test.detections} ignored=${test.ignored} zones=${v.zones} level=${test.p >= 0.78 ? "fail" : "warn"} />
          <div class="small muted">${t("Sum {p}", { p: num(test.p, 2) })} · ${t("{n} detections", { n: test.detections.length })}${test.ignored.length ? ", " + t("{n} in ignored areas", { n: test.ignored.length }) : ""} · ${num(test.ms, 0)} ms. ${t("From {low} slightly, from {high} clearly conspicuous – for an alarm the score must rise over several images during a print.", { low: num(0.38, 2), high: num(0.78, 2) })}</div>
          <button class="btn sm" onClick=${() => setTest(null)}>${t("Back to the camera")}</button>`
        : key_ ? html`<${Boxed} src=${cameraUrl(key_)} size=${v.size} dets=${v.detections} ignored=${v.ignored} zones=${v.zones} level=${v.level} />
          <div class="small muted">${t("Boxes from the last analysed image (every {s} s while printing). Blue: ignored areas.", { s: num(v.settings?.interval_s, 0) })}</div>`
        : html`<div class="media-empty">${t("Camera only on paired devices")}</div>`}
    </section>
  </div>`;
}

// ------------------------------------------------------------ settings
const SENS = [[t("Low"), 0.7], [t("Normal"), 1.0], [t("High"), 1.5]];

function Settings({ v, reload }) {
  const [s, setS] = useState(v.settings);
  useEffect(() => setS(v.settings), [JSON.stringify(v.settings)]);
  const ch = (patch) => setS({ ...s, ...patch });
  const q = s.quiet;
  const changed = JSON.stringify(s) !== JSON.stringify(v.settings);
  const save = guard(async () => {
    const diff = Object.fromEntries(Object.entries(s).filter(([k, val]) => k !== "zones" && JSON.stringify(val) !== JSON.stringify(v.settings[k])));
    await post("/api/vision/settings", diff);
    toast(t("AI settings saved"), "ok");
    reload();
  });
  const seg = (opts, cur, set) => html`<div class="seg">${opts.map(([l, val]) => html`<button class=${cls("seg-btn", cur === val && "on")} onClick=${() => set(val)}>${l}</button>`)}</div>`;
  return html`<section class="card pad col ai-settings">
    <${Toggle} label=${t("AI monitoring")} hint=${v.configured ? t("Send images to the AI service while printing") : t("VISION_URL is not set – set up the kobra-vision service first")} value=${s.enabled} disabled=${!v.configured} onChange=${(x) => ch({ enabled: x })} />
    <div class="lbl">${t("Sensitivity")}</div>
    <div class="row wrap">${seg(SENS, SENS.find(([, x]) => x === s.sensitivity)?.[1] ?? null, (x) => ch({ sensitivity: x }))}
      <input type="range" min="0.3" max="3" step="0.1" value=${s.sensitivity} onInput=${(e) => ch({ sensitivity: Number(e.target.value) })} aria-label=${t("Sensitivity, fine")} />
      <span class="m">× ${num(s.sensitivity, 1)}</span></div>
    <div class="small muted">${t("Multiplies the score. Higher reports earlier (more false alarms), lower later.")}</div>
    <div class="lbl">${t("On failure")}</div>
    ${seg([[t("Notify only"), "warn"], [t("Pause print"), "pause"]], s.action, (x) => ch({ action: x }))}
    <${Toggle} label=${t("Turn the nozzle off after an AI pause")} hint=${t("So nothing chars. Not yet tested on the Kobra: check the nozzle temperature when resuming.")} value=${s.heater_off} onChange=${(x) => ch({ heater_off: x })} />
    <div class="lbl">${t("Alarm to the phone")}</div>
    ${seg([[t("Already at “suspicious”"), "warn"], [t("Only at “failure”"), "fail"]], s.notify, (x) => ch({ notify: x }))}
    <div class="lbl">${t("Quiet hours")}</div>
    <${Toggle} label=${t("Quiet hours")} hint=${t("E.g. react differently at night")} value=${q.enabled} onChange=${(x) => ch({ quiet: { ...q, enabled: x } })} />
    ${q.enabled && html`<div class="row wrap">
      <label class="row small">${t("from")} <input class="inp set-time" type="time" value=${q.start} onInput=${(e) => ch({ quiet: { ...q, start: e.target.value } })} /></label>
      <label class="row small">${t("to")} <input class="inp set-time" type="time" value=${q.end} onInput=${(e) => ch({ quiet: { ...q, end: e.target.value } })} /></label>
      ${seg([[t("Notify failures only"), "fail_only"], [t("Pause on failure"), "pause"]], q.mode, (x) => ch({ quiet: { ...q, mode: x } }))}</div>`}
    <div class="lbl">${t("Times")}</div>
    <div class="row wrap ai-nums">
      <label>${t("Image every")} <input class="inp set-num" type="number" min="2" max="60" value=${s.interval_s} onInput=${(e) => ch({ interval_s: Number(e.target.value) })} /> s</label>
      <label>${t("Learning time at print start")} <input class="inp set-num" type="number" min="0" max="15" value=${Math.round(s.safe_s / 60)} onInput=${(e) => ch({ safe_s: Number(e.target.value) * 60 })} /> min</label>
    </div>
    <div class="small muted">${t("During the learning time the AI never reports (first layer, purging, wiping). The scoring is tuned to ~10 s per image.")}</div>
    <div class="lbl">${t("Image collection")}</div>
    <div class="row wrap ai-nums">
      <label>${t("at most")} <input class="inp set-num" type="number" min="0" max="100" step="0.5" value=${s.dataset_gb} onInput=${(e) => ch({ dataset_gb: Number(e.target.value) })} /> GB</label>
      <label>${t("one image every")} <input class="inp set-num" type="number" min="10" max="600" value=${s.save_every_s} onInput=${(e) => ch({ save_every_s: Number(e.target.value) })} /> s</label>
    </div>
    <div class="small muted">${t("Plus every suspicious image and every alarm. 0 GB = collect nothing. When space runs out the oldest prints are deleted.")}</div>
    <div class="row"><span class="grow"></span>
      ${changed && html`<button class="btn sm" onClick=${() => setS(v.settings)}>${t("Discard")}</button>`}
      <button class="btn sm acc" disabled=${!changed} onClick=${save}>${t("Save")}</button></div>
  </section>`;
}

// ------------------------------------------------------------ areas
function Zones({ v, key_, reload }) {
  const [zones, setZones] = useState(v.settings.zones);
  const [draft, setDraft] = useState(null);
  const [src, setSrc] = useState(null);
  useEffect(() => setZones(v.settings.zones), [JSON.stringify(v.settings.zones)]);
  useEffect(() => { if (key_) setSrc(cameraUrl(key_, "snapshot.jpg") + `&t=${Date.now()}`); }, [key_]);
  const [w, h] = v.size && v.size[0] ? v.size : [1280, 720];
  const pos = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const s = Math.min(r.width / w, r.height / h), ox = (r.width - w * s) / 2, oy = (r.height - h * s) / 2;
    return [Math.min(1, Math.max(0, (e.clientX - r.left - ox) / (w * s))), Math.min(1, Math.max(0, (e.clientY - r.top - oy) / (h * s)))];
  };
  const box = (d) => ({ x: Math.min(d.a[0], d.b[0]), y: Math.min(d.a[1], d.b[1]), w: Math.abs(d.b[0] - d.a[0]), h: Math.abs(d.b[1] - d.a[1]) });
  const ptr = {
    down: (e) => { e.currentTarget.setPointerCapture(e.pointerId); const p = pos(e); setDraft({ a: p, b: p }); },
    move: (e) => { if (draft) setDraft({ ...draft, b: pos(e) }); },
    up: () => { if (draft) { const z = box(draft); if (z.w > 0.02 && z.h > 0.02 && zones.length < 10) setZones([...zones, z]); setDraft(null); } },
  };
  const changed = JSON.stringify(zones) !== JSON.stringify(v.settings.zones);
  const all = draft ? [...zones, box(draft)] : zones;
  return html`<div class="ai-grid">
    <section class="card pad col">
      <h2 class="h2">${t("Ignored areas")}</h2>
      <div class="small muted">${t("Drag a rectangle into the image. Detections whose centre lies inside do not count – e.g. purge chute, cleaning brush, reflections. At most 10.")}</div>
      ${key_ ? html`<${Boxed} src=${src} size=${v.size} zones=${all} onPointer=${ptr} />` : html`<div class="media-empty">${t("Camera only on paired devices")}</div>`}
      <div class="row"><button class="btn sm" onClick=${() => setSrc(cameraUrl(key_, "snapshot.jpg") + `&t=${Date.now()}`)}><${Icon} name="refresh" small />${t("New image")}</button><span class="grow"></span>
        ${changed && html`<button class="btn sm" onClick=${() => setZones(v.settings.zones)}>${t("Discard")}</button>`}
        <button class="btn sm acc" disabled=${!changed} onClick=${guard(async () => { await post("/api/vision/settings", { zones }); toast(t("Areas saved"), "ok"); reload(); })}>${t("Save")}</button></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">${zones.length === 1 ? t("1 area") : t("{n} areas", { n: zones.length })}</h2>
      ${zones.length === 0 && html`<div class="small muted">${t("None yet – the AI analyses the whole image.")}</div>`}
      ${zones.map((z, i) => html`<div class="row small"><span class="m grow">#${i + 1} · ${t("left {x} % · top {y} %", { x: Math.round(z.x * 100), y: Math.round(z.y * 100) })} · ${Math.round(z.w * 100)} × ${Math.round(z.h * 100)} %</span>
        <button class="btn sm" onClick=${() => setZones(zones.filter((_, k) => k !== i))}><${Icon} name="trash" small />${t("Remove")}</button></div>`)}
    </section>
  </div>`;
}

// ------------------------------------------------------------ memory
function Memory({ v, key_, reload }) {
  const p = v.prediction || {};
  const verdict = guard(async (id, x) => { await post("/api/vision/feedback", { id, verdict: x }); toast(t("Rating saved"), "ok"); reload(); });
  return html`<div class="col" style="gap:16px">
    <section class="card pad col">
      <h2 class="h2">${t("What the AI knows")}</h2>
      <div class="small muted" style="max-width:70ch">${t("The model (Obico, trained on real failed prints) does not learn by itself here. What builds up on your side:")}
        ${t("the baseline – how much “noise” your camera normally shows – and the images you collected and labelled, for an own model later.")}</div>
      <div class="kv ai-kv">
        <span>${t("Baseline")}</span><span class="m">${num(p.long, 3)} <span class="muted small">${t("mean sum of detections per image")}</span></span>
        <span>${t("Images seen")}</span><span class="m">${p.lifetime ?? 0} <span class="muted small">${t("(fully valid from ~7200)")}</span></span>
        <span>${t("Thresholds")}</span><span class="small">${t("suspicious from {low} above the baseline (or clearly above the print itself), certain from {high}; failure × {escalate}", { low: v.thresholds?.low, high: v.thresholds?.high, escalate: v.thresholds?.escalate })}</span>
        <span>${t("Ignored areas")}</span><span>${v.settings.zones.length}</span>
      </div>
      <div class="row"><${Confirm} label=${t("Reset the baseline")} sure=${t("Really reset?")} onYes=${async () => { await post("/api/vision/baseline/reset"); toast(t("Baseline reset"), "ok"); reload(); }} />
        <span class="small muted">${t("e.g. after rebuilding the camera")}</span></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">${t("Events")}</h2>
      ${!(v.events || []).length && html`<div class="small muted">${t("No report from the AI yet.")}</div>`}
      <div class="ai-events">${(v.events || []).map((e) => html`<div class="ai-event">
        ${key_ && e.frame ? html`<${Boxed} src=${abs(`/api/vision/event/${e.id}.jpg?key=${encodeURIComponent(key_)}`)} size=${e.size} dets=${e.detections} level=${e.level} />` : html`<div class="media-empty">${t("no image")}</div>`}
        <div class="col" style="gap:4px">
          <div class="row"><span class=${cls("chip", e.level === "fail" ? "bad" : "warn")}>${e.level === "fail" ? t("Failure") : t("suspicious")}</span>
            <span class="small muted">${ago(e.at)} · ${t("score {s}", { s: num(e.score, 2) })}${e.paused ? " · " + t("paused") : ""}</span></div>
          <div class="small ell">${e.file || "–"}</div>
          <div class="row wrap">
            <button class=${cls("btn sm", e.verdict === "false_alarm" && "acc")} onClick=${() => verdict(e.id, "false_alarm")}>${t("False alarm")}</button>
            <button class=${cls("btn sm", e.verdict === "confirmed" && "acc")} onClick=${() => verdict(e.id, "confirmed")}>${t("Correct")}</button>
            ${e.verdict && html`<button class="btn sm" onClick=${() => verdict(e.id, null)}>${t("undo")}</button>`}</div>
        </div></div>`)}</div>
    </section>
  </div>`;
}

// ------------------------------------------------------------ images
const FILTERS = [["all", t("All")], ["event", t("Alarms")], ["suspect", t("Suspicious")], ["startend", t("Start/end")], ["labelled", t("Labelled")], ["open", t("Unlabelled")]];

function Gallery({ key_ }) {
  const [list, setList] = useState(null);
  const [job, setJob] = useState(null);
  const [page, setPage] = useState({ frames: [], total: 0 });
  const [filter, setFilter] = useState("all");
  const loadList = () => get("/api/vision/jobs").then(setList).catch((e) => toast(e.message, "bad"));
  const loadJob = (j, more = false) => get(`/api/vision/jobs/${encodeURIComponent(j)}?filter=${filter}&offset=${more ? page.frames.length : 0}&limit=120`)
    .then((r) => setPage(more ? { ...r, frames: page.frames.concat(r.frames) } : r)).catch((e) => toast(e.message, "bad"));
  useEffect(() => { loadList(); }, []);
  useEffect(() => { if (job) loadJob(job); }, [job, filter]);
  if (!list) return html`<div class="muted">${t("loading …")}</div>`;
  const st = list.stats;
  const img = (j, f) => abs(`/api/vision/jobs/${encodeURIComponent(j)}/${encodeURIComponent(f)}?key=${encodeURIComponent(key_ || "")}`);
  const zip = (j) => abs(`/api/vision/export.zip?key=${encodeURIComponent(key_ || "")}${j ? `&job=${encodeURIComponent(j)}` : ""}`);
  if (!job) {
    return html`<section class="card pad col">
      <div class="row wrap"><h2 class="h2 grow">${t("Image collection")}</h2>
        <span class="small muted">${t("{jobs} prints · {frames} images · {labelled} labelled · {used} of {limit} GB", { jobs: st.jobs, frames: st.frames, labelled: st.labelled, used: num(st.mb / 1024, 2), limit: num(st.limit_gb, 1) })}</span>
        ${key_ && st.frames > 0 && html`<a class="btn sm" href=${zip()} download><${Icon} name="download" small />${t("All as ZIP")}</a>`}</div>
      <div class="ai-bar"><span style=${{ width: `${Math.min(100, (st.mb / 1024 / Math.max(st.limit_gb, 0.001)) * 100)}%` }}></span></div>
      ${!list.jobs.length && html`<div class="small muted">${t("No images yet – the collection starts with the next print.")}</div>`}
      <div class="ai-jobs">${list.jobs.map((j) => html`<div class="ai-job">
        <button class="ai-job-main" onClick=${() => { setFilter("all"); setJob(j.job); }}>
          ${key_ && j.cover ? html`<img src=${img(j.job, j.cover)} alt="" loading="lazy" />` : html`<div class="media-empty">–</div>`}
          <span class="col" style="gap:2px;min-width:0"><b class="ell">${j.job.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\d{2}_/, "$3.$2. $4:$5 · ")}</b>
            <span class="small muted">${t("{frames} images · {events} alarms · {labelled} labelled · {mb} MB", { frames: j.frames, events: j.events, labelled: j.labelled, mb: num(j.mb, 1) })}</span></span></button>
        <div class="row">${key_ && html`<a class="btn sm" href=${zip(j.job)} download>ZIP</a>`}
          <${Confirm} label=${t("Delete")} sure=${t("Delete print?")} onYes=${async () => { await del(`/api/vision/jobs/${encodeURIComponent(j.job)}`); toast(t("Deleted"), "ok"); loadList(); }} /></div>
      </div>`)}</div>
    </section>`;
  }
  const show = page.frames;
  const patch = (frame, fn) => setPage((pg) => ({ ...pg, frames: fn(pg.frames, frame) }));
  const label = guard(async (f, l) => {
    const next = f.label === l ? null : l;
    await post("/api/vision/label", { job, frame: f.frame, label: next });
    patch(f.frame, (fr, n) => fr.map((x) => (x.frame === n ? { ...x, label: next } : x)));
  });
  return html`<section class="card pad col">
    <div class="row wrap"><button class="btn sm" onClick=${() => { setJob(null); loadList(); }}><${Icon} name="back" small />${t("All prints")}</button>
      <h2 class="h2 grow ell">${job}</h2><span class="small muted">${t("{n} images", { n: page.total })}</span></div>
    <div class="row wrap">${FILTERS.map(([k, l]) => html`<button class=${cls("chip", filter === k && "on")} onClick=${() => setFilter(k)}>${l}</button>`)}</div>
    <div class="ai-frames">${show.map((f) => html`<div class="ai-frame">
      ${key_ ? html`<${Boxed} src=${img(job, f.frame)} size=${f.size} dets=${f.detections || []} ignored=${f.ignored || []} level=${f.level === "fail" ? "fail" : "warn"} />` : null}
      <div class="row small"><span class="m">${time(f.t)}</span><span class="muted">${KIND[f.kind] || f.kind}</span><span class="m grow" style="text-align:right" title=${t("Sum of the confidences of all detections in this image – not the 0–1 score from “Live”")}>${t("Detections {p}", { p: num(f.p || 0, 2) })}</span></div>
      <div class="row wrap" style="gap:4px">${Object.entries(list.stats.labels).map(([k, l]) => html`<button class=${cls("chip", f.label === k && "on")} onClick=${() => label(f, k)}>${l}</button>`)}</div>
      <div class="row"><span class="grow small muted">${f.layer != null ? t("Layer {layer}", { layer: f.layer }) : ""}</span>
        <${Confirm} label=${t("Delete")} sure=${t("Delete image?")} onYes=${async () => { await del(`/api/vision/jobs/${encodeURIComponent(job)}/${encodeURIComponent(f.frame)}`); patch(f.frame, (fr, n) => fr.filter((x) => x.frame !== n)); setPage((pg) => ({ ...pg, total: pg.total - 1 })); }} /></div>
    </div>`)}</div>
    ${!show.length && html`<div class="small muted">${t("No images in this selection.")}</div>`}
    ${show.length < page.total && html`<div class="row"><span class="small muted grow">${t("{n} of {total}", { n: show.length, total: page.total })}</span>
      <button class="btn sm" onClick=${guard(() => loadJob(job, true))}>${t("Load more")}</button></div>`}
  </section>`;
}

// ------------------------------------------------------------ page
export function AiPage() {
  const [v, reload] = useVision();
  const [tab, setTab] = useState("live");
  const key_ = useKey();
  if (!v) return html`<div class="muted">${t("loading …")}</div>`;
  if (!v.settings) return html`<section class="card pad">${t("AI not reachable: {error}", { error: v.error })}</section>`;
  const tabBtn = (k, l) => html`<button role="tab" aria-selected=${tab === k} class=${cls("seg-btn", tab === k && "on")} onClick=${() => setTab(k)}>${l}</button>`;
  return html`<div class="col" style="gap:16px">
    ${!v.configured && html`<section class="card pad small">${t("The AI service is not set up: add the kobra-vision service to the stack and set VISION_URL on the bridge (docs: vision.md).")}</section>`}
    <div class="seg" role="tablist" aria-label=${t("AI")}>${tabBtn("live", "Live")}${tabBtn("settings", t("Settings"))}${tabBtn("zones", t("Areas"))}${tabBtn("memory", t("Memory"))}${tabBtn("images", t("Images"))}</div>
    ${tab === "live" ? html`<${Live} v=${v} key_=${key_} reload=${reload} />`
      : tab === "settings" ? html`<${Settings} v=${v} reload=${reload} />`
      : tab === "zones" ? html`<${Zones} v=${v} key_=${key_} reload=${reload} />`
      : tab === "memory" ? html`<${Memory} v=${v} key_=${key_} reload=${reload} />`
      : html`<${Gallery} key_=${key_} />`}
  </div>`;
}
