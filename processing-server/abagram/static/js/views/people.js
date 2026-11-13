// People dialog: followers, following, likers of a post and similar accounts — Instagram's list, mirrored.
// open({u, kind, code}, ctx) → {close}. Rows come from saved data (free); reading asks Instagram via startJob.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { avatarUrl, getProfiles, getPeople, harvestList } from "../core/api.js";
import { mineOrAsk } from "../core/share.js";
import { faNum, faCompact, faDecimal, unit, ago, fresh } from "../core/format.js";
import { state, subscribe, dossier, pokePolling } from "../core/store.js";
import { navigate } from "../core/router.js";
import { avatar, verified, lock, button, iconButton, empty, skeleton, pagedList, listState, segmented, spinner, toast } from "../core/ui.js";
import { dialog, sheet } from "../core/overlay.js";
import { harvestEta } from "./pagejobs.js";
import { startJob, cost, runningFor } from "../core/jobs.js";

const TITLE = { followers: "فالوورها", following: "فالووینگ", likers: "لایک‌کنندگان", similar: "حساب‌های مشابه" };
const NEVER = {
  followers: "فالوورها هنوز خوانده نشده", following: "فالووینگ هنوز خوانده نشده",
  likers: "لایک‌کنندگان این پست هنوز خوانده نشده", similar: "حساب‌های مشابه هنوز خوانده نشده",
};
const NEVER_TEXT = {
  likers: "کامنت‌ها و لایک‌کنندگان این پست را یک بار از اینستاگرام بخوان؛ بعد همین‌جا بدون درخواست تازه باز می‌شود.",
  similar: "حساب‌هایی که اینستاگرام کنار این پروفایل پیشنهاد می‌دهد با خواندن دوبارهٔ پروفایل ذخیره می‌شوند.",
  list: "فهرست را یک بار از اینستاگرام بخوان؛ بعد همین‌جا بدون درخواست تازه باز می‌شود.",
};
const MODE = { followers: "follow", following: "follow", likers: "details", similar: "profile" };
const REASON = {
  empty: { icon: "users", text: "فهرست خالی است" },
  private: { icon: "lock", text: "حساب خصوصی است و دنبالش نمی‌کنی" },
  refused: { icon: "alert", text: "اینستاگرام فهرست را نداد" },
  no_link: { icon: "alert", text: "اینستاگرام لینک این فهرست را نشان نداد" },
  no_reply: { icon: "hourglass", text: "اینستاگرام جواب نداد؛ کمی بعد دوباره بخوان" },
  stalled: { icon: "alert", text: "فهرست وسط کار جلو نرفت؛ همین مقدار ذخیره شد" },
  budget: { icon: "gauge", text: "سقف ایمنی پر شد؛ همین مقدار ذخیره شد" },
  cooldown: { icon: "hourglass", text: "در مکثِ بعد از «صبر کن» ماند؛ بعد از مکث دوباره بخوان" },
};

// Saved profiles (local, free): username → {has_avatar, fetched_at}. The server gives at most 50 per page.
async function savedMap() {
  const map = new Map();
  for (let offset = 0, total = 1; offset < total && offset < 2000; offset += 50) {
    const r = await getProfiles(offset, 50).catch(() => null);
    const items = (r && r.ok && r.data && r.data.items) || [];
    if (!items.length) break;
    total = r.data.total || 0;
    for (const p of items) map.set(String(p.username).toLowerCase(), p);
  }
  return map;
}

/** The list this dialog shows, in one shape; null = never read. */
function pick(ds, kind, code) {
  if (kind === "likers") {
    const p = ds.details?.posts?.[code];
    return p ? { items: p.likers || [], total: p.likers_total, note: p.likers_note, error: p.error, read_at: p.read_at } : null;
  }
  if (kind === "similar") return ds.similar ? { items: ds.similar.items || [], read_at: ds.profile?.fetched_at } : null;
  const l = ds[kind];
  if (!l) return null;
  return { ...l, items: l.items || [], total: l.total ?? ds.profile?.[kind], approx: (ds.profile?.approx || []).includes(kind) };
}

// «۰٫۲٪» at the start (a whole number only says «۰٪» for the first thousand people), whole numbers from ten on
const pct = (n, total) => { const v = Math.min(100, (100 * n) / total); return v < 10 ? faDecimal(Math.floor(v * 10) / 10) : faNum(Math.floor(v)); };

const skelRows = () => Array.from({ length: 5 }, () => h("div", { class: "pp-row pp-sk", "aria-hidden": "true" },
  h("span", { class: "pp-av" }, skeleton("avatar")), h("span", { class: "pp-who" }, skeleton("line", 2))));

