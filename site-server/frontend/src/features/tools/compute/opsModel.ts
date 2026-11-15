/**
 * «بکاپِ شبانه» و «آزمون‌های شبانهٔ سایت» — منطقِ خالصِ نمایش (بدونِ React؛ آزمون: frontend/tests/ops-status.test.ts).
 *
 * داده از `GET /api/v1/compute/ops/` می‌آید (backend/apps/compute/ops_status.py): فایل‌هایی که اسکریپت‌های سرور
 * (deploy/nm/ops/nm-backup و nm-nightly-tests) می‌نویسند.
 */
import { jalaliDateTime, relativeTime, toFa } from "./report/model";

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

export type BackupDb = { file: string; size_mb: number; integrity: string; tables?: number; ok: boolean };

export type BackupStatus = {
  present: boolean;
  state: "ok" | "stale" | "failed" | "missing";
  ok?: boolean;
  at?: string;
  last_good_at?: string;
  age_hours?: number | null;
  size_mb?: number;
  folder?: string;
  databases?: BackupDb[];
  restore_test_ok?: boolean;
  daily_kept?: number;
  weekly_kept?: number;
  media_kept?: number;
  media?: string;
  disk_free_mb?: number;
  errors?: string[];
  offsite?: string;
  duration_s?: number;
};

export type RedTest = { id: string; kind: string; message: string };
export type TestApp = {
  app: string;
  ok: boolean;
  tests: number;
  failures: number;
  errors: number;
  skipped: number;
  seconds: number;
  crashed?: boolean;
  timeout?: boolean;
  lock_timeout?: boolean;
  tail?: string[];
  red: RedTest[];
};
export type SiteTests = {
  present: boolean;
  state: "green" | "red" | "missing" | "stale";
  running: { app: string; since: string } | null;
  started_at?: string;
  finished_at?: string;
  version?: string;
  age_hours?: number | null;
  totals?: { apps: number; red_apps: number; tests: number; failures: number; errors: number; skipped: number; lock_skipped?: number };
  apps?: TestApp[];
};

export type OpsStatus = { backup: BackupStatus; tests: SiteTests };

export const OPS_TEXT = {
  backupTitle: "آخرین بکاپ",
  backupMissing: "هنوز بکاپی گرفته نشده؛ بکاپِ شبانه هر شب حدودِ ساعت ۰۷:۲۰ به وقتِ تهران اجرا می‌شود.",
  backupFailed: "آخرین بکاپ با خطا تمام شد؛ فایلِ /var/log/nm-backup.log را ببینید.",
  backupStale: "بکاپِ شبانه دیرکرده است؛ آخرین بکاپِ سالم قدیمی است.",
  testsTitle: "آزمون‌های شبانهٔ سایت",
  testsSubtitle: "هر اپِ سایت جدا و پشتِ‌هم اجرا می‌شود (هر شب ساعت ۰۳:۰۰ به وقتِ تهران)؛ فهرستِ آزمون‌های قرمز این‌جاست.",
  testsMissing: "هنوز اجرا نشده؛ اولین اجرا امشب ساعت ۰۳:۰۰ به وقتِ تهران است.",
  testsGreen: "همهٔ آزمون‌ها سبزند.",
  testsRed: "آزمون‌های قرمز",
  testsStale: "آخرین اجرا بیش از دو روز پیش بوده؛ اجرای شبانه گیر کرده یا سرور خاموش بوده است.",
  testsLockSkipped: "اپ در آن شب رد شد، چون سرور یک ساعت پر از کارهای سنگینِ دیگر بود (شبِ بعد دوباره امتحان می‌شود)",
  testsRunning: "در حالِ اجراست",
  offsite: "نسخهٔ بیرونی (کپی روی کامپیوترِ دفتر) هنوز تنظیم نشده؛ این بکاپ‌ها روی همان دیسکِ سرورند.",
} as const;

export const BACKUP_STALE_HOURS = 36;
export const TESTS_STALE_HOURS = 48;

function mb(v: number | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  if (v >= 1024) return `${toFa((v / 1024).toFixed(1).replace(/\.0$/, ""))} گیگابایت`;
  return `${toFa(Math.round(v * 10) / 10)} مگابایت`;
}

