// «آلبوم»: the slides of one post (pictures and videos), Instagram's carousel mirrored for RTL. The track follows the
// finger and snaps with the spring; arrows, dots and the «۲/۵» counter sit on the picture; a picture opens the big
// viewer with every slide of the post (gallery). Used by post.js: carousel({u, post, files, onIndex}) → {el, go, destroy}.
import { h, icon, ltr } from "../core/dom.js";
import { media } from "../core/api.js";
import { faNum, faDate } from "../core/format.js";
import { reduced } from "../core/motion.js";
import { gallery } from "../core/zoom.js";

const MAX_DOTS = 9;
const sign = () => (document.documentElement.dir === "rtl" ? 1 : -1);   // RTL: slide 1 sits to the left of slide 0
const clamp = (c, i) => Math.max(0, Math.min(c.n - 1, i));

// A post saved without its slide list still shows its own picture.
const single = (p) => ({ type: p.kind === "reel" || p.kind === "video" ? "video" : "image", image: p.thumb || null,
  video: null, width: p.width, height: p.height, alt: p.alt });

// Every place a slide's picture can come from, best first: downloaded file, live Instagram address, saved thumbnail.
// A source that fails to load hands over to the next one (see picture()).
function pictures(c, it, n) {
  const code = c.post.code;
  const thumbKey = n === 0 && code && c.post.has_thumb !== false ? code : null;
  return [media(c.u, { fileKey: `pp_${code}_${n}`, remote: it.image, thumbKey, files: c.files }),
    media(c.u, { remote: it.image, thumbKey }), media(c.u, { thumbKey })]
    .map((m) => m.src).filter((src, k, all) => src && all.indexOf(src) === k);
}

const placeholder = (video) => h("div", { class: "ca-empty" },
  h("span", { class: "ca-empty-ic" }, icon(video ? "film" : "image", { size: "lg" })),
  h("p", { text: video ? "این ویدیو ذخیره نشده — دانلود کن" : "این تصویر ذخیره نشده — دانلود کن" }));

// A video slide whose video is gone but whose picture is here: the picture, with this line on it.
const note = () => h("span", { class: "ca-note" }, icon("film", { size: "sm" }), h("span", { text: "این ویدیو ذخیره نشده — دانلود کن" }));

function picture(c, s) {
  const img = h("img", { src: s.pics[0], alt: s.alt, decoding: "async", loading: s.n === c.i ? "eager" : "lazy",
    referrerpolicy: "no-referrer", draggable: "false", onclick: () => { if (!c.moved) openBig(c, s.n); } });
  img.addEventListener("error", () => {
    s.pics.shift();
    if (s.pics.length) img.src = s.pics[0];          // our own addresses only (file / proxy / thumbnail)
    else img.replaceWith(placeholder(false));
  });
  return img;
}

const still = (c, s) => (s.pics.length ? [picture(c, s), s.video ? note() : null] : placeholder(s.video));

function video(c, s) {
  const v = h("video", { src: s.vid, poster: s.pics[0] || null, playsinline: true, controls: true, preload: "metadata",
    muted: true, "aria-label": s.alt });
  v.muted = true;
  v.addEventListener("volumechange", () => { c.muted = v.muted; });   // the person's sound choice follows to the next video
  v.addEventListener("error", () => {
    if (s.v !== v || c.dead) return;
    s.vid = null; s.v = null;
    v.replaceWith(...[still(c, s)].flat().filter(Boolean));
  });
  return v;
}

const kindName = (it) => (it.type === "video" ? "ویدیو" : "تصویر");

function slide(c, it, n) {
  const s = { n, video: it.type === "video", pics: pictures(c, it, n),
    alt: it.alt || c.post.alt || `${kindName(it)} ${faNum(n + 1)} از ${faNum(c.n)}` };
  s.vid = s.video ? media(c.u, { fileKey: `pv_${c.post.code}_${n}`, remote: it.video, files: c.files, video: true }).src : null;
  if (s.vid) s.v = video(c, s);
  s.el = h("div", { class: "ca-slide", role: "group", "aria-roledescription": "اسلاید",
    "aria-label": `${faNum(n + 1)} از ${faNum(c.n)}` }, s.v || still(c, s));
  return s;
}

