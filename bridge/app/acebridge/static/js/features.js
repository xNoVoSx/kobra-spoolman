// Features: every feature of the system on one page (bridge features.py) – what it does, what it needs, whether it is on,
// one switch for each, no matter whether it lives in the bridge or in the printer. What the installation sets
// (environment variables, Home Assistant add-on options) is shown, never changed here.

import { html, useEffect, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { t } from "./i18n.js";
import { S, guard, loadHealth, toast } from "./store.js";

function State({ it }) {
  if (!it.available) return html`<span class="chip">${t("not available")}</span>`;
  if (it.switchable) return null;
  if (it.source === "core") return html`<span class="chip ok">${t("always on")}</span>`;
  return html`<span class=${"chip " + (it.on ? "ok" : "")}>${it.on ? t("on") : t("off")}</span>`;
}

export function FeaturesPage() {
  const [v, setV] = useState(null);
  const [busy, setBusy] = useState("");
  const load = () => get("/api/features").then(setV).catch((e) => toast(e.message, "bad"));
  useEffect(() => { load(); }, []);
  const toggle = guard(async (it, on) => {
    setBusy(it.key);
    try {
      await post(`/api/features/${it.key}`, { on });
      toast(on ? t("{name} on", { name: it.title }) : t("{name} off", { name: it.title }), "ok");
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
    load();
  });
  if (!v) return html`<div class="muted">${t("Loading …")}</div>`;
  return html`<div class="col" style="max-width:1100px">
    <h1 class="h1">${t("Features")}</h1>
    <div class="row wrap"><span class="small muted grow">${t("Everything the system can do, in one place. Switch what you want – what the installation sets (environment variables, Home Assistant add-on) stays as it is, and is changed there.")}</span>
      <a class="btn sm" href="#/setup">${t("Start setup")}</a></div>
    ${v.groups.map((g) => html`<section class="card pad col">
      <h2 class="h2">${g.title}</h2>
      ${v.items.filter((it) => it.group === g.key).map((it) => html`<div class="set-row" key=${it.key}>
        <div class="grow">
          <div>${it.title}</div>
          <div class="small muted">${it.text}</div>
          ${(it.why || it.needs) && html`<div class="small faint">${it.why || t("Needs: {needs}", { needs: it.needs })}</div>`}
          ${it.doc && html`<a class="small" href=${it.doc} target="_blank" rel="noopener">${t("How it works")}</a>`}
        </div>
        ${it.available && it.switchable
          ? html`<label class="toggle"><input type="checkbox" role="switch" checked=${!!it.on} disabled=${busy === it.key}
              onChange=${(e) => toggle(it, e.target.checked)} aria-label=${it.title} /><span class="knob" aria-hidden="true"></span></label>`
          : html`<${State} it=${it} />`}
      </div>`)}
    </section>`)}
  </div>`;
}

// ------------------------------------------------------------ setup page (bridge setup.py)
// New installation: opens by itself at the first visit (after pairing). Existing: hint on the overview. Any time again
// from the Features page. Three steps: what the bridge found – choose – what is left to do by hand.

const PLATFORM = { klipper: "Klipper + ACEPRO", rinkhals: "Rinkhals" };

function Found({ ok, label, detail }) {
  const mark = ok === true ? "✓" : ok === false ? "✗" : "?";
  return html`<div class="set-row"><span class=${"chip " + (ok === true ? "ok" : ok === false ? "bad" : "")} aria-hidden="true">${mark}</span>
    <div class="grow"><div>${label}</div>${detail && html`<div class="small muted">${detail}</div>`}</div></div>`;
}

export function SetupPage() {
  const [v, setV] = useState(null);
  const [step, setStep] = useState(1);
  const [want, setWant] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    get("/api/setup").then((r) => {
      setV(r);
      setWant(Object.fromEntries(r.features.items.filter((it) => it.switchable).map((it) => [it.key, !!it.on])));
    }).catch((e) => toast(e.message, "bad"));
  }, []);
  if (!v) return html`<div class="muted">${t("Loading …")}</div>`;
  const f = v.found, items = v.features.items;
  const title = (k) => items.find((it) => it.key === k)?.title || k;
  const apply = guard(async () => {
    setBusy(true);
    for (const it of items.filter((x) => x.switchable && want[x.key] !== !!x.on)) {
      try { await post(`/api/features/${it.key}`, { on: want[it.key] }); } catch (e) { toast(`${it.title}: ${e.message}`, "bad"); }
    }
    setBusy(false);
    setStep(3);
  });
  const finish = guard(async () => {
    try { await post("/api/setup/done"); } catch (e) { toast(e.message, "bad"); }
    await loadHealth();
    location.hash = "#/";
  });
  const todo = items.filter((it) => it.available && !it.switchable && !it.on && (it.source === "client" || it.source === "install"));
  return html`<div class="col" style="max-width:860px">
    <h1 class="h1">${t("Setup")}</h1>
    <div class="row wrap">${[t("Found"), t("Choose"), t("Done")].map((s, i) => html`<span class=${"chip " + (step === i + 1 ? "on" : "")}>${i + 1} · ${s}</span>`)}</div>
    ${step === 1 && html`<section class="card pad col">
      <h2 class="h2">${t("What the bridge found")}</h2>
      <${Found} ok=${f.printer} label=${t("Printer")} detail=${f.printer ? PLATFORM[f.platform] || f.platform : t("Not reachable – check MOONRAKER_URL")} />
      <${Found} ok=${f.ace ? true : f.printer ? false : null} label="ACE" detail=${f.ace ? t("Driver: {name}", { name: f.ace }) : t("No ACE driver found")} />
      <${Found} ok=${f.spoolman} label="Spoolman" detail=${f.spoolman ? t("Version {v}", { v: f.spoolman_version || "?" }) : t("Not reachable – check SPOOLMAN_URL")} />
      <${Found} ok=${f.camera} label=${t("Camera")} detail=${f.camera === true ? t("Image received") : f.camera === false ? t("No image – check the camera at the printer") : t("Checked when someone watches")} />
      ${f.platform === "klipper" && html`<${Found} ok=${f.printer_modules.length > 0 ? true : null} label=${t("Printer modules")}
        detail=${f.printer_modules.length ? f.printer_modules.map(title).join(", ") : t("None installed (optional)")} />`}
      <div class="small muted">${t("Spools, slots, bookings and RFID are always on, camera and print preview too (they can be switched off on the Features page). Next you choose what else the system should do.")}</div>
      <div class="row"><span class="grow"></span><button class="btn acc" onClick=${() => setStep(2)}>${t("Next")}</button></div>
    </section>`}
    ${step === 2 && html`${v.features.groups.filter((g) => g.key !== "core").map((g) => html`<section class="card pad col">
      <h2 class="h2">${g.title}</h2>
      ${items.filter((it) => it.group === g.key).map((it) => html`<div class="set-row" key=${it.key}>
        <div class="grow"><div>${it.title}</div><div class="small muted">${it.text}</div>
          ${!it.switchable && html`<div class="small faint">${it.why}</div>`}
          ${it.doc && html`<a class="small" href=${it.doc} target="_blank" rel="noopener">${t("How it works")}</a>`}</div>
        ${it.switchable ? html`<label class="toggle"><input type="checkbox" role="switch" checked=${!!want[it.key]}
            onChange=${(e) => setWant({ ...want, [it.key]: e.target.checked })} aria-label=${it.title} /><span class="knob" aria-hidden="true"></span></label>`
          : html`<${State} it=${it} />`}
      </div>`)}
    </section>`)}
    <div class="row"><button class="btn" onClick=${() => setStep(1)}>${t("Back")}</button><span class="grow"></span>
      <button class="btn acc" disabled=${busy} onClick=${apply}>${busy ? t("Applying …") : t("Apply")}</button></div>`}
    ${step === 3 && html`<section class="card pad col">
      <h2 class="h2">${t("Ready")}</h2>
      <div>${t("Your choice is applied. You can change everything later on the Features page.")}</div>
      ${todo.length > 0 && html`<div class="col" style="gap:6px"><div class="small muted">${t("This is set up on the device or in the installation – if you want it:")}</div>
        ${todo.map((it) => html`<div class="row wrap"><span class="grow">${it.title} <span class="small faint">${it.needs || ""}</span></span>
          ${it.doc && html`<a class="btn sm" href=${it.doc} target="_blank" rel="noopener">${t("How it works")}</a>`}</div>`)}</div>`}
      <div class="row"><a class="btn" href="#/devices">${t("Pair the app")}</a><span class="grow"></span>
        <button class="btn acc" onClick=${finish}>${t("To the overview")}</button></div>
    </section>`}
  </div>`;
}

const HINT_KEY = "kobra.hint.features";

/** Existing installations: one hint on the new Features page (each browser shows it once). */
export function FeaturesHint() {
  let seen = false;
  try { seen = localStorage.getItem(HINT_KEY) === "1"; } catch { /* private window */ }
  const [hidden, setHidden] = useState(seen);
  if (hidden || !S.health?.setup?.hint) return null;
  const close = () => { try { localStorage.setItem(HINT_KEY, "1"); } catch { /* ignore */ } setHidden(true); };
  return html`<section class="card pad col" style="gap:8px">
    <b>${t("New: Features")}</b>
    <div class="small muted">${t("Everything the system can do on one page – see what is on and switch it in one place. Nothing has changed in your setup.")}</div>
    <div class="row"><a class="btn sm acc" href="#/features" onClick=${close}>${t("Have a look")}</a><button class="btn sm" onClick=${close}>${t("OK")}</button></div>
  </section>`;
}
