import { ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * لایه‌های تمام‌صفحه (دوربین، برگهٔ عکس‌برداری، نوارِ پایین) مستقیم زیرِ body: قابِ پنل (انیمیشن و
 * backdrop-filter) برای `position: fixed` «بلوکِ دربرگیرنده» می‌سازد و لایه را وسطِ صفحه گیر می‌انداخت.
 */
export default function Portal({ children }: { children: ReactNode }) {
  if (typeof document === "undefined") return null;
  return createPortal(children, document.body);
}

/** ترتیبِ لایه‌ها: برگهٔ عکس‌برداری < نوارِ پایین < دوربینِ زنده. */
export const LAYER = { sheet: 50, bar: 55, camera: 70 } as const;
