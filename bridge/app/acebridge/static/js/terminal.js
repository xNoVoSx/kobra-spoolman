// Terminal (Konsole des Druckers ueber die Bridge) und Logs (Bridge, Drucker-Logs, Druck-Aufzeichnungen).
// Ausgabe kommt aus dem Puffer der Bridge - kein eigener Client am Drucker.

import { html, useEffect, useRef, useState } from "../vendor/preact-htm.module.js";
import { ApiError, get, post } from "./api.js";
import { Icon } from "./icons.js";
import { S, openDialog, set, toast } from "./store.js";
import { cls } from "./util.js";

const HIST_KEY = "kobra.consoleHistory";
const clock = (t) => new Date(t * 1000).toLocaleTimeString("de-DE");
function loadHist() { try { return JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); } catch { return []; } }
function saveHist(h) { try { localStorage.setItem(HIST_KEY, JSON.stringify(h.slice(-50))); } catch { /* egal */ } }

/** Zeilen ab einer id nachladen, solange die Seite sichtbar ist. */
function usePolled(path, every, deps = []) {
  const [lines, setLines] = useState([]);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let stop = false, after = 0, timer = null, buf = [];
    const sep = path.includes("?") ? "&" : "?";
    const tick = async () => {
      if (!document.hidden) {
        try {
          const r = await get(`${path}${sep}after=${after}`);
          if (r.lines.length) {
            after = r.lines[r.lines.length - 1].id;
            buf = buf.concat(r.lines).slice(-2000);
            if (!stop) setLines(buf);
          }
          if (!stop) setErr(null);
        } catch (e) { if (!stop) setErr(e.message); }
      }
      if (!stop) timer = setTimeout(tick, every);
    };
    setLines([]);
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, deps);
  return [lines, err];
}

/** Ausgabe, die unten bleibt - ausser man hat hochgescrollt. */
function useStick(dep) {
  const ref = useRef(null);
  const stick = useRef(true);
  const onScroll = () => { const e = ref.current; stick.current = e.scrollHeight - e.scrollTop - e.clientHeight < 40; };
  useEffect(() => { const e = ref.current; if (e && stick.current) e.scrollTop = e.scrollHeight; }, [dep]);
  return [ref, onScroll];
}

// ------------------------------------------------------------ Terminal
export function TerminalPage() {
  const [lines, err] = usePolled("/api/console", 1000);
  const [ref, onScroll] = useStick(lines.length);
  const [cmd, setCmd] = useState("");
  const [help, setHelp] = useState({});
  const [hist, setHist] = useState(loadHist());
  const [pos, setPos] = useState(-1);
  const [busy, setBusy] = useState(false);
  useEffect(() => { get("/api/console/commands").then((r) => setHelp(r.commands || {})).catch(() => {}); }, []);

  const word = cmd.trim().split(/\s+/)[0]?.toUpperCase() || "";
  const sugg = word && !cmd.includes(" ") ? Object.keys(help).filter((k) => k.startsWith(word) && k !== word).slice(0, 8) : [];

  const send = async (script, confirm = false) => {
    setBusy(true);
    try {
      await post("/api/console", { script, confirm });
      const h = [...hist.filter((x) => x !== script), script];
      setHist(h); saveHist(h); setPos(-1); setCmd("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        openDialog("confirm", { title: "Befehl bestätigen", text: e.message, ok: "Trotzdem senden", danger: true,
          action: () => send(script, true) });
      } else toast(e.message, "bad");
    } finally { setBusy(false); }
  };
  const onKey = (e) => {
    if (e.key === "Enter" && cmd.trim()) { e.preventDefault(); send(cmd.trim()); }
    else if (e.key === "Tab" && sugg.length) { e.preventDefault(); setCmd(sugg[0] + " "); }
    else if (e.key === "ArrowUp" && hist.length) {
      e.preventDefault(); const p = pos < 0 ? hist.length - 1 : Math.max(0, pos - 1); setPos(p); setCmd(hist[p]);
    } else if (e.key === "ArrowDown" && pos >= 0) {
      e.preventDefault(); const p = pos + 1; if (p >= hist.length) { setPos(-1); setCmd(""); } else { setPos(p); setCmd(hist[p]); }
    }
  };

  return html`<div class="term-page">
    <section class="card term">
      <div class="term-out m" ref=${ref} onScroll=${onScroll} aria-live="polite">
        ${!lines.length && html`<div class="muted">${err || "Noch keine Ausgabe."}</div>`}
        ${lines.map((l) => html`<div class=${cls("tl", l.kind)}><span class="t">${clock(l.time)}</span>
          ${l.kind === "command" ? html`<span class="src">${l.source || ""}</span><span class="txt">› ${l.text}</span>`
            : html`<span class="src"></span><span class="txt">${l.text}</span>`}</div>`)}
      </div>
      ${S.me ? html`
      <div class="term-in">
        ${sugg.length > 0 && html`<div class="sugg">${sugg.map((k) => html`<button onClick=${() => setCmd(k + " ")}><b class="m">${k}</b> <span class="muted small">${help[k]}</span></button>`)}</div>`}
        <span class="m prompt">›</span>
        <input class="m" aria-label="G-Code-Befehl" placeholder="G-Code oder Makro, z. B. M115 – Tab ergänzt, ↑ ↓ Verlauf"
               value=${cmd} onInput=${(e) => { setCmd(e.target.value); setPos(-1); }} onKeyDown=${onKey} disabled=${busy} autocomplete="off" spellcheck="false" />
        <button class="btn acc" disabled=${busy || !cmd.trim()} onClick=${() => send(cmd.trim())}>Senden</button>
      </div>` : html`<div class="term-in muted">Senden nur auf gekoppelten Geräten. <a href="#" onClick=${(e) => { e.preventDefault(); set({ pairing: true }); }}>Koppeln</a></div>`}
    </section>
    <div class="small muted">Antworten des Druckers und alles, was über die Bridge gesendet wurde (mit Absender). Befehle aus Mainsail erscheinen nur mit ihren Antworten.
      Riskantes (Not-Aus, SAVE_CONFIG, Neustart, Düse über 260 °C, Bewegungen im Druck) fragt vorher nach.</div>
  </div>`;
}

