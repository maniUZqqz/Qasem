// Profile page (#/u/<name>, /reels, /about): Instagram's profile header mirrored for RTL, the highlights tray and the
// tab bar. Tab contents come from profile-tabs.js. Data: store.dossier + store.files; reloads on the person's job-end.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { faNum, faCompact, faDateTime, ago, fresh } from "../core/format.js";
import { avatarUrl, thumbUrl, alive, igUrl, exportUrl } from "../core/api.js";
import * as store from "../core/store.js";
import { button, iconButton, avatar, verified, lock, empty, skeleton, stat, toast, setBusy } from "../core/ui.js";
import { dialog, menu } from "../core/overlay.js";
import { startJob, cost, runningFor, KIND, forget } from "../core/jobs.js";
import { navigate } from "../core/router.js";
import { enter, animate, DUR, reduced } from "../core/motion.js";
import { jobBar } from "./jobbar.js";
import { fullButton, watchButton, taskPanel, privateCard, readingHighlight } from "./pagejobs.js";

// Loaded lazily: the header keeps working even if the tabs module fails. Renderers get (el, d, ctx).
const tabsModule = import("./profile-tabs.js").catch((e) => { console.error(e); return null; });
const TABS = [
  { key: "posts", icon: "grid", label: "پست‌ها", path: "", fn: "renderPosts" },
  { key: "reels", icon: "film", label: "ریلز", path: "/reels", fn: "renderReels" },
  { key: "about", icon: "info", label: "درباره", path: "/about", fn: "renderAbout" },
];
const APPROX = { followers: "عدد فالوور گرد شده است", following: "عدد فالووینگ گرد شده است", posts: "عدد پست گرد شده است" };
const secs = (v) => (typeof v === "number" ? v : (Date.parse(v) || 0) / 1000);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
const host = (u) => { try { return new URL(u).host.replace(/^www\./, ""); } catch { return u; } };
const ext = (cls, href, ...kids) => h("a", { class: cls, href, target: "_blank", rel: "noopener noreferrer" }, ...kids);

// Biography as text nodes: @mentions open the person here, #hashtags open Instagram. Never parsed as HTML.
function bioNodes(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(/@([A-Za-z0-9._]{1,30})|#([\p{L}\p{N}_‌]+)/gu)) {
    if (m.index && /[\p{L}\p{N}_]/u.test(text[m.index - 1])) continue;   // e-mail addresses and a#b are not tags
    const word = m[1] ? m[1].replace(/\.+$/, "") : m[2];
    if (!word) continue;
    out.push(text.slice(last, m.index));
    out.push(m[1]
      ? h("a", { class: "pf-tag", href: `#/u/${word.toLowerCase()}` }, ltr(`@${word}`))
      : ext("pf-tag", igUrl(`/explore/tags/${encodeURIComponent(word)}/`), bdi(`#${word}`)));
    last = m.index + 1 + word.length;
  }
  out.push(text.slice(last));
  return out;
}

const linksDialog = (links) => dialog({ title: "لینک‌ها", size: "sm", content: h("ul", { class: "pf-linklist" }, links.map((l) =>
  h("li", null, ext("pf-linkrow", l.url, h("span", { class: "pf-linkrow-ic" }, icon("link")), h("span", { class: "pf-linkrow-t" },
    l.title ? bdi(l.title) : ltr(host(l.url)), l.title ? h("small", null, ltr(host(l.url))) : null))))) });

function bio(p) {
  const links = (p.links || []).filter((l) => safeUrl(l.url)), first = links[0];
  const pron = p.pronouns?.length ? h("span", { class: "pf-pron" }, bdi(p.pronouns.join("/"))) : null;
  return h("div", { class: "pf-bio" },
    p.full_name || pron ? h("p", { class: "pf-name" }, p.full_name ? bdi(p.full_name) : null, pron) : null,
    p.category ? h("p", { class: "pf-cat" }, bdi(p.category)) : null,
    p.biography ? h("p", { class: "pf-text" }, bioNodes(p.biography)) : null,
    first ? h("p", { class: "pf-links" },
      ext("pf-link", first.url, icon("link", { size: "sm" }), first.title ? bdi(first.title) : ltr(host(first.url))),
      links.length > 1 ? h("button", { type: "button", class: "pf-link-more", text: `و ${faNum(links.length - 1)} مورد دیگر`,
        onclick: () => linksDialog(links) }) : null) : null,
    p.mutual_text ? h("p", { class: "pf-mutual" }, bdi(p.mutual_text)) : null);
}

// 'story' = a saved story that has not expired; 'seen' = Instagram reports a fresh story that was not read yet.
function storyRing(d) {
  const st = d.stories, at = d.profile.more?.story_at;
  if ((st?.reel?.items || []).some((it) => secs(it.expires_at) > Date.now() / 1000)) return "story";
  return at && fresh(at) && !(st?.read_at && secs(st.read_at) >= at) ? "seen" : null;
}

