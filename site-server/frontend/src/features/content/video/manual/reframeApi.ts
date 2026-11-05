import { api } from "../../../../api/client";
import type { Reframe } from "./model";

/** نسبتِ مقصد: نام‌های آماده یا عددِ عرض/ارتفاع */
export type ReframeAspect = "9:16" | "1:1" | "4:5" | "16:9" | "3:4" | number;
export type ReframeEngine = "face" | "motion" | "center";

export type ReframeRequest = {
  ref: string;
  /** ثانیه‌های «منبع» (نه تایم‌لاین) */
  start: number;
  end: number;
  aspect: ReframeAspect;
  follow?: "auto" | "center";
  /** ≥ ۱؛ بیشتر = نزدیک‌تر به سوژه */
  zoom?: number;
  /** سرعتِ قطعه: زمانِ کلیدها به ثانیهٔ تایم‌لاین برمی‌گردد */
  speed?: number;
};

export type ReframeResult = { reframe: Reframe; engine: ReframeEngine; samples: number; notes: string[] };

/** نسبت‌هایی که رابط پیشنهاد می‌دهد (کلید = همان رشتهٔ API) */
export const REFRAME_TARGETS: { key: Exclude<ReframeAspect, number>; title: string }[] = [
  { key: "9:16", title: "۹:۱۶" },
  { key: "1:1", title: "۱:۱" },
  { key: "4:5", title: "۴:۵" },
  { key: "16:9", title: "۱۶:۹" },
];

/** سوژه‌ای که پنجره دنبالش رفته، به فارسی */
export const ENGINE_FA: Record<ReframeEngine, string> = { face: "چهره", motion: "حرکت", center: "وسطِ قاب" };

export const reframeApi = {
  /** پیشنهادِ پنجرهٔ برش با دنبال‌کردنِ سوژه (هم‌گام، تا حدودِ ۲۰ ثانیه) */
  run: (store: string, body: ReframeRequest) =>
    api.post<ReframeResult>(`/stores/${store}/editor/reframe/`, body, { timeout: 90_000 }).then((r) => r.data),
};
