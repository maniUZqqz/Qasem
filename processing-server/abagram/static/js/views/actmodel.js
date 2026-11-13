// «فعالیت»: one list of everything the engine does — the job running now, the queue's tasks and the jobs that ended — and
// the strip that sums it up at a glance. The detail of one item is drawn in activity.js. History: /api/runs (ig_runs.py).
import { h, icon, ltr, bdi } from "../core/dom.js";
import { faNum, faTime, ago } from "../core/format.js";
import { state } from "../core/store.js";
import { JOB_TITLE } from "../core/jobs.js";
import { harvestEta } from "./pagejobs.js";

export const TASK_TITLE = { full: "استخراج کامل", harvest: "خواندن همهٔ فهرست", process: "پردازش نامزدها", check: "بررسی رصد",
  watch: "درخواست فالو و انتظار قبول" };
export const MODE_IC = { login: "login", check: "shield", profile: "user", posts: "grid", details: "comment", stories: "circle-play",
  highlights: "layers", follow: "users", download: "download", request: "send", harvest: "users", lookup: "user", browse: "user" };
export const TASK_IC = { full: "layers", harvest: "users", process: "filter", check: "eye", watch: "send" };
// state → [what it says, its tone]
export const PILL = { running: ["در حال اجرا", "live"], need_code: ["منتظر کد تو", "warn"], need_manual: ["منتظر تو", "warn"],
  waiting: ["در صف", "idle"], paused: ["متوقف", "warn"], success: ["انجام شد", "ok"], done: ["تمام شد", "ok"],
  failed: ["ناموفق", "bad"], cancelled: ["لغو شد", "muted"], idle: ["آماده", "idle"], limited: ["سقف پر بود", "muted"] };
export const FILTERS = [["all", "همه"], ["live", "در جریان"], ["queue", "صف"], ["done", "انجام‌شده"], ["failed", "ناموفق"]];

const LIVE = new Set(["running", "need_code", "need_manual"]);
// a start refused because a limit was full asked nothing of Instagram: not a failure, the queue simply waits
const LIMITED = new Set(["budget", "cooldown"]);
export const runState = (r) => (r.state === "failed" && LIMITED.has(r.kind) ? "limited" : r.state);
export const isLive = (s) => !!s && (s.busy || LIVE.has(s.state));

/** How far a queue task is: people of a whole list, candidates of «پردازش», steps of a full extraction. */
export function taskProgress(t) {
  const [done, total] = t.steps.reduce((a, x) => [a[0] + (x.done || 0), a[1] + (x.total || 0)], [0, 0]);
  if (t.kind === "harvest" && total) return { done, total, unit: "نفر", eta: harvestEta(total, done, null) };
  if (t.kind === "process" && total) return { done, total, unit: "نامزد" };
  const steps = t.steps.filter((x) => ["done", "skipped"].includes(x.state)).length;
  return t.steps.length > 1 ? { done: steps, total: t.steps.length, unit: "مرحله" } : null;
}

/** Every item as {id, type: live|task|run, title, user, state, at (ms), icon, progress, src}, in the order they matter:
 * what runs or waits for him now, the queue (soonest first), then what ended (newest first). */
export function items(runs) {
  const s = state.status, out = [];
  if (isLive(s)) out.push({ id: "now", type: "live", title: JOB_TITLE[s.mode] || "کار", user: s.username, state: s.state,
    at: (s.started_at || Date.now() / 1000) * 1000, icon: MODE_IC[s.mode] || "activity", src: s });
  const rank = { running: 0, waiting: 1, paused: 2 };
  (s?.queue?.tasks || []).filter((t) => t.state in rank)
    .sort((a, b) => rank[a.state] - rank[b.state] || (a.next_at || 0) - (b.next_at || 0))
    .forEach((t) => out.push({ id: `t:${t.id}`, type: "task", title: TASK_TITLE[t.kind] || t.kind, user: t.username, state: t.state,
      at: (t.state === "waiting" && t.next_at ? t.next_at : t.updated_at) * 1000, icon: TASK_IC[t.kind] || "list", progress: taskProgress(t), src: t }));
  for (const r of runs || []) {
    out.push({ id: `r:${r.id}`, type: "run", title: JOB_TITLE[r.mode] || r.mode, user: r.username, state: runState(r),
      at: (r.ended_at || r.started_at) * 1000, icon: MODE_IC[r.mode] || "activity", src: r });
  }
  return out;
}

