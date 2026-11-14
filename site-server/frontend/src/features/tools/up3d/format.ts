/**
 * قالب‌بندیِ بی‌وابستگی (ارقامِ فارسی و مدتِ زمان): بدونِ هیچ importی از UI/axios تا آزمون‌های node (tests/up3d-queue.test.ts)
 * بتوانند بی‌مرورگر بارش کنند. api.ts همین‌ها را دوباره صادر می‌کند.
 */

/** ۱۲۳ ⇒ «۱۲۳» (همان fa ِ components/ui) */
export function faDigits(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

/** ثانیه ⇐ «۳ دقیقه و ۱۰ ثانیه» */
export function dur(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s0 = Math.max(0, Math.round(sec));
  const h = Math.floor(s0 / 3600);
  const m = Math.floor((s0 % 3600) / 60);
  const s = s0 % 60;
  if (h) return `${faDigits(h)} ساعت و ${faDigits(m)} دقیقه`;
  if (m) return `${faDigits(m)} دقیقه${s && m < 10 ? ` و ${faDigits(s)} ثانیه` : ""}`;
  return `${faDigits(s)} ثانیه`;
}