// The profile avatar: 150px, 86px on phones (CSS sets --pf-av).
const bigAvatar = (opts) => { const el = avatar({ size: 150, ...opts }); el.style.setProperty("--av", "var(--pf-av)"); return el; };

const copyJson = (p) => Promise.resolve().then(() => navigator.clipboard.writeText(JSON.stringify(p, null, 2))).then(() => toast("اطلاعات پروفایل کپی شد", { tone: "ok" }),
  () => toast("کپی نشد؛ مرورگر اجازهٔ نوشتن در کلیپ‌بورد را نداد.", { tone: "danger" }));

function moreItems(d, name) {
  const p = d.profile, cap = store.state.status?.budget?.limits?.highlights || 3;
  const job = (kind, body = {}) => () => startJob(kind, { username: name, ...body }, { lines: cost(kind, { profile: p, ...body }) });
  const unread = (d.highlights?.items || []).filter((x) => !d.reels?.highlights?.[x.id]).map((x) => x.id).slice(0, cap);
  return [
    { icon: "circle-play", label: "خواندن استوری فعال", onSelect: job("stories") },
    { icon: "layers", label: "خواندن آیتم‌های هایلایت‌ها", disabled: !d.highlights?.items?.length,
      hint: unread.length ? `${faNum(unread.length)} هایلایت خوانده‌نشده` : null, onSelect: job("highlights", unread.length ? { ids: unread } : {}) },
    { icon: "grid", label: "خواندن پست‌های بیشتر", onSelect: job("posts") },
    { icon: "comment", label: "خواندن کامنت و لایک‌کنندگان پست‌های اخیر", onSelect: job("details") },
    { icon: "download", label: "دانلود عکس و ویدیوی پست‌ها", hint: "بدون درخواست به اینستاگرام", disabled: !d.posts?.items?.length,
      onSelect: job("download", { target: "posts", videos: true }) },
    { icon: "open", label: "باز کردن در اینستاگرام", onSelect: () => window.open(igUrl(`/${name}/`), "_blank", "noopener") },
    { icon: "braces", label: "کپی اطلاعات (JSON)", onSelect: () => copyJson(p) },
    { icon: "trash", label: "حذف از ذخیره‌ها", danger: true, hint: "فقط از این کامپیوتر",
      onSelect: () => forget(name).then((ok) => { if (ok) navigate("/", { replace: true }); }) },
  ];
}

function header(d, name, ctx, refs) {
  const p = d.profile, ring = storyRing(d), go = (path) => () => ctx.navigate(`/u/${name}${path}`);
  const src = p.has_avatar ? avatarUrl(name, p.fetched_at) : alive(p.avatar_remote) ? p.avatar_remote : null;
  refs.avBox = h("div", { class: "pf-av" });
  refs.mkAv = (busy) => bigAvatar({ u: name, src, ring: busy ? "loading" : ring, onClick: ring ? go("/stories") : null,
    label: ring ? "دیدن استوری" : null });
  refs.busy = button({ label: "تازه‌سازی", kind: "primary", size: "sm",
    onClick: () => startJob("profile", { username: name, fresh: true }, { lines: cost("profile", { profile: p }) }) });
  const count = (k, label, path) => { const s = stat(faCompact(p[k]), label, path ? go(path) : null);
    if (p[k] != null) s.title = `${faNum(p[k])} ${label}`; return h("li", null, s); };
  return h("header", { class: "pf-head" }, refs.avBox,
    h("div", { class: "pf-info" },
      h("div", { class: "pf-row1" },
        h("div", { class: "pf-title" }, h("h1", { class: "pf-user", title: p.username || name }, ltr(p.username || name)),
          p.is_verified ? verified() : null, p.is_private ? lock() : null),
        h("div", { class: "pf-actions" }, refs.busy, fullButton(name), watchButton(name), button({ label: "فالوورها", size: "sm", onClick: go("/followers") })),
        iconButton({ icon: "more", label: "بیشتر", cls: "pf-more",
          onClick: (e) => menu(e.currentTarget, moreItems(d, name), { label: "کارهای این پروفایل" }) })),
      h("ul", { class: "pf-stats", "aria-label": "آمار" },
        count("posts", "پست"), count("followers", "فالوور", "/followers"), count("following", "فالووینگ", "/following")),
      bio(p),
      h("p", { class: "pf-fresh", title: faDateTime(p.fetched_at) }, icon("clock", { size: "sm" }),
        h("span", { text: `خوانده‌شده ${ago(p.fetched_at)}` }),
        (p.approx || []).filter((k) => APPROX[k]).map((k) => h("span", { class: "pf-approx", text: APPROX[k] })))));
}

