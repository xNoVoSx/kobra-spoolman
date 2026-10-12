// Card "Resume print?": after a power loss (Klipper module kobra_resume). Live image to check the part, resuming only
// after confirmation - Klipper heats, probes Z on the part and continues printing at that position.

import { html, useState } from "../vendor/preact-htm.module.js";
import { post } from "./api.js";
import { Toggle } from "./ace.js";
import { locale, t } from "./i18n.js";
import { useCamera } from "./media.js";
import { S, guard, loadState, openDialog, toast } from "./store.js";
import { cls } from "./util.js";

export function ResumeCard() {
  const r = S.st?.resume;
  const [busy, setBusy] = useState(false);
  const show = r && (r.pending || r.running || r.error);
  const [src, err, onError] = useCamera(!!show);
  if (!show) return null;
  const p = r.pending || {};

  const call = guard(async (path, body, ok) => {
    setBusy(true);
    try {
      await post(path, body);
      if (ok) toast(ok, "ok");
      await loadState();
    } catch (e) {
      if (e.status !== 401 && e.status !== 403) toast(e.message, "bad");
    } finally { setBusy(false); }
  });
  const resume = () => openDialog("confirm", {
    title: t("Resume the print?"), ok: t("Resume"), back: t("Back"),
    text: t("{file}, layer {layer}: is the part still stuck to the bed? The printer heats the bed, homes X/Y, probes the height on the part and continues printing at that position (takes a few minutes). If the height does not fit, it stops instead of guessing.",
      { file: p.file, layer: p.layer ?? "?" }),
    action: () => call("/api/resume", { confirm: true }, t("Resume started")),
  });
  const discard = () => openDialog("confirm", {
    title: t("Discard the interrupted print?"), ok: t("Discard"), back: t("Back"), danger: true,
    text: t("{file} is not resumed; the saved state is deleted.", { file: p.file }),
    action: () => call("/api/resume/discard", {}, t("Discarded")),
  });
  return html`
  <section class="card pad col" aria-label=${t("Resume print")} style="border-color:var(--danger-line)">
    <h2 class="h2">${r.running ? t("Resuming the print …") : t("Print interrupted")}</h2>
    ${r.pending && html`<div class="small">${p.file} · ${p.layers ? t("layer {layer} of {layers}", { layer: p.layer ?? "?", layers: p.layers })
      : t("layer {layer}", { layer: p.layer ?? "?" })} · ${Math.round(100 * (p.progress || 0))} %</div>`}
    ${src && html`<img src=${src} onError=${onError} alt=${t("Camera")} style="width:100%;border-radius:10px" />`}
    ${err && html`<div class="small faint">${err}</div>`}
    ${r.error && html`<div class="small" style="color:var(--danger-text)">${t("Resume cancelled: {error}", { error: r.error })}</div>`}
    ${r.pending && !r.running && html`<div class="row wrap" style="gap:8px">
      <button class="btn acc" disabled=${busy} onClick=${resume}>${t("Resume …")}</button>
      <button class="btn" disabled=${busy} onClick=${discard}>${t("Discard")}</button></div>`}
  </section>`;
}

/** Switch on the ACE page: resume after power loss on/off (stored in the printer). */
export function PowerlossCard() {
  const r = S.st?.resume;
  const [busy, setBusy] = useState(false);
  if (!r || !r.present) return null;
  const set = guard(async (v) => {
    setBusy(true);
    try { await post("/api/resume/switch", { enabled: v }); await loadState(); }
    catch (e) { if (e.status !== 401 && e.status !== 403) toast(e.message, "bad"); }
    finally { setBusy(false); }
  });
  return html`<section class="card pad col" aria-label=${t("Power loss")}>
    <${Toggle} label=${t("Resume after power loss")}
      hint=${t("The printer keeps saving the position while printing; after switching on it asks whether to continue")}
      value=${r.enabled} disabled=${busy} onChange=${set} /></section>`;
}

// USB tunnel printer <-> Klipper computer: state of the watchdog and its three switches (Moonraker database)
const USB_COLOUR = { ok: "var(--ok-text)", warn: "var(--accent-text)", bad: "var(--danger-text)", off: "var(--muted)" };
const USB_SWITCHES = [
  ["usb_watch", "watch", t("Reconnect USB automatically"), t("Printer on but not connected → the Klipper computer reconnects itself")],
  ["usb_auto_restart", "auto_restart", t("Reload Klipper afterwards"), t("When Klipper lost the boards (never during a print)")],
  ["usb_full_speed", "full_speed", t("Slow, robust USB (12 Mbit/s)"), t("Only if the connection often fails despite the watchdog")],
];

export function UsbCard() {
  const u = S.st?.usb;
  const [busy, setBusy] = useState(false);
  if (!u) return null;
  const set = guard(async (key, value) => {
    setBusy(true);
    try { await post("/api/switch", { key, value }); await loadState(); }
    catch (e) { if (e.status !== 401 && e.status !== 403) toast(e.message, "bad"); }
    finally { setBusy(false); }
  });
  const last = u.events?.length ? u.events[u.events.length - 1] : null;
  return html`<section class="card pad col" aria-label=${t("USB tunnel")}>
    <div class="row" style="gap:8px;align-items:baseline"><b>${t("USB tunnel")}</b>
      <span class="small" style=${{ color: USB_COLOUR[u.state] || "var(--text)" }}>${u.detail}</span></div>
    ${USB_SWITCHES.map(([key, field, label, hint]) => html`<${Toggle} label=${label} hint=${hint}
      value=${!!u.switches?.[field]} disabled=${busy || !u.alive} onChange=${(v) => set(key, v)} />`)}
    ${last && html`<div class="small faint">${new Date(last.at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })} · ${last.text}</div>`}
  </section>`;
}

/** Switch on the ACE page: clog detection (Klipper module kobra_clog) on/off, warn only or pause. */
export function ClogCard() {
  const c = S.st?.clog;
  const [busy, setBusy] = useState(false);
  if (!c || !c.present) return null;
  const set = guard(async (body) => {
    setBusy(true);
    try { await post("/api/clog/switch", body); await loadState(); }
    catch (e) { if (e.status !== 401 && e.status !== 403) toast(e.message, "bad"); }
    finally { setBusy(false); }
  });
  const opt = (val, label) => html`<button class=${cls("seg-btn", c.action === val && "on")} disabled=${busy || !c.enabled}
    onClick=${() => set({ action: val })}>${label}</button>`;
  return html`<section class="card pad col" aria-label=${t("Clog")}>
    <${Toggle} label=${t("Detect clogs")}
      hint=${t("Compares, while printing, what the extruder pushes with the encoder at the filament inlet")}
      value=${c.enabled} disabled=${busy} onChange=${(v) => set({ enabled: v })} />
    <div class="row wrap" style="gap:8px;align-items:center">
      <span class="small">${t("On suspicion")}</span>
      <div class="seg">${opt("warn", t("Warn only"))}${opt("pause", t("Pause print"))}</div></div>
    ${c.available === false && html`<div class="small" style="color:var(--danger-text)">${t("No encoder found – detection inactive")}</div>`}
    ${c.last_ratio != null && html`<div class="small faint">${t("Last measured: {pct} % (limit {min} %)", { pct: Math.round(100 * c.last_ratio), min: Math.round(100 * (c.min_ratio || 0)) })}${c.alarms
      ? " · " + t("{n}× suspicion since Klipper start", { n: c.alarms }) : ""}</div>`}
  </section>`;
}
