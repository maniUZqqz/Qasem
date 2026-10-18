import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import JobProgress from "../../components/JobProgress";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, fa } from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { Job } from "../../types";

/**
 * یک ویدیو، چند خروجی. بند ۱۰
 *
 * `GET`/`POST /video-scripts/{id}/cuts/` هر دو ساخته شده بودند و هیچ
 * دکمه‌ای نداشتند. صفحه‌ی «ادیتور ویدیو» برش‌گیری را فقط برای ویدیوی
 * **آپلودی** می‌داد — یعنی همان قابلیت روی ویدیویی که خودِ محصول ساخته
 * بود، که حالت اصلی است، از پنل در دسترس نبود.
 *
 * دو چیز که از بک‌اند می‌آید و اینجا حفظ می‌شود:
 *
 * **قالبی که از ویدیوی فعلی درنمی‌آید، پیشنهاد نمی‌شود.** یک کلیپ ۱۰
 * ثانیه‌ای ریلزِ ۶۰ ثانیه‌ای نمی‌شود؛ ساختنش فقط همان فایل را با نام
 * دیگری تحویل می‌داد، که بیشتر شبیه قابلیت خراب است تا خروجی.
 *
 * **قالبی که بریده می‌شود، همین را می‌گوید** (`trims`) — پیش از ساخت،
 * نه بعد از اینکه کسی دید آخر ویدیویش قیچی شده.
 */

type Format = {
  key: string;
  title: string;
  label: string;
  where: string;
  max_seconds: number | null;
  trims: boolean;
};

type Cut = { format: string; url: string; trimmed: boolean; has_audio: boolean };

type State = { available: Format[]; cuts: Cut[]; ready: boolean };

export default function CutsPanel({ scriptId }: { scriptId: number }) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<State>(`/video-scripts/${scriptId}/cuts/`);
      setState(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [scriptId]);

  const runner = useJobRunner(load);

  useEffect(() => {
    void load();
  }, [load]);

  const build = async () => {
    setError(null);
    runner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/video-scripts/${scriptId}/cuts/`,
        picked.length ? { formats: picked } : {},
      );
      runner.track(data.job_id, data.job);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!state) return null;

  const made = new Set(state.cuts.map((c) => c.format));
  const title = (key: string) =>
    state.available.find((f) => f.key === key)?.title ?? key;

  return (
    <Card>
      <SectionTitle>برش برای هر پلتفرم</SectionTitle>

      <ErrorBox message={error || runner.error} />

      {!state.ready ? (
        <Alert tone="info" title="اول ویدیوی نهایی">
          وقتی ویدیو ساخته شد، از همان یکی نسخه‌ی ریلز، استوری، فید و افقی درمی‌آید —
          بدون رندر دوباره‌ی GPU.
        </Alert>
      ) : (
        <>
          <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            هرکدام را می‌خواهید تیک بزنید. هیچ‌کدام را تیک نزنید یعنی همه‌ی قالب‌های
            ممکن.
          </p>

          <div className="flex flex-wrap gap-2">
            {state.available.map((f) => {
              const on = picked.includes(f.key);
              return (
                <label
                  key={f.key}
                  className="flex cursor-pointer items-start gap-2 rounded-xl px-3 py-2"
                  style={{
                    background: on ? "var(--brand-soft)" : "var(--surface-2)",
                    border: `1px solid ${on ? "var(--brand)" : "var(--line)"}`,
                    minWidth: 190,
                  }}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={on}
                    onChange={() =>
                      setPicked((prev) =>
                        prev.includes(f.key)
                          ? prev.filter((k) => k !== f.key)
                          : [...prev, f.key],
                      )
                    }
                  />
                  <span className="min-w-0">
                    <span
                      className="flex flex-wrap items-center gap-1.5 text-sm font-semibold"
                      style={{ color: "var(--text)" }}
                    >
                      {f.title}
                      {made.has(f.key) && <Badge tone="ok">ساخته شد</Badge>}
                    </span>
                    <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                      {f.where}
                      {f.max_seconds ? ` · تا ${fa(f.max_seconds)} ثانیه` : ""}
                    </span>
                    {/* پیش از ساخت گفته می‌شود، نه بعدش */}
                    {f.trims && (
                      <span className="block text-xs" style={{ color: "var(--warn)" }}>
                        ویدیوی شما بلندتر است — این نسخه کوتاه می‌شود.
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>

          <div className="mt-4">
            <Button onClick={build} disabled={runner.running}>
              <Icon name="film" size={15} />
              {runner.running
                ? "در حال برش…"
                : picked.length
                  ? `ساخت ${fa(picked.length)} نسخه`
                  : "ساخت همه‌ی نسخه‌ها"}
            </Button>
          </div>

          <JobProgress job={runner.job} />

          {state.cuts.length > 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {state.cuts.map((cut) => (
                <div key={cut.format}>
                  <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-sm">
                    <span style={{ color: "var(--text)" }}>{title(cut.format)}</span>
                    {cut.trimmed && <Badge tone="warn">کوتاه شده</Badge>}
                    {!cut.has_audio && <Badge tone="neutral">بی‌صدا</Badge>}
                  </div>
                  <video
                    src={cut.url}
                    controls
                    className="w-full rounded-xl"
                    style={{ border: "1px solid var(--line)" }}
                  />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