function highlights(d, name, ctx) {
  const items = d.highlights?.items || [], read = d.reels?.highlights || {};
  if (!items.length) return null;
  const open = (it) => (read[it.id] ? ctx.navigate(`/u/${name}/hl/${it.id}`)
    : readingHighlight(name, it.id) ? null : startJob("highlights", { username: name, ids: [it.id] }, { confirm: false }));
  return h("section", { class: "pf-hls", "aria-label": "هایلایت‌ها" }, h("ul", { class: "pf-hl-row" }, items.map((it) => {
    const src = it.has_cover ? thumbUrl(name, `hl_${it.id}`, d.profile.fetched_at) : alive(it.cover) ? it.cover : null;
    const title = it.title || "هایلایت";
    return h("li", null, h("button", { type: "button", class: ["pf-hl", !read[it.id] && "pf-hl-new", readingHighlight(name, it.id) && "is-busy"], "data-hl": it.id, onclick: () => open(it),
      "aria-label": read[it.id] ? title : `${title}، هنوز خوانده نشده` },
      h("span", { class: "pf-hl-ring" }, h("span", { class: "pf-hl-face" }, icon("circle-play"),
        src ? h("img", { src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer",
          onerror: (e) => e.currentTarget.remove() }) : null)),
      h("bdi", { class: "pf-hl-t", text: title })));   // a bdi clips in its own direction: Latin titles keep their start
  })));
}


// «JSONِ این پیج» (his order 2026-11-05): every page has its download — all that is saved about it, its whole lists with
// each follower's own saved profile (ig_export). The chips say what the file holds; nothing is asked of Instagram.
function jsonStrip(d, name) {
  const n = (x) => (x ? (x.count ?? x.items?.length ?? 0) : 0);   // the dossier carries a long list's head + its count
  const held = [["پروفایل", 1], ["پست", d.posts?.items?.length], ["هایلایت", d.highlights?.items?.length],
    ["فالوور", n(d.followers)], ["فالووینگ", n(d.following)]].filter(([, k]) => k);
  return h("section", { class: "pf-json", "aria-labelledby": "pf-json-h" },
    h("span", { class: "pf-json-ic" }, icon("braces")),
    h("div", { class: "pf-json-t" }, h("h2", { class: "pf-json-h", id: "pf-json-h", text: "JSONِ این پیج" }),
      h("p", { class: "pf-json-s" }, held.map(([word, k], i) => h("bdi", { class: "pf-json-part", text: i ? `${faNum(k)} ${word}` : word })),
        n(d.followers) || n(d.following) ? h("span", { class: "pf-json-more", text: "با پروفایلِ هر فالووری که خوانده شده" }) : null)),
    h("a", { class: "btn sm pf-json-go", href: exportUrl(name), download: "" }, icon("download", { size: "sm" }), h("span", { text: "دریافت JSON" })));
}

const tabBar = (name, active) => h("nav", { class: "pf-tabs", "aria-label": "بخش‌های پروفایل" }, TABS.map((t) =>
  h("a", { class: "pf-tab", href: `#/u/${name}${t.path}`, "data-tab": t.key, "aria-current": t.key === active ? "page" : null },
    icon(t.icon, { size: "sm" }), h("span", { text: t.label }))));

