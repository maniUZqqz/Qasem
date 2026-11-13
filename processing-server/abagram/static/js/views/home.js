// «خانه»: a stories tray of the newest saved profiles, then the paged list of every profile read so far.
import { h, icon, ltr, bdi, on, uid } from "../core/dom.js";
import { getProfiles, avatarUrl } from "../core/api.js";
import { faNum, faCompact, faDateTime, ago, fresh } from "../core/format.js";
import { state, subscribe } from "../core/store.js";
import { avatar, verified, lock, empty, skeleton, pagedList, button } from "../core/ui.js";
import { runningFor, forget } from "../core/jobs.js";
import { reduced, stagger } from "../core/motion.js";

const TRAY_MAX = 20;
const LIST_KEY = "home-profiles";
const RINGS = ["av-story", "av-seen", "av-loading"];

const href = (u) => `#/u/${encodeURIComponent(u)}`;
const pic = (p) => (p.has_avatar ? avatarUrl(p.username, p.fetched_at) : null);
// /api/profiles rows may carry story_at flat or inside `more` (the dossier shape); either lights the ring.
const restRing = (p) => (fresh(p.story_at ?? p.more?.story_at) ? "story" : "seen");

const setRing = (av, ring) => { if (!av.classList.contains(`av-${ring}`)) { av.classList.remove(...RINGS); av.classList.add(`av-${ring}`); } };

// ---- stories tray: circles that open the profile; arrows on pointer screens ----
function trayItem(p, rings) {
  const rest = restRing(p);
  const av = avatar({ u: p.username, src: pic(p), size: 66, ring: runningFor(p.username) ? "loading" : rest, zoom: false });
  rings.set(p.username, { av, rest });
  return h("li", { class: "hm-tray-item" },
    h("a", { class: "hm-tray-link", href: href(p.username), title: p.full_name || null },
      av,
      h("span", { class: "hm-tray-name", dir: "ltr" }, ltr(p.username)),
      rest === "story" ? h("span", { class: "sr-only", text: "استوری تازه" }) : null));
}

function trayArrow(cls, ic, label, onClick) {
  return h("button", { type: "button", class: ["hm-arrow", cls], "aria-label": label, title: label, hidden: true, onclick: onClick },
    h("span", { class: "hm-arrow-face" }, icon(ic, { size: "sm" })));
}

function buildTray(items, rings) {
  const list = h("ul", { class: "hm-tray-list" }, items.map((p) => trayItem(p, rings)));
  // forward = toward the inline end (the left in RTL); scrollLeft is 0 at the start and grows negative in RTL
  const go = (dir) => {
    const sign = getComputedStyle(list).direction === "rtl" ? -1 : 1;
    list.scrollBy({ left: dir * sign * Math.max(160, list.clientWidth * 0.8), behavior: reduced() ? "auto" : "smooth" });
  };
  const prev = trayArrow("hm-arrow-prev", "chev-r", "پروفایل‌های قبلی", () => go(-1));
  const next = trayArrow("hm-arrow-next", "chev-l", "پروفایل‌های بعدی", () => go(1));
  const el = h("nav", { class: "hm-tray", "aria-label": "پروفایل‌های اخیر" }, list, prev, next);

  let frame = 0;
  const sync = () => {
    frame = 0;
    const x = Math.abs(list.scrollLeft), max = list.scrollWidth - list.clientWidth;
    prev.hidden = x < 4;
    next.hidden = max <= 4 || x >= max - 4;
  };
  const off = on(list, "scroll", () => { if (!frame) frame = requestAnimationFrame(sync); }, { passive: true });
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(sync) : null;
  ro?.observe(list);
  return { el, list, sync, stop() { off(); ro?.disconnect(); cancelAnimationFrame(frame); } };
}

const trayPlaceholder = () => h("div", { class: "hm-tray hm-tray-sk", "aria-hidden": "true" },
  h("ul", { class: "hm-tray-list" }, Array.from({ length: 8 }, () => h("li", { class: "hm-tray-item" },
    h("span", { class: "sk hm-sk-ring" }), h("span", { class: "sk hm-sk-name" })))));

const rowsPlaceholder = () => h("div", { class: "hm-sk-rows", "aria-hidden": "true" },
  Array.from({ length: 5 }, () => h("div", { class: "hm-sk-row" }, skeleton("avatar"),
    h("span", { class: "hm-sk-lines" }, skeleton("line", 2)))));

// ---- one saved profile: the picture opens big (zoom.js takes that click), the rest of the row opens the profile ----
function row(p) {
  const del = h("button", { type: "button", class: "icon-btn hm-del", "aria-label": `حذف ${p.username}`, title: "حذف از ذخیره‌ها",
    onclick: () => forget(p.username) }, icon("trash", { size: "sm" }));
  return h("div", { class: "hm-rowwrap" }, link(p), del);
}

function link(p) {
  const at = p.fetched_at;
  return h("a", { class: "hm-row", href: href(p.username) },
    avatar({ u: p.username, src: pic(p), size: 44, zoom: true }),
    h("span", { class: "hm-row-text" },
      h("span", { class: "hm-row-top" },
        h("span", { class: "hm-row-name ellipsis" }, bdi(p.full_name || p.username)),
        p.is_verified ? verified() : null,
        p.is_private ? lock() : null,
        at ? h("time", { class: "hm-row-time", datetime: at, title: `خوانده‌شده در ${faDateTime(at)}` }, bdi(ago(at))) : null),
      h("span", { class: "hm-row-sub" },
        h("span", { class: "hm-row-user ellipsis", dir: "ltr" }, ltr(`@${p.username}`)),
        p.followers != null ? h("span", { class: "hm-row-fol" }, bdi(`${faCompact(p.followers)} فالوور`)) : null)));
}

