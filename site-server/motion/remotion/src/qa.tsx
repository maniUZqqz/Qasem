// QA probe: when the composition is rendered with `spec.qa`, the page reports the GEOMETRY of every text block / box it drew (console line "NMQA:{json}")
// after the fonts are loaded and the layout is settled. tools/qa.mjs collects these lines next to a still of the same frame, and the backend
// (apps/motion/qa.py) judges them: overflow, clipping, overlap, safe zone, minimum size, contrast (the pixels behind the text come from the still).
import React, { useEffect, useRef, useState } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";
import { useCtx } from "./ctx";

type Box = {
  kind: string; scene: number; role: string; size: number; x: number; y: number; w: number; h: number;
  color: string; text: string; overflow: boolean; clipped: boolean; opacity: number; id: number; parent: number; overlay: string; excl: string;
};

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
    out.push({
      kind, scene, role: el.getAttribute("data-nm-role") || "", size: Number(el.getAttribute("data-nm-size") || 0),
      x: r.left, y: r.top, w: r.width, h: r.height, color: kind === "text" ? colorOf(el) : "", text: kind === "text" ? (el.textContent || "").slice(0, 90) : "",
      overflow: (el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth + 2 && getComputedStyle(el).overflow !== "visible",
      clipped: clippedBy(el, r, sceneEl), opacity: Math.round(effectiveOpacity(el, sceneEl) * 100) / 100, id: ids.get(el) as number, parent,
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