// Another tab: the line over the active tab glides across to it (a short-lived copy; at rest it is the tab's own border).
function slideTabLine(bar, active) {
  const tabs = [...bar.querySelectorAll(".pf-tab")];
  const old = tabs.find((a) => a.hasAttribute("aria-current")), next = tabs.find((a) => a.dataset.tab === active);
  tabs.forEach((a) => (a === next ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (!old || !next || old === next || reduced()) return;
  bar.querySelector(".pf-tabs-line")?.remove();
  const box = bar.getBoundingClientRect(), from = old.getBoundingClientRect(), to = next.getBoundingClientRect();
  const line = h("i", { class: "pf-tabs-line", "aria-hidden": "true", style: `left:${to.left - box.left}px;width:${to.width}px` });
  bar.append(line);
  next.classList.add("is-gliding");
  animate(line, [{ transform: `translateX(${from.left - to.left}px) scaleX(${from.width / to.width})` }, { transform: "none" }], { dur: DUR.enter })
    .then(() => { line.remove(); next.classList.remove("is-gliding"); });
}

// The placeholder header (loading, or a profile never read): the name is known, the rest is grey.
const skHead = (name, av, still) => h("header", { class: ["pf-skhead", still && "pf-still"] }, h("div", { class: "pf-av" }, av),
  h("div", { class: "pf-sklines" }, h("h1", { class: "pf-user" }, ltr(name)), skeleton("line", 3)));

export function render(params, ctx) {
  const el = h("div", { class: "pf" });
  const body = h("div", { class: "pf-body" });
  let name = String(params.name).toLowerCase(), tab = params.tab || "posts";
  let data = null, refs = {}, loadSeq = 0, tabSeq = 0, tabInst = null, dead = false;
  const bar = jobBar(() => name);   // spinner + latest line + «لغو» while a job reads this person
  const tasksBox = taskPanel(() => name);   // «استخراج کامل» / follow-request progress from the queue
  let lockCard = null;

  function syncRunning() {   // the spinning ring and the busy button while a job reads this person
    for (const b of el.querySelectorAll(".pf-hl[data-hl]")) b.classList.toggle("is-busy", readingHighlight(name, b.dataset.hl));
    const busy = runningFor(name);
    if (busy === refs.running) return;
    refs.running = busy;
    if (refs.busy) setBusy(refs.busy, busy);
    if (refs.mkAv) refs.avBox.replaceChildren(refs.mkAv(busy));
  }

  async function drawTab(fade) {
    const my = ++tabSeq, mod = await tabsModule;
    if (dead || my !== tabSeq || !data) return;
    tabInst?.destroy?.(); tabInst = null; body.replaceChildren();
    const fn = mod?.[TABS.find((t) => t.key === tab)?.fn];
    if (fn) tabInst = fn(body, data, ctx);
    else body.append(empty({ icon: "grid", title: "این بخش باز نشد", text: "صفحه را دوباره باز کن." }));
    if (fade) enter(body, "fade");
  }

  function drawMissing() {   // never read, not on Instagram, or our own server is down
    const s = store.state.status, lost = s?.outcome?.kind === "not_found" && (s.username || "").toLowerCase() === name;
    const read = button({ label: "خواندن از اینستاگرام", kind: "primary", onClick: () => startJob("profile", { username: name }) });
    const box = !store.state.online ? empty({ icon: "globe", title: "برنامه در دسترس نیست",
      text: "سرور برنامه جواب نمی‌دهد. اجرایش کن؛ این صفحه خودش دوباره تلاش می‌کند.", action: button({ label: "دوباره امتحان کن", onClick: () => load() }) })
      : lost ? empty({ icon: "circle-x", title: "این صفحه در اینستاگرام پیدا نشد", text: KIND.not_found.text,
        action: h("a", { class: "btn", href: "#/search", text: "جستجوی یوزرنیم دیگر" }) })
        : empty({ icon: "user", title: "این پروفایل هنوز خوانده نشده", text: "با یک بار خواندن، عکس، بیو، آمار و هایلایت‌ها اینجا ذخیره می‌شود.", action: read });
    refs = { avBox: h("span"), busy: lost ? null : read, mkAv: (busy) => bigAvatar({ u: name, ring: busy ? "loading" : null }) };
    mount(el, skHead(name, refs.avBox, true), bar.el, h("div", { class: "pf-missing" }, box));
    syncRunning();
  }

  function draw() {
    if (!data) return drawMissing();
    refs = {};
    lockCard?.destroy?.();
    const closed = data.profile.is_private && !data.profile.relation?.following;
    lockCard = closed ? privateCard(name, data.profile) : null;
    mount(el, header(data, name, ctx, refs), bar.el, tasksBox.el, lockCard, highlights(data, name, ctx), jsonStrip(data, name), tabBar(name, tab), body);
    syncRunning();
    drawTab(false);
  }

  async function load() {
    const my = ++loadSeq;
    if (!data) mount(el, skHead(name, h("span", { class: "sk pf-sk-av" })), h("div", { class: "pf-skgrid" }, skeleton("tile", 6)));
    const [d, f] = await Promise.all([store.dossier(name), store.files(name)]);
    if (dead || my !== loadSeq) return;
    data = d?.profile ? { ...d, name, files: f } : null;
    draw();
  }

  const offs = [
    store.subscribe("status", () => syncRunning()),
    store.subscribe("job-end", (s) => ((s.result?.profile?.username || s.username || "").toLowerCase() === name ? load() : syncRunning())),
    store.subscribe("online", (on) => { if (on && !data) load(); }),
  ];
  load();

  return {
    el,
    update(p) {   // same params again must stay cheap; params.tab undefined = keep the tab
      const next = String(p.name).toLowerCase();
      if (next !== name) { name = next; tab = p.tab || "posts"; data = null; window.scrollTo({ top: 0 }); load(); return; }
      if (!p.tab || p.tab === tab) return;
      tab = p.tab;
      if (data) { const bar = el.querySelector(".pf-tabs"); if (bar) slideTabLine(bar, tab); drawTab(true); }
    },
    destroy() { dead = true; offs.forEach((off) => off()); tabInst?.destroy?.(); bar.destroy(); tasksBox.destroy(); lockCard?.destroy?.(); },
  };
}
