// The frame around every page: sidebar (desktop) / icon rail (tablet, or while a drawer is open) / phone top bar and
// bottom tab bar, the drawer panel, the job pill, the offline banner and the cooldown line.
import { h, icon, ltr, mount, on } from "../core/dom.js";
import { faTime, faNum } from "../core/format.js";
import { avatarUrl, cancelJob } from "../core/api.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { navigate, back } from "../core/router.js";
import { enter, exit, slideFrom, animate, DUR, reduced } from "../core/motion.js";
import { avatar } from "../core/ui.js";
import { JOB_TITLE } from "../core/jobs.js";

const ITEMS = [
  { name: "home", icon: "home", label: "خانه", href: "#/" },
  { name: "search", icon: "search", label: "جستجو", href: "#/search" },
  { name: "activity", icon: "activity", label: "فعالیت", href: "#/activity" },
  { name: "settings", icon: "settings", label: "تنظیمات", href: "#/settings" },
  { name: "monitors", icon: "eye", label: "رصدها", href: "#/monitors" },
  { name: "monitoring", icon: "monitor", label: "مانیتورینگ", href: "#/monitoring" },
  { name: "process", icon: "filter", label: "پردازش", href: "#/process" },
  { name: "exchange", icon: "braces", label: "تبادلِ JSON", href: "#/exchange" },   // phones: one tap away in «تنظیمات»
];
const DRAWERS = { search: "جستجو" };   // «فعالیت» is a page of its own now
const WAITING = { need_code: "key", need_manual: "window" };   // the job waits for the person: which icon says why
const FAILED_LABEL = "فعالیت، یک کار ناموفق بود";

const side = matchMedia("(min-width: 768px)");     // rail or sidebar instead of the phone bars
const wide = matchMedia("(min-width: 1264px)");    // room for the full sidebar
const roomy = matchMedia("(min-width: 1680px)");   // room for the sidebar AND a drawer: nothing collapses, nothing jumps

const dot = () => h("span", { class: "sh-dot", hidden: true, "aria-hidden": "true" });

function navItem({ name, icon: ic, label, href }) {
  return h("a", { class: "sh-item", href, "data-name": name, "aria-label": label },
    h("span", { class: "sh-ic" }, icon(ic), name === "home" ? icon("home-fill", { cls: "fill sh-ic-on" }) : null, name === "activity" ? dot() : null),
    h("span", { class: "sh-label sh-tip", text: label }));
}

function brand(cls) {
  return h("a", { class: ["sh-brand", cls], href: "#/", "aria-label": "آباگرام، خانه" },
    icon("mark", { size: "lg", cls: "sh-mark" }),
    h("span", { class: "sh-brand-txt", "aria-hidden": "true" }, h("span", { class: "sh-word", text: "آباگرام" }),
      h("span", { class: "sh-sub", text: "خواندن اینستاگرام" })));
}

// The sidebar's search field: one click to the search panel (the rail shows the search icon instead).
const findBtn = () => h("a", { class: "sh-find", href: "#/search", "data-name": "search" },
  icon("search", { size: "sm" }), h("span", { text: "جستجوی یوزرنیم یا لینک" }));

// This hour's page budget, always in sight: Instagram is asked only within it.
const meter = () => h("a", { class: "sh-meter", href: "#/settings/usage", "aria-label": "مصرف این ساعت" },
  h("span", { class: "sh-meter-top" }, h("span", { class: "sh-meter-label", text: "صفحه‌های این ساعت" }), h("b", { class: "sh-meter-val num" })),
  h("span", { class: "sh-meter-bar" }, h("i")));

const pill = (cls) => h("a", { class: ["sh-pill", cls], href: "#/activity", hidden: true });
// His request: every running read can be cancelled from where it shows.
const stopBtn = (cls) => h("button", { type: "button", class: ["icon-btn sh-stop", cls], "aria-label": "لغو و بستن مرورگر", title: "لغو و بستن مرورگر", hidden: true,
  onclick: (e) => { e.currentTarget.disabled = true; cancelJob().finally(() => { e.currentTarget.disabled = false; pokePolling(); }); } }, icon("x", { size: "sm" }));
const coolLine = (cls) => h("div", { class: ["sh-cool", cls], hidden: true });

