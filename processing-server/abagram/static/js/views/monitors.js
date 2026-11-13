// «رصدها»: the pages he watches. Each one had a full extraction (and its whole followers list, if he asked), then a check
// about twice a day: the newest posts and the active story (its media saved before it expires). What is new since the check
// before shows as «تازه‌ها» on the page's card until he has seen it. Server: /api/monitors (ig_monitor.py, ig_queue.py).
import { h, icon, ltr, bdi, uid } from "../core/dom.js";
import { api, getMonitors, addMonitor, monitorAct, avatarUrl, thumbUrl } from "../core/api.js";
import { mineOrAsk } from "../core/share.js";
import { faNum, faCompact, faTime, ago, fresh, unit } from "../core/format.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { avatar, verified, lock, empty, skeleton, pagedList, button, iconButton, toast } from "../core/ui.js";
import { menu, confirm } from "../core/overlay.js";
import { runningFor } from "../core/jobs.js";
import { harvestEta, finishText, taskOf } from "./pagejobs.js";
import { enter } from "../core/motion.js";

const LIST_KEY = "watch-pages";
const href = (u) => `#/u/${encodeURIComponent(u)}`;
const clean = (v) => String(v || "").trim().replace(/^@/, "").replace(/^https?:\/\/(www\.)?instagram\.com\//i, "").split(/[/?#]/)[0].toLowerCase();

// ---- the add bar: username or link, the whole-followers option, one primary action ----
function addBar(onAdded) {
  const id = uid("wt-in");
  const input = h("input", { id, class: "input wt-input", type: "text", dir: "ltr", inputmode: "url", autocomplete: "off",
    spellcheck: "false", enterkeyhint: "go", placeholder: "growtech.events یا لینک پیج" });
  const all = h("input", { type: "checkbox", class: "wt-check-box", checked: true });
  const err = h("p", { class: "wt-err", role: "alert", hidden: true });
  const go = button({ label: "افزودن به رصد", icon: "plus", kind: "primary", cls: "wt-go", type: "submit" });
  const form = h("form", { class: "wt-add", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    const u = clean(input.value);
    err.hidden = true;
    if (!/^[a-z0-9._]{1,30}$/.test(u)) { err.textContent = "یوزرنیم یا لینک پیج را درست بنویس."; err.hidden = false; input.focus(); return; }
    go.disabled = true;
    const r = await mineOrAsk((force) => addMonitor(u, all.checked, force)).catch(() => null);
    go.disabled = false;
    if (r?.declined) return;
    if (!r?.ok) { err.textContent = "اضافه نشد؛ برنامه جواب نداد."; err.hidden = false; return; }
    input.value = "";
    toast(`@${u} به رصدها اضافه شد؛ استخراج کامل در صف است`, { tone: "ok" });
    pokePolling();
    onAdded(u);
  } },
  h("label", { class: "wt-label", for: id, text: "پیج تازه برای رصد" }),
  h("div", { class: "wt-row" }, h("span", { class: "wt-field" }, icon("at", { size: "sm" }), input), go),
  h("label", { class: "wt-check" }, all, h("span", { class: "wt-check-ui", "aria-hidden": "true" }, icon("check", { size: "sm" })),
    h("span", {}, h("b", { text: "همهٔ فالوورها هم خوانده شود" }), h("small", { text: "آرام و در چند روز، در پس‌زمینه" }))),
  err);
  return { el: form, focus: () => input.focus() };
}

// ---- one page: who, its state, its numbers, the whole-list progress and what is new ----
function newsTile(m, n) {
  const src = n.thumb ? thumbUrl(m.username, n.kind === "post" ? n.code : `st_${n.item}`, n.found_at) : null;
  const to = n.kind === "post" ? `${href(m.username)}/p/${encodeURIComponent(n.code)}` : `${href(m.username)}/stories`;
  const word = n.kind === "post" ? "پست" : "استوری";
  return h("a", { class: ["wt-tile", !n.seen && "is-new", n.kind === "story" && "is-story"], href: to,
    "aria-label": `${word} ${n.seen ? "" : "تازه"} ${ago(n.at || n.found_at)}`.replace(/\s+/g, " ") },
  src ? h("img", { src, alt: "", loading: "lazy", decoding: "async", onerror: (e) => e.currentTarget.remove() }) : null,
  h("span", { class: "wt-tile-ic", "aria-hidden": "true" }, icon(n.kind === "post" ? "image" : "circle-play", { size: "sm" })),
  h("span", { class: "wt-tile-tag", "aria-hidden": "true", text: word }),
  h("span", { class: "wt-tile-when", "aria-hidden": "true", text: ago(n.at || n.found_at) }));
}

// time left of the whole followers list, and about when it ends
function etaLine(total, got, info) {
  const eta = harvestEta(total, got, info?.started_at);
  if (!eta) return null;
  const why = info?.note === "rate_limit" ? "اینستاگرام گفت صبر کن؛ بعد از مکث ادامه می‌دهد" : info?.note === "budget" ? "منتظر جای خالی در سقف ساعتی" : "";
  return h("p", { class: "wt-eta" }, icon("clock", { size: "sm" }), h("span", {}, h("b", { text: eta.text }), "، ", finishText(eta)),
    why ? h("small", { text: why }) : null);
}