// The big viewer gets every slide that has something to show; videos go as `url` (the viewer fetches them).
function openBig(c, from) {
  const list = [], at = new Map(), sub = c.post.taken_at ? faDate(c.post.taken_at) : "";
  for (const s of c.slides) {
    if (!s.vid && !s.pics.length) continue;
    at.set(s.n, list.length);
    list.push(s.vid ? { kind: "video", url: s.vid, poster: s.pics[0] || null, title: c.u, sub }
      : { kind: "image", src: s.pics[0], title: c.u, sub });
  }
  if (at.has(from)) gallery(list, at.get(from));
}

// Arrows (44px hit, 32px circle), the counter, the dots (at most 9; the ones at a cut edge are smaller).
function chrome(c) {
  const nav = (side, ic, label, step) => h("button", { type: "button", class: `ca-nav ca-${side}`, "aria-label": label,
    title: label, onclick: () => move(c, c.i + step) }, h("span", {}, icon(ic, { size: "sm" })));
  c.prev = nav("prev", "chev-r", "اسلاید قبلی", -1);
  c.next = nav("next", "chev-l", "اسلاید بعدی", 1);
  c.count = h("span", { class: "ca-count", "aria-hidden": "true" });
  c.dots = Array.from({ length: Math.min(c.n, MAX_DOTS) }, () => h("span", { class: "ca-dot" }));
  c.live = h("span", { class: "sr-only", "aria-live": "polite" });
  return [c.prev, c.next, c.count, h("div", { class: "ca-dots", "aria-hidden": "true" }, c.dots), c.live];
}

function paintDots(c) {
  const start = Math.max(0, Math.min(c.i - 4, c.n - MAX_DOTS)), end = start + c.dots.length;
  c.dots.forEach((d, j) => {
    const k = start + j;
    d.classList.toggle("on", k === c.i);
    d.classList.toggle("sm", (k === start && start > 0) || (k === end - 1 && end < c.n));
  });
}

const place = (c, dx = 0) => { c.track.style.transform = `translateX(calc(${sign() * c.i * 100}% + ${dx}px))`; };

// Only the shown video plays (muted unless the person turned the sound on), and only while the carousel is on screen.
function playback(c) {
  for (const s of c.slides) {
    if (!s.v) continue;
    if (s.n === c.i && c.seen && !c.dead && !reduced()) {
      s.v.muted = c.muted;
      s.v.play().catch(() => { if (s.v && !s.v.muted) { s.v.muted = true; s.v.play().catch(() => {}); } });
    } else if (!s.v.paused) s.v.pause();
  }
}

function show(c, instant = false) {
  if (instant) c.root.classList.add("ca-drag");
  place(c);
  if (instant) { void c.track.offsetWidth; c.root.classList.remove("ca-drag"); }
  for (const s of c.slides) {
    s.el.inert = s.n !== c.i;
    if (Math.abs(s.n - c.i) <= 1) s.el.querySelector("img[loading=lazy]")?.setAttribute("loading", "eager");
  }
  if (c.n > 1) {
    const had = document.activeElement;
    c.prev.hidden = c.i === 0;
    c.next.hidden = c.i === c.n - 1;
    if ((had === c.prev || had === c.next) && had.hidden) c.view.focus({ preventScroll: true });
    c.count.replaceChildren(ltr(`${faNum(c.i + 1)}/${faNum(c.n)}`));
    c.live.textContent = `${kindName(c.items[c.i])} ${faNum(c.i + 1)} از ${faNum(c.n)}`;
    paintDots(c);
  }
  playback(c);
  if (c.last !== c.i) { c.last = c.i; c.onIndex?.(c.i); }
}

function move(c, to, instant = false) { c.i = clamp(c, to); show(c, instant); }

