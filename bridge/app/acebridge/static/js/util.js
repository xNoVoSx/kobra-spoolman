// Formatierung und Farben - wie in der App (ui/Format.kt, ui/theme/Theme.kt).

const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

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
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}
export function minutes(min) { return min == null ? "–" : duration(min * 60); }
export function when(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return "heute " + time;
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) + " " + time;
}
export function ago(ts) {
  if (!ts) return "–";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "gerade eben";
  if (s < 3600) return `vor ${Math.round(s / 60)} min`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} h`;
  return `vor ${Math.round(s / 86400)} Tagen`;
}
/** Zahl aus einem Eingabefeld ("812,5" -> 812.5); leer -> null; ungueltig -> NaN. */
export function parseNum(t) {
  const s = String(t ?? "").trim().replace(",", ".");
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
/** Dunkle Kopffarbe aus der Spulenfarbe (headerTint der App). */
export function tint(c) {
  const v = rgb(c);
  if (!v) return "var(--sunken)";
  const f = luminance(c) > 0.5 ? 0.22 : 0.35;
  const [r, g, b] = [v[0] * f + 0.04, v[1] * f + 0.04, v[2] * f + 0.05].map((x) => Math.round(Math.min(1, x) * 255));
  return `rgb(${r},${g},${b})`;
}

export const PRINTER = {
  printing: { label: "Druckt", cls: "ok", dot: "var(--ok)", fg: "var(--ok-text)", bg: "var(--ok-soft)", line: "var(--ok-line)" },
  paused: { label: "Pausiert", cls: "warn", dot: "var(--accent)", fg: "var(--accent-text)", bg: "#1D1A12", line: "var(--accent-line)" },
  changing: { label: "Wechselt Filament", cls: "warn", dot: "var(--accent)", fg: "var(--accent-text)", bg: "#1D1A12", line: "var(--accent-line)" },
  error: { label: "Fehler", cls: "bad", dot: "var(--danger)", fg: "var(--danger-text)", bg: "var(--danger-soft)", line: "var(--danger-line)" },
  cancelled: { label: "Abgebrochen", cls: "bad", dot: "var(--danger)", fg: "var(--danger-text)", bg: "var(--danger-soft)", line: "var(--danger-line)" },
  offline: { label: "Offline", cls: "", dot: "#6B7280", fg: "#C9CFD6", bg: "#16181B", line: "var(--line)" },
  complete: { label: "Fertig", cls: "", dot: "var(--info)", fg: "var(--info-text)", bg: "var(--info-soft)", line: "var(--info-line)" },
  standby: { label: "Bereit", cls: "", dot: "var(--info)", fg: "var(--info-text)", bg: "var(--info-soft)", line: "var(--info-line)" },
};
export function printerLook(p) {
  if (!p) return PRINTER.offline;
  const key = p.changing_filament ? "changing" : p.state;
  return PRINTER[key] || PRINTER.standby;
}
export const JOB_STATE = { complete: ["fertig", ""], cancelled: ["abgebrochen", "bad"], error: ["Fehler", "bad"], printing: ["läuft", "ok"] };

export function fileName(f) { return String(f || "").replace(/\.gcode$/i, ""); }
export function cls(...parts) { return parts.filter(Boolean).join(" "); }

/** "PETG 2.0 Magenta" statt "PETG PETG 2.0 Magenta": Material nur voranstellen, wenn der Name es nicht schon nennt. */
export function title(s) {
  if (!s) return "";
  const name = s.name || "", mat = s.material || "";
  return mat && !name.toUpperCase().includes(mat.toUpperCase()) ? `${mat} ${name}` : name || mat;
}

/** Feste Nachkommastellen, deutsch: fixed(1, 1) -> "1,0". */
export function fixed(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return "–";
  return Number(v).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
