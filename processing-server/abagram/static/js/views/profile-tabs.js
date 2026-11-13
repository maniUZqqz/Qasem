// Profile tabs: the posts grid, the reels grid and «about this account» (docs/ui/views.md#profile-tabs).
import { h, icon, ltr, bdi, proxied } from "../core/dom.js";
import { fileUrl, thumbUrl, alive } from "../core/api.js";
import { faNum, faCompact, faDate, faDateTime, ago, bytes, unit } from "../core/format.js";
import { state, subscribe, files as filesOf } from "../core/store.js";
import { button, empty, skeleton, avatar, verified, lock, pagedList } from "../core/ui.js";
import { startJob, cost, runningFor } from "../core/jobs.js";

const KIND_ICON = { album: "layers", reel: "film", video: "play" };
const KIND_NAME = { photo: "پست", album: "آلبوم", reel: "ریل", video: "ویدیو" };
const ACCOUNT = { 1: "شخصی", 2: "کسب‌وکار", 3: "تولیدکنندهٔ محتوا" };
const postLimit = () => state.status?.budget?.limits?.posts ?? null;
const isMotion = (p) => p.kind === "reel" || p.kind === "video";

// Where a tile's picture can come from, best first: downloaded file, saved thumbnail, a still-valid Instagram address.
function sources(u, p, map, stamp) {
  const key = `pp_${p.code}_0`;
  return [map[key] ? fileUrl(u, key) : null, p.has_thumb ? thumbUrl(u, p.code, stamp) : null,
    alive(p.thumb) ? proxied(p.thumb) : null].filter(Boolean);
}

function nextSource(img) {
  const list = img._srcs || [];
  if (!list.length) { img.remove(); return; }
  img.src = list.shift();
}

function counts(p) {
  return {
    likes: !p.likes_hidden && Number.isFinite(p.likes) ? p.likes : null,
    comments: !p.comments_disabled && Number.isFinite(p.comments) ? p.comments : null,
  };
}

function hoverLayer({ likes, comments }) {
  if (likes === null && comments === null) return null;
  const n = (ic, v) => h("span", { class: "gr-n" }, icon(ic, { cls: "fill" }), bdi(faCompact(v)));
  return h("span", { class: "gr-hover", "aria-hidden": "true" },
    likes !== null ? n("heart", likes) : null, comments !== null ? n("comment", comments) : null);
}

function tile(u, p, tall) {
  const c = counts(p);
  const label = [`${KIND_NAME[p.kind] || "پست"} ${faDate(p.taken_at)}`,
    c.likes !== null && `${faCompact(c.likes)} لایک`, c.comments !== null && `${faCompact(c.comments)} کامنت`,
    p.pinned && "سنجاق‌شده"].filter(Boolean).join("، ");
  const img = h("img", { alt: "", decoding: "async", loading: "lazy", draggable: "false",
    onload: (e) => e.currentTarget.classList.add("in"), onerror: (e) => nextSource(e.currentTarget) });
  const views = Number.isFinite(p.views) ? p.views : null;
  const foot = tall && (views !== null || c.likes !== null)
    ? h("span", { class: "gr-views", "aria-hidden": "true" }, icon(views !== null ? "play" : "heart", { size: "sm", cls: "fill" }),
      bdi(faCompact(views ?? c.likes)))
    : null;
  const el = h("a", { class: "gr-tile", href: `#/u/${encodeURIComponent(u)}/p/${encodeURIComponent(p.code)}`, "aria-label": label },
    h("span", { class: "gr-ph", "aria-hidden": "true" }, icon(KIND_ICON[p.kind] || "image", { size: "lg" })),
    img,
    p.pinned ? h("span", { class: "gr-pin", "aria-hidden": "true" }, icon("pin")) : null,
    KIND_ICON[p.kind] && !(tall && p.kind === "reel") ? h("span", { class: "gr-kind", "aria-hidden": "true" }, icon(KIND_ICON[p.kind])) : null,
    foot, hoverLayer(c));
  el._img = img;
  el._post = p;
  return el;
}

function grid(u, posts, tall, stamp) {
  const tiles = posts.map((p) => tile(u, p, tall));
  const box = h("div", { class: ["gr-grid", tall && "gr-tall"] }, tiles);
  const fill = (map) => tiles.forEach((t) => { t._img._srcs = sources(u, t._post, map || {}, stamp); nextSource(t._img); });
  filesOf(u).then((f) => fill(f?.files)).catch(() => fill(null));
  return box;
}

