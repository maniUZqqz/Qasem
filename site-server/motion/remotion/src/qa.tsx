// QA probe: when the composition is rendered with `spec.qa`, the page reports the GEOMETRY of every text block / box it drew (console line "NMQA:{json}")
// after the fonts are loaded and the layout is settled. tools/qa.mjs collects these lines next to a still of the same frame, and the backend
// (apps/motion/qa.py) judges them: overflow, clipping, overlap, safe zone, minimum size, contrast (the pixels behind the text come from the still).
import React, { useEffect, useRef, useState } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";
import { useCtx } from "./ctx";

type Box = {
  kind: string; scene: number; role: string; size: number; x: number; y: number; w: number; h: number;
  // the VISIBLE extent of a text block: the union of its word boxes (a block-level container is often as wide as its column although the glyphs are not)
  gx: number; gy: number; gw: number; gh: number;
  color: string; text: string; overflow: boolean; clipped: boolean; opacity: number; id: number; parent: number; overlay: string; excl: string; fixed: boolean;
};

/**
 * where an element sits in the LAYOUT (viewport pixels), ignoring its own transform: a word that is still entering (sliding in from far above, scaled up,
 * rotated) is judged at the place it will settle, not on its way - the transient position is not a defect. The offset box is relative to the offset parent,
 * whose own rect (scene transitions, scales) maps it to the viewport. No offset parent (display:none, fixed): the plain bounding box.
 */
function layoutRect(n: HTMLElement): { left: number; top: number; right: number; bottom: number } {
  const op = n.offsetParent as HTMLElement | null;
  if (!op || typeof n.offsetWidth !== "number") {
    const b = n.getBoundingClientRect();
    return { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
  }
  if (op === document.body || op === document.documentElement) {           // the offsets are measured from the initial containing block: already viewport pixels
    return { left: n.offsetLeft - window.scrollX, top: n.offsetTop - window.scrollY, right: n.offsetLeft - window.scrollX + n.offsetWidth, bottom: n.offsetTop - window.scrollY + n.offsetHeight };
  }
  const pr = op.getBoundingClientRect();
  const sx = op.offsetWidth > 0 ? pr.width / op.offsetWidth : 1;
  const sy = op.offsetHeight > 0 ? pr.height / op.offsetHeight : 1;
  const left = pr.left + (op.clientLeft + n.offsetLeft) * sx;
  const top = pr.top + (op.clientTop + n.offsetTop) * sy;
  return { left, top, right: left + n.offsetWidth * sx, bottom: top + n.offsetHeight * sy };
}

/** union of the boxes of the elements that directly hold text (the words), or of the block itself when it paints its own background */
export function glyphRect(el: Element, r: DOMRect): { x: number; y: number; w: number; h: number } {
  const cs = getComputedStyle(el);
  const paints = (cs.backgroundImage && cs.backgroundImage !== "none") || (() => {
    const m = /rgba?\(([^)]+)\)/.exec(cs.backgroundColor || "");
    if (!m) return false;
    const p = m[1].split(/[ ,/]+/).filter(Boolean);
    return p.length < 4 || parseFloat(p[3]) > 0.05;
  })();
  if (paints) return { x: r.left, y: r.top, w: r.width, h: r.height };      // a visible plate (caption bar, chip): the plate is what the viewer sees
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, sawText = false;
  const all: Element[] = [el, ...Array.from(el.querySelectorAll("*"))];
  for (const n of all) {
    let own = false;
    n.childNodes.forEach((c) => {
      if (c.nodeType === 3 && (c.textContent || "").trim()) own = true;
    });
    if (!own) continue;
    sawText = true;
    const cs2 = getComputedStyle(n);
    if (parseFloat(cs2.opacity) < 0.05 || cs2.visibility === "hidden") continue;       // a word that has not entered yet (or the untyped rest) is not on screen
    const b = layoutRect(n as HTMLElement);
    if (b.right - b.left < 1 || b.bottom - b.top < 1) continue;
    x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom);
  }
  if (!Number.isFinite(x0)) return sawText ? { x: r.left + r.width / 2, y: r.top + r.height / 2, w: 0, h: 0 } : { x: r.left, y: r.top, w: r.width, h: r.height };
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function colorOf(el: Element): string {
  // the colour the reader sees: the first word's (the effects live on the word spans) - transparent fills (gradient text) are reported as is
  const inner = (el.querySelector("span") as HTMLElement | null) ?? (el as HTMLElement);
  const cs = getComputedStyle(inner);
  const fill = (cs as any).webkitTextFillColor;
  return fill && fill !== "rgba(0, 0, 0, 0)" && fill !== "transparent" ? fill : cs.color;
}

