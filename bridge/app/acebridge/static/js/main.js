// Einstieg: Rahmen (Seitenleiste / Leiste unten), Seitenwahl ueber #/..., Abfragen und Tastatur.

import { html, render, useEffect, useState } from "../vendor/preact-htm.module.js";
import { auth, get, setUnauthorizedHandler } from "./api.js";
import { ContextMenu, Toasts } from "./components.js";
import { Dialogs } from "./dialogs.js";
import { Icon } from "./icons.js";
import { DevicesPage, DryerPage, FilamentPage, JobsPage, Overview, PairPage, RegalPage, SettingsPage, Ultra } from "./pages.js";
import { useFilteredSpools } from "./spools.js";
import { S, guard, loadHealth, loadJobs, loadSpools, loadState, openDialog, set, useStore } from "./store.js";
import { cls, printerLook } from "./util.js";

const PAGES = {
  "": { title: "Übersicht", icon: "overview", C: Overview },
  regal: { title: "Regal", icon: "spool", C: RegalPage, fill: true },
  filamente: { title: "Filamente", icon: "drop", C: FilamentPage, fill: true },
  drucke: { title: "Drucke", icon: "clock", C: JobsPage },
  trockner: { title: "Trockner", icon: "dryer", C: DryerPage },
  geraete: { title: "Geräte", icon: "phone", C: DevicesPage, bottom: true },
  einstellungen: { title: "Einstellungen", icon: "sliders", C: SettingsPage, bottom: true },
};
const PHONE_TABS = [["", "Slots", "overview"], ["regal", "Regal", "spool"], ["drucke", "Drucke", "clock"], ["mehr", "Mehr", "more"]];

const route = () => (location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || "");