const readPosts = (u, d, count) => startJob("posts", { username: u, ...(count ? { count } : {}) },
  { lines: cost("posts", { profile: d?.profile }) });

// Under the grid: how many posts are saved, and the button that reads more (or why it cannot).
function footer(u, d, reels) {
  const box = h("div", { class: "gr-foot" });
  const saved = d.posts?.items?.length || 0;
  const total = d.profile?.posts ?? null;
  let last = null;
  const draw = () => {
    const L = postLimit(), mine = runningFor(u), busy = !!state.status?.busy;
    const key = `${L}|${mine}|${busy}`;
    if (key === last) return;
    last = key;
    const line = reels !== undefined
      ? h("p", { class: "gr-foot-line" }, bdi(unit(reels, "ریل و ویدیو")), " در ", bdi(unit(saved, "پست")), " ذخیره‌شده")
      : h("p", { class: "gr-foot-line" }, bdi(unit(saved, "پست")), total !== null ? [" از ", bdi(unit(total, "پست"))] : null, " ذخیره شده");
    let act = null;
    if (total !== null && saved >= total) act = null;
    else if (L !== null && saved >= L) {
      act = h("p", { class: "gr-cap" }, `سقف پست‌ها ${faNum(L)} است؛ `, h("a", { href: "#/settings/limits", text: "در تنظیمات بالا ببر" }));
    } else if (L !== null) {
      act = button({ label: `خواندن پست‌های بیشتر (تا ${faNum(L)})`, busy: mine, disabled: busy && !mine,
        title: busy && !mine ? "یک کار دیگر در حال اجراست" : null, onClick: () => readPosts(u, d, L) });
    }
    box.replaceChildren(line, act || "");
  };
  draw();
  return { el: box, off: subscribe("status", draw) };
}

function emptyFor(u, d, { reels } = {}) {
  const posts = d.posts;
  if (d.profile?.is_private || posts?.reason === "private") {
    return empty({ icon: "lock", title: "این حساب خصوصی است", text: "پست‌هایش فقط برای دنبال‌کننده‌هایش دیده می‌شود." });
  }
  if (!posts || posts.reason === "unread") {
    return empty({ icon: "grid", title: "پست‌ها هنوز خوانده نشده", text: "بعد از خواندن، پست‌های این حساب همین‌جا مثل اینستاگرام چیده می‌شوند.",
      action: button({ label: "خواندن پست‌ها", kind: "primary", onClick: () => readPosts(u, d, postLimit()) }) });
  }
  if (posts.reason === "empty" || !posts.items?.length) {
    return empty({ icon: "image", title: "هنوز پستی نیست", text: "این حساب هنوز پستی نگذاشته است." });
  }
  return reels ? empty({ icon: "film", title: "ریلی ذخیره نشده", text: "در پست‌های ذخیره‌شده ریل یا ویدیویی نیست. پست‌های بیشتری بخوان." }) : null;
}

function loading(el, tall) {
  el.replaceChildren(h("div", { class: "gr" }, h("div", { class: ["gr-grid", tall && "gr-tall"], "aria-busy": "true" }, skeleton("tile", 12))));
  return { destroy() {} };
}

function renderGrid(el, d, tall, ctx) {
  if (!d) return loading(el, tall);
  const u = d.profile?.username || ctx?.username || "";
  const all = d.posts?.items || [];
  const shown = tall ? all.filter(isMotion) : all;
  const stamp = d.posts?.fetched_at || d.profile?.fetched_at || "";
  const none = shown.length ? null : emptyFor(u, d, { reels: tall });
  const foot = all.length ? footer(u, d, tall ? shown.length : undefined) : null;
  el.replaceChildren(h("div", { class: "gr" }, none || grid(u, shown, tall, stamp), foot?.el));
  return { destroy() { foot?.off(); } };
}

/** Posts tab: 3 columns of 3/4 tiles, newest first, like Instagram's profile grid. */
export const renderPosts = (el, d, ctx) => renderGrid(el, d, false, ctx);
/** Reels tab: only reels and videos, as tall 9/16 tiles with their view count. */
export const renderReels = (el, d, ctx) => renderGrid(el, d, true, ctx);

// ---- About tab ----
const row = (ic, label, value, sub) => h("div", { class: "ab-row" },
  h("span", { class: "ab-ic", "aria-hidden": "true" }, icon(ic)), h("dt", { text: label }),
  h("dd", null, h("span", { class: "ab-val" }, value), sub ? h("span", { class: "ab-sub" }, sub) : null));