function stateOf(m) {
  if (runningFor(m.username)) return { cls: "is-run", text: "در حال خواندن" };
  if (!m.enabled) return { cls: "is-off", text: "رصد متوقف است" };
  return { cls: "is-on", text: m.next_at ? `بررسی بعدی ساعت ${faTime(m.next_at)}` : "بررسی به‌زودی" };
}

function card(m, act) {
  const p = m.profile || {}, u = m.username, st = stateOf(m);
  const ring = runningFor(u) ? "loading" : fresh(m.story_at) ? "story" : null;
  const more = iconButton({ icon: "more", label: `گزینه‌های رصد ${u}`, cls: "wt-more", onClick: (e) => menu(e.currentTarget, [
    { icon: "refresh", label: "بررسی همین الان", hint: "پست‌ها و استوری تازه", onSelect: () => act(u, "check") },
    m.enabled ? { icon: "pause", label: "توقف رصد", onSelect: () => act(u, "pause") } : { icon: "circle-play", label: "ادامهٔ رصد", onSelect: () => act(u, "resume") },
    { icon: "trash", label: "حذف از رصد", danger: true, onSelect: () => act(u, "remove") },
  ], { label: `گزینه‌های رصد ${u}` }) });
  const total = p.followers, got = m.followers_read || 0;
  const harvest = !m.harvest ? null : h("div", { class: "wt-harvest" },
    h("p", { class: "wt-harvest-text" }, icon("users", { size: "sm" }), m.followers_done
      ? h("span", {}, "همهٔ فالوورها خوانده شد: ", bdi(unit(got, "نفر")))
      : h("span", {}, bdi(faNum(got)), " از ", bdi(Number.isFinite(total) ? faCompact(total) : "؟"), " فالوور خوانده شده")),
    m.followers_done ? null : h("span", { class: "wt-bar", "aria-hidden": "true" },
      h("i", { style: `--p:${Number.isFinite(total) && total ? Math.min(1, got / total) : 0}` })),
    m.followers_done ? null : etaLine(total, got, m.harvest_info));
  const unseen = (m.unseen?.post || 0) + (m.unseen?.story || 0);
  const news = (m.news || []).slice(0, 8);
  // a queue task of this page that waits on something he should know about (no connection, Instagram's "wait", a pause)
  const stuck = ["harvest", "full", "check"].map((k) => taskOf(k, u)).find((t) => t && (t.state === "paused" || (t.state === "waiting" && t.note)));
  const alert = !stuck ? null : h("div", { class: ["wt-alert", stuck.state === "paused" && "is-paused"] },
    icon(stuck.state === "paused" ? "pause" : "hourglass", { size: "sm" }), h("span", { text: stuck.note || "متوقف است" }),
    stuck.state === "paused" ? button({ label: "ادامه", size: "sm", kind: "primary", onClick: () => act(u, "task-resume", stuck) }) : null);
  return h("article", { class: ["wt-card", !m.enabled && "is-paused"], "aria-label": `رصد ${u}` },
    h("header", { class: "wt-top" },
      h("a", { class: "wt-who", href: href(u) },
        avatar({ u, src: p.has_avatar ? avatarUrl(u, p.fetched_at) : null, size: 56, ring, zoom: false }),
        h("span", { class: "wt-names" },
          h("span", { class: "wt-user" }, ltr(u), p.is_verified ? verified() : null, p.is_private ? lock() : null),
          p.full_name ? h("bdi", { class: "wt-full", text: p.full_name }) : null,
          h("span", { class: ["wt-state", st.cls] }, h("i", { "aria-hidden": "true" }), st.text))),
      more),
    h("ul", { class: "wt-facts" },
      h("li", {}, h("b", { text: faCompact(p.followers) }), " فالوور"),
      h("li", {}, h("b", { text: faCompact(p.posts) }), " پست"),
      h("li", {}, m.last_check_at ? ["آخرین بررسی ", bdi(ago(m.last_check_at))] : "هنوز بررسی نشده")),
    harvest,
    alert,
    news.length ? h("section", { class: "wt-news", "aria-label": "تازه‌ها" },
      h("header", { class: "wt-news-head" },
        h("h3", {}, "تازه‌ها", unseen ? h("span", { class: "wt-badge", text: faNum(unseen) }) : null),
        unseen ? button({ label: "همه را دیدم", kind: "link", size: "sm", onClick: () => act(u, "seen") }) : null),
      h("div", { class: "wt-tiles" }, news.map((n) => newsTile(m, n)))) : null);
}

const placeholder = () => h("div", { class: "wt-list", "aria-hidden": "true" }, Array.from({ length: 3 }, () =>
  h("div", { class: "wt-card wt-sk" }, h("span", { class: "wt-sk-row" }, skeleton("avatar"), h("span", { class: "wt-sk-lines" }, skeleton("line", 2))))));

