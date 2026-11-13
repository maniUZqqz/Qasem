// Small shared widgets. Their look lives in css/ui.css (and buttons/inputs in base.css).
import { h, icon, uid } from "./dom.js";
import { faNum } from "./format.js";
import { pref } from "./store.js";
import { enter } from "./motion.js";

export const spinner = (size = 20) => h("span", { class: "spin", style: `width:${size}px;height:${size}px`, "aria-hidden": "true" });

export function button({ label, icon: ic, kind = "secondary", size = "md", onClick, busy, disabled, title, type = "button", full, cls } = {}) {
  const el = h("button", {
    type, class: ["btn", kind !== "secondary" && kind, size !== "md" && size, full && "full", cls],
    title, disabled: !!disabled, "aria-busy": busy ? "true" : null, onclick: onClick,
  }, ic ? icon(ic, { size: size === "sm" ? "sm" : "md" }) : null, label ? h("span", { text: label }) : null, busy ? spinner(18) : null);
  return el;
}

export function setBusy(btn, busy) {
  btn.setAttribute("aria-busy", busy ? "true" : "false");
  btn.querySelector(".spin")?.remove();
  if (busy) btn.append(spinner(18));
}

export function iconButton({ icon: ic, label, onClick, size = "md", pressed, cls } = {}) {
  return h("button", {
    type: "button", class: ["icon-btn", cls], "aria-label": label, title: label, onclick: onClick,
    "aria-pressed": pressed === undefined ? null : String(!!pressed),
  }, icon(ic, { size }));
}

/** Avatar with an optional ring: 'story' (gradient), 'seen' (grey), 'loading' (gradient that turns).
 * A plain avatar (no onClick/href of its own) opens big in the image viewer when clicked (zoom: false turns it off;
 * zoomSrc gives a bigger picture than src). */