/** وضعیتِ بکاپ ⇒ لحن، تیتر و سطرهای توضیح. */
export function backupView(b: BackupStatus | null | undefined, nowMs: number = Date.now()): { tone: Tone; headline: string; lines: string[]; badge: string } {
  if (!b || !b.present || b.state === "missing") {
    return { tone: "warn", headline: OPS_TEXT.backupMissing, lines: [], badge: "بکاپ ندارد" };
  }
  const when = b.at ? `${jalaliDateTime(b.at)} (${relativeTime(b.at, nowMs)})` : "—";
  const lines: string[] = [];
  const dbs = b.databases ?? [];
  if (dbs.length) {
    const good = dbs.filter((d) => d.ok).length;
    lines.push(`${toFa(good)} از ${toFa(dbs.length)} دیتابیس سالم بازیابی شد (آزمونِ بازیابی روی رونوشت)`);
  }
  if (typeof b.size_mb === "number") lines.push(`حجمِ این نسخه: ${mb(b.size_mb)}`);
  const kept: string[] = [];
  if (b.daily_kept !== undefined) kept.push(`${toFa(b.daily_kept)} روزانه`);
  if (b.weekly_kept !== undefined) kept.push(`${toFa(b.weekly_kept)} هفتگی`);
  if (b.media_kept) kept.push(`${toFa(b.media_kept)} عکسِ لحظه‌ایِ مدیا`);
  if (kept.length) lines.push(`نگه‌داری: ${kept.join("، ")}`);
  if (b.state === "failed" || (b.errors && b.errors.length)) {
    for (const e of (b.errors ?? []).slice(0, 4)) lines.push(`خطا: ${e}`);
  }
  if (b.state === "failed") {
    const good = b.last_good_at ? `؛ آخرین بکاپِ سالم: ${jalaliDateTime(b.last_good_at)}` : "";
    return { tone: "bad", headline: `${OPS_TEXT.backupFailed}${good}`, lines, badge: "ناموفق" };
  }
  if (b.state === "stale") {
    return { tone: "warn", headline: `${OPS_TEXT.backupStale} ${when}`, lines, badge: "دیرکرد" };
  }
  return { tone: "ok", headline: when, lines, badge: "سالم" };
}

export function testsView(t: SiteTests | null | undefined, nowMs: number = Date.now()): {
  tone: Tone;
  headline: string;
  badge: string;
  tiles: { key: string; label: string; value: string; tone: Tone }[];
  red: { app: string; tests: number; items: RedTest[]; note: string }[];
} {
  const empty = { tiles: [], red: [] };
  if (!t || !t.present || t.state === "missing") {
    return { tone: "neutral", headline: OPS_TEXT.testsMissing, badge: t?.running ? OPS_TEXT.testsRunning : "اجرا نشده", ...empty };
  }
  const tot = t.totals ?? { apps: 0, red_apps: 0, tests: 0, failures: 0, errors: 0, skipped: 0 };
  const redCount = tot.failures + tot.errors;
  const when = t.finished_at ? `${jalaliDateTime(t.finished_at)} (${relativeTime(t.finished_at, nowMs)})` : "—";
  const tiles = [
    { key: "tests", label: "آزمون", value: toFa(tot.tests), tone: "neutral" as Tone },
    { key: "apps", label: "اپ", value: toFa(tot.apps), tone: "neutral" as Tone },
    { key: "red", label: "قرمز", value: toFa(redCount), tone: (redCount ? "bad" : "ok") as Tone },
    { key: "redapps", label: "اپِ قرمز", value: toFa(tot.red_apps), tone: (tot.red_apps ? "bad" : "ok") as Tone },
  ];
  if (tot.lock_skipped) tiles.push({ key: "lockskipped", label: "اپِ ردشده (قفل پر بود)", value: toFa(tot.lock_skipped), tone: "warn" as Tone });
  const red = (t.apps ?? [])
    .filter((a) => !a.ok)
    .map((a) => ({
      app: a.app,
      tests: a.tests,
      items: a.red ?? [],
      note: a.timeout
        ? "زمانِ اجرا تمام شد"
        : a.crashed
          ? "اجرا نیمه‌کاره ماند" + (a.tail && a.tail.length ? ` — ${a.tail[a.tail.length - 1]}` : "")
          : `${toFa(a.failures)} شکست، ${toFa(a.errors)} خطا از ${toFa(a.tests)} آزمون`,
    }));
  const stale = t.state === "stale" || (typeof t.age_hours === "number" && t.age_hours > TESTS_STALE_HOURS);
  if (stale) {
    return { tone: "warn", headline: `${OPS_TEXT.testsStale} (${when})`, badge: "قدیمی", tiles, red };
  }
  if (tot.red_apps > 0 || redCount > 0) {
    return { tone: "bad", headline: `${toFa(redCount)} آزمون قرمز در ${toFa(tot.red_apps)} اپ — ${when}`, badge: "قرمز", tiles, red };
  }
  return { tone: "ok", headline: `${OPS_TEXT.testsGreen} ${when}`, badge: "سبز", tiles, red };
}
