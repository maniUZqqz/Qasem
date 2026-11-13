// Every picture can be opened large. The viewer itself is the one from MIRA/Exhibition (js/vendor/viewer.js,
// window.Viewer: anchored zoom, pinch, swipe to close, its own video player). This file only connects it.
//
// Mark anything with data-zoom (an ancestor with data-nozoom, or the nav/top bar, turns it off): a click on it (or on an <img> inside it) opens the viewer.
//   data-zoom-src   a bigger picture than the one shown (else the <img> inside is used)
//   data-zoom-title / data-zoom-sub   the two lines at the top of the viewer
// The click is taken before the element's own click handler, so an avatar inside a row button opens big
// instead of opening the row.
import { proxied } from "./dom.js";

const V = () => window.Viewer;

export function zoom(src, { title = "", sub = "", caption = "" } = {}) {
  if (!src || !V()) return;
  V().open([{ kind: "image", src: proxied(src), title, sub, caption }], 0);
}

/** items: [{kind: 'image'|'video', src (shown at once) | url (fetched with progress), title, sub, caption, poster}] */
export function gallery(items, index = 0) {
  if (!items?.length || !V()) return;
  V().open(items.map((it) => ({ ...it, src: it.src && proxied(it.src), url: it.url && proxied(it.url, it.kind === "video" ? "vid" : "img"), poster: it.poster && proxied(it.poster) })), index);
}

function sourceOf(el) {
  if (el.dataset.zoomSrc) return el.dataset.zoomSrc;
  const img = el.tagName === "IMG" ? el : el.querySelector("img");
  return img && img.complete && img.naturalWidth ? img.currentSrc || img.src : null;
}

document.addEventListener("click", (e) => {
  // The viewer keeps its own zoom state in data-zoom="0|1" on its root (.vw): a click inside it (X, arrows, the dark
  // backdrop) belongs to the viewer, never a picture to open again.
  if (!e.target.closest || e.target.closest(".vw")) return;
  const host = e.target.closest("[data-zoom]");
  if (!host || e.button !== 0 || e.metaKey || e.ctrlKey) return;
  if (host.closest("[data-nozoom], .sh-nav, .sh-top, .sh-pill")) return;   // navigation chrome keeps its own click
  const src = sourceOf(host);
  if (!src) return;                     // nothing loaded (a letter avatar): let the normal click happen
  e.preventDefault();
  e.stopPropagation();
  zoom(src, { title: host.dataset.zoomTitle || "", sub: host.dataset.zoomSub || "" });
}, true);
