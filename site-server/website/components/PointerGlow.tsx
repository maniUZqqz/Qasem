"use client";

import { useEffect } from "react";

/**
 * درخششی که زیر اشاره‌گر حرکت می‌کند، روی هر المان `.glow-edge`.
 *
 * یک شنونده روی کل صفحه، نه یکی به‌ازای هر کارت: صفحه‌ی راه‌حل‌ها بیش از
 * چهل کارت دارد و چهل شنونده‌ی pointermove یعنی چهل بار کار در هر حرکت
 * موشواره.
 *
 * `passive` است و در هر فریم حداکثر یک بار می‌نویسد — نوشتن مستقیم روی
 * هر رویداد، در مرورگر layout مجدد می‌سازد و همان افکتی که قرار بود
 * روان باشد، تکان‌تکان می‌شود.
 *
 * روی لمس اصلاً نصب نمی‌شود: hover آنجا حالتی است که گیر می‌کند، و
 * درخششی که بعد از تپ روی کارت می‌ماند، بیشتر شبیه باگ است تا افکت.
 */
export default function PointerGlow() {
  useEffect(() => {
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    let pending: { el: HTMLElement; x: number; y: number } | null = null;

    const flush = () => {
      frame = 0;
      if (!pending) return;
      const { el, x, y } = pending;
      pending = null;
      el.style.setProperty("--mx", `${x}px`);
      el.style.setProperty("--my", `${y}px`);
    };

    const onMove = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest<HTMLElement>(".glow-edge");
      if (!el) return;
      const r = el.getBoundingClientRect();
      pending = { el, x: e.clientX - r.left, y: e.clientY - r.top };
      if (!frame) frame = requestAnimationFrame(flush);
    };

    document.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      document.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return null;
}
