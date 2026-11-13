// Building DOM without HTML strings: Instagram's text can never run as markup.
const SVG_NS = "http://www.w3.org/2000/svg";

// Instagram's picture/video host forbids showing its files on other sites (Cross-Origin-Resource-Policy:
// same-origin), so every such address goes through our own server (/api/img caches pictures, /api/vid streams).
const IG_HOST = /^https:\/\/[^/]+\.(cdninstagram\.com|fbcdn\.net)\//i;

export function proxied(url, kind = "img") {
  return typeof url === "string" && IG_HOST.test(url) ? `/api/${kind}?u=${encodeURIComponent(url)}` : url;
}

function apply(el, attrs) {
  const tag = el.tagName ? el.tagName.toLowerCase() : "";
  for (let [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if ((key === "src" || key === "poster") && typeof value === "string") {
      value = proxied(value, key === "src" && (tag === "video" || tag === "source") ? "vid" : "img");
    }
    if (key === "class") el.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
    else if (key === "text") el.textContent = String(value);
    else if (key === "style") el.setAttribute("style", value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false || kid === true) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, kids);
  return el;
}

export function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, kids);
  return el;
}

const SIZES = { sm: "ic-sm", md: "", lg: "ic-lg" };

export function icon(name, { size = "md", cls, label } = {}) {
  const el = svg("svg", { class: ["ic", SIZES[size] || "", cls], ...(label ? { role: "img", "aria-label": label } : { "aria-hidden": "true" }) },
    svg("use", { href: `#i-${name}` }));
  return el;
}

export const ltr = (text) => h("bdi", { dir: "ltr", text: text ?? "" });
export const bdi = (text) => h("bdi", { text: text ?? "" });

export function mount(el, ...kids) {
  el.replaceChildren();
  append(el, kids);
  return el;
}

export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

export function on(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  return () => target.removeEventListener(type, fn, opts);
}

let counter = 0;
export const uid = (prefix = "id") => `${prefix}-${++counter}`;
