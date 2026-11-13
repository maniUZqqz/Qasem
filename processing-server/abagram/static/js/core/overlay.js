// Dialogs, sheets, menus and confirms: scrim, Esc, focus trap, focus restore, page scroll lock.
import { h, icon, uid } from "./dom.js";
import { enter, exit } from "./motion.js";

const phone = () => matchMedia("(max-width: 767px)").matches;
let open = 0;
const stack = [];   // open layers, topmost last: only the top one answers Esc and Tab

function lockPage(on) {
  open = Math.max(0, open + (on ? 1 : -1));
  if (open) document.documentElement.setAttribute("data-overlay", "");
  else document.documentElement.removeAttribute("data-overlay");
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, video[controls], [tabindex]:not([tabindex="-1"])';
// The big picture viewer (js/vendor/viewer.js) opens above any layer and answers Esc and Tab itself.
const viewerOpen = () => !!document.querySelector(".vw:not([hidden])");

function trap(panel, e) {
  if (e.key !== "Tab") return;
  const items = [...panel.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
  if (!items.length) { e.preventDefault(); panel.focus(); return; }
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/**
 * size: sm (400px) | md (560px) | lg (post viewer) | full (always full screen) | sheet (bottom sheet on phones).
 * bare: no header (the content brings its own). Returns {el, panel, body, close, setTitle}.
 */
export function dialog({ title = "", content, size = "md", onClose, actions, cls, bare = false, label } = {}) {
  const titleId = uid("dlg");
  const back = document.activeElement;
  const asSheet = size === "sheet" && phone();
  const heading = h("h2", { class: "ov-title", id: titleId, text: title });
  const body = h("div", { class: "ov-body" });
  const panel = h("section", {
    class: ["ov-panel", cls], role: "dialog", "aria-modal": "true", tabindex: "-1",
    "aria-labelledby": bare ? null : titleId, "aria-label": bare ? label || title : null,
  },
  asSheet ? h("div", { class: "ov-grab", "aria-hidden": "true" }) : null,
  bare ? null : h("header", { class: "ov-head" }, heading,
    h("button", { type: "button", class: "icon-btn ov-close", "aria-label": "بستن", onclick: () => close() }, icon("x"))),
  body,
  actions ? h("footer", { class: "ov-foot" }, actions) : null);
  const scrim = h("div", { class: "ov-scrim", onclick: () => close() });
  const el = h("div", { class: "ov-layer", "data-size": size, style: `z-index:${40 + open}` }, scrim, panel);
  if (content) body.append(...[content].flat().filter(Boolean));

  let closed = false;
  const onKey = (e) => {
    if (stack[stack.length - 1] !== el || viewerOpen()) return;
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    else trap(panel, e);
  };
  async function close(reason) {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey, true);
    await Promise.all([exit(panel, asSheet || (phone() && size !== "sm") ? "sheet" : "scale"), exit(scrim, "fade")]);
    el.remove();
    stack.splice(stack.indexOf(el), 1);
    lockPage(false);
    if (back && back.focus && document.contains(back)) back.focus({ preventScroll: true });
    onClose?.(reason);
  }

  document.body.append(el);
  stack.push(el);
  lockPage(true);
  document.addEventListener("keydown", onKey, true);
  enter(scrim, "fade");
  enter(panel, asSheet || (phone() && size !== "sm") ? "sheet" : "scale");
  requestAnimationFrame(() => (panel.querySelector("[autofocus]") || panel.querySelector(FOCUSABLE) || panel).focus({ preventScroll: true }));
  return { el, panel, body, close, setTitle: (t) => (heading.textContent = t) };
}

export const sheet = (opts) => dialog({ ...opts, size: "sheet" });

export function confirm({ title, text, cta = "ادامه", cancel = "انصراف", danger = false } = {}) {
  return new Promise((resolve) => {
    let answer = false;
    const yes = h("button", { type: "button", class: ["btn", "full", danger ? "danger" : "primary"], text: cta, onclick: () => { answer = true; d.close(); } });
    const no = h("button", { type: "button", class: "btn ghost full", text: cancel, onclick: () => d.close() });
    const d = sheet({ title, content: text ? h("p", { class: "ov-text", text }) : null, actions: [yes, no], onClose: () => resolve(answer) });
  });
}

/** items: [{icon, label, hint, danger, disabled, onSelect}] — a popover menu on desktop, an action sheet on phones. */
export function menu(anchor, items, { label = "گزینه‌ها" } = {}) {
  const rows = (closeFn) => items.filter(Boolean).map((it) => h("button", {
    type: "button", role: "menuitem", class: ["mn-item", it.danger && "danger"], disabled: !!it.disabled,
    onclick: () => { closeFn(); it.onSelect?.(); },
  }, it.icon ? icon(it.icon) : null, h("span", { class: "mn-text" }, h("span", { text: it.label }), it.hint ? h("small", { text: it.hint }) : null)));

  if (phone()) {
    const d = dialog({ size: "sheet", bare: true, label, cls: "mn-sheet" });
    d.body.append(h("div", { role: "menu", class: "mn-list" }, rows(() => d.close())));
    return d;
  }
  const back = document.activeElement;
  const pop = h("div", { class: "mn-pop", role: "menu", "aria-label": label });
  const done = () => { pop.remove(); document.removeEventListener("pointerdown", outside, true); document.removeEventListener("keydown", keys, true); back?.focus?.({ preventScroll: true }); };
  pop.append(...rows(done));
  const outside = (e) => { if (!pop.contains(e.target) && e.target !== anchor) done(); };
  const keys = (e) => {
    const list = [...pop.querySelectorAll(".mn-item:not(:disabled)")];
    const i = list.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); done(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length]?.focus(); }
    else if (e.key === "Tab") done();
  };
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth;
  const inlineEnd = document.documentElement.dir === "rtl" ? Math.max(8, r.left) : Math.min(innerWidth - w - 8, r.right - w);
  pop.style.top = `${Math.min(r.bottom + 6, innerHeight - pop.offsetHeight - 8)}px`;
  pop.style.left = `${Math.max(8, Math.min(inlineEnd, innerWidth - w - 8))}px`;
  enter(pop, "pop");
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("keydown", keys, true);
  pop.querySelector(".mn-item:not(:disabled)")?.focus();
  return { close: done };
}
