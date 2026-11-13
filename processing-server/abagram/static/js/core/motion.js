// Motion that answers an action: open, close, move. Transform/opacity only; instant when reduced motion is asked.
const query = matchMedia("(prefers-reduced-motion: reduce)");

export const reduced = () => query.matches;

export const DUR = { fast: 150, base: 220, enter: 320, exit: 200 };
export const EASE = {
  std: "cubic-bezier(.2, 0, 0, 1)",
  exit: "cubic-bezier(.3, 0, 1, 1)",
  spring: "linear(0, .06 2.4%, .23 5.1%, .5 8.9%, .75 13.3%, .9 17.7%, 1 22.5%, 1.04 27.8%, 1.05 33%, 1.03 41%, 1.01 50%, 1)",
};

export function animate(el, keyframes, { dur = DUR.base, ease = EASE.std, delay = 0, fill = "none" } = {}) {
  if (!el || !el.animate || reduced()) return Promise.resolve();
  const a = el.animate(keyframes, { duration: dur, easing: ease, delay, fill });
  return a.finished.catch(() => {});
}

const rtl = () => document.documentElement.dir === "rtl";

const KINDS = {
  fade: () => [{ opacity: 0 }, { opacity: 1 }],
  rise: () => [{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }],
  scale: () => [{ opacity: 0, transform: "scale(.96)" }, { opacity: 1, transform: "none" }],
  pop: () => [{ opacity: 0, transform: "scale(.92)" }, { opacity: 1, transform: "none" }],
  sheet: () => [{ transform: "translateY(100%)" }, { transform: "none" }],
  drawer: () => [{ transform: `translateX(${rtl() ? "100%" : "-100%"})` }, { transform: "none" }],
};

export function enter(el, kind = "fade") {
  const frames = (KINDS[kind] || KINDS.fade)();
  return animate(el, frames, { dur: kind === "sheet" || kind === "drawer" ? DUR.enter : DUR.base, ease: kind === "sheet" ? EASE.spring : EASE.std });
}

export function exit(el, kind = "fade") {
  const frames = (KINDS[kind] || KINDS.fade)().reverse();
  return animate(el, frames, { dur: DUR.exit, ease: EASE.exit, fill: "forwards" });
}

/** Shared-element move: el now sits where it ends; it starts at fromRect and travels home. */
export function flip(fromRect, el, { dur = DUR.enter } = {}) {
  if (!fromRect || !el || reduced()) return Promise.resolve();
  const to = el.getBoundingClientRect();
  if (!to.width || !to.height) return Promise.resolve();
  const dx = fromRect.left - to.left;
  const dy = fromRect.top - to.top;
  const sx = fromRect.width / to.width;
  const sy = fromRect.height / to.height;
  return animate(el, [
    { transformOrigin: "0 0", transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
    { transformOrigin: "0 0", transform: "none" },
  ], { dur, ease: EASE.std });
}

/** The layout moved el (a drawer opened, a column changed): it slides from where it was instead of jumping.
 * Transform only (GPU-cheap); a width change happens at once and the slide carries the eye over it. */
export function slideFrom(el, fromRect, { dur = DUR.enter } = {}) {
  if (!fromRect || !el || reduced()) return Promise.resolve();
  el.getAnimations?.().forEach((a) => a.cancel());      // a toggle mid-way: fromRect already holds where it is on screen now
  const to = el.getBoundingClientRect();
  const dx = (fromRect.left + fromRect.width / 2) - (to.left + to.width / 2);
  const dy = fromRect.top - to.top;
  if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return Promise.resolve();
  return animate(el, [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { dur, ease: EASE.std });
}

/** Same-document View Transition when the browser has it; otherwise just run fn. */
export function transition(fn) {
  if (document.startViewTransition && !reduced()) return document.startViewTransition(fn).finished.catch(() => {});
  fn();
  return Promise.resolve();
}

export function stagger(els, kind = "rise", step = 30) {
  if (reduced()) return;
  [...els].slice(0, 12).forEach((el, i) => {
    const frames = (KINDS[kind] || KINDS.rise)();
    animate(el, frames, { dur: DUR.base, delay: i * step, fill: "backwards" });
  });
}
