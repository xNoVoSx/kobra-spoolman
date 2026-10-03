// KI-Tab: Fehldruck-Erkennung (kobra-vision ueber die Bridge) sehen und steuern.
// Live (Kamera mit Funden, Verlauf, Jetzt pruefen), Einstellungen, ignorierte Bereiche, Gedaechtnis
// (Grundlinie, Ereignisse) und Bildersammlung (kennzeichnen, loeschen, ZIP).

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { auth, del, get, post } from "./api.js";
import { Toggle } from "./ace.js";
import { Icon } from "./icons.js";
import { cameraKey, cameraUrl } from "./media.js";
import { S, guard, toast } from "./store.js";
import { ago, cls, num } from "./util.js";

const LEVEL = { ok: ["unauffällig", "ok"], warn: ["verdächtig", "warn"], fail: ["Fehldruck?", "bad"] };
const KIND = { start: "Start", periodic: "laufend", suspect: "verdächtig", event: "Alarm", end: "Ende", test: "Test" };
const abs = (p) => new URL(p.replace(/^\//, ""), location.href).href;
const time = (t) => new Date(t * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Zustand der KI, alle 3 s neu, solange der Tab offen ist. */
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

/** Zweistufiger Knopf fuer Loeschen/Zuruecksetzen: erst tippen, dann bestaetigen. */
function Confirm({ label, sure = "Wirklich?", onYes, small = true, danger = true }) {
  const [arm, setArm] = useState(false);
  useEffect(() => { if (!arm) return; const t = setTimeout(() => setArm(false), 4000); return () => clearTimeout(t); }, [arm]);
  return html`<button class=${cls("btn", small && "sm", arm && danger && "danger")} onClick=${guard(async () => { if (!arm) { setArm(true); return; } setArm(false); await onYes(); })}>${arm ? sure : label}</button>`;
}

/** Bild mit Rahmen: Funde (rot/gelb), ignorierte Funde (grau gestrichelt), ignorierte Bereiche (blau). */
function Boxed({ src, size, dets = [], ignored = [], zones = [], level = "warn", children, onPointer }) {
  const [w, h] = size && size[0] ? size : [1280, 720];
  const color = level === "fail" ? "var(--danger)" : "var(--accent)";
  const rect = (b, stroke, dash, label) => {
    const [xc, yc, bw, bh] = b;
    return html`<g><rect x=${(xc - bw / 2) * w} y=${(yc - bh / 2) * h} width=${bw * w} height=${bh * h} fill="none" stroke=${stroke}
      stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray=${dash || null} />
      ${label && html`<text x=${(xc - bw / 2) * w + 4} y=${(yc - bh / 2) * h + Math.max(14, h / 40)} fill=${stroke} font-size=${Math.max(12, h / 45)}>${label}</text>`}</g>`;
  };
  return html`<div class="ai-img" style=${{ aspectRatio: `${w} / ${h}` }}>
    ${src ? html`<img src=${src} alt="Kamerabild" />` : html`<div class="media-empty">kein Bild</div>`}
    <svg class="ai-boxes" viewBox=${`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true"
      onPointerDown=${onPointer?.down} onPointerMove=${onPointer?.move} onPointerUp=${onPointer?.up} style=${onPointer ? { pointerEvents: "auto", cursor: "crosshair", touchAction: "none" } : null}>
      ${zones.map((z) => html`<rect x=${z.x * w} y=${z.y * h} width=${z.w * w} height=${z.h * h} fill="rgba(80,140,255,.18)" stroke="#5a8cff" stroke-width="2" vector-effect="non-scaling-stroke" />`)}
      ${ignored.map((d) => rect(d[2], "#9aa0a6", "6 4", `${Math.round(d[1] * 100)} % ignoriert`))}
      ${dets.map((d) => rect(d[2], color, null, `${Math.round(d[1] * 100)} %`))}
      ${children}
    </svg>
  </div>`;
}

/** Verlauf des Werts im laufenden Druck: 0..1, Baender fuer verdaechtig (1/3) und Fehldruck (2/3). */
function Chart({ history }) {
  if (!history?.length) return html`<div class="small muted">Noch kein Verlauf – er beginnt mit dem nächsten Druck.</div>`;
  const W = 600, H = 120, t0 = history[0][0], t1 = Math.max(history[history.length - 1][0], t0 + 60);
  const x = (t) => ((t - t0) / (t1 - t0)) * W, y = (s) => H - s * H;
  const pts = history.map(([t, , s]) => `${x(t).toFixed(1)},${y(s).toFixed(1)}`).join(" ");
  const last = history[history.length - 1];
  return html`<svg class="ai-chart" viewBox=${`0 0 ${W} ${H + 18}`} preserveAspectRatio="none" role="img" aria-label="Verlauf des KI-Werts">
    <rect x="0" y=${y(1)} width=${W} height=${H / 3} fill="var(--danger-soft)" />
    <rect x="0" y=${y(2 / 3)} width=${W} height=${H / 3} fill="var(--accent-soft)" />
    <line x1="0" x2=${W} y1=${y(1 / 3)} y2=${y(1 / 3)} stroke="var(--line-strong)" stroke-dasharray="4 4" />
    <line x1="0" x2=${W} y1=${y(2 / 3)} y2=${y(2 / 3)} stroke="var(--line-strong)" stroke-dasharray="4 4" />
    <polyline points=${pts} fill="none" stroke="var(--text)" stroke-width="2" vector-effect="non-scaling-stroke" />
    <circle cx=${x(last[0])} cy=${y(last[2])} r="4" fill="var(--accent)" />
    <text x="4" y=${H + 14} font-size="11" fill="var(--muted)">${time(t0)}</text>
    <text x=${W - 4} y=${H + 14} font-size="11" fill="var(--muted)" text-anchor="end">${time(last[0])}</text>
    <text x=${W - 4} y=${y(2 / 3) - 4} font-size="11" fill="var(--danger-text)" text-anchor="end">Fehldruck</text>
    <text x=${W - 4} y=${y(1 / 3) - 4} font-size="11" fill="var(--accent-text)" text-anchor="end">verdächtig</text>
  </svg>`;
}

// ------------------------------------------------------------ Live
async function upload(file) {
  // beliebiges Bild -> JPEG (der Dienst erwartet JPEG)
  const bmp = await createImageBitmap(file);
  const c = document.createElement("canvas");
  c.width = bmp.width; c.height = bmp.height;
  c.getContext("2d").drawImage(bmp, 0, 0);
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.9));
  const resp = await fetch("/api/vision/test", { method: "POST", body: blob, headers: { "Content-Type": "image/jpeg", Authorization: "Bearer " + auth.key } });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `Fehler ${resp.status}`);
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
      <div class="row wrap"><h2 class="h2 grow">Jetzt</h2>
        ${v.printing ? html`<span class=${cls("chip", v.muted ? "" : chip)}>${v.muted ? "stumm" : learning ? "lernt" : word}</span>` : html`<span class="chip">kein Druck</span>`}</div>
      <div class="kv ai-kv">
        <span>Wert</span><span class="m">${v.score == null ? "–" : num(v.score, 2)} <span class="muted small">(0–1; ab 0,33 verdächtig, ab 0,67 Fehldruck)</span></span>
        <span>Letztes Bild</span><span class="m">${p.p == null ? "–" : num(p.p, 2)} <span class="muted small">Summe der Funde · ${(v.detections || []).length} Funde${(v.ignored || []).length ? `, ${v.ignored.length} ignoriert` : ""}</span></span>
        <span>Dieser Druck</span><span>${v.printing ? `${p.frames} Bilder${learning ? ` · lernt noch ${v.safe_frames - p.frames}` : ""}` : "–"}</span>
        <span>Dienst</span><span>${v.error ? html`<span class="err-text">${v.error}</span>` : `${prov === "CUDA" ? "Grafikkarte" : prov || "bereit"}${v.ms ? ` · ${num(v.ms, 0)} ms pro Bild` : ""} · Modell ${v.health?.model?.loaded ? "geladen" : "entladen"}`}</span>
        <span>Jetzt gilt</span><span>${v.action_now === "pause" ? "bei Fehldruck pausieren" : "nur melden"}${v.quiet_now ? " (Ruhezeit)" : ""}</span>
      </div>
      <div class="row wrap">
        <button class="btn sm" onClick=${runTest}><${Icon} name="refresh" small />Jetzt prüfen</button>
        <button class="btn sm" onClick=${() => fileRef.current?.click()}><${Icon} name="plus" small />Bild testen</button>
        <input ref=${fileRef} type="file" accept="image/*" hidden onChange=${guard(async (e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setTest(await upload(f)); })} />
        ${v.printing && html`<button class="btn sm" onClick=${guard(async () => { await post("/api/vision/mute", { on: !v.muted }); toast(v.muted ? "KI überwacht wieder" : "Dieser Druck wird nicht überwacht", "ok"); reload(); })}>
          ${v.muted ? "Wieder überwachen" : "Diesen Druck nicht überwachen"}</button>`}
      </div>
      <div class="lbl">Verlauf dieses Drucks</div>
      <${Chart} history=${v.history} />
    </section>
    <section class="card pad col">
      <h2 class="h2">${test ? `Test: ${test.verdict}` : "Kamera mit Funden"}</h2>
      ${test
        ? html`<${Boxed} src=${test.src} size=${test.size} dets=${test.detections} ignored=${test.ignored} zones=${v.zones} level=${test.p >= 0.78 ? "fail" : "warn"} />
          <div class="small muted">Summe ${num(test.p, 2)} · ${test.detections.length} Funde${test.ignored.length ? `, ${test.ignored.length} in ignorierten Bereichen` : ""} · ${num(test.ms, 0)} ms. Ab 0,38 leicht, ab 0,78 deutlich auffällig – für einen Alarm muss der Wert im Druck über mehrere Bilder steigen.</div>
          <button class="btn sm" onClick=${() => setTest(null)}>Zurück zur Kamera</button>`
        : key_ ? html`<${Boxed} src=${cameraUrl(key_)} size=${v.size} dets=${v.detections} ignored=${v.ignored} zones=${v.zones} level=${v.level} />
          <div class="small muted">Rahmen aus dem letzten ausgewerteten Bild (alle ${num(v.settings?.interval_s, 0)} s im Druck). Blau: ignorierte Bereiche.</div>`
        : html`<div class="media-empty">Kamera nur auf gekoppelten Geräten</div>`}
    </section>
  </div>`;
}

// ------------------------------------------------------------ Einstellungen
const SENS = [["Niedrig", 0.7], ["Normal", 1.0], ["Hoch", 1.5]];

function Settings({ v, reload }) {
  const [s, setS] = useState(v.settings);
  useEffect(() => setS(v.settings), [JSON.stringify(v.settings)]);
  const ch = (patch) => setS({ ...s, ...patch });
  const q = s.quiet;
  const changed = JSON.stringify(s) !== JSON.stringify(v.settings);
  const save = guard(async () => {
    const diff = Object.fromEntries(Object.entries(s).filter(([k, val]) => k !== "zones" && JSON.stringify(val) !== JSON.stringify(v.settings[k])));
    await post("/api/vision/settings", diff);
    toast("KI-Einstellungen gespeichert", "ok");
    reload();
  });
  const seg = (opts, cur, set) => html`<div class="seg">${opts.map(([l, val]) => html`<button class=${cls("seg-btn", cur === val && "on")} onClick=${() => set(val)}>${l}</button>`)}</div>`;
  return html`<section class="card pad col ai-settings">
    <${Toggle} label="KI-Überwachung" hint=${v.configured ? "Bilder im Druck an den KI-Dienst schicken" : "VISION_URL ist nicht gesetzt – erst den Dienst kobra-vision einrichten"} value=${s.enabled} disabled=${!v.configured} onChange=${(x) => ch({ enabled: x })} />
    <div class="lbl">Empfindlichkeit</div>
    <div class="row wrap">${seg(SENS, SENS.find(([, x]) => x === s.sensitivity)?.[1] ?? null, (x) => ch({ sensitivity: x }))}
      <input type="range" min="0.3" max="3" step="0.1" value=${s.sensitivity} onInput=${(e) => ch({ sensitivity: Number(e.target.value) })} aria-label="Empfindlichkeit fein" />
      <span class="m">× ${num(s.sensitivity, 1)}</span></div>
    <div class="small muted">Multipliziert den Wert. Höher meldet früher (mehr Fehlalarme), niedriger später.</div>
    <div class="lbl">Bei Fehldruck</div>
    ${seg([["Nur melden", "warn"], ["Druck pausieren", "pause"]], s.action, (x) => ch({ action: x }))}
    <${Toggle} label="Nach einer KI-Pause die Düse ausschalten" hint="Damit nichts verkokelt. Noch ungetestet am Kobra: beim Weiterdrucken die Düsentemperatur prüfen." value=${s.heater_off} onChange=${(x) => ch({ heater_off: x })} />
    <div class="lbl">Alarm aufs Handy</div>
    ${seg([["Schon bei „verdächtig“", "warn"], ["Erst bei „Fehldruck“", "fail"]], s.notify, (x) => ch({ notify: x }))}
    <div class="lbl">Ruhezeiten</div>
    <${Toggle} label="Ruhezeiten" hint="Z. B. nachts anders reagieren" value=${q.enabled} onChange=${(x) => ch({ quiet: { ...q, enabled: x } })} />
    ${q.enabled && html`<div class="row wrap">
      <label class="row small">von <input type="time" value=${q.start} onInput=${(e) => ch({ quiet: { ...q, start: e.target.value } })} /></label>
      <label class="row small">bis <input type="time" value=${q.end} onInput=${(e) => ch({ quiet: { ...q, end: e.target.value } })} /></label>
      ${seg([["Nur Fehldruck melden", "fail_only"], ["Bei Fehldruck pausieren", "pause"]], q.mode, (x) => ch({ quiet: { ...q, mode: x } }))}</div>`}
    <div class="lbl">Zeiten</div>
    <div class="row wrap ai-nums">
      <label>Bild alle <input type="number" min="2" max="60" value=${s.interval_s} onInput=${(e) => ch({ interval_s: Number(e.target.value) })} /> s</label>
      <label>Lernzeit am Druckanfang <input type="number" min="0" max="15" value=${Math.round(s.safe_s / 60)} onInput=${(e) => ch({ safe_s: Number(e.target.value) * 60 })} /> min</label>
    </div>
    <div class="small muted">In der Lernzeit meldet die KI nie (erste Schicht, Spülen, Abstreifen). Die Bewertung ist auf ~10 s je Bild abgestimmt.</div>
    <div class="lbl">Bildersammlung</div>
    <div class="row wrap ai-nums">
      <label>höchstens <input type="number" min="0" max="100" step="0.5" value=${s.dataset_gb} onInput=${(e) => ch({ dataset_gb: Number(e.target.value) })} /> GB</label>
      <label>ein Bild alle <input type="number" min="10" max="600" value=${s.save_every_s} onInput=${(e) => ch({ save_every_s: Number(e.target.value) })} /> s</label>
    </div>
    <div class="small muted">Dazu jedes verdächtige Bild und jeder Alarm. 0 GB = nichts sammeln. Bei weniger Platz werden die ältesten Drucke gelöscht.</div>
    <div class="row"><span class="grow"></span>
      ${changed && html`<button class="btn sm" onClick=${() => setS(v.settings)}>Verwerfen</button>`}
      <button class="btn sm acc" disabled=${!changed} onClick=${save}>Speichern</button></div>
  </section>`;
}

// ------------------------------------------------------------ Bereiche
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
      <h2 class="h2">Ignorierte Bereiche</h2>
      <div class="small muted">Rechteck ins Bild ziehen. Funde, deren Mitte darin liegt, zählen nicht – z. B. Spülrutsche, Reinigungsbürste, Spiegelungen. Höchstens 10.</div>
      ${key_ ? html`<${Boxed} src=${src} size=${v.size} zones=${all} onPointer=${ptr} />` : html`<div class="media-empty">Kamera nur auf gekoppelten Geräten</div>`}
      <div class="row"><button class="btn sm" onClick=${() => setSrc(cameraUrl(key_, "snapshot.jpg") + `&t=${Date.now()}`)}><${Icon} name="refresh" small />Neues Bild</button><span class="grow"></span>
        ${changed && html`<button class="btn sm" onClick=${() => setZones(v.settings.zones)}>Verwerfen</button>`}
        <button class="btn sm acc" disabled=${!changed} onClick=${guard(async () => { await post("/api/vision/settings", { zones }); toast("Bereiche gespeichert", "ok"); reload(); })}>Speichern</button></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">${zones.length} Bereich${zones.length === 1 ? "" : "e"}</h2>
      ${zones.length === 0 && html`<div class="small muted">Noch keine – die KI wertet das ganze Bild aus.</div>`}
      ${zones.map((z, i) => html`<div class="row small"><span class="m grow">#${i + 1} · links ${Math.round(z.x * 100)} % · oben ${Math.round(z.y * 100)} % · ${Math.round(z.w * 100)} × ${Math.round(z.h * 100)} %</span>
        <button class="btn sm" onClick=${() => setZones(zones.filter((_, k) => k !== i))}><${Icon} name="trash" small />Entfernen</button></div>`)}
    </section>
  </div>`;
}

// ------------------------------------------------------------ Gedaechtnis
function Memory({ v, key_, reload }) {
  const p = v.prediction || {};
  const verdict = guard(async (id, x) => { await post("/api/vision/feedback", { id, verdict: x }); toast("Bewertung gespeichert", "ok"); reload(); });
  return html`<div class="col" style="gap:16px">
    <section class="card pad col">
      <h2 class="h2">Was die KI weiß</h2>
      <div class="small muted" style="max-width:70ch">Das Modell (Obico, auf echten Fehldrucken trainiert) lernt hier nicht von selbst dazu. Was bei dir entsteht:
        die <b>Grundlinie</b> – wie viel „Rauschen“ deine Kamera normal zeigt – und die gesammelten, von dir gekennzeichneten <b>Bilder</b> für ein späteres eigenes Modell.</div>
      <div class="kv ai-kv">
        <span>Grundlinie</span><span class="m">${num(p.long, 3)} <span class="muted small">mittlere Summe der Funde je Bild</span></span>
        <span>Gesehene Bilder</span><span class="m">${p.lifetime ?? 0} <span class="muted small">(gilt ab ~7200 voll)</span></span>
        <span>Schwellen</span><span class="small">verdächtig ab ${v.thresholds?.low} über der Grundlinie (oder deutlich über dem Druck selbst), sicher ab ${v.thresholds?.high}; Fehldruck × ${v.thresholds?.escalate}</span>
        <span>Ignorierte Bereiche</span><span>${v.settings.zones.length}</span>
      </div>
      <div class="row"><${Confirm} label="Grundlinie zurücksetzen" sure="Wirklich zurücksetzen?" onYes=${async () => { await post("/api/vision/baseline/reset"); toast("Grundlinie zurückgesetzt", "ok"); reload(); }} />
        <span class="small muted">z. B. nach einem Kamera-Umbau</span></div>
    </section>
    <section class="card pad col">
      <h2 class="h2">Ereignisse</h2>
      ${!(v.events || []).length && html`<div class="small muted">Noch keine Meldung der KI.</div>`}
      <div class="ai-events">${(v.events || []).map((e) => html`<div class="ai-event">
        ${key_ && e.frame ? html`<${Boxed} src=${abs(`/api/vision/event/${e.id}.jpg?key=${encodeURIComponent(key_)}`)} size=${e.size} dets=${e.detections} level=${e.level} />` : html`<div class="media-empty">kein Bild</div>`}
        <div class="col" style="gap:4px">
          <div class="row"><span class=${cls("chip", e.level === "fail" ? "bad" : "warn")}>${e.level === "fail" ? "Fehldruck" : "verdächtig"}</span>
            <span class="small muted">${ago(e.at)} · Wert ${num(e.score, 2)}${e.paused ? " · pausiert" : ""}</span></div>
          <div class="small ell">${e.file || "–"}</div>
          <div class="row wrap">
            <button class=${cls("btn sm", e.verdict === "false_alarm" && "acc")} onClick=${() => verdict(e.id, "false_alarm")}>Fehlalarm</button>
            <button class=${cls("btn sm", e.verdict === "confirmed" && "acc")} onClick=${() => verdict(e.id, "confirmed")}>Stimmt</button>
            ${e.verdict && html`<button class="btn sm" onClick=${() => verdict(e.id, null)}>zurücknehmen</button>`}</div>
        </div></div>`)}</div>
    </section>
  </div>`;
}

// ------------------------------------------------------------ Bilder
const FILTERS = [["all", "Alle"], ["event", "Alarme"], ["suspect", "Verdächtig"], ["startend", "Start/Ende"], ["labelled", "Gekennzeichnet"], ["open", "Ohne Kennzeichen"]];

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
  if (!list) return html`<div class="muted">lädt …</div>`;
  const st = list.stats;
  const img = (j, f) => abs(`/api/vision/jobs/${encodeURIComponent(j)}/${encodeURIComponent(f)}?key=${encodeURIComponent(key_ || "")}`);
  const zip = (j) => abs(`/api/vision/export.zip?key=${encodeURIComponent(key_ || "")}${j ? `&job=${encodeURIComponent(j)}` : ""}`);
  if (!job) {
    return html`<section class="card pad col">
      <div class="row wrap"><h2 class="h2 grow">Bildersammlung</h2>
        <span class="small muted">${st.jobs} Drucke · ${st.frames} Bilder · ${st.labelled} gekennzeichnet · ${num(st.mb / 1024, 2)} von ${num(st.limit_gb, 1)} GB</span>
        ${key_ && st.frames > 0 && html`<a class="btn sm" href=${zip()} download><${Icon} name="download" small />Alles als ZIP</a>`}</div>
      <div class="ai-bar"><span style=${{ width: `${Math.min(100, (st.mb / 1024 / Math.max(st.limit_gb, 0.001)) * 100)}%` }}></span></div>
      ${!list.jobs.length && html`<div class="small muted">Noch keine Bilder – die Sammlung beginnt mit dem nächsten Druck.</div>`}
      <div class="ai-jobs">${list.jobs.map((j) => html`<div class="ai-job">
        <button class="ai-job-main" onClick=${() => { setFilter("all"); setJob(j.job); }}>
          ${key_ && j.cover ? html`<img src=${img(j.job, j.cover)} alt="" loading="lazy" />` : html`<div class="media-empty">–</div>`}
          <span class="col" style="gap:2px;min-width:0"><b class="ell">${j.job.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\d{2}_/, "$3.$2. $4:$5 · ")}</b>
            <span class="small muted">${j.frames} Bilder · ${j.events} Alarme · ${j.labelled} gekennzeichnet · ${num(j.mb, 1)} MB</span></span></button>
        <div class="row">${key_ && html`<a class="btn sm" href=${zip(j.job)} download>ZIP</a>`}
          <${Confirm} label="Löschen" sure="Druck löschen?" onYes=${async () => { await del(`/api/vision/jobs/${encodeURIComponent(j.job)}`); toast("Gelöscht", "ok"); loadList(); }} /></div>
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
    <div class="row wrap"><button class="btn sm" onClick=${() => { setJob(null); loadList(); }}><${Icon} name="back" small />Alle Drucke</button>
      <h2 class="h2 grow ell">${job}</h2><span class="small muted">${page.total} Bilder</span></div>
    <div class="row wrap">${FILTERS.map(([k, l]) => html`<button class=${cls("chip", filter === k && "on")} onClick=${() => setFilter(k)}>${l}</button>`)}</div>
    <div class="ai-frames">${show.map((f) => html`<div class="ai-frame">
      ${key_ ? html`<${Boxed} src=${img(job, f.frame)} size=${f.size} dets=${f.detections || []} ignored=${f.ignored || []} level=${f.level === "fail" ? "fail" : "warn"} />` : null}
      <div class="row small"><span class="m">${time(f.t)}</span><span class="muted">${KIND[f.kind] || f.kind}</span><span class="m grow" style="text-align:right">p ${num(f.p, 2)}</span></div>
      <div class="row wrap" style="gap:4px">${Object.entries(list.stats.labels).map(([k, l]) => html`<button class=${cls("chip", f.label === k && "on")} onClick=${() => label(f, k)}>${l}</button>`)}</div>
      <div class="row"><span class="grow small muted">${f.layer != null ? `Schicht ${f.layer}` : ""}</span>
        <${Confirm} label="Löschen" sure="Bild löschen?" onYes=${async () => { await del(`/api/vision/jobs/${encodeURIComponent(job)}/${encodeURIComponent(f.frame)}`); patch(f.frame, (fr, n) => fr.filter((x) => x.frame !== n)); setPage((pg) => ({ ...pg, total: pg.total - 1 })); }} /></div>
    </div>`)}</div>
    ${!show.length && html`<div class="small muted">Keine Bilder in dieser Auswahl.</div>`}
    ${show.length < page.total && html`<div class="row"><span class="small muted grow">${show.length} von ${page.total}</span>
      <button class="btn sm" onClick=${guard(() => loadJob(job, true))}>Weitere laden</button></div>`}
  </section>`;
}

// ------------------------------------------------------------ Seite
export function AiPage() {
  const [v, reload] = useVision();
  const [tab, setTab] = useState("live");
  const key_ = useKey();
  if (!v) return html`<div class="muted">lädt …</div>`;
  if (!v.settings) return html`<section class="card pad">KI nicht erreichbar: ${v.error}</section>`;
  const t = (k, l) => html`<button role="tab" aria-selected=${tab === k} class=${cls("seg-btn", tab === k && "on")} onClick=${() => setTab(k)}>${l}</button>`;
  return html`<div class="col" style="gap:16px">
    ${!v.configured && html`<section class="card pad small">Der KI-Dienst ist nicht eingerichtet: im Stack den Dienst <span class="m">kobra-vision</span> aufnehmen und bei der Bridge <span class="m">VISION_URL</span> setzen (Doku: vision.md).</section>`}
    <div class="seg" role="tablist" aria-label="KI">${t("live", "Live")}${t("settings", "Einstellungen")}${t("zones", "Bereiche")}${t("memory", "Gedächtnis")}${t("images", "Bilder")}</div>
    ${tab === "live" ? html`<${Live} v=${v} key_=${key_} reload=${reload} />`
      : tab === "settings" ? html`<${Settings} v=${v} reload=${reload} />`
      : tab === "zones" ? html`<${Zones} v=${v} key_=${key_} reload=${reload} />`
      : tab === "memory" ? html`<${Memory} v=${v} key_=${key_} reload=${reload} />`
      : html`<${Gallery} key_=${key_} />`}
  </div>`;
}