export function inFilter(it, f) {
  if (f === "live") return it.type === "live" || it.state === "running";
  if (f === "queue") return it.type === "task";
  if (f === "done") return it.type === "run" && it.state === "success";
  if (f === "failed") return ["failed", "cancelled", "paused"].includes(it.state);
  return true;
}

const when = (it) => (it.type === "live" ? "همین حالا"
  : it.type === "task" && it.state === "waiting" && it.at > Date.now() ? `نوبت بعد ساعت ${faTime(it.at)}` : ago(it.at));

/** One row of the list: what, for whom, its state and when; a thin bar when it has a measurable progress. */
export function row(it, selected, onPick) {
  const [label, tone] = PILL[it.state] || [it.state, "idle"];
  const p = it.progress;
  return h("button", { type: "button", class: ["act-item", `is-${tone}`], "aria-current": selected ? "true" : null, "data-id": it.id,
    onclick: () => onPick(it.id) },
  h("span", { class: ["act-ic", `is-${tone}`], "aria-hidden": "true" }, icon(it.icon)),
  h("span", { class: "act-item-main" },
    h("span", { class: "act-item-top" }, h("b", { class: "act-item-t", text: it.title }), h("span", { class: ["act-pill", `is-${tone}`], text: label })),
    h("span", { class: "act-item-sub" }, it.user ? ltr(`@${it.user}`) : null, h("span", { class: "act-item-when", text: when(it) })),
    p ? h("span", { class: "act-mini", title: `${faNum(p.done)} از ${faNum(p.total)} ${p.unit}` }, h("i", { style: `--p:${Math.min(1, p.done / p.total)}` })) : null));
}

/** The strip at the top: what runs now, the queue, today's runs and this hour's page limit. A tile filters the list. */
export function overview(runs, onFilter) {
  const s = state.status, tasks = (s?.queue?.tasks || []).filter((t) => ["waiting", "running", "paused"].includes(t.state));
  const b = s?.budget || {}, used = b.used?.page || {}, lim = b.limits || {};
  const midnight = new Date().setHours(0, 0, 0, 0);
  const today = (runs || []).filter((r) => (r.ended_at || 0) * 1000 >= midnight);
  const ok = today.filter((r) => r.state === "success").length, bad = today.filter((r) => runState(r) === "failed").length;
  const next = tasks.filter((t) => t.state === "waiting" && t.next_at * 1000 > Date.now()).map((t) => t.next_at).sort((x, y) => x - y)[0];
  const live = isLive(s);
  const tile = (f, ic, tone, label, value, sub) => h("button", { type: "button", class: ["act-tile", `is-${tone}`], onclick: () => onFilter(f),
    "aria-label": `${label}: ${typeof value === "string" ? value : ""}` },
  h("span", { class: "act-tile-head" }, h("span", { class: "act-tile-ic", "aria-hidden": "true" }, icon(ic, { size: "sm" })), h("span", { class: "act-tile-l", text: label })),
  h("b", { class: "act-tile-v" }, value), h("span", { class: "act-tile-s" }, sub || " "));
  return h("div", { class: "act-tiles" },
    tile("live", "activity", live ? (s.state === "running" ? "live" : "warn") : "idle", "همین حالا",
      live ? JOB_TITLE[s.mode] || "کار" : "کاری اجرا نمی‌شود",
      live ? (s.username ? ltr(`@${s.username}`) : null) : s?.queue?.signed_in === false ? "وارد اینستاگرام نشده‌ای" : "موتور آماده است"),
    tile("queue", "list", tasks.some((t) => t.state === "paused") ? "warn" : "idle", "صف",
      `${faNum(tasks.length)} کار`, next ? ["نوبت بعد ساعت ", bdi(faTime(next))] : tasks.length ? "" : "خالی است"),
    tile(bad ? "failed" : "done", bad ? "alert" : "circle-check", bad ? "bad" : "ok", "امروز",
      `${faNum(ok)} موفق`, bad ? `${faNum(bad)} ناموفق` : "بدون خطا"),
    tile("all", "gauge", lim.pages_hour && (used.hour || 0) / lim.pages_hour >= 0.9 ? "warn" : "idle", "صفحه‌های این ساعت",
      `${faNum(used.hour || 0)} از ${faNum(lim.pages_hour || 0)}`,
      b.cooldown ? ["مکث تا ساعت ", bdi(faTime(b.cooldown.until))] : `امروز ${faNum(used.day || 0)} از ${faNum(lim.pages_day || 0)}`));
}
