// Work on one page that runs through the queue: «استخراج کامل» (with its live progress card) and the follow request
// to a private page (with its watch). The queue itself lives on the server (ig_queue.py); this only shows and steers it.
import { h, icon, ltr, mount } from "../core/dom.js";
import { api, addMonitor, monitorAct } from "../core/api.js";
import { faNum, faTime } from "../core/format.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { sheet, confirm } from "../core/overlay.js";
import { mineOrAsk } from "../core/share.js";
import { button, toast, spinner } from "../core/ui.js";

const STATE_FA = { waiting: "در صف", running: "در حال انجام", paused: "متوقف", done: "تمام شد", failed: "ناموفق", cancelled: "لغو شد" };
const tasks = () => [...(state.status?.queue?.tasks || []), ...(state.status?.queue?.recent || [])];
export const taskOf = (kind, u) => tasks().filter((t) => t.kind === kind && t.username === String(u).toLowerCase()).pop() || null;

// A desktop notification when a follow request is accepted needs the person's yes once.
function askNotify() {
  try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch { /* not offered */ }
}

/** Is a running job reading this highlight right now? (its ring turns) */
export function readingHighlight(u, id) {
  const s = state.status;
  if (!s?.busy || s.mode !== "highlights" || (s.username || "").toLowerCase() !== String(u).toLowerCase()) return false;
  const ids = s.options?.ids;
  return !ids || ids.includes(String(id));
}

/** How long the rest of a whole list takes: from the speed really reached since it started (once there is enough of it),
 * else from his limits — the daily one counts too (60 an hour but 1,000 a day is about 42 an hour round the clock).
 * Returns {hours, at (ms), text} or null. */
export function harvestEta(total, got, startedAt) {
  const left = total - got;
  if (!Number.isFinite(left) || left <= 0) return null;
  const lim = state.status?.budget?.limits || {};
  const capped = Math.min(lim.harvests_hour || 60, (lim.harvests_day || 1000) / 24, 3600 / (lim.harvest_scroll || 30)) * 12;      // people an hour
  const since = startedAt ? (Date.now() - Date.parse(startedAt)) / 3600000 : 0;
  const seen = since >= 1 && got >= 480 ? got / since : 0;                                     // measured, breathers included
  const perHour = seen ? Math.min(seen, capped * 1.2) : capped;
  const hours = left / perHour, at = Date.now() + hours * 3600000;
  const text = hours < 1 ? "کمتر از یک ساعت دیگر" : hours < 36 ? `حدود ${faNum(Math.round(hours))} ساعت دیگر`
    : `حدود ${faNum(Math.round(hours / 12) / 2)} روز دیگر`;
  return { hours, at, text };
}

const finishFmt = new Intl.DateTimeFormat("fa-IR", { weekday: "long", hour: "2-digit", minute: "2-digit" });
export const finishText = (eta) => (eta ? `تمام شدن حدود ${finishFmt.format(new Date(eta.at))}` : "");

/** «رصد»: a toggle on the profile. On: the page is checked about twice a day (posts, story); the first time it asks whether the
 * whole followers list should be read too. Off: from «رصدها» (or here, after a confirm). */
export function watchButton(name) {
  const watched = () => (state.status?.queue?.watched || []).includes(String(name).toLowerCase());
  const el = h("span", { class: "pj-watch" });
  let key = null, shown = false;
  function draw() {
    if (el.isConnected) shown = true;
    else if (shown) { off(); return; }    // the header was drawn again: this copy is gone, so it stops listening
    const on = watched();
    if (on === key) return;
    key = on;
    el.replaceChildren(button({ label: on ? "در رصد" : "رصد", icon: on ? "check" : "eye", size: "sm", cls: on ? "pj-watch-on" : null,
      onClick: () => (on ? stop() : start()) }));
  }
  async function stop() {
    if (!(await confirm({ title: `رصد @${name} متوقف شود؟`, cta: "حذف از رصد", danger: true,
      text: "دیگر روزی دو بار بررسی نمی‌شود. آنچه تا الان درآمده سر جایش می‌ماند." }))) return;
    const r = await monitorAct(name, "remove").catch(() => null);
    if (r?.ok) { toast(`@${name} از رصدها حذف شد`); pokePolling(); } else toast("انجام نشد.", { tone: "danger" });
  }
  function start() {
    const all = h("input", { type: "checkbox", checked: true });
    const go = button({ label: "افزودن به رصد", kind: "primary", full: true, onClick: async () => {
      const r = await mineOrAsk((force) => addMonitor(name, all.checked, force)).catch(() => null);
      d.close();
      if (r?.declined) return;
      if (r?.ok) { toast(`@${name} به رصدها اضافه شد`, { tone: "ok" }); pokePolling(); } else toast("اضافه نشد.", { tone: "danger" });
    } });
    const d = sheet({ title: "رصد این پیج", actions: [go, button({ label: "انصراف", kind: "ghost", full: true, onClick: () => d.close() })],
      content: h("div", { class: "pj-sheet" }, h("p", { class: "pj-who" }, ltr(`@${name}`)),
        h("ol", { class: "pj-steps" }, ["اگر قبلاً نشده، اول همه‌چیزش استخراج می‌شود", "بعد روزی دو بار پست‌ها و استوری تازه‌اش بررسی می‌شود",
          "تازه‌ها در «رصدها» علامت می‌خورد و خبرت می‌کنم"].map((t) => h("li", { text: t }))),
        h("label", { class: "pj-opt" }, all, h("span", { text: "همهٔ فالوورها هم خوانده شود (آرام، در چند روز)" }))) });
  }
  const off = subscribe("status", draw);
  draw();
  el.destroy = off;
  return el;
}

