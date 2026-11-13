// «کامنت‌ها»: the comment rows under a post (Instagram's own rows, mirrored for RTL) and the «liked by» line.
// Both are plain builders: post.js mounts them and builds them again after a reading job ends.
import { h, icon, ltr, bdi } from "../core/dom.js";
import { faNum, faDateTime, ago } from "../core/format.js";
import { state, subscribe } from "../core/store.js";
import { avatar, verified, button, chip, empty, pagedList, setBusy } from "../core/ui.js";
import { startJob, cost, runningFor } from "../core/jobs.js";
import { gallery } from "../core/zoom.js";

// @mentions open that person here, #hashtags take the link colour. Text nodes only, never HTML.
const TOKEN = /(@[A-Za-z0-9._]{1,30}|#[\p{L}\p{N}_‌]+)/u;
const rich = (text) => String(text || "").split(TOKEN).map((part, i) => (i % 2 === 0 ? part
  : part[0] === "#" ? h("span", { class: "cm-hash" }, bdi(part))
    : h("a", { class: "cm-at", href: `#/u/${part.slice(1).replace(/\.+$/, "").toLowerCase()}` }, ltr(part))));
const iso = (t) => {
  const ms = typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : Date.parse(t);
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null;
};
const count = (n, word) => bdi(`${faNum(n)} ${word}`);   // every number + unit in its own <bdi>
const when = (t, cls, ...lead) => h("time", { class: cls, datetime: iso(t), title: faDateTime(t) }, ...lead, bdi(ago(t)));
const limits = (label) => h("a", { class: "cm-limit", href: "#/settings/limits" }, `«${label}»`);

// The details job for this one post. The spinner follows /api/status while that job reads this person;
// the subscription ends by itself once the button has left the page (post.js rebuilds the block after the job).
function readButton(u, post, label = "خواندن کامنت و لایک‌کنندگان") {
  const btn = button({ label, icon: "comment", kind: "primary", cls: "cm-read",
    onClick: () => startJob("details", { username: u, codes: [post.code] }, { lines: cost("details", { codes: [post.code] }) }) });
  let was = null;
  const sync = () => {
    const now = runningFor(u) && state.status?.mode === "details";
    if (now !== was) { was = now; setBusy(btn, now); }
  };
  sync();
  const off = subscribe("status", () => (btn.isConnected ? sync() : off()));
  return btn;
}

// One comment: avatar (opens big), name above the text, then a quiet meta row — like Instagram's app.
function row(cm) {
  const name = cm.user
    ? h("a", { class: "cm-user", href: `#/u/${String(cm.user).toLowerCase()}`, title: `پروفایل ${cm.user}` }, ltr(cm.user))
    : h("span", { class: "cm-user", text: "کاربر ناشناس" });
  const text = cm.text ? h("p", { class: "cm-text", dir: "auto" }, rich(cm.text)) : null;
  const more = text ? h("button", { type: "button", class: "cm-more", text: "بیشتر", hidden: true,
    onclick: () => { text.classList.add("open"); more.hidden = true; } }) : null;
  if (text) requestAnimationFrame(() => { more.hidden = text.scrollHeight <= text.clientHeight + 1; });
  return h("article", { class: ["cm-row", cm.reply_to && "cm-reply"] },
    avatar({ u: cm.user || "", src: cm.avatar || null, size: 32 }),
    h("div", { class: "cm-main" },
      h("div", { class: "cm-name" }, name, cm.verified ? verified() : null),
      text, more,
      !text && cm.gif ? h("p", { class: "cm-gif" }, icon("image", { size: "sm" }), "گیف فرستاده؛ تصویرش خوانده نمی‌شود") : null,
      h("div", { class: "cm-meta" },
        cm.at ? when(cm.at, "cm-ago") : null,
        cm.likes ? h("span", { class: "cm-likes" }, count(cm.likes, "لایک")) : null,
        cm.replies ? h("span", {}, count(cm.replies, "پاسخ")) : null,
        cm.edited ? h("span", { text: "ویرایش‌شده" }) : null,
        cm.pinned ? chip({ icon: "pin", text: "سنجاق‌شده", title: "صاحب پست این کامنت را بالای فهرست سنجاق کرده" }) : null)));
}

// «۲۰ کامنت از ۱٬۰۶۳ کامنت خوانده شده»: how much of the conversation is here, and how to get more.
function head(post, detail, n) {
  const total = detail.comments_total ?? post.comments;
  const part = total != null && total > n;
  return h("div", { class: "cm-head" },
    h("p", { class: "cm-count" }, count(n, "کامنت"), part ? [" از ", count(total, "کامنت")] : null, " خوانده شده"),
    detail.read_at ? when(detail.read_at, "cm-when", "آخرین خواندن ") : null,
    detail.comments_more || part ? h("p", { class: "cm-hint" }, "بقیه با بالا بردن سقف ", limits("کامنت برای هر پست")) : null);
}

const ERROR = {
  not_found: "اینستاگرام گفت این پست پیدا نشد؛ شاید پاک شده یا حسابش خصوصی شده.",
  unreachable: "صفحهٔ پست در اینستاگرام باز نشد. اتصال را چک کن و دوباره بخوان.",
};
const openLimits = () => h("a", { class: "btn", href: "#/settings/limits" }, icon("gauge"), h("span", { text: "باز کردن محدودیت‌ها" }));

// No rows to show: say why, and offer the one thing that changes it.
function blank(u, post, detail) {
  if (post.comments_disabled) {
    return empty({ icon: "comment", title: "کامنت‌های این پست بسته است", text: "صاحب پست کامنت گذاشتن را بسته؛ کامنتی برای خواندن نیست." });
  }
  if (!detail) {
    return empty({ icon: "comment", title: "کامنت‌ها هنوز خوانده نشده",
      text: "با خواندن، کامنت‌ها و لایک‌کنندگان این پست اینجا نشان داده می‌شوند.", action: readButton(u, post) });
  }
  if (detail.error) {
    return empty({ icon: "alert", title: "کامنت‌ها خوانده نشد", text: ERROR[detail.error] || "خواندن این پست کامل نشد. دوباره بخوان.",
      action: readButton(u, post, "دوباره خواندن") });
  }
  if ((detail.comments_total ?? post.comments) === 0) {
    return empty({ icon: "comment", title: "هنوز کامنتی نیست", text: "این پست وقتی خوانده شد کامنتی نداشت." });
  }
  return empty({ icon: "comment", title: "کامنتی خوانده نشد",
    text: "سقف «کامنت برای هر پست» را در محدودیت‌ها بالا ببر و پست را دوباره بخوان.", action: openLimits() });
}

/** The comments block of a post: rows in pages of 5/10/15/20, or a state that says what to do next. */
export function comments({ u, post, detail } = {}) {
  u = String(u || "").toLowerCase();
  if (!post) return h("div", { class: "cm" });
  const list = Array.isArray(detail?.comments) ? detail.comments : [];
  if (!list.length) return h("div", { class: "cm cm-blank" }, blank(u, post, detail));
  return h("section", { class: "cm", "aria-label": "کامنت‌ها" },
    head(post, detail, list.length),
    pagedList({ key: `cm:${u}/${post.code}`, items: list, row, cls: "cm-list", label: "کامنت‌ها" }));
}

// Why the likers are not here (likers_note from the details job).
const NOTE = {
  hidden: ["eye-off", "صاحب پست شمارش لایک را پنهان کرده"],
  none: ["heart", "هنوز کسی این پست را نپسندیده"],
  empty: ["info", "اینستاگرام فهرست لایک‌کنندگان را خالی نشان داد."],
  no_count: ["alert", "لایک‌کنندگان خوانده نشدند؛ شمار لایک روی صفحه با شمار ذخیره‌شده یکی نبود. پروفایل را دوباره بخوان."],
  no_click: ["alert", "لایک‌کنندگان خوانده نشدند؛ فهرستشان در اینستاگرام باز نشد. دوباره بخوان."],
};
const note = (ic, ...text) => h("p", { class: "cm-note" }, icon(ic, { size: "sm" }), h("span", {}, ...text));

/** «پسندیده‌شده توسط ali و ۱۳۵٬۶۷۷ نفر دیگر» with up to 3 stacked faces, or the note that says why not. */
export function likersSummary({ u, post = {}, detail, onOpen } = {}) {
  const people = Array.isArray(detail?.likers) ? detail.likers.filter((p) => p?.username) : [];
  if (!people.length) {
    const key = detail?.likers_note || (post.likes_hidden ? "hidden" : null);
    if (NOTE[key]) return note(...NOTE[key]);
    if (detail && state.status?.budget?.limits?.likers === 0) {
      return note("gauge", "لایک‌کنندگان خوانده نشدند؛ سقف ", limits("لایک‌کننده برای هر پست"), " صفر است.");
    }
    return null;
  }
  const total = Math.max(post.likes ?? detail.likers_total ?? 0, people.length);
  const faces = people.slice(0, 3).map((p) => ({ p, el: avatar({ u: p.username, src: p.avatar || null, size: 24, zoom: false }) }));
  // The faces open big as one gallery (rule 16); when no picture loaded, the tap opens the list instead.
  const pics = () => faces.map(({ p, el }) => ({ p, img: el.querySelector("img") })).filter(({ img }) => img?.complete && img.naturalWidth)
    .map(({ p, img }) => ({ kind: "image", src: img.currentSrc || img.src, title: `@${p.username}`, sub: p.full_name || "" }));
  const stack = h("button", { type: "button", class: "cm-stack", "aria-label": "عکس لایک‌کنندگان", title: "عکس لایک‌کنندگان",
    onclick: () => { const items = pics(); if (items.length) gallery(items, 0); else onOpen?.(); } }, faces.map((f) => f.el));
  const others = total - 1;
  return h("div", { class: "cm-likers" }, stack,
    h("button", { type: "button", class: "cm-liked", title: "دیدن لایک‌کنندگان", onclick: () => onOpen?.() },
      h("span", { class: "cm-liked-line" }, "پسندیده‌شده توسط ", h("strong", {}, ltr(people[0].username)),
        others > 0 ? [" و ", h("strong", {}, count(others, "نفر")), " دیگر"] : null),
      h("span", { class: "cm-liked-read" }, count(people.length, "نفر"), total > people.length ? [" از ", count(total, "نفر")] : null, " خوانده شده")));
}
