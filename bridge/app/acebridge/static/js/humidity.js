// Feuchte: Verlauf der ACE mit Trocknungen und Drucken, Liste der Trocknungen, Feuchte-Schaetzung je Spule.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { S, guard, toast } from "./store.js";
import { cls, num } from "./util.js";

const SOURCE = { auto: "Automatik", hand: "von Hand", plan: "geplant", spule: "Spule eingelegt", drucker: "Display/Mainsail", unbekannt: "schon vorher" };
const RANGES = [[6, "6 h"], [24, "24 h"], [168, "7 Tage"], [720, "30 Tage"]];
const fmtTime = (t, long) => new Date(t * 1000).toLocaleString("de-DE", long ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
const dur = (min) => (min >= 90 ? `${num(min / 60, 1)} h` : `${Math.round(min)} min`);

function useHumidity(hours) {
  const [d, setD] = useState(null);
  useEffect(() => {
    let stop = false, timer = null;
    const tick = async () => {
      try { const r = await get(`/api/humidity?hours=${hours}`); if (!stop) setD(r); } catch (e) { if (!stop) setD((o) => o || { error: e.message }); }
      if (!stop) timer = setTimeout(tick, 60000);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [hours]);
  return d;
}

function Chart({ d, hours }) {
  const ref = useRef(null);
  const [hover, setHover] = useState(null);
  const W = 1000, H = 260, L = 44, R = 46, T = 22, B = 26;
  const now = Date.now() / 1000, t0 = now - hours * 3600;
  const pts = d.points || [];
  const hMax = Math.max(40, ...pts.map((p) => (p[1] ?? 0) + 5));
  const x = (t) => L + ((t - t0) / (now - t0)) * (W - L - R);
  const yh = (h) => T + (1 - h / hMax) * (H - T - B);
  const yt = (c) => T + (1 - (c - 15) / (75 - 15)) * (H - T - B);
  const line = (k, y) => pts.filter((p) => p[k] != null).map((p) => `${x(p[0]).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ");
  // Soll als Stufen, nur waehrend getrocknet wird
  const setp = []; let run = [];
  pts.forEach((p) => { if (p[4] && p[3]) run.push(`${x(p[0]).toFixed(1)},${yt(p[3]).toFixed(1)}`); else if (run.length) { setp.push(run.join(" ")); run = []; } });
  if (run.length) setp.push(run.join(" "));
  const auto = d.automation || {};
  const ticks = []; const span = hours <= 24 ? 3600 * (hours <= 6 ? 1 : 3) : 86400 * (hours <= 168 ? 1 : 5);
  for (let t = Math.ceil(t0 / span) * span; t < now; t += span) ticks.push(t);
  const move = (e) => {
    const r = ref.current.getBoundingClientRect(), tx = t0 + ((e.clientX - r.left) / r.width * W - L) / (W - L - R) * (now - t0);
    let best = null; for (const p of pts) if (!best || Math.abs(p[0] - tx) < Math.abs(best[0] - tx)) best = p;
    setHover(best);
  };
  return html`<div class="hum-chart">
    <svg ref=${ref} viewBox=${`0 0 ${W} ${H}`} preserveAspectRatio="none" onPointerMove=${move} onPointerLeave=${() => setHover(null)} role="img" aria-label="Feuchte-Verlauf der ACE">
      ${(d.prints || []).map((p) => html`<rect x=${x(Math.max(p.start, t0))} y=${T} width=${Math.max(1, x(Math.min(p.end, now)) - x(Math.max(p.start, t0)))} height=${H - T - B} fill="var(--line)" opacity=".45"><title>Druck ${p.file}</title></rect>`)}
      ${(d.sessions || []).map((s) => { const e = s.end || now, a = x(Math.max(s.start, t0)), w = Math.max(2, x(Math.min(e, now)) - a);
        return html`<g><rect x=${a} y=${T} width=${w} height=${H - T - B} fill="var(--accent-soft)" />
          <text x=${a > W - R - 170 ? W - R : a + 4} y=${T - 6} font-size="11" text-anchor=${a > W - R - 170 ? "end" : "start"} fill="var(--accent-text)">${s.temps?.[0]?.[1] ?? "?"} °C · ${SOURCE[s.source] || s.source}</text>
          <title>${s.reason}${s.end_reason ? ` → ${s.end_reason}` : ""}</title></g>`; })}
      ${[0, 20, 40, 60, 80, 100].filter((v) => v <= hMax).map((v) => html`<g><line x1=${L} x2=${W - R} y1=${yh(v)} y2=${yh(v)} stroke="var(--line)" /><text x=${L - 6} y=${yh(v) + 4} font-size="11" text-anchor="end" fill="var(--muted)">${v} %</text></g>`)}
      ${[20, 40, 60].map((c) => html`<text x=${W - R + 6} y=${yt(c) + 4} font-size="11" fill="var(--faint)">${c} °C</text>`)}
      ${auto.start_above != null && html`<g><line x1=${L} x2=${W - R} y1=${yh(auto.start_above)} y2=${yh(auto.start_above)} stroke="var(--accent)" stroke-dasharray="6 5" opacity=${auto.enabled ? 0.9 : 0.35} />
        <text x=${W - R - 4} y=${yh(auto.start_above) - 4} font-size="11" text-anchor="end" fill="var(--accent-text)">Start ab ${auto.start_above} %${auto.enabled ? "" : " (Automatik aus)"}</text></g>`}
      ${auto.stop_below != null && html`<g><line x1=${L} x2=${W - R} y1=${yh(auto.stop_below)} y2=${yh(auto.stop_below)} stroke="var(--ok)" stroke-dasharray="6 5" opacity=${auto.enabled ? 0.9 : 0.35} />
        <text x=${W - R - 4} y=${yh(auto.stop_below) - 4} font-size="11" text-anchor="end" fill="var(--ok-text)">Stopp unter ${auto.stop_below} %</text></g>`}
      <polyline points=${line(2, yt)} fill="none" stroke="var(--muted)" stroke-width="1.2" vector-effect="non-scaling-stroke" />
      ${setp.map((s) => html`<polyline points=${s} fill="none" stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="4 3" vector-effect="non-scaling-stroke" />`)}
      <polyline points=${line(1, yh)} fill="none" stroke="var(--accent)" stroke-width="2.2" vector-effect="non-scaling-stroke" />
      ${ticks.map((t) => html`<text x=${x(t)} y=${H - 8} font-size="11" text-anchor="middle" fill="var(--muted)">${hours <= 24 ? fmtTime(t) : new Date(t * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })}</text>`)}
      ${hover && html`<line x1=${x(hover[0])} x2=${x(hover[0])} y1=${T} y2=${H - B} stroke="var(--text)" opacity=".4" />`}
    </svg>
    ${hover && html`<div class="hum-tip m">${fmtTime(hover[0], hours > 24)} · Feuchte ${hover[1] ?? "–"} % · ACE ${hover[2] ?? "–"} °C${hover[4] ? ` · Soll ${hover[3]} °C` : ""}</div>`}
    <div class="hum-legend small"><span><i style="background:var(--accent)"></i>Feuchte</span><span><i style="background:var(--muted)"></i>ACE-Temperatur</span>
      <span><i style="background:var(--danger)"></i>Soll beim Trocknen</span><span><i class="box" style="background:var(--accent-soft)"></i>Trocknung</span><span><i class="box" style="background:var(--line)"></i>Druck</span></div>
  </div>`;
}

/** Karte auf der ACE-Seite: Verlauf und Trocknungen. */
export function HumidityCard() {
  const [hours, setHours] = useState(24);
  const d = useHumidity(hours);
  const sessions = d?.sessions || [];
  return html`<section class="card pad col">
    <div class="row wrap"><h2 class="h2 grow">Feuchte-Verlauf</h2>
      <div class="seg">${RANGES.map(([h, l]) => html`<button class=${cls("seg-btn", hours === h && "on")} onClick=${() => setHours(h)}>${l}</button>`)}</div></div>
    ${!d ? html`<div class="muted">lädt …</div>` : d.error ? html`<div class="err-text">${d.error}</div>`
      : !(d.points || []).length ? html`<div class="small muted">Noch kein Verlauf – die Bridge zeichnet ab jetzt jede Minute auf.</div>`
      : html`<${Chart} d=${d} hours=${hours} />`}
    <div class="lbl">Trocknungen</div>
    ${!sessions.length && html`<div class="small muted">Keine Trocknung in diesem Zeitraum.</div>`}
    <div class="hum-sessions">${sessions.map((s) => html`<div class="hum-session">
      <div class="row wrap" style="gap:8px"><b class="m">${fmtTime(s.start, true)}</b>
        <span class=${cls("chip", s.running && "warn")}>${s.running ? "läuft" : dur(s.minutes)}</span>
        <span class="chip">${(s.temps || []).map((t) => t[1]).join(" → ")} °C</span>
        <span class="small muted">${SOURCE[s.source] || s.source}</span>
        <span class="grow"></span>
        <span class="m small">${s.humidity_start ?? "?"} %${s.running ? "" : ` → ${s.humidity_end ?? "?"} %`}</span></div>
      <div class="small">${s.reason}${s.end_reason ? html` <span class="muted">→ ${s.end_reason}</span>` : ""}</div>
      ${(s.spools || []).length > 0 && html`<div class="small faint">${s.spools.map((p) => `Slot ${p.slot}: ${p.name}${p.score != null ? ` (${p.score} %)` : ""}`).join(" · ")}</div>`}
    </div>`)}</div>
  </section>`;
}

/** Feuchte einer Spule: Schaetzung, Verlauf, "ausserhalb getrocknet". */
export function SpoolMoisture({ id }) {
  const [m, setM] = useState(null);
  const [form, setForm] = useState(null);
  const load = () => get(`/api/spool/${id}/moisture`).then(setM).catch((e) => toast(e.message, "bad"));
  useEffect(() => { load(); }, [id]);
  if (!m) return html`<div class="muted">lädt …</div>`;
  const p = m.params || {};
  const word = { unknown: "unbekannt – noch kein Verlauf", ok: "trocken", soon: "bald trocknen", wet: "trocknen empfohlen" }[m.state];
  const color = { unknown: "var(--muted)", ok: "var(--ok)", soon: "var(--accent)", wet: "var(--danger)" }[m.state];
  const KIND = { in: "in die ACE", out: "aus der ACE", dried: "getrocknet" };
  return html`<div class="col" style="gap:14px">
    <div class="col" style="gap:6px">
      <div class="row"><b class="grow" style=${{ color }}>${word}</b><span class="m">${m.score == null ? "–" : `${m.score} %`}</span></div>
      <div class="ai-bar"><span style=${{ width: `${Math.min(100, (m.score ?? 0) / 2)}%`, background: color }}></span></div>
      <div class="small muted">100 % = trocknen empfohlen. Geschätzt aus Lagerort, Luftfeuchte und Trocknungen – messen lässt sich die Feuchte in der Spule nicht.</div>
    </div>
    <div class="kv">
      <span>Wo</span><span>${m.where || "–"}</span>
      ${m.out_since && html`<span>Außerhalb der ACE seit</span><span>${fmtTime(m.out_since, true)}</span>`}
      <span>Zuletzt getrocknet</span><span>${m.last_dried ? `${fmtTime(m.last_dried.at, true)}${m.last_dried.temp ? ` · ${m.last_dried.temp} °C` : ""}${m.last_dried.minutes ? ` · ${dur(m.last_dried.minutes)}` : ""}` : "–"}</span>
      <span>Material</span><span>${p.material || "–"} · offen bis trocknen ${num(p.open_days, 1)} Tage (bei 50 % rF) · trocknen ${num(p.dry_hours, 1)} h bei ${p.dry_temp} °C</span>
      ${m.needs_drying && html`<span>Jetzt nötig</span><span>~${num(m.hours_needed, 1)} h bei ${p.dry_temp} °C</span>`}
    </div>
    ${S.me && (form ? html`<div class="row wrap">
        <label class="row small">Temperatur <input class="set-num" value=${form.temp} onInput=${(e) => setForm({ ...form, temp: e.target.value })} /> °C</label>
        <label class="row small">Dauer <input class="set-num" value=${form.hours} onInput=${(e) => setForm({ ...form, hours: e.target.value })} /> h</label>
        <button class="btn sm acc" onClick=${guard(async () => { await post(`/api/spool/${id}/dried`, { temp: Number(form.temp), minutes: Number(String(form.hours).replace(",", ".")) * 60 }); setForm(null); toast("Als getrocknet gemerkt", "ok"); load(); })}>Speichern</button>
        <button class="btn sm" onClick=${() => setForm(null)}>Abbrechen</button></div>`
      : html`<div><button class="btn sm" onClick=${() => setForm({ temp: p.dry_temp, hours: p.dry_hours })}>Außerhalb getrocknet …</button>
        <span class="small muted"> eigener Trockner oder Ofen</span></div>`)}
    <div class="lbl">Verlauf</div>
    ${!(m.history || []).length && html`<div class="small muted">Noch nichts aufgezeichnet.</div>`}
    <div class="col" style="gap:4px">${(m.history || []).map((h) => html`<div class="row small">
      <span class="m" style="min-width:110px">${fmtTime(h.at, true)}</span><span class="grow">${KIND[h.kind] || h.kind}${h.slot ? ` (Slot ${h.slot})` : ""}${h.temp ? ` · ${h.temp} °C` : ""}${h.minutes ? ` · ${dur(h.minutes)}` : ""}${h.manual ? " · außerhalb" : ""}</span>
      <span class="m muted">${h.score == null ? "–" : `${h.score} %`}</span></div>`)}</div>
  </div>`;
}

/** Kleiner Hinweis fuer Listen und Slot-Karten. */
export function MoistureChip({ id }) {
  const m = S.st?.moisture?.[String(id)];
  if (!m || (m.state === "ok")) return null;
  const t = { unknown: ["neu", ""], soon: [`${m.score} %`, "warn"], wet: [`feucht ${m.score} %`, "bad"] }[m.state] || [m.state, ""];
  return html`<span class=${cls("chip", t[1])} title="Feuchte-Schätzung">${t[0]}</span>`;
}
