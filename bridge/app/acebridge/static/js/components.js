// Gemeinsame Bausteine: Karten fuer Drucker, Slots, Trockner, offene Posten, Drucke; Dialograhmen, Meldungen, Menue.

import { html, useEffect, useRef } from "../vendor/preact-htm.module.js";
import { Icon } from "./icons.js";
import { S, set, closeDialog, guard, openDialog, spoolById } from "./store.js";
import { JOB_STATE, cls, duration, fileName, grams, hex, minutes, num, printerLook, tint, title, when } from "./util.js";

export function Spool({ color, size = 56, empty }) {
  const c = hex(color);
  if (empty || !c) return html`<span class="spool empty" style=${{ width: size + "px", height: size + "px" }}></span>`;
  return html`<span class="spool" style=${{ width: size + "px", height: size + "px", background: c }}></span>`;
}
export function Swatch({ color, size = 20 }) {
  return html`<span class="swatch" style=${{ width: size + "px", height: size + "px", background: hex(color) || "var(--surface2)" }}></span>`;
}

export function Bar({ value, max, warnBelow = 200 }) {
  const pct = max ? Math.max(0, Math.min(100, (100 * value) / max)) : 0;
  const color = value != null && value < warnBelow ? "var(--danger)" : "var(--muted)";
  return html`<span class="bar"><i style=${{ width: pct + "%", background: color }}></i></span>`;
}

// ------------------------------------------------------------ Drucker
export function PrinterCard({ compact }) {
  const p = S.st?.printer;
  const look = printerLook(p);
  const running = p && (p.state === "printing" || p.state === "paused");
  const live = S.st?.usage?.live;
  const active = p?.active_slot ? S.st.slots.find((s) => s.slot === p.active_slot) : null;
  const ui = S.health?.links?.printer_ui;
  return html`
  <section class="card pad printer" style=${{ background: look.bg, borderColor: look.line }} aria-label="Drucker">
    <div class="row">
      <span class="dot" style=${{ background: look.dot }}></span>
      <span class="state" style=${{ color: look.fg }}>${look.label}</span>
      ${p?.file && html`<span class="m small muted ell grow">${fileName(p.file)}</span>`}
      ${!p?.file && html`<span class="grow"></span>`}
      ${p?.progress != null && html`<span class="m" style=${{ color: look.fg, fontSize: "19px" }}>${Math.round(p.progress * 100)} %</span>`}
    </div>
    ${running && html`<span class="bar" style=${{ background: look.line }}><i style=${{ width: (p.progress || 0) * 100 + "%", background: look.dot }}></i></span>`}
    ${running && html`
    <div class=${cls("row wrap", "small")} style=${{ gap: compact ? "16px" : "24px" }}>
      <span class="muted">Rest <b class="m" style="color:var(--text)">${duration(p.eta_s)}</b></span>
      <span class="muted">Läuft <b class="m" style="color:var(--text)">${duration(p.print_duration_s)}</b></span>
      ${active && html`<span class="muted row" style="gap:6px">Aktiv <${Swatch} color=${active.spool?.color} size=${12} /> <b style="color:var(--text)">Slot ${active.slot}</b></span>`}
      ${live && html`<span class="muted">bisher <b class="m" style="color:var(--text)">${grams(live.slots.reduce((a, s) => a + s.g, 0))}</b> · ${live.changes} Wechsel</span>`}
    </div>`}
    ${p?.message && html`<div class="small" style=${{ color: look.fg }}>${p.message}</div>`}
    ${p?.state === "offline" && html`<div class="small muted">Die Bridge erreicht den Drucker gerade nicht.</div>`}
    ${ui && html`<a class="small" href=${ui} target="_blank" rel="noopener" style=${{ color: look.fg }}>In Mainsail öffnen →</a>`}
  </section>`;
}

