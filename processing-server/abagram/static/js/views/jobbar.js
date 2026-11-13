// The slim bar under a profile header while a reading job works on that person: what it does, its latest line,
// and «لغو» (his request: every running read can be cancelled from where it shows).
import { h, icon, ltr, mount } from "../core/dom.js";
import { cancelJob } from "../core/api.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { JOB_TITLE, runningFor } from "../core/jobs.js";
import { spinner } from "../core/ui.js";

// Log lines carry ⁦…⁩ around Latin parts; show them as isolated runs.
function line(msg) {
  return String(msg || "").split(/(⁦[^⁩]*⁩)/).filter(Boolean)
    .map((part) => (part.startsWith("⁦") ? ltr(part.slice(1, -1)) : part));
}

export function jobBar(nameOf) {
  const text = h("span", { class: "jbar-text" });
  const stop = h("button", { type: "button", class: "btn sm jbar-stop" }, icon("x", { size: "sm" }), h("span", { text: "لغو" }));
  const el = h("div", { class: "jbar", role: "status", "aria-live": "polite", hidden: true }, spinner(18), text, stop);
  let key = "";

  stop.addEventListener("click", async () => {
    stop.disabled = true;
    try { await cancelJob(); } finally { stop.disabled = false; pokePolling(); }
  });

  function draw() {
    const s = state.status;
    const on = runningFor(nameOf());
    const last = state.log.length ? state.log[state.log.length - 1].msg : "";
    const next = on ? `${s.mode}|${last}` : "";
    if (next === key) return;
    key = next;
    el.hidden = !on;
    if (on) mount(text, h("b", { text: JOB_TITLE[s.mode] || "در حال خواندن" }), last ? h("span", { class: "jbar-log" }, line(last)) : null);
  }

  const offs = [subscribe("status", draw), subscribe("log", draw)];
  draw();
  return { el, draw, destroy: () => offs.forEach((off) => off()) };
}
