// Strich-Symbole (24er Raster), gleiche Formen wie in den Entwuerfen.

import { html } from "../vendor/preact-htm.module.js";

const P = {
  overview: () => html`<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>`,
  spool: () => html`<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/>`,
  drop: () => html`<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11z"/>`,
  clock: () => html`<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`,
  dryer: () => html`<path d="M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/>`,
  phone: () => html`<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>`,
  sliders: () => html`<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>`,
  search: () => html`<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>`,
  plus: () => html`<path d="M12 5v14M5 12h14"/>`,
  back: () => html`<path d="M15 5l-7 7 7 7"/>`,
  close: () => html`<path d="M6 6l12 12M18 6L6 18"/>`,
  more: () => html`<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>`,
  copy: () => html`<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>`,
  shelf: () => html`<path d="M4 20V4M20 20V4M4 9h16M4 15h16"/>`,
  archive: () => html`<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10h14V9M10 13h4"/>`,
  check: () => html`<path d="M5 12l5 5L20 7"/>`,
  warn: () => html`<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5M12 18v.5"/>`,
  link: () => html`<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>`,
  key: () => html`<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3"/>`,
  trash: () => html`<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>`,
  play: () => html`<path d="M7 5l12 7-12 7z"/>`,
  stop: () => html`<rect x="6" y="6" width="12" height="12" rx="2"/>`,
  refresh: () => html`<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>`,
  pause: () => html`<path d="M8 5v14M16 5v14"/>`,
  terminal: () => html`<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 9l3 3-3 3M13 15h4"/>`,
  log: () => html`<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>`,
  download: () => html`<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>`,
};

export function Icon({ name, small, style }) {
  return html`<svg class=${small ? "ic s" : "ic"} viewBox="0 0 24 24" aria-hidden="true" style=${style}>${P[name] ? P[name]() : null}</svg>`;
}
