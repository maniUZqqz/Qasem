/**
 * «آزمونِ خودکارِ سرورِ پردازش» — نوع‌ها و واژه‌های فارسیِ صفحه (۱۴۰۵/۰۸/۲۱).
 * داده از GET /compute/selftests/ می‌آید (backend/apps/compute/views_platform.py).
 */
import type { QueueOutput } from "../queue/model";

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

export type TestState = "PENDING" | "WAITING" | "QUEUED" | "RUNNING" | "PASSED" | "FAILED" | "SKIPPED";

export type GpuSample = {
  util_avg?: number;
  util_max?: number;
  vram_max_mb?: number;
  vram_total_mb?: number;
  temp_max_c?: number;
};

export type TestResult = {
  key: string;
  label: string;
  group: string;
  state: TestState;
  state_label: string;
  optional: boolean;
  detail: string;
  device: string;
  warning: string;
  seconds: number | null;
  artifacts: QueueOutput[];
  extra: { gpu?: GpuSample; tokens_per_s?: number; before?: string; after?: string; action?: string; audio_seconds?: number };
  job: string;
  describe: string;
  deep: boolean;
  started: string | null;
  finished: string | null;
};

export type RunSummary = {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  pending: number;
  required_failed: number;
  ok: boolean;
  warnings: number;
};

export type RequeueInfo = { retried?: number; skipped?: number; errors?: string[]; kinds?: string[] };

export type Run = {
  id: number;
  node: string;
  node_id: number;
  trigger: string;
  state: "RUNNING" | "FINISHED" | "ABORTED";
  state_label: string;
  by: string;
  agent_version: string;
  code_id: string;
  created: string;
  finished: string | null;
  note: string;
  requeued: Record<string, RequeueInfo>;
  summary: RunSummary;
  node_online: boolean;
  node_agent: string | null;
  results?: TestResult[];
};

export type BootItem = {
  id: string;
  type: string;
  title: string;
  state: string;
  progress: number | null;
  detail: string;
  error: string;
  tail: string[];
  tries: number;
};

export type BootFeature = {
  title: string;
  state: "ready" | "installing" | "waiting" | "failed" | "skipped";
  kinds: string[];
  items: BootItem[];
  applicable: boolean;
  why: string;
};

export type Bootstrap = {
  features?: Record<string, BootFeature>;
  summary?: Record<string, number>;
  blocked_kinds?: Record<string, string>;
  errors?: { file: string; error: string }[];
};

export type GpuInfo = {
  visible?: boolean;
  driver?: string;
  name?: string;
  vram_total_mb?: number | null;
  vram_used_mb?: number | null;
  util?: number | null;
  temp_c?: number | null;
  driver_ok?: boolean | null;
  error?: string;
  ffmpeg?: { path?: string; version?: string; nvenc_h264?: boolean; nvenc_hevc?: boolean; cuda_decode?: boolean; error?: string };
};

export type AutoInfo = {
  auto_update: boolean;
  update_wanted: boolean;
  update_note: string;
  update_tries: number;
  update_last_at: string | null;
  latest_version: string | null;
  node_version: string | null;
  withholding: boolean;
};

export type NodeBlock = {
  id: number;
  name: string;
  online: boolean;
  enabled: boolean;
  agent: string | null;
  gpu: string;
  gpu_info: GpuInfo;
  last_seen: string | null;
  run: Run | null;
  running: boolean;
  auto: AutoInfo;
  bootstrap: Bootstrap;
  autostart: { supported?: boolean; registered?: boolean; state?: string; path?: string; disabled?: string };
  autostart_wanted: boolean;
  outbox: { pending?: number };
  net: { offline_s?: number; last_error?: string };
  lanes: { main?: number; light?: number };
  can_bootstrap: boolean;
};

export type CatalogItem = { key: string; label: string; group: string; kind: string; deep: boolean; optional: boolean; describe: string };

export type KindProgress = { queued: number; running: number; done: number; failed: number; cancelled: number; label?: string };

export type Progress = {
  kinds: Record<string, KindProgress>;
  totals: { queued: number; running: number; done: number; failed: number; cancelled: number };
  percent: number;
  hours: number;
};

export type AutoSettings = {
  auto_update: boolean;
  auto_selftest: boolean;
  nightly_selftest: boolean;
  nightly_time: string;
  requeue_after_pass: boolean;
  short_burst: number;
};

export type Overview = { nodes: NodeBlock[]; catalog: CatalogItem[]; settings: AutoSettings; progress: Progress };

export const TRIGGER_FA: Record<string, string> = {
  version: "پس از نسخهٔ تازهٔ برنامه",
  nightly: "آزمونِ شبانه",
  manual: "دکمهٔ «آزمونِ کامل»",
  deep: "آزمونِ عمیق",
};

export const GROUP_FA: Record<string, string> = {
  gpu: "کارت گرافیک",
  system: "سامانه",
  text: "متن",
  image: "تصویر",
  audio: "صدا",
  video: "ویدیو",
};

export const DEVICE_FA: Record<string, string> = {
  cuda: "کارت گرافیک (CUDA)",
  directml: "کارت گرافیک (DirectML)",
  nvenc: "کارت گرافیک (NVENC)",
  cpu: "پردازنده (CPU)",
  mixed: "کارت + پردازنده",
  unknown: "نامشخص",
  none: "",
};

export function deviceTone(device: string): Tone {
  if (["cuda", "directml", "nvenc"].includes(device)) return "ok";
  if (device === "cpu" || device === "mixed") return "warn";
  return "neutral";
}

export function stateTone(state: TestState): Tone {
  switch (state) {
    case "PASSED":
      return "ok";
    case "FAILED":
      return "bad";
    case "RUNNING":
    case "QUEUED":
      return "info";
    case "WAITING":
      return "warn";
    default:
      return "neutral";
  }
}

export function stateText(state: TestState): string {
  return (
    {
      PENDING: "منتظرِ نوبت",
      WAITING: "منتظرِ نصب",
      QUEUED: "در صف",
      RUNNING: "در حال اجرا",
      PASSED: "قبول",
      FAILED: "رد",
      SKIPPED: "اجرا نشد",
    } as Record<TestState, string>
  )[state];
}

export function featureTone(state: string): Tone {
  return state === "ready" ? "ok" : state === "failed" ? "bad" : state === "installing" ? "info" : state === "waiting" ? "warn" : "neutral";
}

export function featureText(state: string): string {
  return (
    { ready: "آماده", installing: "در حال نصب", waiting: "منتظر", failed: "ناموفق", skipped: "لازم نیست" } as Record<string, string>
  )[state] ?? state;
}

/** ۱۲٫۵ ثانیه / ۲ دقیقه */
export function secondsText(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 90) return `${Math.round(s * 10) / 10} ثانیه`;
  return `${Math.round(s / 60)} دقیقه`;
}

export function mbText(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return "";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} گیگابایت` : `${Math.round(mb)} مگابایت`;
}

export function whenText(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function offlineText(seconds?: number): string {
  if (!seconds) return "";
  if (seconds < 120) return `${seconds} ثانیه`;
  return `${Math.round(seconds / 60)} دقیقه`;
}

/** درصدِ «تمام‌شده» در ردیفِ یک نوعِ کار؛ ناموفق و لغو از مخرج کنار می‌روند (پیشرفتِ کار، نه نمرهٔ کیفیت). */
export function kindPercent(r: KindProgress): number {
  const all = r.queued + r.running + r.done;
  return all ? Math.round((100 * r.done) / all) : 100;
}
