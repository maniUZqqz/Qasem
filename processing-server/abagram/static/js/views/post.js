// «پست»: Instagram's post viewer, mirrored for RTL. Desktop: one dialog with the media pane and the info pane side by
// side (prev/next outside it); phones: a full-screen page (top bar, header, media, counts, caption, comments in a sheet).
import { h, icon, ltr, bdi, on } from "../core/dom.js";
import { igUrl, avatarUrl, media } from "../core/api.js";
import { faNum, faDate, faDateTime, ago } from "../core/format.js";
import { dossier, files, subscribe, state } from "../core/store.js";
import { avatar, verified, button, iconButton, chip, empty, skeleton, toast, setBusy } from "../core/ui.js";
import { dialog, sheet, menu } from "../core/overlay.js";
import { startJob, cost, runningFor } from "../core/jobs.js";
import { animate, flip, reduced } from "../core/motion.js";

const phone = () => matchMedia("(max-width: 767px)").matches;
// The sibling views load on their own: a broken one leaves a plain picture instead of a dead viewer.
const parts = Promise.all([import("./carousel.js"), import("./comments.js")]
  .map((p) => p.catch((e) => { console.error("post view:", e); return {}; })));

// Caption text: @mentions open that profile here, #hashtags are coloured like on Instagram. Text nodes only.
const TOKEN = /(@[A-Za-z0-9._]{1,30}|#[\p{L}\p{N}_\u200c]+)/u;
const rich = (text) => String(text || "").split(TOKEN).map((part, i) => (i % 2 === 0 ? part
  : part[0] === "#" ? h("span", { class: "po-hash" }, bdi(part))
    : h("a", { class: "po-at", href: `#/u/${part.slice(1).replace(/\.+$/, "").toLowerCase()}` }, ltr(part))));
// A caption reads in its own direction: an English caption starts at the left, like on Instagram.
const dirOf = (t) => (/[A-Za-z]/.test(String(t || "").match(/[A-Za-z\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefe]/)?.[0] || "") ? "ltr" : "rtl");
const ratio = (p) => { const it = p.items?.[0]?.width ? p.items[0] : p;
  return Math.min(1.91, Math.max(0.5625, it.width && it.height ? it.width / it.height : 1)).toFixed(4); };
const userLink = (u) => h("a", { class: "po-user", href: `#/u/${u}` }, ltr(u));
const savedCount = (p, fl) => (p.items || []).filter((it, n) => fl?.[`${it.type === "video" ? "pv" : "pp"}_${p.code}_${n}`]).length;
const go = (c, code) => c.ctx.navigate(`/u/${c.u}/p/${code}`, { replace: true });
const copy = (text, done) => (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject(new Error("no clipboard")))
  .then(() => toast(done, { tone: "ok" }), () => toast("کپی نشد؛ مرورگر اجازهٔ کپی نداد.", { tone: "danger" }));

const readDetails = (c) => startJob("details", { username: c.u, codes: [c.post.code] }, { lines: cost("details", { profile: c.profile, codes: [c.post.code] }) });
const download = (c) => startJob("download", { username: c.u, target: "posts", codes: [c.post.code], videos: true, again: false }, { lines: cost("download", { profile: c.profile }) });
const openLikers = (c) => (c.detail?.likers?.length ? c.ctx.navigate(`/u/${c.u}/p/${c.post.code}/likers`) : readDetails(c));
function showComments(c) {
  if (!c.mods.comments) return;
  if (phone()) sheet({ title: "کامنت‌ها", cls: "po-sheet", content: c.mods.comments({ u: c.u, post: c.post, detail: c.detail }) });
  else c.cmBox?.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" });
}
const menuItems = (c, link = igUrl(c.post.url || `/p/${c.post.code}/`)) => [
  { icon: "open", label: "باز کردن در اینستاگرام", onSelect: () => window.open(link, "_blank", "noopener") },
  { icon: "link", label: "کپی لینک", onSelect: () => copy(link, "لینک کپی شد") },
  { icon: "braces", label: "کپی اطلاعات (JSON)", onSelect: () => copy(JSON.stringify({ post: c.post, detail: c.detail }, null, 2), "اطلاعات پست کپی شد") },
  { icon: "download", label: "دانلود این پست", hint: c.saved ? (c.saved >= c.all ? "قبلاً دانلود شده" : "بخشی از آن قبلاً دانلود شده") : null, onSelect: () => download(c) },
];

// The header avatar wears the story ring when a story was read, and the spinning ring while a job reads this person.
function headAvatar(c) {
  c.ring = runningFor(c.u) ? "loading" : c.story ? "story" : null;
  return avatar({ u: c.u, src: c.profile.has_avatar ? avatarUrl(c.u, c.profile.fetched_at) : null, size: 32, ring: c.ring,
    href: c.story ? `#/u/${c.u}/stories` : `#/u/${c.u}`, label: c.story ? `استوری ${c.u}` : `پروفایل ${c.u}` });
}
function header(c) {
  const { post, profile } = c;
  const co = (post.coauthors || []).filter((n) => n !== c.u);
  c.av = headAvatar(c);
  return h("header", { class: "po-head" }, c.av,
    h("div", { class: "po-who" },
      h("div", { class: "po-names" }, userLink(c.u), profile.is_verified ? verified() : null,
        co.length ? [h("span", { class: "po-and", text: "و" }), userLink(co[0])] : null,
        co.length > 1 ? h("span", { class: "po-and" }, "و ", bdi(`${faNum(co.length - 1)} نفر`), " دیگر") : null),
      post.location?.name ? h("span", { class: "po-loc" }, bdi(post.location.name)) : null),
    iconButton({ icon: "more", label: "گزینه‌های پست", onClick: (e) => menu(e.currentTarget, menuItems(c), { label: "گزینه‌های پست" }) }));
}
function tagRow(post) {
  const people = (post.tagged || []).map((t) => h("a", { class: "chip po-chip", href: `#/u/${t.username}`, title: "تگ‌شده در این پست" },
    icon("tag", { size: "sm" }), h("span", {}, ltr(t.username)), t.verified ? verified() : null));
  const m = post.music;
  if (!people.length && !m) return null;
  return h("div", { class: "po-tags" },
    m ? h("p", { class: "po-music" }, icon("music", { size: "sm" }), bdi(m.title || "صدای اصلی"),
      m.artist ? h("span", { class: "muted" }, ltr(m.artist)) : null) : null,
    people.length ? h("div", { class: "po-chips" }, people) : null);
}

// Caption = the first row (avatar + name + text, like Instagram). Phones clamp it to 3 lines + «بیشتر».
function caption(c) {
  const { post, profile } = c;
  const text = post.caption || "", tags = tagRow(post), dir = dirOf(text);
  if (!text && !tags) return null;
  const txt = text ? h("p", { class: "po-cap-text" }, userLink(c.u), profile.is_verified ? verified() : null, " ", rich(text)) : null;
  const more = h("button", { type: "button", class: "po-more", text: "بیشتر", hidden: true,
    onclick: () => { txt.classList.add("open"); more.hidden = true; } });
  if (txt) requestAnimationFrame(() => { more.hidden = txt.scrollHeight <= txt.clientHeight + 1; });
  return h("div", { class: "po-cap" },
    avatar({ u: c.u, src: profile.has_avatar ? avatarUrl(c.u, profile.fetched_at) : null, size: 32, href: `#/u/${c.u}`, label: c.u }),
    h("div", { class: "po-cap-main", dir: text ? dir : null }, txt, txt ? more : null,
      h("time", { class: "po-ago", datetime: post.taken_iso || null, text: ago(post.taken_at) }), tags));
}

// Instagram's action bar, but every icon says what it shows: likes, comments, views (each count in its own <bdi>).
function counts(c, post = c.post) {
  const btn = (ic, text, onclick, title) => h(onclick ? "button" : "span", { type: onclick ? "button" : null, class: "po-count", onclick, title }, icon(ic), bdi(text));
  return h("div", { class: "po-counts" },
    btn("heart", post.likes_hidden || post.likes == null ? "شمار لایک پنهان است" : `${faNum(post.likes)} لایک`, () => openLikers(c),
      c.detail?.likers?.length ? "دیدن لایک‌کنندگان" : "خواندن لایک‌کنندگان"),
    post.comments_disabled ? btn("comment", "کامنت بسته است")
      : btn("comment", post.comments == null ? "کامنت‌ها" : `${faNum(post.comments)} کامنت`, () => showComments(c), "کامنت‌ها"),
    post.views != null ? btn("play", `${faNum(post.views)} بازدید`) : null);
}
function meta(c) {
  const { post } = c;
  c.readBtn = button({ label: "خواندن کامنت و لایک‌کنندگان", icon: "comment", cls: "po-read", onClick: () => readDetails(c) });
  c.dlBtn = c.saved >= c.all ? chip({ icon: "circle-check", text: "دانلود شده", tone: "ok", title: `${faNum(c.saved)} فایل روی این کامپیوتر` })
    : button({ label: "دانلود", icon: "download", onClick: () => download(c) });
  return h("div", { class: "po-meta" },
    h("time", { class: "po-date", datetime: post.taken_iso || null, title: faDateTime(post.taken_at), text: faDate(post.taken_at) }),
    h("div", { class: "po-jobs" }, c.readBtn, c.dlBtn));
}

const topBar = (c) => h("div", { class: "po-top" },
  iconButton({ icon: "arrow-r", label: "برگشت", onClick: () => c.d.close() }), h("h2", { class: "po-title", text: "پست" }));

// One grid for both layouts: CSS puts the media pane beside the info pane on desktop and stacks it on phones.
function build(c) {
  const { post, mods } = c;
  const n = post.comments || c.detail?.comments?.length || 0;
  const all = !post.comments_disabled && n ? h("button", { type: "button", class: "po-all", onclick: () => showComments(c) },
    n === 1 ? "دیدن " : "دیدن همهٔ ", bdi(`${faNum(n)} کامنت`)) : null;
  const cm = mods.comments ? mods.comments({ u: c.u, post, detail: c.detail }) : null;
  c.cmBox = cm ? h("div", { class: "po-cm" }, cm) : null;
  const likers = c.detail && mods.likersSummary ? mods.likersSummary({ u: c.u, post, detail: c.detail, onOpen: () => openLikers(c) }) : null;
  c.media = h("div", { class: "po-media" }, c.car.el);
  return h("article", { class: "po-grid", style: `--po-ar:${ratio(post)}` }, topBar(c), header(c), c.media,
    h("div", { class: "po-body" }, caption(c), c.cmBox, all),
    h("div", { class: "po-acts" }, counts(c), likers), meta(c));
}

function plain(c) {   // only when carousel.js failed to load
  const it = c.post.items?.[0] || {};
  const m = media(c.u, { fileKey: `pp_${c.post.code}_0`, remote: it.image, thumbKey: c.post.code, files: c.files });
  return { el: m.src ? h("img", { class: "po-plain", src: m.src, alt: it.alt || "", "data-zoom": "", referrerpolicy: "no-referrer" })
    : h("div", { class: "po-plain" }, icon("image", { size: "lg" })), go() {}, destroy() {} };
}
const loading = (c) => h("div", { class: "po-grid po-wait", style: "--po-ar:1", "aria-busy": "true" }, topBar(c),
  h("div", { class: "po-head" }, skeleton("avatar"), skeleton("line")), h("div", { class: "po-media" }), h("div", { class: "po-body" }, skeleton("line", 3)));
const navBtn = (c, code, side, ic, label) => (code ? h("button", { type: "button", class: `po-nav po-nav-${side}`, "aria-label": label,
  title: label, onclick: () => go(c, code) }, h("span", {}, icon(ic))) : null);

function draw(c) {
  c.car?.destroy?.(); c.nav?.remove(); c.car = c.av = null;
  const items = c.dos?.posts?.items || [];
  c.codes = items.map((p) => p.code);
  c.post = items.find((p) => p.code === c.code) || null;
  if (!c.post) {
    const ig = button({ label: "باز کردن در اینستاگرام", icon: "open", kind: "primary", onClick: () => window.open(igUrl(`/p/${c.code}/`), "_blank", "noopener") });
    return c.d.body.replaceChildren(h("div", { class: "po-solo" }, topBar(c), c.dos
      ? empty({ icon: "image", title: "این پست ذخیره نشده", text: "فقط پست‌هایی که از پروفایل خوانده شده‌اند اینجا باز می‌شوند. پست‌های بیشتر را از صفحهٔ پروفایل بخوان.", action: ig })
      : empty({ icon: "alert", title: "این پست باز نشد", text: "برنامه جواب نداد. مطمئن شو برنامه روشن است و دوباره باز کن." })));
  }
  Object.assign(c, { profile: c.dos.profile || { username: c.u }, detail: c.dos.details?.posts?.[c.code] || null,
    story: !!c.dos.stories?.reel?.items?.length, all: (c.post.items || []).length || 1, saved: savedCount(c.post, c.files) });
  c.car = c.mods.carousel ? c.mods.carousel({ u: c.u, post: c.post, files: c.files, onIndex: (i) => { c.idx = i; } }) : plain(c);
  c.d.body.replaceChildren(build(c));
  if (c.idx) c.car.go?.(c.idx);
  const i = c.codes.indexOf(c.code);
  c.nav = h("div", { class: "po-chrome" }, navBtn(c, c.codes[i - 1], "prev", "chev-r", "پست قبلی"), navBtn(c, c.codes[i + 1], "next", "chev-l", "پست بعدی"));
  c.d.el.append(c.nav);
  c.busy = undefined; sync(c);
  if (c.from) fly(c);
  c.from = null;
}

// Job state → the buttons' spinners and the header ring. Cheap: only touches the DOM when the state changes.
function sync(c) {
  if (!c.post || !c.av) return;
  const key = runningFor(c.u) ? state.status.mode : "";
  if (key === c.busy) return;
  c.busy = key;
  setBusy(c.readBtn, key === "details");
  if (c.dlBtn.tagName === "BUTTON") setBusy(c.dlBtn, key === "download");
  if ((key ? "loading" : c.story ? "story" : null) !== c.ring) { const av = headAvatar(c); c.av.replaceWith(av); c.av = av; }
}

// The grid tile grows into the media pane (a ghost copy flies; the real pane is under it when it lands).
function fly(c) {
  const to = c.media.getBoundingClientRect();
  if (reduced() || !to.width) return;
  c.d.panel.getAnimations().forEach((a) => a.finish());
  const g = h("img", { class: "po-ghost", src: c.from.src, alt: "", style: `top:${to.top}px;left:${to.left}px;width:${to.width}px;height:${to.height}px` });
  c.d.el.append(g);
  animate(c.d.panel, [{ opacity: 0 }, { opacity: 1 }], { dur: 320 });
  flip(c.from.rect, g).then(() => animate(g, [{ opacity: 1 }, { opacity: 0 }], { dur: 150, fill: "forwards" })).then(() => g.remove());
}

// RTL: ArrowLeft = the next (older) post. Only when this viewer is on top; the carousel answers its own arrows.
function keys(c, e) {
  const top = [...document.querySelectorAll(".ov-layer, .mn-pop")].pop();
  if (top !== c.d.el || !c.d.el.contains(document.activeElement) || e.target.closest?.(".po-media, input, textarea")) return;
  const i = (c.codes || []).indexOf(c.code), to = i < 0 ? null : { ArrowLeft: c.codes[i + 1], ArrowRight: c.codes[i - 1] }[e.key];
  if (to) { e.preventDefault(); go(c, to); }
}
async function load(c, force = false) {
  const [mods, dos, fl] = await Promise.all([parts, dossier(c.u, { force }), files(c.u, { force })]);
  if (c.dead) return;
  Object.assign(c, { mods: Object.assign({}, ...mods), dos, files: fl?.files || null });
  draw(c);
}

export function open(params, ctx) {
  const c = { u: String(params.name || "").toLowerCase(), code: params.code, ctx, idx: 0, mods: {} };
  const img = phone() ? null : document.querySelector(`a[href="#/u/${c.u}/p/${c.code}"] img`);
  c.from = img?.currentSrc ? { rect: img.getBoundingClientRect(), src: img.currentSrc } : null;
  let byMain = false;
  const offs = [];
  const cleanup = () => { c.dead = true; offs.splice(0).forEach((off) => off()); c.car?.destroy?.(); };
  c.d = dialog({ size: "lg", bare: true, label: "پست", cls: "po-panel", content: loading(c),
    onClose: () => { cleanup(); if (!byMain) ctx.dismiss(); } });
  c.d.el.classList.add("po-layer");
  c.d.el.append(h("button", { type: "button", class: "po-x", "aria-label": "بستن", title: "بستن", onclick: () => c.d.close() }, icon("x", { size: "lg" })));
  offs.push(subscribe("status", () => sync(c)), on(document, "keydown", (e) => keys(c, e)), subscribe("job-end", (s) => {
    if (String(s.result?.profile?.username || s.username || "").toLowerCase() === c.u) load(c, true);
  }));
  load(c);
  return {
    close() { byMain = true; cleanup(); c.d.close(); },
    // main.js may call this for the same overlay with another code (prev/next): swap the post without a new dialog.
    update(p) { if (p?.code && p.code !== c.code) { Object.assign(c, { code: p.code, idx: 0, from: null }); if (c.dos) draw(c); } },
  };
}
