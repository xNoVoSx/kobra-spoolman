// Meldungen & Status auf der Uebersicht: was die Bridge aus Drucker, Spoolman, Druckdatei und Geraeten ableitet
// (GET /api/app/state -> notices). Meldungen nach Wichtigkeit, darunter der Zustand aller Verbindungen.

import { html } from "../vendor/preact-htm.module.js";
import { visionFeedback } from "./actions.js";
import { S, guard } from "./store.js";
import { ago, cls } from "./util.js";

const LEVEL = { error: "var(--danger)", warn: "var(--accent)", info: "var(--muted)" };
const STATE = { ok: "var(--ok)", warn: "var(--accent)", bad: "var(--danger)", off: "var(--faint)" };

export function NoticesCard() {
  const n = S.st?.notices;
  const msgs = n?.messages || [];
  const worst = msgs[0]?.level;
  return html`
  <section class="card pad col notices" aria-label="Meldungen und Status">
    <div class="row"><h2 class="h2 grow">Meldungen</h2>
      ${msgs.length ? html`<span class=${cls("chip", worst === "error" ? "bad" : worst === "warn" ? "warn" : "")}>${msgs.length}</span>`
                    : html`<span class="chip ok">alles gut</span>`}</div>
    ${msgs.length > 0 && html`<ul class="msgs">
      ${msgs.map((m) => html`<li class=${m.level}><span class="dot" style=${{ background: LEVEL[m.level] }}></span><span class="grow">${m.text}
        ${m.key?.startsWith("ai-") && m.key !== "ai-down" && S.st?.vision?.event && html`<span class="ai-acts">
          <button class="btn sm" onClick=${guard(() => visionFeedback(S.st.vision.event.id, "false_alarm"))}>Fehlalarm</button>
          <button class="btn sm" onClick=${guard(() => visionFeedback(S.st.vision.event.id, "confirmed"))}>Stimmt</button></span>`}</span></li>`)}
    </ul>`}
    <div class="lbl" style="margin-top:4px">Status</div>
    <ul class="stat-lines">
      ${(n?.status || []).map((s) => html`<li>
        <span class="dot" style=${{ background: STATE[s.state] || STATE.off }}></span>
        <span class="lab">${s.label}</span>
        <span class="det muted ell">${s.detail || ""}${s.seen ? ` · ${ago(s.seen)}` : ""}</span></li>`)}
      <li><span class="dot" style=${{ background: S.stErr ? STATE.bad : STATE.ok }}></span><span class="lab">Bridge</span>
        <span class="det muted ell">${S.stErr || `${S.st?.version || "–"} · verbunden`}</span></li>
    </ul>
  </section>`;
}
