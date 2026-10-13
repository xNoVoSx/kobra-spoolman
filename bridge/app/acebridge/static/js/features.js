// Features: every feature of the system on one page (bridge features.py) – what it does, what it needs, whether it is on,
// one switch for each, no matter whether it lives in the bridge or in the printer. What the installation sets
// (environment variables, Home Assistant add-on options) is shown, never changed here.

import { html, useEffect, useState } from "../vendor/preact-htm.module.js";
import { get, post } from "./api.js";
import { t } from "./i18n.js";
import { guard, toast } from "./store.js";

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
    <div class="small muted">${t("Everything the system can do, in one place. Switch what you want – what the installation sets (environment variables, Home Assistant add-on) stays as it is, and is changed there.")}</div>
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