function facts(p) {
  const m = p.more || {};
  const c = m.contact || {};
  const addr = [m.address?.street, m.address?.city, m.address?.zip].filter(Boolean);
  const kind = ACCOUNT[m.account_type] || (p.is_business ? ACCOUNT[2] : null);
  return [
    kind && row(p.is_business || m.account_type === 2 ? "briefcase" : "user", "نوع حساب", kind),
    p.category && row("tag", "دسته", bdi(p.category)),
    c.email && row("send", "ایمیل", h("a", { class: "ab-link", href: `mailto:${c.email}` }, ltr(c.email))),
    c.phone && row("phone", "تلفن", h("a", { class: "ab-link", href: `tel:${c.phone}` }, ltr(c.phone))),
    addr.length && row("pin-map", "نشانی", bdi(addr.join("، "))),
    m.story_at && row("circle-play", "آخرین استوری", bdi(faDateTime(m.story_at)), bdi(ago(m.story_at))),
    Number.isFinite(m.reels) && row("film", "ریل‌ها", bdi(unit(m.reels, "ریل"))),
    m.threads && row("at", "Threads", ["نشان ", ltr("Threads"), " را روی پروفایل دارد"]),
    m.facebook_id && row("globe", "شناسهٔ فیسبوک", ltr(m.facebook_id)),
    p.user_id && row("hash", "شناسهٔ کاربری", ltr(p.user_id)),
    p.fetched_at && row("clock", "خوانده‌شده در", bdi(faDateTime(p.fetched_at))),
  ].filter(Boolean);
}

const person = (s) => h("a", { class: "ab-person", href: `#/u/${encodeURIComponent(s.username)}` },
  avatar({ u: s.username, src: s.avatar, size: 44, zoom: false }),
  h("span", { class: "ab-pname" },
    h("span", { class: "ab-puser" }, h("span", { class: "ellipsis" }, ltr(s.username)), s.verified ? verified() : null, s.private ? lock() : null),
    s.full_name ? h("span", { class: "ab-pfull ellipsis" }, bdi(s.full_name)) : null),
  icon("chev-l", { size: "sm", cls: "ab-chev" }));

const section = (title, count, ...kids) => h("section", { class: "ab-sec" },
  h("h2", { class: "ab-h" }, h("span", { text: title }), count ? h("span", { class: "ab-count" }, bdi(count)) : null), ...kids);

function filesRow(u) {
  const val = h("span", { class: "ab-val" }, h("span", { class: "sk sk-line", "aria-hidden": "true" }));
  const dd = h("dd", null, val);
  filesOf(u).then((f) => {
    const n = Object.keys(f?.files || {}).length;
    val.replaceChildren(...(n ? [bdi(unit(n, "فایل")), "، ", bdi(bytes(f.bytes || 0)), " دانلود شده"] : ["هنوز فایلی دانلود نشده"]));
  }).catch(() => val.replaceChildren("فهرست فایل‌ها خوانده نشد"));
  return h("dl", { class: "ab-list" }, h("div", { class: "ab-row" },
    h("span", { class: "ab-ic", "aria-hidden": "true" }, icon("folder")), h("dt", { text: "فایل‌های این حساب" }), dd));
}

/** About tab: facts about the account, similar accounts (paged) and what was downloaded. */
export function renderAbout(el, d, ctx) {
  if (!d) {
    el.replaceChildren(h("div", { class: "ab", "aria-busy": "true" }, skeleton("line", 6)));
    return { destroy() {} };
  }
  const p = d.profile;
  if (!p) {
    el.replaceChildren(empty({ icon: "user", title: "پروفایل خوانده نشده", text: "اول پروفایل را بخوان تا مشخصات این حساب اینجا بیاید." }));
    return { destroy() {} };
  }
  const u = p.username;
  const list = facts(p);
  const sim = d.similar?.items;
  el.replaceChildren(h("div", { class: "ab" },
    section("دربارهٔ این حساب", null, list.length ? h("dl", { class: "ab-list" }, list)
      : h("p", { class: "ab-none", text: "اینستاگرام مشخصات بیشتری از این حساب نشان نداده است." })),
    sim ? section("حساب‌های مشابه", sim.length ? unit(sim.length, "حساب") : null, sim.length
      ? pagedList({ key: `similar:${u}`, items: sim, row: person, label: "حساب‌های مشابه", cls: "ab-people" })
      : h("p", { class: "ab-none", text: "اینستاگرام حساب مشابهی برای این صفحه نشان نداد." })) : null,
    section("دانلودها", null, filesRow(u))));
  return { destroy() {} };
}