function fillPill(el, s, wait) {
  const u = s.username || "";
  const face = wait ? h("span", { class: "sh-pill-ic" }, icon(wait, { size: "sm" }))
    : avatar({ u, src: u ? avatarUrl(u) : null, size: 24, ring: "loading" });
  mount(el, face, h("span", { class: "sh-pill-text sh-tip" },
    h("span", { class: "sh-pill-title", text: wait ? "منتظر تو" : "در حال خواندن…" }),
    h("span", { class: "sh-pill-sub" }, h("span", { class: "sh-pill-job", text: JOB_TITLE[s.mode] || "کار" }), u ? ltr(`@${u}`) : null)));
  el.classList.toggle("is-wait", !!wait);
}

function pulse(el) {
  el.classList.remove("pulse");
  void el.offsetWidth;                     // restart the one-time animation
  el.classList.add("pulse");
  el.addEventListener("animationend", () => el.classList.remove("pulse"), { once: true });
}

export function renderShell(root) {
  const items = ITEMS.map(navItem);
  const ind = h("span", { class: "sh-ind", "aria-hidden": "true" });   // the active pill: slides from item to item
  const acct = h("a", { class: "sh-item sh-acct", href: "#/settings/session", "data-name": "account", "aria-label": "حساب" },
    h("span", { class: "sh-ic" }), h("span", { class: "sh-label sh-tip" }), h("span", { class: "sh-acct-more", "aria-hidden": "true" }, icon("chev-l", { size: "sm" })));
  const find = findBtn(), gauge = meter();
  const [navPill, topPill, navCool, topCool] = [pill("sh-pill-nav"), pill("sh-pill-top"), coolLine("sh-cool-nav"), coolLine("sh-cool-top")];
  const stops = [stopBtn("sh-stop-nav"), stopBtn("sh-stop-top")];
  const nav = h("nav", { class: "sh-nav", "aria-label": "ناوبری اصلی" }, brand("sh-brand-nav"), find,
    h("div", { class: "sh-items" }, ind, items), h("div", { class: "sh-foot" }, h("div", { class: "sh-pillrow" }, navPill, stops[0]), navCool, gauge, acct));

  const topAct = h("a", { class: "sh-act", href: "#/activity", "aria-label": "فعالیت" },
    h("span", { class: "sh-ic" }, icon("activity"), dot()));
  const top = h("header", { class: "sh-top" }, brand("sh-brand-top"),
    h("div", { class: "sh-top-end" }, topPill, stops[1], topAct));
  const offline = h("p", { class: "sh-offline", hidden: state.online },
    icon("globe", { size: "sm" }), h("span", {}, "سرور محلی در دسترس نیست؛ ", ltr("app.py"), " را اجرا کن"));
  const head = h("div", { class: "sh-head" }, top, h("div", { class: "sh-alerts", role: "status" }, offline, topCool));

  const panel = h("aside", { class: "sh-drawer", hidden: true });
  const main = h("main", { id: "main", class: "sh-main", tabindex: "-1" });
  const col = h("div", { class: "sh-col" }, head, panel, main);
  const el = h("div", { class: "sh" }, nav, col);
  mount(root, el);

  const pills = [navPill, topPill], cools = [navCool, topCool], actLinks = [items[2], topAct];
  const dots = [...el.querySelectorAll(".sh-dot")];

  let route = null, pagePath = "/", fromPage = false, hint = null, active = null;
  let drawerEl = null, drawerName = null, phoneY = 0;
  let failed = false, jobKey = "", coolKey = "", acctUser;

  const setRail = () => { el.toggleAttribute("data-rail", !wide.matches || (!!drawerEl && !roomy.matches)); moveInd(); };

  // The sidebar folds into the rail (and back) as one movement: the island's width glides (CSS), every row glides from
  // where it was to where it lands, and what only one of the two shows fades in. Transform/opacity only.
  let morphT = 0;
  function morph(change) {
    const was = el.hasAttribute("data-rail");
    if (!side.matches || reduced()) { change(); return; }
    const rows = [...nav.querySelectorAll(".sh-brand-nav, .sh-find, .sh-item, .sh-pillrow, .sh-cool-nav, .sh-meter")];
    const from = rows.map((x) => (x.offsetParent ? x.getBoundingClientRect() : null));
    nav.setAttribute("data-morph", "");          // before the change: no tooltip fade flash, no wrapping mid-way
    change();
    if (el.hasAttribute("data-rail") === was) { if (!morphT) nav.removeAttribute("data-morph"); return; }
    const start = (r) => (document.documentElement.dir === "rtl" ? r.right : r.left);
    rows.forEach((x, i) => {
      if (!x.offsetParent) return;
      x.getAnimations().forEach((m) => m.cancel());   // a fold mid-way: from[] already holds where it is on screen
      const a = from[i], b = x.getBoundingClientRect();
      if (!a) { enter(x, "fade"); return; }      // only this side shows it (the search icon in the rail, the search field)
      const dx = start(a) - start(b), dy = a.top - b.top;
      if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) animate(x, [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { dur: DUR.enter });
    });
    if (was) nav.querySelectorAll(".sh-label, .sh-brand-txt, .sh-acct-more").forEach((x) => { if (x.offsetParent) enter(x, "fade"); });
    clearTimeout(morphT);
    morphT = setTimeout(() => { morphT = 0; nav.removeAttribute("data-morph"); }, DUR.enter + 60);
  }

  // A drawer opened or closed: the page column glides to its new place instead of jumping there.
  function reflow(change) {
    const parts = side.matches ? [head, main].filter((x) => x.offsetHeight) : [];
    const from = parts.map((x) => x.getBoundingClientRect());
    morph(() => { change(); setRail(); });
    parts.forEach((x, i) => slideFrom(x, from[i]));
  }

  function derive() {
    if (!route) return hint;
    const { name, params = {} } = route;
    if (DRAWERS[name] || name === "home" || name === "settings" || name === "activity" || name === "monitors" || name === "monitoring" || name === "process" || name === "exchange") return name;
    if (name === "login") return "account";
    if (name === "settings-section") return params.section === "session" ? "account" : "settings";
    const me = state.status?.session?.username;
    return params.name && me && params.name.toLowerCase() === me.toLowerCase() ? "account" : null;
  }

  function drawActive() {
    active = derive();
    for (const a of [...items, acct]) {
      if (a.dataset.name === active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    if (active === "activity" && failed) { failed = false; drawDot(); }
    if (active === "search") find.setAttribute("aria-current", "page"); else find.removeAttribute("aria-current");
    moveInd();
  }

  // The pill under the active item glides to the next one (≥768px); hidden on the phone tab bar and when no item is active.
  function moveInd() {
    const a = side.matches ? items.find((x) => x.dataset.name === active && x.offsetParent !== null) : null;
    ind.parentNode.toggleAttribute("data-ind", side.matches);
    if (!a) { ind.style.opacity = "0"; return; }
    const first = !ind.style.transform;            // the first place is taken at once, not slid into from the top
    if (first) ind.style.transition = "none";
    ind.style.height = `${a.offsetHeight}px`;
    ind.style.transform = `translateY(${a.offsetTop}px)`;
    ind.style.opacity = "1";
    if (first) { void ind.offsetWidth; ind.style.transition = ""; }
  }

  function drawDot() {
    dots.forEach((d) => { d.hidden = !failed; });
    actLinks.forEach((a) => a.setAttribute("aria-label", failed ? FAILED_LABEL : "فعالیت"));
  }

  function drawAccount() {
    const s = state.status?.session, u = s?.username || null, lost = !!(u && s.lost_at);   // lost: Instagram threw it out
    if (`${u}|${lost}` === acctUser) return;
    acctUser = `${u}|${lost}`;
    const [face, label] = acct.children;
    mount(face, u ? avatar({ u, src: avatarUrl(u), size: 36, zoom: false }) : icon("user"));
    mount(label, h("span", { class: "sh-acct-name" }, u ? ltr(u) : "حساب"),
      h("span", { class: ["sh-acct-state", u && !lost ? "on" : "off"] }, h("i", { "aria-hidden": "true" }),
        !u ? "وارد نشده‌ای" : lost ? "بیرون افتاده؛ دوباره وارد شو" : "نشست فعال"));
    acct.setAttribute("aria-label", u ? `حساب ${u}` : "حساب");
  }

  function drawJob(s) {
    const busy = !!s?.busy;
    const wait = busy ? WAITING[s.state] : null;
    const key = busy ? `${s.state}|${s.mode}|${s.username || ""}` : "";
    if (key === jobKey) return;
    const was = jobKey;
    jobKey = key;
    stops.forEach((b) => { b.hidden = !busy; });
    for (const p of pills) {
      const appearing = busy && p.hidden;
      p.hidden = !busy;
      if (!busy) { p.replaceChildren(); continue; }
      fillPill(p, s, wait);
      if (appearing && p.offsetParent) enter(p, "pop");
      if (wait && !was.startsWith(`${s.state}|`)) pulse(p);
    }
  }

  let meterKey = "";
  function drawMeter(s) {
    const b = s?.budget;
    if (!b) return;
    const used = b.used.page.hour, cap = b.limits.pages_hour, key = `${used}/${cap}`;
    if (key === meterKey) return;
    meterKey = key;
    const r = cap ? Math.min(1, used / cap) : 0;
    gauge.querySelector(".sh-meter-val").textContent = `${faNum(used)} از ${faNum(cap)}`;
    gauge.querySelector(".sh-meter-bar i").style.setProperty("--p", r);
    gauge.dataset.t = r >= 1 ? "bad" : r >= 0.8 ? "warn" : "ok";
  }

  function drawCooldown(s) {
    const c = s?.budget?.cooldown;
    const on = !!(c && c.until * 1000 > Date.now());
    const key = on ? String(c.until) : "";
    if (key === coolKey) return;
    coolKey = key;
    for (const line of cools) {
      line.hidden = !on;
      if (!on) { line.replaceChildren(); continue; }
      mount(line, icon("hourglass", { size: "sm" }), h("span", { class: "sh-cool-text sh-tip" },
        "مکث تا ", h("bdi", { class: "num", text: faTime(c.until) }), " — اینستاگرام گفت صبر کن"));
    }
  }

  function showDrawer(view) {
    if (view === drawerEl) return;
    const opening = !drawerEl;
    drawerEl = view || null;
    panel.getAnimations().forEach((a) => a.cancel());
    if (view) {
      drawerName = route && DRAWERS[route.name] ? route.name : drawerName;
      panel.setAttribute("aria-label", DRAWERS[drawerName] || "پنل");
      if (opening && !side.matches) phoneY = window.scrollY;
      mount(panel, view);
      panel.hidden = false;
      if (!opening) { enter(view, "fade"); return; }      // another drawer's content: a crossfade, not a cut
      reflow(() => el.setAttribute("data-drawer", ""));
      if (!side.matches) window.scrollTo({ top: 0 });
      enter(panel, side.matches ? "drawer" : "fade");
      return;
    }
    const hadFocus = panel.contains(document.activeElement);
    reflow(() => el.removeAttribute("data-drawer"));
    const done = () => { if (!drawerEl) { panel.hidden = true; panel.replaceChildren(); panel.getAnimations().forEach((a) => a.cancel()); } };
    if (side.matches) exit(panel, "drawer").then(done);
    else { done(); window.scrollTo({ top: phoneY }); }
    if (hadFocus) items.find((a) => a.dataset.name === drawerName)?.focus({ preventScroll: true });
  }

  // Closing a drawer returns to the page under it; history.back() when the page was the step before.
  function closeDrawer() {
    if (!drawerEl) return;
    if (fromPage) back(pagePath);
    else navigate(pagePath, { replace: true });
  }

  const offs = [
    subscribe("route", (r) => {
      if (DRAWERS[r.name]) fromPage = !!route && !DRAWERS[route.name];
      else pagePath = r.path;
      route = r;
      drawActive();
    }),
    subscribe("status", (s) => { drawJob(s); drawCooldown(s); drawMeter(s); drawAccount(); drawActive(); }),
    subscribe("online", (v) => { offline.hidden = !!v; }),
    subscribe("job-end", (s) => { if (s.state === "failed" && active !== "activity") { failed = true; drawDot(); } }),
    on(side, "change", setRail),
    on(wide, "change", () => morph(setRail)),
    on(roomy, "change", () => morph(setRail)),
    on(document, "keydown", (e) => {
      if (e.key === "Escape" && drawerEl && !e.defaultPrevented && !document.documentElement.hasAttribute("data-overlay")) closeDrawer();
    }),
    // A click beside the open drawer closes it: on the page, or on the dimmed backdrop (the column's ::after).
    on(col, "click", (e) => {
      if (drawerEl && side.matches && !panel.contains(e.target) && !e.target.closest("a[href], button")) closeDrawer();
    }),
  ];
  // The open drawer's own item closes it again (Instagram's search panel does the same).
  for (const a of [...items, ...actLinks]) {
    on(a, "click", (e) => {
      const name = a.dataset.name || "activity";
      if (drawerEl && DRAWERS[name] && active === name && !e.metaKey && !e.ctrlKey) { e.preventDefault(); closeDrawer(); }
    });
  }

  setRail();
  drawAccount();
  drawActive();
  if (state.status) { drawJob(state.status); drawCooldown(state.status); drawMeter(state.status); }

  return {
    main,
    setActive(name) { hint = name; drawActive(); },
    showDrawer,
    destroy() { offs.forEach((off) => off()); },
  };
}
