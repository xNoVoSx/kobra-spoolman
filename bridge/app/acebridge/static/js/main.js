// Entry: frame (side rail / bottom bar), page choice through #/..., polling and keyboard.

import { html, render, useEffect, useState } from "../vendor/preact-htm.module.js";
import { auth, get, setUnauthorizedHandler } from "./api.js";
import { ContextMenu, Toasts } from "./components.js";
import { Dialogs } from "./dialogs.js";
import { t } from "./i18n.js";
import { Icon } from "./icons.js";
import { AcePage, DevicesPage, FilamentHub, JobsPage, Overview, PairPage, SettingsPage, Ultra, filamentView } from "./pages.js";
import { useFilteredSpools } from "./spools.js";
import { AiPage } from "./ai.js";
import { FeaturesPage, SetupPage } from "./features.js";
import { LogsPage, TerminalPage } from "./terminal.js";
import { S, guard, loadHealth, loadJobs, loadSpools, loadState, openDialog, set, useStore } from "./store.js";
import { cls, printerLook } from "./util.js";

const PAGES = {
  "": { title: t("Overview"), icon: "overview", C: Overview },
  filament: { title: t("Filament"), icon: "spool", C: FilamentHub, fill: true },
  prints: { title: t("Prints"), icon: "clock", C: JobsPage },
  ace: { title: "ACE", icon: "dryer", C: AcePage },
  ai: { title: t("AI"), icon: "eye", C: AiPage },
  terminal: { title: t("Terminal"), icon: "terminal", C: TerminalPage, fill: true },
  logs: { title: t("Logs"), icon: "log", C: LogsPage, fill: true },
  features: { title: t("Features"), icon: "check", C: FeaturesPage, bottom: true },
  setup: { title: t("Setup"), icon: "check", C: SetupPage, hidden: true },
  devices: { title: t("Devices"), icon: "phone", C: DevicesPage, bottom: true },
  settings: { title: t("Settings"), icon: "sliders", C: SettingsPage, bottom: true },
};
let openedSetup = false;      // the setup page opened by itself once in this browser session
const PHONE_TABS = [["", t("Overview"), "overview"], ["filament", t("Filament"), "spool"], ["prints", t("Prints"), "clock"],
  ["more", t("More"), "more"]];

// old URLs (bookmarks): German page names before 3.12, #/regal = spools, #/filamente = filaments (FilamentHub reads it)
const ALIASES = { trockner: "ace", regal: "filament", filamente: "filament", drucke: "prints", ki: "ai", geraete: "devices",
  einstellungen: "settings", mehr: "more" };
