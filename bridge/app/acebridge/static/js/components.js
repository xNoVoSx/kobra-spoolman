// Shared building blocks: cards for printer, slots, dryer, open items, prints; dialog frame, toasts, menu.

import { MoistureChip } from "./humidity.js";
import { html, useEffect, useRef } from "../vendor/preact-htm.module.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { ControlBar } from "./control.js";
import { PrintMedia } from "./media.js";
import { S, set, closeDialog, guard, openDialog, spoolById } from "./store.js";
import { JOB_STATE, cls, duration, fileName, finishAt, grams, hex, minutes, num, printerLook, tint, title, when } from "./util.js";

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

// ------------------------------------------------------------ printer
export function PrinterCard({ compact, tall }) {
  const p = S.st?.printer;
  const look = printerLook(p);
  const running = p && (p.state === "printing" || p.state === "paused");
  const live = S.st?.usage?.live;
  const active = p?.active_slot ? S.st.slots.find((s) => s.slot === p.active_slot) : null;
  const ui = S.health?.links?.printer_ui;
  const pct = p?.progress != null ? Math.round(p.progress * 100) : null;
  return html`
  <section class="card pad printer" style=${{ background: look.bg, borderColor: look.line }} aria-label=${t("Printer")}>
    <div class="row">
      <span class="dot" style=${{ background: look.dot }}></span>
      <span class="state" style=${{ color: look.fg }} title=${p?.phase ? look.label : ""}>${p?.phase || look.label}</span>
      <span class="m small muted ell grow" title=${p?.file || ""}>${p?.file ? fileName(p.file) : ""}</span>
      ${pct != null && html`<span class="m pct" style=${{ color: look.fg }}>${pct} %</span>`}
      ${ui && html`<a class="btn sm ghost" href=${ui} target="_blank" rel="noopener" title=${t("Open Mainsail")} style=${{ borderColor: look.line, color: look.fg }}><${Icon} name="link" small />Mainsail</a>`}
    </div>
    ${running && html`<span class="bar" style=${{ background: look.line }}><i style=${{ width: (p.progress || 0) * 100 + "%", background: look.dot }}></i></span>`}
    ${running && html`
    <div class="times">
      <div><span>${t("Running")}</span><b class="m">${duration(p.print_duration_s)}</b></div>
      <div><span>${t("Left approx.")}</span><b class="m">${duration(p.eta_s)}</b></div>
      <div><span>${t("Done")}</span><b class="m">${finishAt(p.eta_s)}</b></div>
    </div>`}
    <${ControlBar} p=${p} />
    ${p?.message && html`<div class="small" style=${{ color: look.fg }}>${p.message}</div>`}
    ${p?.state === "offline" && html`<div class="small muted">${t("The bridge cannot reach the printer right now.")}</div>`}
    ${p?.state !== "offline" && html`<${PrintMedia} tall=${tall} />`}
    ${running && (active || live) && html`
    <div class="row wrap small" style="gap:6px 18px">
      ${active && html`<span class="muted row" style="gap:6px">${t("Active")} <${Swatch} color=${active.spool?.color} size=${12} /> <b style="color:var(--text)">${t("Slot {slot}", { slot: active.slot })}</b></span>`}
      ${live && html`<span class="muted">${t("so far {g} · {n} changes", { g: grams(live.slots.reduce((a, s) => a + s.g, 0)), n: live.changes })}</span>`}
    </div>`}
    ${running && S.st?.uses?.length > 0 && html`
    <div class="row wrap small" style="gap:6px 18px" aria-label=${t("Used slots")}>
      <span class="muted">${t("Used")}</span>
      ${S.st.uses.map((u) => html`<span class="muted row" style="gap:6px" title=${t("total {total} mm incl. purging, {rest} mm left", { total: u.total_mm, rest: u.rest_mm })}>
        <${Swatch} color=${u.color} size=${12} /><b style="color:var(--text)">${t("Slot {slot}", { slot: u.slot })}</b>${u.name ? ` ${u.name}` : ""}${" · "}${t("~{total}, {rest} left", { total: grams(u.total_g), rest: grams(u.rest_g) })}</span>`)}
    </div>`}
  </section>`;
}