function useRoute() {
  const [r, setR] = useState(route());
  useEffect(() => {
    const on = () => { setR(route()); set({ menu: null }); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}
function useWidth() {
  const [w, setW] = useState(window.innerWidth);
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return w;
}

function MorePage() {
  return html`<div class="col">
    <h1 class="h1">Mehr</h1>
    ${["filamente", "trockner", "geraete", "einstellungen"].map((k) => html`<a class="card pad row" href=${"#/" + k} style="color:var(--text)"><${Icon} name=${PAGES[k].icon} /><span class="grow">${PAGES[k].title}</span><${Icon} name="back" style="transform:rotate(180deg)" /></a>`)}
  </div>`;
}

function Rail({ page }) {
  const open = (S.st?.usage?.open || []).length;
  const link = (k) => html`<a href=${"#/" + k} class=${page === k ? "on" : ""} aria-current=${page === k ? "page" : null} title=${PAGES[k].title}>
    <${Icon} name=${PAGES[k].icon} /><span>${PAGES[k].title}</span>${k === "drucke" && open > 0 && html`<b class="badge">${open}</b>`}</a>`;
  return html`<nav class="rail" aria-label="Hauptmenü">
    <div class="brand"><span class="logo"><${Icon} name="spool" /></span><span class="g" style="font-weight:700;font-size:18px">Kobra Spoolman</span></div>
    ${Object.keys(PAGES).filter((k) => !PAGES[k].bottom).map(link)}
    <span class="grow"></span>
    ${Object.keys(PAGES).filter((k) => PAGES[k].bottom).map(link)}
    <div class="foot">Bridge ${S.st?.version || "–"}</div>
  </nav>`;
}

function TopBar({ page, ultra }) {
  const look = printerLook(S.st?.printer);
  const onSearch = (e) => {
    set({ q: e.target.value });
    if (!ultra && page !== "regal") location.hash = "#/regal";
  };
  return html`<header class="top">
    <h1 class="h1">${ultra && page === "" ? "Kobra Spoolman" : (PAGES[page] || { title: "Mehr" }).title}</h1>
    <div class="status-chips hide-phone">
      <span class=${cls("chip", look.cls)}><span class="dot" style=${{ background: look.dot, width: "8px", height: "8px" }}></span>Kobra S1 · ${look.label}</span>
      ${S.st && !S.st.spoolman && html`<span class="chip bad">Spoolman getrennt</span>`}
      ${S.stErr && html`<span class="chip bad">${S.stErr}</span>`}
      ${!S.me && html`<button class="chip warn" onClick=${() => set({ pairing: true })}>nur ansehen – koppeln</button>`}
    </div>
    <span class="grow"></span>
    <label class="search"><${Icon} name="search" small />
      <input id="search" aria-label="Spulen suchen" placeholder="Spule suchen …" value=${S.q || ""} onInput=${onSearch}
             onKeyDown=${(e) => e.key === "Escape" && (set({ q: "" }), e.target.blur())} /><kbd>/</kbd></label>
    <button class="btn acc" onClick=${guard(() => openDialog("newSpool"))}><${Icon} name="plus" small /><span class="hide-phone">Neue Spule</span></button>
  </header>`;
}

function BottomNav({ page }) {
  const open = (S.st?.usage?.open || []).length;
  const cur = PHONE_TABS.some(([k]) => k === page) ? page : "mehr";
  return html`<nav class="bottomnav" aria-label="Hauptmenü">
    ${PHONE_TABS.map(([k, l, i]) => html`<a href=${"#/" + k} class=${cur === k ? "on" : ""} aria-current=${cur === k ? "page" : null}><${Icon} name=${i} />${l}${k === "drucke" && open > 0 && html`<b class="badge">${open}</b>`}</a>`)}
  </nav>`;
}

/** Tastatur: / sucht, n neue Spule, Pfeile waehlen im Regal, Escape schliesst. */
function useKeys(page, list, ultra) {
  useEffect(() => {
    const on = (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
      if (e.key === "Escape") {
        if (S.menu) return set({ menu: null });
        if (S.dialog) return set({ dialog: null });
        if (!typing && S.sel != null && page === "regal") return set({ sel: null });
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || S.dialog) return;
      if (e.key === "/") { e.preventDefault(); document.getElementById("search")?.focus(); }
      else if (e.key === "n") { e.preventDefault(); guard(() => openDialog("newSpool"))(); }
      else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && (page === "regal" || (ultra && page === ""))) {
        e.preventDefault();
        if (!list.length) return;
        const i = list.findIndex((s) => s.spool_id === S.sel);
        const next = e.key === "ArrowDown" ? Math.min(list.length - 1, i + 1) : Math.max(0, i - 1);
        set({ sel: list[i < 0 ? 0 : next].spool_id });
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [page, list, ultra]);
}

function App() {
  useStore();
  const page = useRoute();
  const width = useWidth();
  const ultra = width >= 3000;
  const list = useFilteredSpools();
  useKeys(page, list, ultra);

  // Abfragen: Zustand alle 3 s (nur die Bridge, nie der Drucker direkt), Spulen/Drucke seltener
  useEffect(() => {
    loadState(); loadSpools(); loadJobs(); loadHealth();
    const a = setInterval(() => { if (!document.hidden) loadState(); }, 3000);
    const b = setInterval(() => { if (!document.hidden) loadSpools(); }, 15000);
    const c = setInterval(() => { if (!document.hidden) { loadJobs(); loadHealth(); } }, 30000);
    const vis = () => { if (!document.hidden) { loadState(); loadSpools(); } };
    document.addEventListener("visibilitychange", vis);
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); document.removeEventListener("visibilitychange", vis); };
  }, []);
  // Druckende -> Drucke und Spulen neu
  const pstate = S.st?.printer?.state;
  useEffect(() => { if (pstate) { loadJobs(); loadSpools(); } }, [pstate]);

  if (S.me === undefined) return html`<div class="boot">Kobra Spoolman lädt …</div>`;
  if (S.pairing || (!S.me && !auth.viewOnly)) {
    return html`<${PairPage} reason=${S.pairReason} /><${Toasts} />`;
  }

  const P = page === "mehr" ? { C: MorePage } : PAGES[page] || PAGES[""];
  const isUltraOverview = ultra && page === "";
  const C = isUltraOverview ? Ultra : P.C;
  return html`
  <div class="shell">
    <${Rail} page=${page} />
    <div class="main">
      <${TopBar} page=${page} ultra=${ultra} />
      <main class=${cls("content", (P.fill || isUltraOverview) && "fill")}>${isUltraOverview || P.fill ? html`<${C} />` : html`<${C} />`}</main>
      <${BottomNav} page=${page} />
    </div>
  </div>
  <${Dialogs} /><${ContextMenu} /><${Toasts} />`;
}

// ------------------------------------------------------------ Start: Schluessel pruefen (einmal koppeln, danach nie wieder)
async function checkAuth() {
  try {
    const st = await get("/api/auth/status");
    const reason = auth.key && !st.device ? "Der gespeicherte Schlüssel gilt nicht mehr (Gerät entfernt?). Bitte neu koppeln." : null;
    if (reason) auth.clear();
    set({ me: st.device || null, setupRequired: st.setup_required, pairReason: reason, pairing: !!reason });
  } catch {
    set({ me: null });   // Bridge nicht erreichbar: Kopplungsseite bzw. Anzeige meldet es
  }
}
setUnauthorizedHandler(() => {
  if (S.me) { auth.clear(); set({ me: null, pairing: true, pairReason: "Dieser Browser ist nicht mehr gekoppelt. Bitte neu koppeln." }); }
  else set({ pairing: true });
});

checkAuth();
render(html`<${App} />`, document.getElementById("app"));