const route = () => { const r = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || ""; return ALIASES[r] || r; };

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
    <h1 class="h1">${t("More")}</h1>
    ${["ace", "ai", "terminal", "logs", "features", "devices", "settings"].map((k) => html`<a class="card pad row" href=${"#/" + k} style="color:var(--text)"><${Icon} name=${PAGES[k].icon} /><span class="grow">${PAGES[k].title}</span><${Icon} name="back" style="transform:rotate(180deg)" /></a>`)}
  </div>`;
}

function Rail({ page }) {
  const open = (S.st?.usage?.open || []).length;
  const link = (k) => html`<a href=${"#/" + k} class=${page === k ? "on" : ""} aria-current=${page === k ? "page" : null} title=${PAGES[k].title}>
    <${Icon} name=${PAGES[k].icon} /><span>${PAGES[k].title}</span>${k === "prints" && open > 0 && html`<b class="badge">${open}</b>`}</a>`;
  return html`<nav class="rail" aria-label=${t("Main menu")}>
    <div class="brand"><span class="logo"><${Icon} name="spool" /></span><span class="g" style="font-weight:700;font-size:18px">Kobra Spoolman</span></div>
    ${Object.keys(PAGES).filter((k) => !PAGES[k].bottom && !PAGES[k].hidden).map(link)}
    <span class="grow"></span>
    ${Object.keys(PAGES).filter((k) => PAGES[k].bottom && !PAGES[k].hidden).map(link)}
    <div class="foot">Bridge ${S.st?.version || "–"}</div>
  </nav>`;
}

function TopBar({ page, ultra }) {
  const look = printerLook(S.st?.printer);
  const onSearch = (e) => {
    set({ q: e.target.value });
    if (!ultra && page !== "filament") location.hash = "#/filament/spools";
  };
  return html`<header class="top">
    <h1 class="h1">${ultra && page === "" ? "Kobra Spoolman" : (PAGES[page] || { title: t("More") }).title}</h1>
    <div class="status-chips hide-phone">
      <span class=${cls("chip", look.cls)}><span class="dot" style=${{ background: look.dot, width: "8px", height: "8px" }}></span>${S.st?.printer_name || t("Printer")} · ${look.label}</span>
      ${S.st && !S.st.spoolman && html`<span class="chip bad">${t("Spoolman disconnected")}</span>`}
      ${S.stErr && html`<span class="chip bad">${S.stErr}</span>`}
      ${!S.me && html`<button class="chip warn" onClick=${() => set({ pairing: true })}>${t("view only – pair")}</button>`}
    </div>
    <span class="grow"></span>
    <label class="search"><${Icon} name="search" small />
      <input id="search" aria-label=${t("Search spools")} placeholder=${t("Search spool …")} value=${S.q || ""} onInput=${onSearch}
             onKeyDown=${(e) => e.key === "Escape" && (set({ q: "" }), e.target.blur())} /><kbd>/</kbd></label>
    <button class="btn acc" onClick=${guard(() => openDialog("newSpool"))}><${Icon} name="plus" small /><span class="hide-phone">${t("New spool")}</span></button>
  </header>`;
}

function BottomNav({ page }) {
  const open = (S.st?.usage?.open || []).length;
  const cur = PHONE_TABS.some(([k]) => k === page) ? page : "more";
  return html`<nav class="bottomnav" aria-label=${t("Main menu")}>
    ${PHONE_TABS.map(([k, l, i]) => html`<a href=${"#/" + k} class=${cur === k ? "on" : ""} aria-current=${cur === k ? "page" : null}><${Icon} name=${i} />${l}${k === "prints" && open > 0 && html`<b class="badge">${open}</b>`}</a>`)}
  </nav>`;
}

/** Keyboard: / searches, n new spool, arrows select on the shelf, Escape closes. */
function useKeys(page, list, ultra) {
  useEffect(() => {
    const on = (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
      if (e.key === "Escape") {
        if (S.menu) return set({ menu: null });
        if (S.dialog) return set({ dialog: null });
        if (!typing && S.sel != null && page === "filament") return set({ sel: null });
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || S.dialog) return;
      if (e.key === "/") { e.preventDefault(); document.getElementById("search")?.focus(); }
      else if (e.key === "n") { e.preventDefault(); guard(() => openDialog("newSpool"))(); }
      else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && page === "filament" && filamentView() === "spools") {
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

  // polling: state every 3 s (only the bridge, never the printer directly), spools/prints less often
  useEffect(() => {
    loadState(); loadSpools(); loadJobs(); loadHealth();
    const a = setInterval(() => { if (!document.hidden) loadState(); }, 3000);
    const b = setInterval(() => { if (!document.hidden) loadSpools(); }, 15000);
    const c = setInterval(() => { if (!document.hidden) { loadJobs(); loadHealth(); } }, 30000);
    const vis = () => { if (!document.hidden) { loadState(); loadSpools(); } };
    document.addEventListener("visibilitychange", vis);
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); document.removeEventListener("visibilitychange", vis); };
  }, []);
  // print end -> prints and spools again
  const pstate = S.st?.printer?.state;
  useEffect(() => { if (pstate) { loadJobs(); loadSpools(); } }, [pstate]);

  if (S.me === undefined) return html`<div class="boot">${t("Kobra Spoolman is loading …")}</div>`;
  if (S.pairing || (!S.me && !auth.viewOnly)) {
    return html`<${PairPage} reason=${S.pairReason} /><${Toasts} />`;
  }

  // new installation: the setup page opens by itself once (after pairing), until it is done
  if (S.me && S.health?.setup?.open_setup && page !== "setup" && !openedSetup) { openedSetup = true; location.hash = "#/setup"; }
  const P = page === "more" ? { C: MorePage } : PAGES[page] || PAGES[""];
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

// ------------------------------------------------------------ start: check the key (pair once, then never again)
async function checkAuth() {
  try {
    const st = await get("/api/auth/status");
    const reason = auth.key && !st.device ? t("The saved key is no longer valid (device removed?). Please pair again.") : null;
    if (reason) auth.clear();
    set({ me: st.device || null, setupRequired: st.setup_required, pairReason: reason, pairing: !!reason });
  } catch {
    set({ me: null });   // bridge not reachable: the pairing page or the view reports it
  }
}
setUnauthorizedHandler(() => {
  if (S.me) { auth.clear(); set({ me: null, pairing: true, pairReason: t("This browser is no longer paired. Please pair again.") }); }
  else set({ pairing: true });
});

checkAuth();
render(html`<${App} />`, document.getElementById("app"));