// ------------------------------------------------------------ slots
export function SlotCard({ slot }) {
  const sp = slot.spool;
  const active = slot.ace?.active;
  const live = (S.st?.usage?.live?.slots || []).find((x) => x.slot === slot.slot);
  const tag = sp?.tag_nr ? t("Tag {nr}", { nr: sp.tag_nr }) : slot.ace?.tag_id ? t("Tag {nr}", { nr: slot.ace.tag_id }) : sp ? t("no tag") : null;
  const assign = guard(() => openDialog("assign", { slot: slot.slot }));
  const clear = guard(() => openDialog("confirm", {
    title: t("Empty slot {slot}?", { slot: slot.slot }), text: t("{name} goes back to the shelf.", { name: sp.display_name }), ok: t("Empty"),
    action: () => import("./actions.js").then((a) => a.assignSlot(slot.slot, null)),
  }));
  // the overview has no spool detail: open the spool on Filament → Spools (idea: MineTech13's HA add-on)
  const open = () => { if (!sp) return; set({ sel: sp.spool_id }); if (!location.hash.startsWith("#/filament")) location.hash = "#/filament/spools"; };
  return html`
  <article class=${cls("card slot", active && "active")} aria-label=${t("Slot {slot}", { slot: slot.slot })}>
    <div class="head" style=${{ background: sp ? tint(sp.color) : "var(--sunken)" }}>
      <span class="num">${t("SLOT {slot}", { slot: slot.slot })}</span>
      <${Spool} color=${sp?.color} empty=${!sp} size=${84} />
    </div>
    <div class="body">
      <div class="row">
        ${sp ? html`<button class="name g ell" style="background:none;border:0;padding:0;cursor:pointer;text-align:left" onClick=${open}>${title(sp)}</button>`
             : html`<span class="name muted">${t("Empty")}</span>`}
        ${sp && html`<${MoistureChip} id=${sp.spool_id} />`}
        ${active && html`<span class="chip acc" style="margin-left:auto">${t("active")}</span>`}
      </div>
      <div class="small muted ell">${sp ? `${sp.vendor} · #${sp.spool_id}` : slot.ace?.present
        ? t("ACE reports {material}", { material: slot.ace.material || t("a spool without material") }) : t("Insert a spool and assign it here")}</div>
      ${sp && html`<div class="row"><${Bar} value=${sp.remaining_weight} max=${sp.initial_weight || 1000} /><span class="m small" style="min-width:64px;text-align:right">${grams(sp.remaining_weight)}</span></div>`}
      <div class="row wrap" style="gap:6px">
        ${tag && html`<span class=${cls("chip", slot.by_tag && "ok")} title=${slot.by_tag ? t("Assigned automatically: the ACE read the tag") : ""}>${slot.by_tag ? `RFID · ${tag}` : tag}</span>`}
        ${sp?.nozzle_temp && html`<span class="chip">${sp.nozzle_temp} °C</span>`}
        ${live && html`<span class="chip ok">${t("this print {g}", { g: grams(live.g) })}</span>`}
      </div>
      ${slot.hints.map((h) => html`<div class="hint">${h}</div>`)}
      <div class="actions">
        <button class="btn sm" onClick=${assign}>${sp ? t("Change spool") : t("Assign spool")}</button>
        ${sp && html`<button class="btn sm ghost" onClick=${clear}>${t("Empty")}</button>`}
      </div>
    </div>
  </article>`;
}

export function Slots() {
  const slots = S.st?.slots || [];
  return html`<div class="slots">${slots.map((s) => html`<${SlotCard} key=${s.slot} slot=${s} />`)}</div>`;
}

// ------------------------------------------------------------ dryer
const RUN_SOURCE = { hand: t("by hand"), plan: t("scheduled"), spule: t("after inserting") };
export function dryerLook(d) {
  if (!d?.present) return [t("no ACE found"), ""];
  if (d.drying) return [d.auto_run ? t("drying · automatic") : t("drying"), "warn"];
  if (d.paused_until) return [t("Pause"), ""];
  return [d.config?.enabled ? t("off · automation on") : t("off"), ""];
}
function dryerText(d, req) {
  const parts = [];
  if (d.drying) {
    const src = d.run && d.run.source !== "auto" ? (RUN_SOURCE[d.run.source] || d.run.source) : null;
    parts.push(src ? t("{time} left ({source}, runs until its time).", { time: minutes(d.remaining_min), source: src })
      : t("{time} left.", { time: minutes(d.remaining_min) }));
  }
  const c = d.config || {};
  parts.push(c.enabled ? t("Automation starts from {start} % (after {delay} min in a row), stops below {stop} %, at most {hours} h.",
    { start: num(c.start_above, 0), delay: num(c.start_delay_minutes ?? 15, 0), stop: num(c.stop_below, 0), hours: num(c.max_hours) })
    : t("Automation is off."));
  if (req.temp != null) parts.push(t("At most {temp} °C for the loaded spools.", { temp: req.temp }));
  return parts.join(" ");
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
  const plan = guard(() => openDialog("dryerPlan"));
  const big1 = { fontSize: big ? "44px" : "32px", fontWeight: 600, lineHeight: 1 };
  return html`
  <section class="card pad col" aria-label=${t("Dryer")}>
    <div class="row"><span style="color:var(--accent)"><${Icon} name="dryer" /></span><h2 class="h2">${t("Dryer")}</h2><span class="grow"></span><span class=${cls("chip", kind)}>${label}</span></div>
    ${d.present && html`
    <div class="row wrap" style="gap:28px;align-items:flex-end">
      <div><div class="m" style=${big1}>${num(d.humidity, 0)}<span class="muted" style="font-size:.5em"> %</span></div>
        <div class="small muted">${t("Humidity")}${d.config?.enabled ? " · " + t("target below {stop} %", { stop: num(d.config.stop_below, 0) }) : ""}</div></div>
      <div><div class="m" style=${big1}>${num(d.temp, 0)}<span class="muted" style="font-size:.5em"> °C</span></div>
        <div class="small muted">${t("in the ACE")}${d.drying ? " · " + t("target {t} °C", { t: num(d.target_temp, 0) }) : ""}${limited.length ? " · " + t("limit {name}", { name: limited[0].name }) : ""}</div></div>
    </div>
    <div class="small muted">${dryerText(d, req)}</div>
    ${d.schedule && html`<div class="small" style="color:var(--accent-text)">${t("Scheduled: {when}", { when: when(d.schedule.at_iso) })}${d.schedule.temp ? ` · ${num(d.schedule.temp, 0)} °C` : ""}${d.schedule.hours ? ` · ${num(d.schedule.hours)} h` : ""}</div>`}
    ${d.last_event && html`<div class="small faint">${t("Last: {text} ({when})", { text: d.last_event.text, when: when(d.last_event.at) })}</div>`}
    <div class="row wrap">
      ${d.drying ? html`<button class="btn sm" onClick=${stop}><${Icon} name="stop" small />${t("Stop")}</button>`
                 : html`<button class="btn sm" onClick=${start}><${Icon} name="play" small />${t("Dry")}</button>`}
      <button class="btn sm ghost" onClick=${plan}><${Icon} name="clock" small />${d.schedule ? t("Scheduled") : t("Schedule")}</button>
      <button class="btn sm ghost" onClick=${rules}>${t("Rules")}</button>
    </div>`}
  </section>`;
}

// ------------------------------------------------------------ open bookings
const REASON = { retry: t("Spoolman was not reachable"), no_spool: t("Slot without a spool"), spool_missing: t("The spool no longer exists") };
export function OpenItemsCard() {
  const open = S.st?.usage?.open || [];
  return html`
  <section class="card pad col" aria-label=${t("Open bookings")}>
    <div class="row"><h2 class="h2">${t("Open bookings")}</h2><span class="grow"></span><span class=${cls("chip", open.length ? "bad" : "ok")}>${open.length}</span></div>
    ${!open.length && html`<div class="small muted">${t("Everything booked in Spoolman.")}</div>`}
    ${open.map((it) => html`
      <div class="row" key=${it.id} style="align-items:flex-start">
        <div class="grow">
          <div class="small"><b>${it.slot > 0 ? t("Slot {slot}", { slot: it.slot }) : t("without a slot")}</b> · ${num(it.mm, 0)} mm ≈ ${grams(it.g_est)}</div>
          <div class="small muted ell">${fileName(it.file)} · ${REASON[it.reason] || it.reason}${it.spool_id ? " · " + t("Spool #{id}", { id: it.spool_id }) : ""}</div>
        </div>
        <button class="btn sm" onClick=${guard(() => openDialog("bookOpen", { item: it }))}>${t("Book")}</button>
      </div>`)}
  </section>`;
}

// ------------------------------------------------------------ connections
export function OrcaCard() {
  const h = S.health;
  const state = (on) => (on ? html`<span class="chip ok">${t("connected")}</span>` : html`<span class="chip bad">${t("disconnected")}</span>`);
  return html`
  <section class="card pad col" aria-label=${t("Connections")}>
    <h2 class="h2">${t("Connections")}</h2>
    <div class="kv">
      <span>${t("Printer (Moonraker)")}</span><span>${state(h?.moonraker?.connected)}</span>
      <span>Spoolman ${h?.spoolman?.version || ""}</span><span>${state(h?.spoolman?.connected)}</span>
      <span>${t("Spools / filaments")}</span><span class="m">${h ? `${h.spoolman.spools} / ${h.spoolman.filaments}` : "–"}</span>
      <span>${t("Booking")}</span><span>${h ? (h.booking ? t("on") : t("off (test run)")) : "–"}</span>
    </div>
  </section>`;
}

// ------------------------------------------------------------ prints
export function JobCard({ job, live }) {
  const [label, kind] = live ? [t("running"), "ok"] : (JOB_STATE[job.state] || [job.state, ""]);
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
    <div class="small muted">${live ? t("since {when} · so far {g} · {n} changes", { when: when(job.started), g: grams(total), n: job.changes })
      : job.loads === 1 ? t("{when} · {g} · 1 load", { when: when(job.ended), g: grams(total) })
        : t("{when} · {g} · {n} loads", { when: when(job.ended), g: grams(total), n: job.loads ?? "–" })}</div>
    <div class="row wrap" style="gap:6px">
      ${parts.map((p) => html`<span class="chip" style="color:var(--text)" title=${t("Slot {slot}", { slot: p.slot })}><${Swatch} color=${colorFor(p)} size=${10} />${grams(p.g)}</span>`)}
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
    ${!live && !jobs.length && html`<div class="empty-state">${t("No prints recorded yet.")}</div>`}
    ${compact && html`<a href="#/prints" class="small">${t("All prints →")}</a>`}
  </div>`;
}