export function fullButton(name) {
  return button({ label: "استخراج کامل", icon: "layers", size: "sm", cls: "pj-full", onClick: () => startFull(name) });
}

function startFull(name) {
  const steps = ["پروفایل تازه", "همهٔ پست‌ها (تا سقف «پست برای خواندن»)", "استوری فعال", "آیتم‌های همهٔ هایلایت‌ها",
    "فالوورها و فالووینگ", "کامنت و لایک‌کنندگان همهٔ پست‌ها", "دانلود عکس و ویدیوی پست‌ها، هایلایت‌ها و استوری"];
  const go = button({ label: "شروع استخراج کامل", kind: "primary", full: true, onClick: async () => {
    askNotify();
    const r = await mineOrAsk((force) => api("/api/full", { username: name, ...(force ? { force: true } : {}) })).catch(() => null);
    d.close();
    if (r?.declined) return;
    if (r?.ok) { toast(`استخراج کامل @${name} در صف گذاشته شد`, { tone: "ok" }); pokePolling(); } else toast("شروع نشد.", { tone: "danger" });
  } });
  const d = sheet({ title: "استخراج کامل این پیج", actions: [go, button({ label: "انصراف", kind: "ghost", full: true, onClick: () => d.close() })],
    content: h("div", { class: "pj-sheet" }, h("p", { class: "pj-who" }, ltr(`@${name}`)),
      h("ol", { class: "pj-steps" }, steps.map((t) => h("li", { text: t }))),
      h("p", { class: "pj-note", text: "قدم‌به‌قدم و پشت سر هم اجرا می‌شود. هر وقت سقف ساعتی پر شد صبر می‌کند و خودش ادامه می‌دهد؛ تمام که شد خبرت می‌کنم." })) });
}

const act = (t, action) => api(`/api/queue/${t.id}/${action}`, {}).then(() => pokePolling());

function stepLine(s) {
  const n = s.total != null ? ` (${faNum(s.done)} از ${faNum(s.total)})` : "";
  return h("li", { class: ["pj-step", `is-${s.state}`] }, h("span", { class: "pj-dot", "aria-hidden": "true" },
    s.state === "active" ? spinner(14) : s.state === "done" ? icon("check", { size: "sm" }) : s.state === "failed" ? icon("x", { size: "sm" }) : null),
  h("span", { class: "pj-step-t", text: s.title + n }), s.note ? h("small", { text: s.note }) : null);
}