function effectiveOpacity(el: Element, stop: Element | null): number {
  let o = 1;
  for (let n: Element | null = el; n && n !== stop; n = n.parentElement) {
    const v = parseFloat(getComputedStyle(n).opacity);
    if (Number.isFinite(v)) o *= v;
  }
  return o;
}

function clippedBy(el: Element, r: DOMRect, stop: Element | null): boolean {
  for (let n = el.parentElement; n && n !== stop; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.overflow !== "visible" || cs.overflowX !== "visible" || cs.overflowY !== "visible") {
      const p = n.getBoundingClientRect();
      if (r.left < p.left - 2 || r.right > p.right + 2 || r.top < p.top - 2 || r.bottom > p.bottom + 2) return true;
    }
  }
  return false;
}

export function collect(root: Document | Element): Box[] {
  const out: Box[] = [];
  const ids = new Map<Element, number>();
  const els = Array.from(root.querySelectorAll("[data-nm]"));
  els.forEach((el, i) => ids.set(el, i));
  for (const el of els) {
    const kind = el.getAttribute("data-nm") || "";
    if (kind !== "text" && kind !== "box" && kind !== "stage") continue;
    const sceneEl = el.closest("[data-nm-scene]");
    const scene = sceneEl ? Number(sceneEl.getAttribute("data-nm-scene")) : -1;
    const ov = el.closest("[data-nm-overlay]");
    const r = el.getBoundingClientRect();
    let parent = -1;
    for (let n = el.parentElement; n; n = n.parentElement) {
      if (ids.has(n)) { parent = ids.get(n) as number; break; }
    }
    const g = kind === "text" ? glyphRect(el, r) : { x: r.left, y: r.top, w: r.width, h: r.height };
    out.push({
      kind, scene, role: el.getAttribute("data-nm-role") || "", size: Number(el.getAttribute("data-nm-size") || 0),
      x: r.left, y: r.top, w: r.width, h: r.height, gx: g.x, gy: g.y, gw: g.w, gh: g.h,
      color: kind === "text" ? colorOf(el) : "", text: kind === "text" ? (el.textContent || "").slice(0, 90) : "",
      fixed: el.getAttribute("data-nm-fixed") === "1",                       // the component chose this colour itself (tokens.text does not reach it)
      overflow: (el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth + 2 && getComputedStyle(el).overflow !== "visible",
      clipped: clippedBy(el, new DOMRect(g.x, g.y, g.w, g.h), sceneEl), opacity: Math.round(effectiveOpacity(el, sceneEl) * 100) / 100, id: ids.get(el) as number, parent,
      overlay: ov ? ov.getAttribute("data-nm-overlay") || "" : "",
      excl: el.closest("[data-nm-excl]")?.getAttribute("data-nm-excl") || "",         // layers stacked on purpose (before/after wipe): never an overlap
    });
  }
  return out;
}

export const QaProbe: React.FC = () => {
  const frame = useCurrentFrame();
  const ctx = useCtx();
  const [handle] = useState(() => delayRender("nm-qa-probe", { timeoutInMilliseconds: 60000 }));
  const done = useRef(false);
  useEffect(() => {
    if (!ctx.fonts || done.current) return;
    done.current = true;
    let n = 0;
    const tick = () => {
      if (++n < 4) {
        requestAnimationFrame(tick);
        return;
      }
      try {
        const boxes = collect(document);
        // eslint-disable-next-line no-console
        console.log("NMQA:" + JSON.stringify({ frame, W: ctx.W, H: ctx.H, fps: ctx.fps, platform: ctx.platform, safe: ctx.safe, boxes }));
      } catch (e) {
        // eslint-disable-next-line no-console
        console.log("NMQA:" + JSON.stringify({ frame, error: String(e) }));
      } finally {
        continueRender(handle);
      }
    };
    requestAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.fonts]);
  return null;
};
