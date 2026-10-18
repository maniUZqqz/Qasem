import axios from "axios";

import { api, errorMessage } from "../../../api/client";

/**
 * کمک‌تابع‌های مشترکِ صفحه‌های سایت‌ساز.
 *
 * همهٔ درخواست‌ها با همان نمونهٔ `api` (JWT خودکار) و زیرِ `/studio/…` می‌روند.
 * خطاهای این API شکلِ `{error: "…"}` یا `{errors: {field: "…"}}` دارند —
 * `errorMessage` عمومیِ پنل این دو را نمی‌شناسد، پس اول همین‌جا خوانده می‌شوند.
 */

/** ریشهٔ مسیرهای این ابزار داخلِ روترِ پنل (basename خودِ روتر /panel است). */
export const BASE = "/tools/studio";

export function pUrl(slug: string, sub = ""): string {
  return `${BASE}/p/${slug}${sub ? `/${sub}` : ""}`;
}

export function studioError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as
      | { error?: unknown; errors?: Record<string, unknown>; detail?: unknown }
      | undefined;
    if (data && typeof data === "object") {
      if (typeof data.error === "string") return data.error;
      if (data.errors && typeof data.errors === "object") {
        const first = Object.values(data.errors)[0];
        if (typeof first === "string") return first;
        if (Array.isArray(first) && first.length) return String(first[0]);
      }
      if (typeof data.detail === "string") return data.detail;
    }
    if (err.response?.status === 403) return "دسترسی نداری — فقط کاربرِ کارمند (is_staff) به سایت‌ساز راه دارد.";
  }
  return errorMessage(err);
}

/** خطای فیلدمحور (برای نشان‌دادن زیرِ همان فیلد)، اگر سرور فرستاده باشد. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { errors?: Record<string, unknown> } | undefined;
    if (data?.errors && typeof data.errors === "object") {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(data.errors)) {
        if (typeof v === "string") out[k] = v;
        else if (Array.isArray(v) && v.length) out[k] = String(v[0]);
      }
      return out;
    }
  }
  return {};
}

/** «1404/07/23 14:05» از ISO؛ همان قالبِ `Y/m/d H:i` ِ رابطِ قدیمی، به وقتِ مرورگر. */
export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const two = (n: number) => String(n).padStart(2, "0");
  const date = `${d.getFullYear()}/${two(d.getMonth() + 1)}/${two(d.getDate())}`;
  return withTime ? `${date} ${two(d.getHours())}:${two(d.getMinutes())}` : date;
}

/** «m/d H:i» — جدولِ پیشنهادها */
export function fmtShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(d.getMonth() + 1)}/${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

export function truncate(s: string | null | undefined, n: number): string {
  const t = s ?? "";
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

/**
 * دانلودِ ZIPِ خروجی. لینکِ ساده نمی‌شود چون JWT در هدر می‌رود نه در URL؛
 * پس blob می‌گیریم و با یک object URL ذخیره می‌کنیم.
 */
export async function downloadZip(slug: string, withGit: boolean): Promise<void> {
  try {
    const { data } = await api.get<Blob>(`/studio/projects/${slug}/export/${withGit ? "?git=1" : ""}`, {
      responseType: "blob",
    });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${slug}${withGit ? "-git" : ""}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (err) {
    // با responseType=blob بدنهٔ خطا هم Blob است؛ متنش را بخوان تا پیامِ فارسیِ سرور دیده شود
    if (axios.isAxiosError(err) && err.response?.data instanceof Blob) {
      const text = await err.response.data.text();
      let message = text;
      try {
        const parsed = JSON.parse(text) as { error?: string; detail?: string };
        message = parsed.error || parsed.detail || text;
      } catch {
        /* متنِ خام */
      }
      throw new Error(message || studioError(err));
    }
    throw new Error(studioError(err));
  }
}

/** ۱۲۳ ⇒ «۱۲۳» */
export function fa(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

export { api };
