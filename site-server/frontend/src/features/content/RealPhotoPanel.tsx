import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import JobProgress from "../../components/JobProgress";
import { Alert, Button, Card, ErrorBox, SectionTitle } from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";

/**
 * «عکس واقعی را آخرِ ویدیو بگذار». بند ۲۶
 *
 * این اندپوینت از قبل ساخته و تست شده بود و هیچ دکمه‌ای نداشت — یعنی
 * چیزی که سند «کاری که باور بیننده را می‌سازد» می‌نامد، از پنل قابل
 * اجرا نبود.
 *
 * دو قاعده‌ای که از خودِ بک‌اند می‌آید و اینجا هم نگه داشته می‌شود:
 *
 * **عکسی که AI ساخته هرگز جای عکس واقعی نمی‌نشیند** — حتی نوع `ENHANCED`
 * که از عکس خود فروشگاه شروع شده. کل ارزش این فریم، باور بیننده است که
 * این یکی ساختگی نیست. فروشگاهی که عکس واقعی ندارد «نه» می‌شنود، نه یک
 * جایگزین.
 *
 * **خودکار نیست.** منتشر کردن عکس صورت خودت یک تصمیم است؛ خط تولیدی که
 * چون فیلد پر بوده آن را می‌چسباند، دارد آن تصمیم را به‌جای کسی می‌گیرد.
 */

type Photo = { kind?: string; label?: string; url?: string; source?: string };

type State = {
  available: boolean;
  reason: string;
  photo: Photo | null;
  video: string | null;
};

export default function RealPhotoPanel({
  storeId,
  scriptId,
}: {
  storeId: string | number;
  scriptId: number;
}) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefer, setPrefer] = useState<"owner" | "product">("owner");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<State>(
        `/stores/${storeId}/video-scripts/${scriptId}/real-photo/`,
      );
      setState(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, scriptId]);

  const runner = useJobRunner(load);

  useEffect(() => {
    void load();
  }, [load]);

  const append = async () => {
    setError(null);
    runner.begin();
    try {
      const { data } = await api.post<{ job_id: number }>(
        `/stores/${storeId}/video-scripts/${scriptId}/real-photo/`,
        { prefer },
      );
      runner.track(data.job_id);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!state) return null;

  return (
    <Card>
      <SectionTitle>عکس واقعی، آخر ویدیو</SectionTitle>

      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        آخرین فریم ویدیو، یک عکس <strong>واقعی</strong> می‌شود — خودتان یا خودِ محصول.
        عکسی که AI ساخته هرگز اینجا استفاده نمی‌شود.
      </p>

      <ErrorBox message={error || runner.error} />

      {!state.available ? (
        <Alert tone="warn" title="عکس واقعی‌ای برای این کار نیست">
          {state.reason || "اول یک عکس واقعی از خودتان یا محصول آپلود کنید."}
        </Alert>
      ) : (
        <div className="space-y-3">
          <div
            className="flex flex-wrap items-center gap-3 rounded-xl p-3"
            style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
          >
            {state.photo?.url && (
              <img
                src={state.photo.url}
                alt=""
                className="h-16 w-16 rounded-lg object-cover"
                style={{ border: "1px solid var(--line-strong)" }}
              />
            )}
            <div className="min-w-0 text-sm">
              <div style={{ color: "var(--text)" }}>
                {state.photo?.label || "عکس واقعی"}
              </div>
              {state.photo?.source && (
                <div className="text-xs" style={{ color: "var(--text-3)" }}>
                  منبع: {state.photo.source}
                </div>
              )}
            </div>
          </div>

          <fieldset className="flex flex-wrap items-center gap-3">
            <legend className="mb-1 text-sm" style={{ color: "var(--text-2)" }}>
              کدام عکس ترجیح داده شود؟
            </legend>
            {(
              [
                ["owner", "عکس خودم"],
                ["product", "عکس واقعی محصول"],
              ] as const
            ).map(([key, label]) => (
              <label
                key={key}
                className="flex cursor-pointer items-center gap-1.5 text-sm"
                style={{ color: "var(--text-2)" }}
              >
                <input
                  type="radio"
                  name={`prefer-${scriptId}`}
                  checked={prefer === key}
                  onChange={() => setPrefer(key)}
                />
                {label}
              </label>
            ))}
          </fieldset>

          <Button onClick={append} disabled={runner.running}>
            <Icon name="image" size={15} />
            {runner.running ? "در حال ساخت…" : "به آخر ویدیو اضافه کن"}
          </Button>

          <JobProgress job={runner.job} />

          {state.video && (
            <div>
              <p className="mb-2 text-sm" style={{ color: "var(--ok)" }}>
                نسخه‌ی با عکس واقعی آماده است:
              </p>
              <video
                src={state.video}
                controls
                className="w-full rounded-xl"
                style={{ border: "1px solid var(--line)" }}
              />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