const emptyState = () => empty({
  icon: "search",
  title: "هنوز هیچ پروفایلی نخوانده‌ای",
  text: "یوزرنیم یا لینک یک صفحه را بنویس تا از اینستاگرام خوانده شود.",
  action: h("a", { class: "btn primary", href: "#/search" }, icon("search"), h("span", { text: "جستجو" })),
});

const errorState = (retry) => h("div", { class: "hm-error", role: "alert" }, empty({
  icon: "alert",
  title: "فهرست پروفایل‌ها باز نشد",
  action: h("div", { class: "hm-error-body" },
    h("p", { class: "empty-text" }, "سرور محلی جواب نداد. ", ltr("app.py"), " را اجرا کن و دوباره امتحان کن."),
    button({ label: "تلاش دوباره", icon: "refresh", onClick: retry })),
}));

export function render(params, ctx) {
  let dead = false, failed = false, animated = false, tray = null, lastRun = null, lastBudget = "";
  const rings = new Map();
  const titleId = uid("hm-title");

  const budgetText = h("span", { class: "hm-budget-text" });
  const fill = h("span", { class: "hm-fill" });
  const budget = h("p", { class: "hm-budget", hidden: true },
    icon("gauge", { size: "sm" }), budgetText, h("span", { class: "hm-meter", "aria-hidden": "true" }, fill));
  const count = h("span", { class: "hm-count" });
  const trayBox = h("div", { class: "hm-tray-slot" }, trayPlaceholder());
  const listBox = h("div", { class: "hm-list", "aria-busy": "true" }, rowsPlaceholder());

  const el = h("div", { class: "hm" },
    h("h1", { class: "sr-only", text: "خانه" }),
    h("a", { class: "hm-find", href: "#/search", "aria-label": "جستجوی پروفایل" },
      icon("search", { size: "sm" }), h("span", { text: "جستجو" })),
    trayBox,
    h("section", { class: "hm-saved", "aria-labelledby": titleId },
      h("header", { class: "hm-head" },
        h("div", { class: "hm-head-row" }, h("h2", { class: "hm-title", id: titleId, text: "پروفایل‌های ذخیره‌شده" }), count),
        budget),
      listBox));

  // «۱۲ از ۳۰ صفحه در این ساعت» from the last status; redrawn only when the numbers change
  function drawBudget() {
    const b = state.status?.budget;
    const cap = b?.limits?.pages_hour, used = b?.used?.page?.hour;
    if (cap == null || used == null) { budget.hidden = true; return; }
    const key = `${used}/${cap}`;
    if (key === lastBudget) return;
    lastBudget = key;
    budget.hidden = false;
    budgetText.textContent = `${faNum(used)} از ${faNum(cap)} صفحه در این ساعت`;
    fill.style.transform = `scaleX(${cap > 0 ? Math.min(1, used / cap) : 1})`;
    budget.classList.toggle("is-full", used >= cap);
  }

  // the ring turns on the profile a reading job is working on
  function drawRings(force) {
    const s = state.status;
    const run = s?.busy ? String(s.username || "").toLowerCase() : "";
    if (!force && run === lastRun) return;
    lastRun = run;
    for (const [u, { av, rest }] of rings) setRing(av, run && u.toLowerCase() === run ? "loading" : rest);
  }

  function drawTray(items) {
    const keep = tray ? tray.list.scrollLeft : 0;
    tray?.stop();
    rings.clear();
    tray = buildTray(items.slice(0, TRAY_MAX), rings);
    trayBox.replaceChildren(tray.el);
    tray.list.scrollLeft = keep;
    tray.sync();
    drawRings(true);
    if (!animated) { animated = true; stagger(tray.list.children, "scale", 30); }
  }

  function drawList(first, total) {
    const cache = first.slice();
    const load = async (offset, size) => {
      if (offset + size <= cache.length || cache.length >= total) return cache.slice(offset, offset + size);
      try {
        const r = await getProfiles(offset, size);
        return r.ok ? r.data?.items || [] : [];
      } catch { return []; }
    };
    listBox.replaceChildren(pagedList({ key: LIST_KEY, total, load, row, label: "پروفایل‌های ذخیره‌شده" }));
  }

  async function load() {
    let r = null;
    try { r = await getProfiles(0, TRAY_MAX); } catch { r = null; }
    if (dead) return;
    listBox.setAttribute("aria-busy", "false");
    failed = !r?.ok || !r.data;
    const items = failed ? [] : r.data.items || [];
    const total = failed ? 0 : r.data.total ?? items.length;
    count.textContent = total ? `${faNum(total)} پروفایل` : "";
    if (!total) {
      tray?.stop(); tray = null; rings.clear();
      trayBox.replaceChildren();
      listBox.replaceChildren(failed ? errorState(retry) : emptyState());
      return;
    }
    drawTray(items);
    drawList(items, total);
  }

  function retry() {
    listBox.setAttribute("aria-busy", "true");
    listBox.replaceChildren(rowsPlaceholder());
    trayBox.replaceChildren(trayPlaceholder());
    load();
  }

  const unsubs = [
    subscribe("status", () => { drawBudget(); drawRings(); }),
    subscribe("job-end", () => load()),
    subscribe("profiles-changed", () => load()),
    subscribe("online", (up) => { if (up && failed) retry(); }),
  ];
  drawBudget();
  load();

  return {
    el,
    update() { drawBudget(); drawRings(); },
    destroy() {
      dead = true;
      unsubs.forEach((off) => off());
      tray?.stop();
    },
  };
}