export function open({ u, kind = "followers", code } = {}, ctx = {}) {
  if (!TITLE[kind]) kind = "followers";
  const word = kind === "similar" ? "حساب" : "نفر";
  const key = `pp:${String(u).toLowerCase()}:${kind}:${code || ""}`;
  let ds = null, saved = new Map(), list = null, plist = null, q = "", tab = "all", gone = false, external = false, loadedAt = 0, liveKey = "", heroKey = "";
  const whole = kind === "followers" || kind === "following";
  // the queue's task of this list that is still alive (a finished one must never make the button look free)
  const liveTask = () => (state.status?.queue?.tasks || []).find((t) => t.kind === "harvest" && t.username === String(u).toLowerCase()
    && ["waiting", "running", "paused"].includes(t.state)) || null;
  const readingNow = () => { const s = state.status; return !!(s?.busy && s.mode === "harvest" && String(s.username || "").toLowerCase() === String(u).toLowerCase()); };
  const TABS = [["all", "همه"], ["public", "عمومی"], ["private", "خصوصی"], ["read", "پروفایل خوانده‌شده"]];
  const inTab = (p, t = tab) => t === "all" || (t === "public" && !p.private) || (t === "private" && p.private)
    || (t === "read" && saved.has(String(p.username || "").toLowerCase()));

  const input = h("input", {
    class: "input pp-q", type: "search", dir: "auto", placeholder: "جستجو در این فهرست", "aria-label": "جستجو در این فهرست",
    autocomplete: "off", spellcheck: "false", enterkeyhint: "search", oninput: () => { q = input.value; filter(); },
  });
  const clear = iconButton({ icon: "x", label: "پاک کردن جستجو", size: "sm", cls: "pp-clear",
    onClick: () => { input.value = ""; q = ""; filter(); input.focus(); } });
  clear.hidden = true;
  const found = h("p", { class: "pp-found", "aria-live": "polite", hidden: true });
  const noMatch = h("p", { class: "pp-none" });
  const segBox = h("div", { class: "pp-tabs" });
  const hero = h("div", { class: "pp-hero", hidden: true });
  const top = h("div", { class: "pp-top", hidden: true },
    h("div", { class: "pp-tools" }, h("div", { class: "pp-search" }, icon("search", { size: "sm" }), input, clear), segBox), found);
  const main = h("div", { class: "pp-main" }, skelRows());
  const foot = h("div", { class: "pp-foot" });
  const offs = [];
  const d = dialog({
    title: TITLE[kind], content: h("div", { class: "pp-body" }, hero, top, main), actions: foot, cls: whole ? "pp-dlg pp-wide" : "pp-dlg",
    size: matchMedia("(max-width: 767px)").matches ? "full" : whole ? "lg" : "sm",
    onClose: () => { gone = true; offs.forEach((off) => off()); if (!external) ctx.dismiss?.(); },
  });
  foot.parentElement.hidden = true;

  // ---- reading from Instagram (each one opens the cost sheet first) ----
  function readList() {
    if (kind === "likers") return startJob("details", { username: u, codes: [code] }, { lines: cost("details", { codes: [code] }) });
    if (kind === "similar") return startJob("profile", { username: u, fresh: true }, { lines: cost("profile") });
    return startJob("follow", { username: u, which: [kind] }, { lines: cost("follow", { profile: ds?.profile, which: [kind] }) });
  }

  // ---- the WHOLE list, slowly, through the queue (ig_harvest): his choice after a sheet that says how long it takes ----
  function harvestBtn() {
    const t = liveTask(), live = !!t && t.state !== "paused";
    const all = list?.harvest?.done;
    if (all) return null;
    if (live) return h("a", { class: "btn md full pp-live", href: "#/activity" }, readingNow() ? spinner(16) : icon("hourglass", { size: "sm" }),
      h("span", { text: readingNow() ? `در حال خواندن همهٔ ${TITLE[kind]}؛ دیدن در «فعالیت»` : `خواندن همهٔ ${TITLE[kind]} در صف است؛ دیدن در «فعالیت»` }));
    // started before (a saved position to go on from): say that it continues, and from which person
    const from = list?.harvest?.next ? (list.items?.length || 0) + 1 : null;
    return button({ label: from ? `ادامهٔ خواندن همهٔ ${TITLE[kind]} (از نفر ${faNum(from)})` : `خواندن همهٔ ${TITLE[kind]}`,
      icon: "users", kind: "primary", full: true, onClick: () => askHarvest() });
  }

  function askHarvest() {
    const total = list?.total ?? ds?.profile?.[kind];
    const lim = state.status?.budget?.limits || {};
    const pages = Number.isFinite(total) ? Math.ceil(total / 12) : null;
    const hours = pages ? Math.max(1, Math.ceil(pages / Math.min(lim.harvests_hour || 60, 3600 / (lim.harvest_scroll || 30)))) : null;
    const days = pages ? Math.max(1, Math.ceil(pages / (lim.harvests_day || 1000))) : null;
    const go = button({ label: "شروع خواندن کامل", kind: "primary", full: true, onClick: async () => {
      const r = await mineOrAsk((force) => harvestList(u, [kind], force)).catch(() => null);
      sh.close();
      if (r?.declined) return;
      if (r?.ok) { toast(`خواندن همهٔ ${TITLE[kind]} @${u} در صف گذاشته شد`, { tone: "ok" }); pokePolling(); drawFoot(); }
      else toast("شروع نشد.", { tone: "danger" });
    } });
    const lines = [
      pages ? [bdi(unit(total, "نفر")), " یعنی حدود ", bdi(unit(pages, "صفحه")), " دوازده‌نفره"] : ["تعداد این فهرست هنوز معلوم نیست"],
      hours ? ["با سقف فعلی حدود ", bdi(unit(hours, "ساعت")), " کار؛ چون سقف روزانه هم هست، حدود ", bdi(unit(days, "روز"))] : null,
      ["هر نوبت چند ده صفحه با مکث می‌خواند و ذخیره می‌کند؛ اگر سقف پر شد یا برنامه بسته شد، بعداً از همان‌جا ادامه می‌دهد"],
      ["اگر اینستاگرام بگوید صبر کن، خودش مکث می‌کند؛ سه بار پشت سر هم، متوقف می‌شود تا خودت ادامه بدهی"],
    ].filter(Boolean);
    const sh = sheet({ title: `خواندن همهٔ ${TITLE[kind]}`, actions: [go, button({ label: "انصراف", kind: "ghost", full: true, onClick: () => sh.close() })],
      content: h("div", { class: "pj-sheet" }, h("p", { class: "pj-who" }, ltr(`@${u}`)),
        h("ul", { class: "pj-steps" }, lines.map((l) => h("li", {}, ...l))),
        h("p", { class: "pj-note", text: "سرعت را در «تنظیمات › محدودیت‌ها» (خواندن کامل فهرست) عوض کن." })) });
  }

  async function readProfile(name) {
    const r = await startJob("profile", { username: name, fresh: false }, { lines: cost("profile") });
    if (r?.ok && !gone) (ctx.navigate || navigate)(`/u/${name}`);
  }

  function readBtn(primary) {
    const cap = state.status?.budget?.limits?.[kind];
    const label = kind === "likers" ? "خواندن کامنت و لایک‌کنندگان"
      : kind !== "similar" && Number.isFinite(cap) && list?.harvest ? `خواندن تازه‌ترین‌ها (${faNum(cap)} نفر اول فهرست)`   // not where the whole read stopped
      : kind !== "similar" && Number.isFinite(cap) ? `خواندن از اینستاگرام (تا ${faNum(cap)} نفر)` : "خواندن از اینستاگرام";
    const running = runningFor(u) && state.status?.mode === MODE[kind];
    return button({ label, icon: primary ? null : "refresh", kind: primary ? "primary" : "secondary", full: true, busy: running, onClick: readList });
  }

  // ---- one person: avatar (opens big), name, the action at the inline end ----
  function row(it) {
    const name = it.username || "";
    const s = saved.get(name.toLowerCase());
    const src = s?.has_avatar ? avatarUrl(name, s.fetched_at) : it.default_avatar ? null : it.avatar || null;
    const ring = runningFor(name) ? "loading" : fresh(it.story_at) ? "story" : null;
    const href = `#/u/${name}`;
    const tags = [
      s ? h("span", { class: "pp-tag is-ok", text: "پروفایل خوانده شد" }) : null,
      s?.is_business ? h("span", { class: "pp-tag", text: "کسب‌وکار" }) : null,
      s?.category ? h("span", { class: "pp-tag" }, bdi(s.category)) : null,
    ].filter(Boolean);
    return h("div", { class: ["pp-row", s && "is-read"] },
      h("span", { class: "pp-av" }, avatar({ u: name, src, size: 48, ring })),
      h("a", { class: "pp-who", href, tabindex: s ? "-1" : null },
        h("span", { class: "pp-name" }, ltr(name), it.verified ? verified() : null, it.private ? lock() : null,
          s && Number.isFinite(s.followers) ? h("span", { class: "pp-fcount", text: `${faCompact(s.followers)} فالوور` }) : null),
        it.full_name ? h("bdi", { class: "pp-full", text: it.full_name }) : null,
        tags.length ? h("span", { class: "pp-tags" }, tags) : null),
      s ? h("a", { class: "btn sm pp-act", href, text: "نمایش", "aria-label": `نمایش ${name}` })
        : button({ label: "خواندن", kind: "secondary", size: "sm", cls: "pp-act", title: `خواندن پروفایل ${name}`, onClick: () => readProfile(name) }));
  }

  // ---- filter: counts say how many of how many match ----
  function filter(keepPage = false) {
    if (!list || !plist) return;
    const needle = q.trim().replace(/^@/, "").toLowerCase();
    const rows = list.items.filter((p) => inTab(p) && (!needle || `${p.username || ""} ${p.full_name || ""}`.toLowerCase().includes(needle)));
    const narrowed = !!needle || tab !== "all";
    clear.hidden = !q;
    found.hidden = !narrowed;
    found.replaceChildren(...(narrowed ? [bdi(unit(rows.length, word)), " از ", bdi(unit(list.items.length, word))] : []));
    noMatch.replaceChildren(...(needle ? [kind === "similar" ? "حسابی با «" : "کسی با «", bdi(q.trim()), "» پیدا نشد"] : ["کسی در این دسته نیست"]));
    if (!keepPage) listState(key).page = 0;
    plist.redraw(rows);
  }

  // ---- the filter tabs (followers / following): how many each one holds ----
  function drawTabs() {
    if (!list || !whole) return mount(segBox);
    mount(segBox, segmented({ label: "کدام افراد", value: tab,
      options: TABS.map(([v, l]) => ({ value: v, label: `${l} (${faNum(list.items.filter((p) => inTab(p, v)).length)})` })),
      onChange: (v) => { tab = v; filter(); } }));
  }

  // ---- the head of a whole list: how many of how many, the bar, and what the reading does right now ----
  function drawHero() {
    if (!list || !whole || !list.items.length) { hero.hidden = true; return; }
    const n = list.items.length, total = Number.isFinite(list.total) ? list.total : null, t = liveTask(), now = readingNow();
    const eta = t && total ? harvestEta(total, n, null) : null;
    const st = list.harvest?.done ? ["ok", "circle-check", "همهٔ فهرست خوانده شده"]
      : now ? ["live", null, `در حال خواندن همهٔ ${TITLE[kind]}، مثل اسکرول دست` + (eta ? `؛ ${eta.text}` : "")]
      : t?.state === "waiting" ? ["idle", "hourglass", t.note || "در صف است و خودش ادامه می‌دهد"]
      : t?.state === "paused" ? ["warn", "alert", t.note || "متوقف شده؛ «ادامه» را بزن"]
      : list.harvest ? ["idle", "info", "خواندن کامل نیمه‌کاره مانده؛ دکمهٔ پایین از همان‌جا ادامه می‌دهد"]
      : ["idle", "info", list.read_at ? `آخرین خواندن ${ago(list.read_at)}` : ""];
    const hk = JSON.stringify([n, total, st[0], st[2]]);
    if (hk === heroKey && !hero.hidden) return;   // a poll every second must not rebuild it (nor restart the spinner)
    heroKey = hk;
    hero.hidden = false;
    mount(hero,
      h("div", { class: "pp-hero-num" }, h("b", { class: "pp-big" }, bdi(faNum(n))),
        h("span", { class: "pp-of" }, ...(total ? ["از ", bdi(`${list.approx ? "حدود " : ""}${faCompact(total)}`),
          ` ${kind === "following" ? "فالووینگ" : "فالوور"} خوانده شده`] : [" نفر خوانده شده"])),
        total ? h("span", { class: "pp-pct", text: `${pct(n, total)}٪` }) : null),
      total ? h("span", { class: "pj-bar pp-bar", "aria-hidden": "true" }, h("i", { style: `--p:${Math.min(1, n / total)}` })) : null,
      st[2] ? h("p", { class: ["pp-line", `is-${st[0]}`] }, st[1] ? icon(st[1], { size: "sm" }) : spinner(14), h("span", { text: st[2] })) : null);
  }

  // ---- footer: what was read, Instagram's notes, and the read action ----
  function drawFoot() {
    foot.parentElement.hidden = !list;
    if (!list) return foot.replaceChildren();
    const n = list.items.length, notes = [];
    const note = (ic, tone, ...txt) => notes.push(h("li", { class: ["pp-note", tone && `pp-${tone}`] }, icon(ic, { size: "sm" }), h("span", {}, ...txt)));
    const why = REASON[list.reason];
    if (n && why) note(why.icon, "warn", why.text);
    if (list.limited) note("alert", "warn", "اینستاگرام فهرست این حساب را کوتاه نشان می‌دهد");
    if (typeof list.hidden === "number" && list.hidden > 0) note("eye-off", null, bdi(unit(list.hidden, "نفر")), " پنهان");
    if (typeof list.note === "string" && list.note) note("alert", null, bdi(list.note));
    if (list.error) note("alert", "warn", "خواندن لایک‌کنندگان کامل نشد؛ دوباره بخوان");
    if (list.harvest?.done) note("circle-check", null, "همهٔ فهرست خوانده شده");
    const count = kind !== "similar" && Number.isFinite(list.total)
      ? [bdi(unit(n, word)), " از ", bdi(`${list.approx ? "حدود " : ""}${faCompact(list.total)} ${word}`), " خوانده شده"]
      : [bdi(unit(n, word)), kind === "similar" ? " مشابه" : " خوانده شده"];
    mount(foot,
      n && !whole ? h("div", { class: "pp-sum" }, h("p", { class: "pp-count" }, ...count),
        list.read_at ? h("p", { class: "pp-when", text: `آخرین خواندن ${ago(list.read_at)}` }) : null) : null,
      notes.length ? h("ul", { class: "pp-notes" }, notes) : null,
      readBtn(!n),
      kind === "followers" || kind === "following" ? harvestBtn() : null);
  }

  function showState(el) {
    top.hidden = true;
    plist = null;
    main.replaceChildren(h("div", { class: "pp-state" }, el));
  }

  function draw() {
    if (gone) return;
    list = ds ? pick(ds, kind, code) : null;
    drawFoot();
    if (!ds) {
      return showState(empty({ icon: "alert", title: "اطلاعات ذخیره‌شده باز نشد",
        text: "برنامه جواب نداد. اگر پنجرهٔ برنامه بسته شده، دوباره اجرایش کن و بعد امتحان کن.",
        action: button({ label: "دوباره امتحان کن", icon: "refresh", onClick: () => load() }) }));
    }
    if (!list) {
      return showState(empty({ icon: kind === "likers" ? "heart" : "users", title: NEVER[kind],
        text: NEVER_TEXT[kind] || NEVER_TEXT.list, action: readBtn(true) }));
    }
    if (!list.items.length) {
      const why = REASON[list.reason] || REASON.empty;
      return showState(empty({ icon: why.icon, title: why.text, text: list.read_at ? `آخرین خواندن ${ago(list.read_at)}` : null }));
    }
    top.hidden = false;
    drawTabs();
    drawHero();
    plist = pagedList({ key, items: list.items, row, emptyEl: noMatch, cls: whole ? "pp-list pp-grid" : "pp-list", label: TITLE[kind],
      per: whole && matchMedia("(min-width: 900px)").matches ? 2 : 1 });   // two columns: a page is still 5/10/15/20 rows
    main.replaceChildren(plist);
    if (q || tab !== "all") filter();
  }

  async function load(quiet = false) {
    if (!quiet) { top.hidden = true; main.replaceChildren(...skelRows()); }
    const [x, m] = await Promise.all([dossier(u), savedMap()]);
    if (gone) return;
    ds = x;
    if (ds?.[kind]?.trimmed) {          // a long list: the dossier has only its head, the whole of it comes on its own
      const r = await getPeople(u, kind).catch(() => null);
      if (gone) return;
      if (r?.ok && r.data?.items) ds = { ...ds, [kind]: r.data };
    }
    saved = m;
    loadedAt = Date.now();
    if (quiet && plist && pick(ds, kind, code)?.items?.length) {   // while the list grows: new numbers, same page, no flicker
      list = pick(ds, kind, code);
      drawFoot(); drawTabs(); drawHero(); filter(true);
      return;
    }
    draw();
  }

  // A job that starts spins its rings and button; a job that ends brings fresh saved data (store dropped the cache).
  offs.push(
    subscribe("job-start", () => { if (list) { drawFoot(); plist?.redraw(); } }),
    subscribe("job-end", () => load(true)),
    subscribe("status", () => {   // the whole list is being read: its head says so, and every half minute the rows grow
      if (!list || !whole) return;
      drawHero();
      const k = JSON.stringify([liveTask()?.state, readingNow()]);
      if (k !== liveKey) { liveKey = k; drawFoot(); }
      if (readingNow() && Date.now() - loadedAt > 30000) load(true);
    }),
  );
  load();

  return {
    close() {
      if (gone || external) return;
      external = true;
      d.close();
    },
  };
}