// ------------------------------------------------------------ frame for dialogs
export function Dialog({ title, children, footer, wide, onClose = closeDialog }) {
  const ref = useRef(null);
  useEffect(() => {
    const box = ref.current;
    (box?.querySelector(".dbody input, .dbody select, .dbody textarea") || box?.querySelector("footer .acc"))?.focus();
  }, []);
  return html`
  <div class="scrim" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class=${cls("dialog", wide && "wide")} role="dialog" aria-modal="true" aria-label=${title} ref=${ref}>
      <header><h2 class="h2 grow">${title}</h2><button class="btn icon ghost" aria-label=${t("Close")} onClick=${onClose}><${Icon} name="close" /></button></header>
      <div class="dbody">${children}</div>
      ${footer && html`<footer>${footer}</footer>`}
    </div>
  </div>`;
}

export function Toasts() {
  return html`<div class="toasts" role="status" aria-live="polite">${S.toasts.map((x) => html`<div key=${x.id} class=${cls("toast", x.kind)}>${x.text}</div>`)}</div>`;
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

// ------------------------------------------------------------ inputs
export function Field({ label, orca, hint, error, changed, children, id }) {
  return html`<div class=${cls("f", changed && "changed", error && "err")}>
    <label for=${id}>${label}</label>
    ${children}
    ${error ? html`<span class="err-text">${error}</span>` : hint && html`<span class="hint">${hint}</span>`}
    ${orca && html`<span class="orca" title=${t("Orca key")}>${orca}</span>`}
  </div>`;
}