// ------------------------------------------------------------ Logs
const LEVELS = [["DEBUG", "Alle"], ["INFO", "Info"], ["WARNING", "Warnungen"], ["ERROR", "Fehler"]];

function BridgeLog() {
  const [level, setLevel] = useState("INFO");
  const [q, setQ] = useState("");
  const [lines, err] = usePolled(`/api/logs?level=${level}`, 2000, [level]);
  const shown = q ? lines.filter((l) => `${l.name} ${l.text}`.toLowerCase().includes(q.toLowerCase())) : lines;
  const [ref, onScroll] = useStick(shown.length);
  return html`<section class="card term">
    <div class="listbar">
      ${LEVELS.map(([k, l]) => html`<button class=${cls("chip", level === k && "on")} onClick=${() => setLevel(k)}>${l}</button>`)}
      <span class="grow"></span>
      <label class="search sm"><${Icon} name="search" small /><input placeholder="filtern" value=${q} onInput=${(e) => setQ(e.target.value)} /></label>
      <a class="btn sm" href="api/logs.txt" download><${Icon} name="download" small />Download</a>
    </div>
    <div class="term-out m" ref=${ref} onScroll=${onScroll}>
      ${!shown.length && html`<div class="muted">${err || "Keine Zeilen."}</div>`}
      ${shown.map((l) => html`<div class=${cls("tl", "lv-" + l.level.toLowerCase())}><span class="t">${clock(l.time)}</span><span class="src">${l.name}</span><span class="txt">${l.text}</span></div>`)}
    </div>
  </section>`;
}

const size = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);

function PrinterLogs() {
  const [files, setFiles] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);
  const [kb, setKb] = useState(200);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [ref] = useStick(text);
  useEffect(() => { get("/api/logs/printer").then((r) => setFiles(r.files)).catch((e) => setErr(e.message)); }, []);
  const load = async (name, k = kb) => {
    setOpen(name); setKb(k); setLoading(true);
    try {
      const r = await fetch(`/api/logs/printer/${encodeURIComponent(name)}?kb=${k}`, { cache: "no-store" });
      setText(r.ok ? await r.text() : (await r.json().catch(() => ({}))).error || `Fehler ${r.status}`);
    } catch { setText("Bridge nicht erreichbar"); }
    setLoading(false);
  };
  return html`<section class="card term">
    <div class="listbar">
      ${files == null && !err && html`<span class="muted small">lade …</span>`}
      ${err && html`<span class="small" style="color:var(--danger-text)">${err}</span>`}
      ${(files || []).map((f) => html`<button class=${cls("chip", open === f.name && "on")} onClick=${() => load(f.name, 200)}>${f.name} <span class="muted">${size(f.size)}</span></button>`)}
      <span class="grow"></span>
      ${open && html`<button class="btn sm" onClick=${() => load(open, kb)}><${Icon} name="refresh" small />Neu laden</button>
        ${kb < 1024 && html`<button class="btn sm" onClick=${() => load(open, 1024)}>Mehr (1 MB)</button>`}`}
    </div>
    <pre class="term-out m log-pre" ref=${ref}>${loading ? "lade …" : open ? text : "Datei wählen – gezeigt wird das Ende (die Dateien sind mehrere MB groß)."}</pre>
  </section>`;
}

function Recordings() {
  const [files, setFiles] = useState(null);
  useEffect(() => { get("/api/telemetry").then((r) => setFiles(r.files || r)).catch((e) => toast(e.message, "bad")); }, []);
  return html`<section class="card">
    ${files == null && html`<div class="empty-state">lade …</div>`}
    ${files && !files.length && html`<div class="empty-state">Noch keine Aufzeichnungen.</div>`}
    ${(files || []).map((f, i) => html`<div class="row" style=${{ padding: "12px 18px", borderTop: i ? "1px solid var(--line)" : "0" }}>
      <span class="m small grow ell">${f.name}</span>${f.recording && html`<span class="chip ok">läuft</span>`}
      <span class="small muted">${size(f.size)}</span>
      <a class="btn sm" href=${"api/telemetry/" + encodeURIComponent(f.name)} download><${Icon} name="download" small /></a></div>`)}
  </section>`;
}

export function LogsPage() {
  const [tab, setTab] = useState("bridge");
  const t = (k, l) => html`<button role="tab" aria-selected=${tab === k} class=${cls("seg-btn", tab === k && "on")} onClick=${() => setTab(k)}>${l}</button>`;
  return html`<div class="term-page">
    <div class="seg" role="tablist" aria-label="Logs">${t("bridge", "Bridge")}${t("printer", "Drucker")}${t("rec", "Druck-Aufzeichnungen")}</div>
    ${tab === "bridge" ? html`<${BridgeLog} />` : tab === "printer" ? html`<${PrinterLogs} />` : html`<${Recordings} />`}
  </div>`;
}
