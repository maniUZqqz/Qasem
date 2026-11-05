import { useEffect, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { fa } from "../../../../components/ui";
import { AssetKind, AudioAsset, assetFile, createAsset, getAsset, isFinal, listAssets, patchAsset } from "../../../audio/api";
import type { MediaItem } from "../api";
import { Project, fromApi, toApi } from "./model";

/**
 * سرویس‌گیرِ «صداگذاریِ راحت‌تر»:
 *  ۱) `directorApply` — ابزارهای صدا (add_music، remove_silence، set_loudness، clean_voice، auto_mix، add_voiceover، ducking) از راهِ
 *     POST editor/director/apply/ ؛ پروژهٔ تازه برمی‌گردد و یک گامِ برگشت می‌شود.
 *  ۲) `makeAsset` — ساختنِ گفتار/موسیقی در کتابخانهٔ صدا، تا آماده‌شدن صبر می‌کند، و «ذخیره» می‌کند تا در سطلِ رسانه بیاید.
 *  ۳) `useAudioKinds` — نوعِ هر صدای ذخیره‌شده (گفتار/موسیقی/افکت)، چون سطلِ رسانه نوع را نمی‌گوید.
 */

/** پیامِ خطا: پیامِ فارسیِ سرور همان‌طور که هست، یا متنِ خطای خودمان (مثلاً «بیش از حد طول کشید») */
export function soundError(err: unknown): string {
  const m = errorMessage(err);
  return m === "خطای ناشناخته" && err instanceof Error && err.message ? err.message : m;
}

export type DirectorStep ={ tool: string; params: Record<string, unknown> };
export type DirectorResult = { tool: string; ok: boolean; message: string };
export type DirectorOutcome = {
  /** پروژهٔ تازه؛ null = پاسخ پروژهٔ معتبر نداشت (چیزی نباید جایگزین شود) */
  project: Project | null;
  results: DirectorResult[];
  notes: string[];
};

export async function directorApply(storeId: string, project: Project, steps: DirectorStep[]): Promise<DirectorOutcome> {
  const { data } = await api.post<{ data?: unknown; results?: DirectorResult[]; notes?: string[] }>(
    `/stores/${storeId}/editor/director/apply/`,
    { data: toApi(project), steps },
  );
  const d = data?.data as { tracks?: unknown } | undefined;
  const valid = !!d && Array.isArray(d.tracks) && d.tracks.length > 0;
  return { project: valid ? fromApi(data.data) : null, results: data?.results ?? [], notes: data?.notes ?? [] };
}

/** آپلودِ یک فایلِ صدا (مثلاً ضبطِ گوشی) به کتابخانهٔ صدا؛ فایل در سرور به wav تبدیل و «ذخیره» می‌شود. */
export async function uploadAudio(storeId: string, file: File, kind: "speech" | "music" | "sfx" = "speech"): Promise<AudioAsset> {
  const body = new FormData();
  body.append("file", file);
  body.append("kind", kind);
  body.append("title", file.name.replace(/\.[^.]+$/, "").slice(0, 100));
  const { data } = await api.post<AudioAsset>(`/stores/${storeId}/audio/assets/upload/`, body, { timeout: 120_000 });
  return data;
}

// ───────────── ساختنِ صدا (گفتار / موسیقی) و صبر تا آماده شدن
const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));
const MAX_WAIT_MS = 8 * 60 * 1000;

const progressText = (a: AudioAsset): string => {
  const pct = a.job && a.job.progress > 0 && a.job.progress < 1 ? ` (${fa(Math.round(a.job.progress * 100))}٪)` : "";
  const what = a.job?.message || a.job?.label || (a.status === "PENDING" ? "در صفِ سرورِ پردازش…" : "در حالِ ساختن…");
  return `${what}${pct}`;
};

/**
 * `body` همان بدنهٔ POST /stores/{id}/audio/assets/ است. خطای ساخت (مثلاً «سرورِ پردازش خاموش است…») همان‌طور که هست پرتاب می‌شود؛
 * پس از آماده‌شدن، دارایی «ذخیره» می‌شود تا در سطلِ رسانه (ref = audio:<id>) بیاید.
 */
export async function makeAsset(storeId: string, body: Record<string, unknown>, onProgress: (text: string) => void): Promise<AudioAsset> {
  onProgress("در حالِ فرستادنِ درخواست…");
  let a = await createAsset(storeId, body);
  const t0 = Date.now();
  while (!isFinal(a)) {
    if (Date.now() - t0 > MAX_WAIT_MS) throw new Error("ساختِ صدا بیش از حد طول کشید؛ کمی بعد در بخشِ «صدا» از پنل ببینید.");
    onProgress(progressText(a));
    await sleep(2000);
    a = await getAsset(storeId, a.id);
  }
  if (a.status === "FAILED") throw new Error(a.error || "ساختِ صدا ناموفق بود.");
  onProgress("آماده شد؛ در حالِ ذخیره…");
  return patchAsset(storeId, a.id, { saved: true });
}

/** یک دارایی که همین حالا ساخته شده، به‌شکلِ «آیتمِ سطلِ رسانه» (برای پیش‌شنیدن پیش از آن‌که سطل دوباره بارگیری شود) */
export const assetAsMedia = (storeId: string, a: AudioAsset): MediaItem => ({
  ref: `audio:${a.id}`, title: a.title || (a.kind === "MUSIC" ? "موسیقی" : "گفتار"), kind: "audio", source: "audio", duration: a.duration || 0,
  has_audio: true, width: 0, height: 0, url: `/api/v1${assetFile(storeId, a.id)}`, auth: true, proxy: "not_needed", proxy_url: null,
});

/**
 * نوعِ هر صدای ذخیره‌شدهٔ فروشگاه، با کلیدِ ref (`audio:<id>`). null تا وقتی بارگیری نشده (یا ناموفق بوده).
 * `version` را عوض کنید تا دوباره بخواند (مثلاً وقتی سطل تازه شد).
 */
export function useAudioKinds(storeId: string | undefined, enabled: boolean, version: number): Record<string, AssetKind> | null {
  const [kinds, setKinds] = useState<Record<string, AssetKind> | null>(null);
  useEffect(() => {
    if (!storeId || !enabled) return;
    let alive = true;
    listAssets(storeId, { saved: true }).then(
      (rows) => {
        if (alive) setKinds(Object.fromEntries(rows.map((r) => [`audio:${r.id}`, r.kind])));
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [storeId, enabled, version]);
  return kinds;
}
