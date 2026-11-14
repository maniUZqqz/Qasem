import { api } from "../../../../api/client";
import type { CaptionMode } from "./CaptionMode";
import type { SpeechLang } from "./SpeechLanguage";
import type { CaptionLook } from "./CaptionLook";
import type { SilenceAction, SilenceRow } from "./logic";

/** API ِ «تدوینِ خودکار» (backend/apps/content/views_autoedit.py) */

export type SilenceReviewData = {
  ref: string;
  title: string;
  duration: number;
  url: string | null;
  silences: SilenceRow[];
  questions: SilenceRow[];
  counts: Partial<Record<SilenceAction, number>>;
  removed_seconds: number;
  answered: number;
  pending: number;
  /** ready = کلمه‌ها شناخته شده · waiting = سرورِ پردازش خاموش است و کار در صف می‌ماند · off = تشخیصِ گفتار نیست · later = هنوز اجرا نشده */
  words: "ready" | "waiting" | "off" | "later";
  note: string;
  has_picture: boolean;
};

export async function fetchSilences(storeId: string, ref: string): Promise<SilenceReviewData> {
  const { data } = await api.get<SilenceReviewData>(`/stores/${storeId}/autoedit/silences/`, { params: { ref } });
  return data;
}

export async function saveSilenceAnswers(
  storeId: string,
  ref: string,
  answers: { start: number; end: number; action: SilenceAction }[],
  fallback?: SilenceAction | "suggest",
): Promise<SilenceReviewData> {
  const { data } = await api.post<SilenceReviewData>(`/stores/${storeId}/autoedit/silences/`, { ref, answers, ...(fallback ? { default: fallback } : {}) });
  return data;
}

/** چند پرسشِ بی‌پاسخ هست؟ (هرگز خطا نمی‌دهد: اگر نشد، ۰ — تدوین بدونِ پرسش ادامه پیدا می‌کند) */
export async function openQuestions(storeId: string, ref: string): Promise<number> {
  try {
    const d = await fetchSilences(storeId, ref);
    return d.questions.length;
  } catch {
    return 0;
  }
}

export type SizeInfo = { key: string; title: string; network: string; aspect: string; width: number; height: number; max_seconds: number | null; zone: string; export: string };

export async function fetchSizes(storeId: string): Promise<{ sizes: SizeInfo[]; default: string[] }> {
  const { data } = await api.get<{ sizes: SizeInfo[]; default: string[] }>(`/stores/${storeId}/autoedit/sizes/`);
  return data;
}

export type SizeJob = { size: string; title: string; project_id: number; job_id: number; notes: string[] };

export async function makeSizes(storeId: string, projectId: number, sizes: string[], captions?: CaptionMode): Promise<{ jobs: SizeJob[]; skipped: { size: string; title: string; reason: string }[] }> {
  const { data } = await api.post(`/stores/${storeId}/editor/projects/${projectId}/sizes/`, { sizes, ...(captions ? { captions } : {}) });
  return data;
}

export async function startPolish(storeId: string, uploadId: number, opts: { platform?: string; wait_for_words?: boolean; deliver?: boolean; sizes?: string[]; captions?: CaptionMode; language?: SpeechLang; caption_style?: CaptionLook } = {}): Promise<{ job_id: number }> {
  const { data } = await api.post<{ job_id: number }>(`/stores/${storeId}/videos/${uploadId}/autoedit/`, opts);
  return data;
}

export type LookPreview = { ref: string; t: number; duration?: number; auto_t?: boolean; changed: boolean; before: string; after: string; note: string; report: { what?: string; from?: number; to?: number; note?: string }[] };

/** قبل/بعدِ نور و رنگِ خودکارِ یک لحظه از ویدیو (چیزی ذخیره نمی‌شود) */
export async function fetchLookPreview(storeId: string, ref: string, t?: number): Promise<LookPreview> {
  const { data } = await api.get<LookPreview>(`/stores/${storeId}/autoedit/look-preview/`, { params: { ref, ...(t === undefined ? {} : { t }) } });
  return data;
}