// ------------------------------------------------------------ Slots
export function SlotCard({ slot }) {
  const sp = slot.spool;
  const active = slot.ace?.active;
  const live = (S.st?.usage?.live?.slots || []).find((x) => x.slot === slot.slot);
  const tag = sp?.tag_nr ? `Tag ${sp.tag_nr}` : slot.ace?.tag_id ? `Tag ${slot.ace.tag_id}` : sp ? "ohne Tag" : null;
  const assign = guard(() => openDialog("assign", { slot: slot.slot }));
  const clear = guard(() => openDialog("confirm", {
    title: `Slot ${slot.slot} leeren?`, text: `${sp.display_name} kommt zurück ins Regal.`, ok: "Leeren",
    action: () => import("./actions.js").then((a) => a.assignSlot(slot.slot, null)),
  }));
  const open = () => sp && set({ sel: sp.spool_id });
  return html`
  <article class=${cls("card slot", active && "active")} aria-label=${"Slot " + slot.slot}>
    <div class="head" style=${{ background: sp ? tint(sp.color) : "var(--sunken)" }}>
      <span class="num">SLOT ${slot.slot}</span>
      <${Spool} color=${sp?.color} empty=${!sp} size=${84} />
    </div>
    <div class="body">
      <div class="row">
        ${sp ? html`<button class="name g ell" style="background:none;border:0;padding:0;cursor:pointer;text-align:left" onClick=${open}>${title(sp)}</button>`
             : html`<span class="name muted">Leer</span>`}
        ${active && html`<span class="chip acc" style="margin-left:auto">aktiv</span>`}
      </div>
      <div class="small muted ell">${sp ? `${sp.vendor} · #${sp.spool_id}` : slot.ace?.present ? `ACE meldet ${slot.ace.material || "Spule ohne Material"}` : "Spule einlegen und hier zuordnen"}</div>
      ${sp && html`<div class="row"><${Bar} value=${sp.remaining_weight} max=${sp.initial_weight || 1000} /><span class="m small" style="min-width:64px;text-align:right">${grams(sp.remaining_weight)}</span></div>`}
      <div class="row wrap" style="gap:6px">
        ${tag && html`<span class="chip">${tag}</span>`}
        ${sp?.nozzle_temp && html`<span class="chip">${sp.nozzle_temp} °C</span>`}
        ${live && html`<span class="chip ok">dieser Druck ${grams(live.g)}</span>`}
      </div>
      ${slot.hints.map((h) => html`<div class="hint">${h}</div>`)}
      <div class="actions">
        <button class="btn sm" onClick=${assign}>${sp ? "Spule wechseln" : "Spule zuordnen"}</button>
        ${sp && html`<button class="btn sm ghost" onClick=${clear}>Leeren</button>`}
      </div>
    </div>
  </article>`;
}

export function Slots() {
  const slots = S.st?.slots || [];
  return html`<div class="slots">${slots.map((s) => html`<${SlotCard} key=${s.slot} slot=${s} />`)}</div>`;
}

// ------------------------------------------------------------ Trockner
export function dryerLook(d) {
  if (!d?.present) return ["keine ACE erkannt", ""];
  if (d.drying) return [d.auto_run ? "trocknet · Automatik" : "trocknet", "warn"];
  if (d.paused_until) return ["Pause", ""];
  return [d.config?.enabled ? "aus · Automatik an" : "aus", ""];
}
export function DryerCard({ big }) {
  const d = S.st?.dryer;
  if (!d) return null;
  const [label, kind] = dryerLook(d);
  const req = d.required || {};
  const limited = (req.slots || []).filter((p) => (req.limited_by || []).includes(p.slot));
  const start = guard(() => openDialog("dryerStart"));
  const stop = guard(() => import("./actions.js").then((a) => a.dryerStop()));
  const rules = guard(() => openDialog("dryerRules"));
  return html`
  <section class="card pad col" aria-label="Trockner">
    <div class="row"><span style="color:var(--accent)"><${Icon} name="dryer" /></span><h2 class="h2">Trockner</h2><span class="grow"></span><span class=${cls("chip", kind)}>${label}</span></div>
    ${d.present && html`
    <div class="row wrap" style="gap:28px;align-items:flex-end">
      <div><div class="m" style=${{ fontSize: big ? "44px" : "32px", fontWeight: 600, lineHeight: 1 }}>${num(d.humidity, 0)}<span class="muted" style="font-size:.5em"> %</span></div><div class="small muted">Feuchte${d.config?.enabled ? ` · Ziel unter ${num(d.config.stop_below, 0)} %` : ""}</div></div>
      <div><div class="m" style=${{ fontSize: big ? "44px" : "32px", fontWeight: 600, lineHeight: 1 }}>${num(d.drying ? d.target_temp : d.temp, 0)}<span class="muted" style="font-size:.5em"> °C</span></div><div class="small muted">${d.drying ? "Soll" : "im ACE"}${limited.length ? ` · Grenze ${limited[0].name}` : ""}</div></div>
    </div>
    <div class="small muted">
      ${d.drying ? `Noch ${minutes(d.remaining_min)}. ` : ""}
      ${d.config?.enabled ? `Automatik startet ab ${num(d.config.start_above, 0)} %, stoppt unter ${num(d.config.stop_below, 0)} %, höchstens ${num(d.config.max_hours)} h.` : "Automatik ist aus."}
      ${req.temp != null ? ` Höchstens ${req.temp} °C für die eingelegten Spulen.` : ""}
    </div>
    ${d.last_event && html`<div class="small faint">Zuletzt: ${d.last_event.text} (${when(d.last_event.at)})</div>`}
    <div class="row wrap">
      ${d.drying ? html`<button class="btn sm" onClick=${stop}><${Icon} name="stop" small />Stoppen</button>`
                 : html`<button class="btn sm" onClick=${start}><${Icon} name="play" small />Trocknen</button>`}
      <button class="btn sm ghost" onClick=${rules}>Regeln</button>
    </div>`}
  </section>`;
}

// ------------------------------------------------------------ Offene Buchungen
const REASON = { retry: "Spoolman war nicht erreichbar", no_spool: "Slot ohne Spule", spool_missing: "Spule gibt es nicht mehr" };
export function OpenItemsCard() {
  const open = S.st?.usage?.open || [];
  return html`
  <section class="card pad col" aria-label="Offene Buchungen">
    <div class="row"><h2 class="h2">Offene Buchungen</h2><span class="grow"></span><span class=${cls("chip", open.length ? "bad" : "ok")}>${open.length}</span></div>
    ${!open.length && html`<div class="small muted">Alles in Spoolman gebucht.</div>`}
    ${open.map((it) => html`
      <div class="row" key=${it.id} style="align-items:flex-start">
        <div class="grow">
          <div class="small"><b>${it.slot > 0 ? `Slot ${it.slot}` : "ohne Slot"}</b> · ${num(it.mm, 0)} mm ≈ ${grams(it.g_est)}</div>
          <div class="small muted ell">${fileName(it.file)} · ${REASON[it.reason] || it.reason}${it.spool_id ? ` · Spule #${it.spool_id}` : ""}</div>
        </div>
        <button class="btn sm" onClick=${guard(() => openDialog("bookOpen", { item: it }))}>Buchen</button>
      </div>`)}
  </section>`;
}

// ------------------------------------------------------------ Orca
export function OrcaCard() {
  const h = S.health;
  return html`
  <section class="card pad col" aria-label="Verbindungen">
    <h2 class="h2">Verbindungen</h2>
    <div class="kv">
      <span>Drucker (Moonraker)</span><span>${h?.moonraker?.connected ? html`<span class="chip ok">verbunden</span>` : html`<span class="chip bad">getrennt</span>`}</span>
      <span>Spoolman ${h?.spoolman?.version || ""}</span><span>${h?.spoolman?.connected ? html`<span class="chip ok">verbunden</span>` : html`<span class="chip bad">getrennt</span>`}</span>
      <span>Spulen / Filamente</span><span class="m">${h ? `${h.spoolman.spools} / ${h.spoolman.filaments}` : "–"}</span>
      <span>Buchen</span><span>${h ? (h.booking ? "an" : "aus (Testlauf)") : "–"}</span>
    </div>
  </section>`;
}

// ------------------------------------------------------------ Drucke
export function JobCard({ job, live }) {
  const [label, kind] = live ? ["läuft", "ok"] : (JOB_STATE[job.state] || [job.state, ""]);
  const parts = live ? (job.slots || []).map((s) => ({ slot: s.slot, g: s.g }))
                     : (job.slots || []).filter((s) => s.slot > 0).map((s) => ({ slot: s.slot, g: s.g, spools: s.spools }));
  const colorFor = (p) => {
    const id = p.spools?.[0]?.id ?? S.st?.slots?.find((x) => x.slot === p.slot)?.spool?.spool_id;
    return spoolById(id)?.color;
  };
  const total = parts.reduce((a, p) => a + (p.g || 0), 0);
  return html`
  <article class="card job">
    <div class="row"><span class="file ell grow">${fileName(job.file)}</span><span class=${cls("chip", kind)}>${label}</span></div>
    <div class="small muted">${live ? `seit ${when(job.started)} · bisher ${grams(total)} · ${job.changes} Wechsel`
                                    : `${when(job.ended)} · ${grams(total)} · ${job.loads ?? "–"} Ladevorgänge`}</div>
    <div class="row wrap" style="gap:6px">
      ${parts.map((p) => html`<span class="chip" style="color:var(--text)" title=${"Slot " + p.slot}><${Swatch} color=${colorFor(p)} size=${10} />${grams(p.g)}</span>`)}
    </div>
    ${(job.warnings || []).map((w) => html`<div class="small" style="color:var(--accent-text)">${w}</div>`)}
  </article>`;
}

export function JobsList({ limit = 6, compact }) {
  const live = S.st?.usage?.live;
  const jobs = (S.jobs || []).slice(0, limit);
  return html`
  <div class="col" style="gap:12px">
    ${live && html`<${JobCard} job=${live} live />`}
    ${jobs.map((j) => html`<${JobCard} key=${j.job} job=${j} />`)}
    ${!live && !jobs.length && html`<div class="empty-state">Noch keine Drucke aufgezeichnet.</div>`}
    ${compact && html`<a href="#/drucke" class="small">Alle Drucke →</a>`}
  </div>`;
}

// ------------------------------------------------------------ Rahmen fuer Dialoge
export function Dialog({ title, children, footer, wide, onClose = closeDialog }) {
  const ref = useRef(null);
  useEffect(() => {
    const box = ref.current;
    (box?.querySelector(".dbody input, .dbody select, .dbody textarea") || box?.querySelector("footer .acc"))?.focus();
  }, []);
  return html`
  <div class="scrim" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class=${cls("dialog", wide && "wide")} role="dialog" aria-modal="true" aria-label=${title} ref=${ref}>
      <header><h2 class="h2 grow">${title}</h2><button class="btn icon ghost" aria-label="Schließen" onClick=${onClose}><${Icon} name="close" /></button></header>
      <div class="dbody">${children}</div>
      ${footer && html`<footer>${footer}</footer>`}
    </div>
  </div>`;
}

export function Toasts() {
  return html`<div class="toasts" role="status" aria-live="polite">${S.toasts.map((t) => html`<div key=${t.id} class=${cls("toast", t.kind)}>${t.text}</div>`)}</div>`;
}

export function ContextMenu() {
  const m = S.menu;
  useEffect(() => {
    if (!m) return;
    const close = () => set({ menu: null });
    window.addEventListener("click", close);
    window.addEventListener("blur", close);
    return () => { window.removeEventListener("click", close); window.removeEventListener("blur", close); };
  }, [m]);
  if (!m) return null;
  const x = Math.min(m.x, window.innerWidth - 240), y = Math.min(m.y, window.innerHeight - 40 * m.items.length - 20);
  return html`<div class="menu" role="menu" style=${{ left: x + "px", top: y + "px" }}>
    ${m.items.map((it) => it === "-" ? html`<hr />` : html`<button role="menuitem" disabled=${it.disabled} onClick=${() => { set({ menu: null }); it.run(); }}>${it.icon && html`<${Icon} name=${it.icon} small />`}${it.label}</button>`)}
  </div>`;
}

// ------------------------------------------------------------ Eingaben
export function Field({ label, orca, hint, error, changed, children, id }) {
  return html`<div class=${cls("f", changed && "changed", error && "err")}>
    <label for=${id}>${label}</label>
    ${children}
    ${error ? html`<span class="err-text">${error}</span>` : hint && html`<span class="hint">${hint}</span>`}
    ${orca && html`<span class="orca" title="Orca-Schlüssel">${orca}</span>`}
  </div>`;
}
