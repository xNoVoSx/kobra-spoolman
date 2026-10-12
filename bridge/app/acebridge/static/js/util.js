// Formatting and colours - like in the app (ui/Format.kt, ui/theme/Theme.kt). Numbers and dates follow the page
// language (i18n.js).

import { locale, t } from "./i18n.js";

const nf0 = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });

export function num(v, digits = 1) {
  if (v == null || v === "" || Number.isNaN(Number(v))) return "–";
  return (digits === 0 ? nf0 : nf1).format(Number(v));
}
export function grams(v) {
  if (v == null) return "–";
  return (Math.abs(v) >= 100 ? nf0 : nf1).format(v) + " g";
}
export function meters(mm) {
  if (mm == null) return "–";
  return nf0.format(mm / 1000) + " m";
}
export function duration(s) {
  if (s == null) return "–";
  const total = Math.round(s / 60), h = Math.floor(total / 60), m = total % 60;   // round first, else "1 h 60 min"
  return h ? `${h} h ${m} min` : `${m} min`;
}
/** Approximate finish time: "~14:35", "tomorrow ~02:10", else with the weekday. */
export function finishAt(etaS, now = new Date()) {
  if (etaS == null || etaS < 0) return "–";
  const end = new Date(now.getTime() + etaS * 1000);
  const time = "~" + end.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(end) - day(now)) / 86400000);
  if (days === 0) return time;
  if (days === 1) return t("tomorrow {time}", { time });
  return end.toLocaleDateString(locale, { weekday: "short" }) + " " + time;
}
export function minutes(min) { return min == null ? "–" : duration(min * 60); }
export function when(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return t("today {time}", { time });
  return d.toLocaleDateString(locale, { day: "2-digit", month: "2-digit" }) + " " + time;
}
export function ago(ts) {
  if (!ts) return "–";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return t("just now");
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400) return t("{n} h ago", { n: Math.round(s / 3600) });
  return t("{n} days ago", { n: Math.round(s / 86400) });
}
/** Number from an input field ("812,5" or "812.5" -> 812.5); empty -> null; invalid -> NaN. */
export function parseNum(text) {
  const s = String(text ?? "").trim().replace(",", ".");
  if (!s) return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : NaN;
}

export function hex(c) {
  const h = String(c || "").trim().replace(/^#/, "").slice(0, 6);
  return /^[0-9a-fA-F]{6}$/.test(h) ? "#" + h.toUpperCase() : null;
}
function rgb(c) {
  const h = hex(c);
  if (!h) return null;
  return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}
export function luminance(c) {
  const v = rgb(c);
  if (!v) return 0;
  const [r, g, b] = v.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/** Dark header colour from the spool colour (headerTint of the app). */
export function tint(c) {
  const v = rgb(c);
  if (!v) return "var(--sunken)";
  const f = luminance(c) > 0.5 ? 0.22 : 0.35;
  const [r, g, b] = [v[0] * f + 0.04, v[1] * f + 0.04, v[2] * f + 0.05].map((x) => Math.round(Math.min(1, x) * 255));
  return `rgb(${r},${g},${b})`;
}

export const PRINTER = {
  printing: { label: t("Printing"), cls: "ok", dot: "var(--ok)", fg: "var(--ok-text)", bg: "var(--ok-soft)", line: "var(--ok-line)" },
  paused: { label: t("Paused"), cls: "warn", dot: "var(--accent)", fg: "var(--accent-text)", bg: "#1D1A12", line: "var(--accent-line)" },
  changing: { label: t("Changing filament"), cls: "warn", dot: "var(--accent)", fg: "var(--accent-text)", bg: "#1D1A12", line: "var(--accent-line)" },
  error: { label: t("Error"), cls: "bad", dot: "var(--danger)", fg: "var(--danger-text)", bg: "var(--danger-soft)", line: "var(--danger-line)" },
  cancelled: { label: t("Cancelled"), cls: "bad", dot: "var(--danger)", fg: "var(--danger-text)", bg: "var(--danger-soft)", line: "var(--danger-line)" },
  offline: { label: t("Offline"), cls: "", dot: "#6B7280", fg: "#C9CFD6", bg: "#16181B", line: "var(--line)" },
  complete: { label: t("Finished"), cls: "", dot: "var(--info)", fg: "var(--info-text)", bg: "var(--info-soft)", line: "var(--info-line)" },
  standby: { label: t("Ready"), cls: "", dot: "var(--info)", fg: "var(--info-text)", bg: "var(--info-soft)", line: "var(--info-line)" },
};
export function printerLook(p) {
  if (!p) return PRINTER.offline;
  const key = p.changing_filament ? "changing" : p.state;
  return PRINTER[key] || PRINTER.standby;
}
export const JOB_STATE = { complete: [t("finished"), ""], cancelled: [t("cancelled"), "bad"], error: [t("Error"), "bad"],
  printing: [t("running"), "ok"] };

export function fileName(f) { return String(f || "").replace(/\.gcode$/i, ""); }
export function cls(...parts) { return parts.filter(Boolean).join(" "); }

/** "PETG 2.0 Magenta" instead of "PETG PETG 2.0 Magenta": put the material first only if the name does not say it. */
export function title(s) {
  if (!s) return "";
  const name = s.name || "", mat = s.material || "";
  return mat && !name.toUpperCase().includes(mat.toUpperCase()) ? `${mat} ${name}` : name || mat;
}

/** Fixed decimals in the page language: fixed(1, 1) -> "1.0" / "1,0". */
export function fixed(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "–";
  return Number(v).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
