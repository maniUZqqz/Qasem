import { dur, faDigits as fa } from "./format";
import type { Estimate, Job } from "./types";

/**
 * متنِ «در صف بگذار»: وقتی کارگرِ مناسب (معمولاً GPU) آنلاین نیست، کار در صفِ ماندگار می‌ماند و بی‌هیچ کاری از مالک
 * (به‌روزرسانیِ خودکار ⇐ نصبِ Blender ⇐ رندر) وقتی سرورِ پردازش روشن شد اجرا می‌شود. این‌ها فقط توابعِ خالص‌اند (آزمون: tests/up3d-queue.test.ts).
 */

/** جملهٔ تخمین برای یک پروفایل (در کارتِ پروفایل و در خلاصه). */
export function estimateText(e: Estimate | undefined): { text: string; tone: "ok" | "warn" | "bad" | "neutral" } {
  if (!e) return { text: "در حالِ تخمین…", tone: "neutral" };
  if (e.available) return { text: `${fa(e.frames)} فریم · ~${dur(e.seconds)} روی ${e.worker}`, tone: "ok" };
  if (e.cpu_seconds)
    return { text: `${fa(e.frames)} فریم · کارگرِ GPU آنلاین نیست · در صف می‌ماند تا روشن شود (یا روی CPU ِ سرور ~${dur(e.cpu_seconds)})`, tone: "warn" };
  return { text: `${fa(e.frames)} فریم · هیچ کارگری آنلاین نیست · در صف می‌ماند تا کارگری آنلاین شود`, tone: "warn" };
}

/** دقیقاً منتظرِ چه چیزی هستیم؟ (از وضعیتِ سرورهای پردازشِ GPU که تخمین گزارش کرده) */
export function queueNote(e: Estimate | undefined): string {
  const nodes = e?.gpu_nodes || [];
  if (nodes.length === 0) return "کار در صفِ ماندگار می‌ماند و وقتی یک کارگرِ مناسب آنلاین شد خودکار اجرا می‌شود.";
  const lines = nodes.map((n) => {
    if (!n.online) {
      return `سرورِ پردازشِ ${n.name} آفلاین است؛ همین که روشن شود، خودش را به‌روز می‌کند، Blender را نصب می‌کند و این رندر را اجرا می‌کند — کاری از شما لازم نیست.`;
    }
    if (!n.via_queue) return `سرورِ پردازشِ ${n.name} آنلاین است و در حالِ به‌روزرسانیِ خودکار؛ بعد از آن کار را برمی‌دارد.`;
    if (n.install && n.install !== "ready") return `سرورِ پردازشِ ${n.name}: Blender در حالِ نصبِ خودکار است؛ بعد از آن رندر شروع می‌شود.`;
    return `سرورِ پردازشِ ${n.name} آماده است؛ کار به نوبتِ کارتِ گرافیک (یکی‌یکی با کارهای سنگینِ دیگر) اجرا می‌شود.`;
  });
  return lines.join(" ");
}

/** پیامِ کوتاهِ بعد از ساختنِ یک کار (توست). */
export function queuedText(j: Job): string {
  const w = j.waiting;
  if (!w || w.eligible.length > 0) return `کار #${fa(j.id)} در صف گذاشته شد`;
  if (w.node_queue && w.node_queue.length > 0) return `کار #${fa(j.id)} در صفِ سرورِ پردازشِ ${w.node_queue.join("، ")} است و خودکار اجرا می‌شود`;
  const nodes = w.gpu_nodes || [];
  if (nodes.length > 0)
    return `کار #${fa(j.id)} در صفِ انتظار ماند؛ وقتی سرورِ پردازشِ ${nodes.map((n) => n.name).join("، ")} روشن شد خودکار اجرا می‌شود`;
  return `کار #${fa(j.id)} در صفِ انتظار ماند؛ وقتی کارگری آنلاین شد خودکار اجرا می‌شود`;
}