export function render(params, ctx) {
  let dead = false, items = null, lastKey = "", lastWatched = "";
  const titleId = uid("wt-title");
  const count = h("span", { class: "wt-count" });
  const summary = h("p", { class: "wt-summary", hidden: true });
  const listBox = h("div", { class: "wt-body", "aria-busy": "true" }, placeholder());
  const bar = addBar((u) => load(u));
  const el = h("div", { class: "wt" },
    h("header", { class: "wt-head" },
      h("div", { class: "wt-head-row" }, h("h1", { class: "wt-title", id: titleId, text: "رصدها" }), count),
      h("p", { class: "wt-lede", text: "پیج‌هایی که روزی دو بار بررسی می‌شوند: پست‌ها و استوری‌های تازه‌شان اینجا علامت می‌خورد." })),
    bar.el, summary,
    h("section", { class: "wt-pages", "aria-labelledby": titleId }, listBox));

  async function act(u, action, task) {
    if (action === "task-resume") {
      const r = await api(`/api/queue/${task.id}/resume`, {}).catch(() => null);
      if (r?.ok) { toast("ادامه پیدا کرد", { tone: "ok" }); pokePolling(); } else toast("انجام نشد.", { tone: "danger" });
      return;
    }
    if (action === "remove" && !(await confirm({ title: `@${u} از رصد حذف شود؟`, cta: "حذف از رصد", danger: true,
      text: "دیگر بررسی نمی‌شود. آنچه تا الان درآمده (پروفایل، پست‌ها، فالوورها) سر جایش می‌ماند." }))) return;
    const r = await monitorAct(u, action).catch(() => null);
    if (!r?.ok) { toast("انجام نشد.", { tone: "danger" }); return; }
    if (action === "check") toast(`بررسی @${u} در صف گذاشته شد`, { tone: "ok" });
    pokePolling();
    load();
  }

  function draw(fresh) {
    const n = items.length;
    count.textContent = n ? unit(n, "پیج") : "";
    const unseen = items.reduce((a, m) => a + (m.unseen?.post || 0) + (m.unseen?.story || 0), 0);
    const next = items.filter((m) => m.enabled && m.next_at).map((m) => m.next_at).sort((a, b) => a - b)[0];
    summary.hidden = !n;
    summary.replaceChildren(...(n ? [icon("eye", { size: "sm" }),
      h("span", {}, unseen ? [bdi(unit(unseen, "تازهٔ دیده‌نشده"))] : "تازهٔ دیده‌نشده‌ای نیست",
        next ? ["، بررسی بعدی ساعت ", bdi(faTime(next))] : "")] : []));
    if (!n) {
      listBox.replaceChildren(empty({ icon: "eye", title: "هنوز پیجی رصد نمی‌شود",
        text: "یوزرنیم یک پیج را بالا بنویس. اول همه‌چیزش استخراج می‌شود، بعد روزی دو بار پست و استوری تازه‌اش بررسی می‌شود.",
        action: button({ label: "نوشتن یوزرنیم", onClick: () => bar.focus() }) }));
      return;
    }
    listBox.replaceChildren(pagedList({ key: LIST_KEY, items, row: (m) => card(m, act), cls: "wt-list", label: "پیج‌های در رصد" }));
    if (fresh) enter(listBox, "fade");
  }

  async function load(focusUser) {
    const r = await getMonitors().catch(() => null);
    if (dead) return;
    listBox.setAttribute("aria-busy", "false");
    if (!r?.ok) {
      listBox.replaceChildren(empty({ icon: "alert", title: "فهرست رصدها باز نشد", text: "سرور محلی جواب نداد؛ برنامه را اجرا کن و دوباره امتحان کن.",
        action: button({ label: "تلاش دوباره", icon: "refresh", onClick: () => load() }) }));
      return;
    }
    const first = items === null;
    items = (r.data.items || []).slice().sort((a, b) => (b.added_at || 0) - (a.added_at || 0));   // newest first
    lastWatched = JSON.stringify(state.status?.queue?.watched || []);
    draw(first);
    if (focusUser) listBox.querySelector(`.wt-card[aria-label="رصد ${focusUser}"]`)?.scrollIntoView({ block: "nearest" });
  }

  const offs = [
    subscribe("job-end", () => load()),
    subscribe("job-start", () => items && draw(false)),
    subscribe("status", (s) => {     // a page added elsewhere: fetch again; a task's state or note changed: draw again
      if (!items) return;
      if (JSON.stringify(s?.queue?.watched || []) !== lastWatched) return load();
      const k = JSON.stringify((s?.queue?.tasks || []).map((t) => [t.id, t.state, t.note]));
      if (k !== lastKey) { lastKey = k; draw(false); }
    }),
  ];
  load();
  return { el, update() {}, destroy() { dead = true; offs.forEach((off) => off()); } };
}