// Swipe: past 8px sideways the track follows the finger (a stiff pull at the ends); on release it snaps with the
// spring. RTL: swipe right = next. A vertical move is the page's scroll, and the video's own control bar is left alone.
function drag(c) {
  let p = null;
  const v = c.view;
  v.addEventListener("pointerdown", (e) => {
    c.moved = false;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const vid = e.target.closest?.("video");
    if (vid && e.clientY > vid.getBoundingClientRect().bottom - 56) return;
    p = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, lx: e.clientX, lt: e.timeStamp, vx: 0, on: false };
  });
  v.addEventListener("pointermove", (e) => {
    if (!p || e.pointerId !== p.id) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (!p.on) {
      if (Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx)) { p = null; return; }
      if (Math.abs(dx) < 8) return;
      p.on = true; c.moved = true; c.root.classList.add("ca-drag");
      try { v.setPointerCapture(e.pointerId); } catch { /* the pointer is already gone */ }
    }
    const dt = e.timeStamp - p.lt;
    if (dt > 0) { p.vx = (e.clientX - p.lx) / dt; p.lx = e.clientX; p.lt = e.timeStamp; }
    const s = sign(), out = (c.i === 0 && s * dx < 0) || (c.i === c.n - 1 && s * dx > 0);
    p.dx = out ? dx * 0.35 : dx;
    place(c, p.dx);
  });
  const end = (e) => {
    if (!p || e.pointerId !== p.id) return;
    const was = p; p = null;
    if (!was.on) return;
    c.root.classList.remove("ca-drag");
    const s = sign(), w = v.clientWidth || 1, push = s * was.dx;
    const fling = e.timeStamp - was.lt < 100 ? s * was.vx : 0;
    const step = e.type === "pointercancel" ? 0
      : push > w * 0.18 || fling > 0.4 ? 1 : push < -w * 0.18 || fling < -0.4 ? -1 : 0;
    move(c, c.i + step);
  };
  ["pointerup", "pointercancel"].forEach((type) => v.addEventListener(type, end));
  // The click that ends a drag must not open the big viewer.
  v.addEventListener("click", (e) => { if (c.moved) { e.preventDefault(); e.stopPropagation(); c.moved = false; } }, true);
}

// RTL: ArrowLeft = next. The video keeps its own keys (seek, volume).
function keys(c, e) {
  if (e.altKey || e.ctrlKey || e.metaKey || e.target.closest?.("video")) return;
  const s = sign();
  const to = c.n > 1 ? { ArrowLeft: c.i + s, ArrowRight: c.i - s, Home: 0, End: c.n - 1 }[e.key] : undefined;
  if (to !== undefined) { e.preventDefault(); e.stopPropagation(); move(c, to); return; }
  if ((e.key === "Enter" || e.key === " ") && e.target === c.view) { e.preventDefault(); openBig(c, c.i); }
}

export function carousel({ u, post, files, onIndex } = {}) {
  const p = post || {};
  const items = p.items?.length ? p.items : [single(p)];
  const c = { u: String(u || ""), post: p, files: files || null, onIndex, items, n: items.length, i: 0, muted: true, seen: false };
  c.slides = items.map((it, n) => slide(c, it, n));
  c.track = h("div", { class: "ca-track" }, c.slides.map((s) => s.el));
  c.view = h("div", { class: "ca-view", tabindex: "0", role: "region", "aria-roledescription": "آلبوم",
    "aria-label": c.n > 1 ? `رسانه‌های پست، ${faNum(c.n)} مورد؛ با کلیدهای جهت جابه‌جا شو` : "رسانهٔ پست" }, c.track);
  c.root = h("div", { class: ["ca", c.n > 1 && "ca-many"], onkeydown: (e) => keys(c, e) }, c.view, c.n > 1 ? chrome(c) : null);
  if (c.n > 1) drag(c);
  if (c.slides.some((s) => s.v) && "IntersectionObserver" in window) {
    c.io = new IntersectionObserver((es) => { c.seen = es[es.length - 1].isIntersecting; playback(c); }, { threshold: 0.6 });
    c.io.observe(c.root);
  }
  show(c, true);
  return {
    el: c.root,
    go: (i) => move(c, Number(i) || 0, true),
    destroy() {
      if (c.dead) return;
      c.dead = true;
      c.io?.disconnect();
      for (const s of c.slides) if (s.v) { s.v.pause(); s.v.removeAttribute("src"); s.v.load(); }
    },
  };
}