export function avatar({ u = "", src, size = 44, ring = null, label, onClick, href, zoom, zoomSrc } = {}) {
  const letter = (u || "?").replace(/^[^a-z0-9]+/i, "").slice(0, 1).toUpperCase() || "?";
  const face = h("span", { class: "av-face", "aria-hidden": "true" }, letter,
    src ? h("img", { src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer", onerror: (e) => e.currentTarget.remove() }) : null);
  const canZoom = src && zoom !== false && (zoom === true || (!onClick && !href));
  const attrs = { class: ["av", ring && `av-ring av-${ring}`], style: `--av:${typeof size === "number" ? `${size}px` : size}`,
    "data-zoom": canZoom ? "" : null, "data-zoom-src": canZoom && zoomSrc ? zoomSrc : null, "data-zoom-title": canZoom && u ? `@${u}` : null };
  if (href) return h("a", { ...attrs, href, "aria-label": label || u }, face);
  if (onClick) return h("button", { ...attrs, type: "button", onclick: onClick, "aria-label": label || u }, face);
  return h("span", attrs, face);
}

export const verified = () => icon("verified", { size: "sm", cls: "badge-verified fill", label: "تأییدشده" });
export const lock = () => icon("lock", { size: "sm", cls: "badge-lock", label: "خصوصی" });

export function chip({ icon: ic, text, tone, onClick, href, title } = {}) {
  const kids = [ic ? icon(ic, { size: "sm" }) : null, h("span", { text })];
  const cls = ["chip", tone && `chip-${tone}`];
  if (href) return h("a", { class: cls, href, title, target: href.startsWith("http") ? "_blank" : null, rel: "noopener noreferrer" }, ...kids);
  if (onClick) return h("button", { type: "button", class: cls, onclick: onClick, title }, ...kids);
  return h("span", { class: cls, title }, ...kids);
}

export function empty({ icon: ic = "image", title, text, action } = {}) {
  return h("div", { class: "empty" },
    h("span", { class: "empty-ic" }, icon(ic, { size: "lg" })),
    title ? h("h3", { class: "empty-title", text: title }) : null,
    text ? h("p", { class: "empty-text", text }) : null,
    action || null);
}

export function skeleton(kind = "line", n = 1) {
  return Array.from({ length: n }, () => h("span", { class: `sk sk-${kind}`, "aria-hidden": "true" }));
}

export function segmented({ label, options, value, onChange } = {}) {
  const box = h("div", { class: "seg", role: "radiogroup", "aria-label": label });
  const draw = (v) => box.replaceChildren(...options.map((o) => h("button", {
    type: "button", role: "radio", "aria-checked": String(o.value === v), text: o.label,
    onclick: () => { draw(o.value); onChange?.(o.value); },
  })));
  draw(value);
  return box;
}

export function field({ id = uid("f"), label, input, help, error } = {}) {
  input.id = input.id || id;
  const helpId = help ? `${input.id}-help` : null;
  const errId = `${input.id}-err`;
  input.setAttribute("aria-describedby", [helpId, errId].filter(Boolean).join(" "));
  const err = h("p", { class: "error", id: errId, role: "alert", hidden: !error, text: error || "" });
  const el = h("div", { class: "field" }, h("label", { for: input.id, text: label }), input,
    help ? h("p", { class: "help", id: helpId, text: help }) : null, err);
  el.setError = (msg) => { err.textContent = msg || ""; err.hidden = !msg; input.setAttribute("aria-invalid", msg ? "true" : "false"); };
  return el;
}

export function stat(value, label, onClick, title) {
  const kids = [h("span", { class: "stat-n num", text: value }), h("span", { class: "stat-l", text: label })];
  return onClick ? h("button", { type: "button", class: "stat", onclick: onClick, title }, ...kids) : h("span", { class: "stat", title }, ...kids);
}

// ---- paged lists: 5/10/15/20 per page (default 5, remembered), numbered pager, never a long scroll ----
export const SIZES = [5, 10, 15, 20];
const pageState = new Map();

export function listState(key) {
  if (!pageState.has(key)) {
    const saved = Number(pref("psize"));
    pageState.set(key, { size: SIZES.includes(saved) ? saved : 5, page: 0 });
  }
  return pageState.get(key);
}

function pageNumbers(page, pages) {
  if (pages <= 7) return [...Array(pages).keys()];
  const set = new Set([0, pages - 1, page - 1, page, page + 1]);
  const out = [];
  [...set].filter((p) => p >= 0 && p < pages).sort((a, b) => a - b).forEach((p, i, arr) => {
    if (i && p - arr[i - 1] > 1) out.push(null);
    out.push(p);
  });
  return out;
}

/**
 * items: array; row(item) → Element. Returns an element that redraws itself.
 * opts.total + opts.load(offset, size) → Promise<items> for lists paged by the server.
 */
/** per: items side by side (a grid of two columns): the size he picks stays rows (5/10/15/20), a page holds size × per items,
 * and the choices say how many people that is. */
export function pagedList({ key, items = [], row, emptyEl, cls, label = "فهرست", total, load, per = 1 } = {}) {
  const st = listState(key);
  const box = h("div", { class: ["plist", cls] });
  const body = h("ul", { class: "plist-rows", "aria-label": label });
  const foot = h("div", { class: "plist-foot" });
  box.append(body, foot);

  // moved: he changed the page or the page size, so the new rows fade in (a live refresh just swaps them)
  async function draw(moved) {
    const count = load ? total : items.length;
    const step = st.size * per;
    const pages = Math.max(1, Math.ceil(count / step));
    st.page = Math.min(st.page, pages - 1);
    const from = st.page * step;
    const rows = load ? await load(from, step) : items.slice(from, from + step);
    if (!count) { body.replaceChildren(); foot.replaceChildren(); if (emptyEl) body.replaceChildren(h("li", { class: "plist-empty" }, emptyEl)); return; }
    body.replaceChildren(...rows.map((it) => h("li", { class: "plist-row" }, row(it))));
    if (moved) enter(body, "fade");
    const seg = count > SIZES[0] * per ? h("div", { class: "seg seg-sm", role: "radiogroup", "aria-label": "تعداد در هر صفحه" },
      SIZES.map((n) => h("button", { type: "button", role: "radio", "aria-checked": String(n === st.size), text: faNum(n * per),
        onclick: () => { st.size = n; st.page = 0; pref("psize", n); draw(true); } }))) : null;
    const nav = pages > 1 ? h("nav", { class: "pager", "aria-label": "صفحه‌بندی" },
      h("button", { type: "button", class: "pager-btn", "aria-label": "صفحهٔ قبل", disabled: st.page === 0, onclick: () => { st.page -= 1; draw(true); } }, icon("chev-r", { size: "sm" })),
      pageNumbers(st.page, pages).map((p) => (p === null ? h("span", { class: "pager-gap", text: "…" }) : h("button", {
        type: "button", class: "pager-num", "aria-current": p === st.page ? "page" : null, "aria-label": `صفحهٔ ${faNum(p + 1)}`,
        text: faNum(p + 1), onclick: () => { st.page = p; draw(true); },
      }))),
      h("button", { type: "button", class: "pager-btn", "aria-label": "صفحهٔ بعد", disabled: st.page >= pages - 1, onclick: () => { st.page += 1; draw(true); } }, icon("chev-l", { size: "sm" }))) : null;
    foot.replaceChildren(...[seg, nav].filter(Boolean));
  }

  box.redraw = (next) => { if (next) items = next; return draw(); };
  draw();
  return box;
}

// ---- toasts: polite, never steal focus, gone after 4s ----
let toastBox = null;

export function toast(text, { tone, action } = {}) {
  if (!toastBox) {
    toastBox = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastBox);
  }
  const el = h("div", { class: ["toast", tone && `toast-${tone}`] }, h("span", { text }),
    action ? h("button", { type: "button", class: "toast-act", text: action.label, onclick: () => { action.onClick(); el.remove(); } }) : null);
  toastBox.append(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 250); }, 4000);
  return el;
}

export { faNum };