/** The progress card of this page's full extraction and follow-request watch. */
export function taskPanel(nameOf) {
  const el = h("div", { class: "pj" });
  let key = "";
  function card(t) {
    const done = t.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
    const head = { full: "استخراج کامل", harvest: "خواندن کامل فهرست", process: "پردازش نامزدها", check: "بررسی رصد" }[t.kind] || "درخواست فالو";
    // a whole list: people read of all there are, and about how long the rest takes at his hourly limit (12 people a page)
    const ppl = t.kind === "harvest" ? t.steps.reduce((a, x) => [a[0] + (x.done || 0), a[1] + (x.total || 0)], [0, 0]) : null;
    const eta = ppl ? harvestEta(ppl[1], ppl[0], null) : null;
    const cand = t.kind === "process" ? t.steps[0] : null;       // «پردازش»: candidates read of all there are
    // the queue's own note often names the time already («… ادامه از ساعت ۰۹:۵۷»): never say it twice
    const when = faTime(t.next_at);
    const next = t.state === "waiting" && t.next_at * 1000 > Date.now() && !(t.note || "").includes(when) ? `بعدی ساعت ${when}` : "";
    const btns = [
      t.state === "waiting" && t.next_at * 1000 > Date.now() ? button({ label: "الان انجام بده", size: "sm", onClick: () => act(t, "now") }) : null,
      t.state === "waiting" ? button({ label: "توقف", size: "sm", kind: "ghost", onClick: () => act(t, "pause") }) : null,
      t.state === "paused" ? button({ label: "ادامه", size: "sm", kind: "primary", onClick: () => act(t, "resume") }) : null,
      ["waiting", "paused"].includes(t.state) ? button({ label: "لغو", size: "sm", kind: "danger", onClick: async () => {
        if (await confirm({ title: `${head} لغو شود؟`, text: "آنچه تا الان خوانده شده می‌ماند.", cta: "لغو", danger: true })) act(t, "cancel");
      } }) : null,
    ].filter(Boolean);
    return h("section", { class: ["pj-card", `is-${t.state}`], "aria-label": head },
      h("header", { class: "pj-head" }, h("b", { text: head }), nameOf() ? null : h("a", { class: "pj-user", href: `#/u/${t.username}` }, ltr(`@${t.username}`)), h("span", { class: "pj-state", text: STATE_FA[t.state] || t.state }),
        t.kind === "full" ? h("span", { class: "pj-count", text: `${faNum(done)} از ${faNum(t.steps.length)} مرحله` })
          : ppl?.[1] ? h("span", { class: "pj-count", text: `${faNum(ppl[0])} از ${faNum(ppl[1])} نفر` + (eta && t.state !== "done" ? `، ${eta.text}` : "") })
          : cand?.total ? h("span", { class: "pj-count", text: `${faNum(cand.done)} از ${faNum(cand.total)} نامزد` }) : null),
      t.kind === "full" ? h("span", { class: "pj-bar", "aria-hidden": "true" }, h("i", { style: `--p:${done / t.steps.length}` }))
        : ppl?.[1] ? h("span", { class: "pj-bar", "aria-hidden": "true" }, h("i", { style: `--p:${Math.min(1, ppl[0] / ppl[1])}` }))
        : cand?.total ? h("span", { class: "pj-bar", "aria-hidden": "true" }, h("i", { style: `--p:${Math.min(1, cand.done / cand.total)}` })) : null,
      h("ul", { class: "pj-list" }, t.steps.map(stepLine)),
      t.note || next ? h("p", { class: "pj-note", text: [t.note, next].filter(Boolean).join(" — ") }) : null,
      btns.length ? h("div", { class: "pj-btns" }, btns) : null);
  }
  function draw() {
    const u = nameOf();
    const recent = (t) => t && (["waiting", "running", "paused"].includes(t.state) || Date.now() / 1000 - t.updated_at < 600);
    const live = u ? ["full", "watch", "harvest"].map((k) => taskOf(k, u)).filter(recent) : tasks().filter(recent);   // no name: every page (activity drawer)
    const next = JSON.stringify(live.map((t) => [t.id, t.state, t.note, t.next_at, t.steps.map((s) => s.state + s.done)]));
    if (next === key) return;
    key = next;
    mount(el, live.map(card));
  }
  const off = subscribe("status", draw);
  draw();
  return { el, destroy: off };
}

/** The private-page card: what is locked, and the follow request with its state. */
export function privateCard(name, profile) {
  const el = h("section", { class: "pf-private pj-private" });
  const rel = profile?.relation || {};
  let key = null;
  function draw() {
    const w = taskOf("watch", name);
    const k = JSON.stringify([w?.state, w?.note, rel.requested]);
    if (k === key) return;
    key = k;
    const asked = rel.requested || (w && w.state !== "cancelled" && w.state !== "failed");
    const action = asked ? h("p", { class: "pj-note", text: w?.note || "درخواست فرستاده شده؛ منتظر قبول." })
      : button({ label: "ارسال درخواست فالو", kind: "primary", size: "sm", onClick: async () => {
        if (!(await confirm({ title: `درخواست فالو به @${name} فرستاده شود؟`, cta: "ارسال درخواست",
          text: "با حساب واردشده دکمهٔ Follow زده می‌شود. هر چند ساعت یک بار (تنظیم «بررسی درخواست فالو») وضعیتش بررسی می‌شود و وقتی قبول کرد خبرت می‌کنم و همه‌چیزش خودکار استخراج می‌شود." }))) return;
        askNotify();
        const r = await mineOrAsk((force) => api("/api/request", { username: name, ...(force ? { force: true } : {}) })).catch(() => null);
        if (r?.declined) return;
        if (r?.ok) { toast("درخواست در صف گذاشته شد", { tone: "ok" }); pokePolling(); } else toast("فرستاده نشد.", { tone: "danger" });
      } });
    mount(el, h("span", { class: "pf-private-ic" }, icon("lock", { size: "lg" })),
      h("div", { class: "pj-private-text" }, h("h2", { text: "این حساب خصوصی است" }),
        h("p", { text: asked ? "تا درخواستت قبول نشود پست‌ها و فهرست‌هایش دیده نمی‌شود." : "برای دیدن پست‌ها، استوری و فهرست‌هایش باید درخواست فالو بفرستی." }), action));
  }
  const off = subscribe("status", draw);
  draw();
  el.destroy = off;
  return el;
}
