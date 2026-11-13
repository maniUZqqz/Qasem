import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, ErrorBox, Spinner, fa } from "../../../../components/ui";
import { fetchSilences, saveSilenceAnswers, type SilenceReviewData } from "./api";
import { ACTION_HINT, ACTION_LABEL, clock, countsLine, previewWindow, seedChoices, toAnswers, type SilenceAction, type SilenceRow } from "./logic";

const ORDER: SilenceAction[] = ["keep", "shorten", "cut"];

/**
 * «این مکث را سناریو خواسته؟» — فهرستِ مکث‌هایی که سیستم نمی‌تواند خودش تصمیم بگیرد.
 *
 * مکثِ بی‌دلیل را خودِ سیستم کوتاه می‌کند؛ مکثِ بعد از سؤال، بعد از یک عبارتِ تأکیدی یا وقتی تصویر عوض می‌شود ممکن است عمدی باشد.
 * برای هرکدام: جای مکث، دلیل، کلماتِ پیش و پس از آن، دکمهٔ «بشنو» (همان‌جا با کمی پیش و پس) و سه گزینه. پیشنهادِ سیستم از پیش انتخاب
 * شده است؛ پس «ثبت» بدونِ هیچ تغییری هم درست است. پاسخ‌ها برای همین ویدیو یادآوری می‌شود.
 */
export default function SilenceReview({
  storeId,
  refId,
  onDone,
  onCancel,
  doneLabel = "ثبت پاسخ‌ها و ادامه",
}: {
  storeId: string;
  refId: string;
  onDone?: (data: SilenceReviewData) => void;
  onCancel?: () => void;
  doneLabel?: string;
}) {
  const [data, setData] = useState<SilenceReviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<string, SilenceAction>>({});
  const [saving, setSaving] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number>(0);

  useEffect(() => {
    let alive = true;
    setData(null);
    fetchSilences(storeId, refId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setChoices(seedChoices(d.questions));
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [storeId, refId]);

  const stop = useCallback(() => {
    video.current?.pause();
    setPlaying(null);
  }, []);

  function play(q: SilenceRow) {
    const el = video.current;
    if (!el || !data) return;
    if (playing === q.id) return stop();
    const w = previewWindow(q, data.duration);
    stopAt.current = w.to;
    el.currentTime = w.from;
    el.muted = false;
    void el.play().then(() => setPlaying(q.id)).catch(() => setPlaying(null));
  }

  function onTime() {
    const el = video.current;
    if (el && playing && el.currentTime >= stopAt.current) stop();
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveSilenceAnswers(storeId, refId, toAnswers(data.questions, choices));
      onDone?.(saved);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const summary = useMemo(() => (data ? countsLine(data.counts, data.removed_seconds, fa) : ""), [data]);

  if (error && !data) return <ErrorBox message={error} />;
  if (!data) {
    return (
      <div className="flex items-center gap-2 py-3 text-sm" style={{ color: "var(--text-2)" }}>
        <Spinner size={16} /> در حال بررسیِ مکث‌های ویدیو…
      </div>
    );
  }

  return (
    <div className="rounded-xl p-3" style={{ border: "1px solid var(--line)", background: "var(--surface-2, transparent)" }} data-testid="silence-review">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
            {data.questions.length ? `${fa(data.questions.length)} مکث را خودم نمی‌توانم تشخیص بدهم` : "همهٔ مکث‌ها تصمیم‌گرفته شد"}
          </div>
          <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>{summary}</div>
        </div>
        {data.words !== "ready" && (
          <Badge tone="neutral">{data.words === "waiting" ? "کلمه‌ها: منتظرِ روشن شدنِ سرورِ پردازش" : data.words === "off" ? "کلمه‌ها: تشخیصِ گفتار خاموش" : "کلمه‌ها: هنوز شناخته نشده"}</Badge>
        )}
      </div>

      {data.note && (
        <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>{data.note}</p>
      )}

      {/* یک پخش‌کننده برای همهٔ ردیف‌ها؛ فقط وقتی کاربر «بشنو» را می‌زند صدا می‌دهد */}
      {data.url && <video ref={video} src={data.url} preload="metadata" playsInline onTimeUpdate={onTime} onEnded={stop} className="hidden" />}

      <ul className="flex flex-col gap-2">
        {data.questions.map((q) => (
          <li key={q.id} className="rounded-lg p-3" style={{ border: "1px solid var(--line)", background: "var(--surface, transparent)" }} data-testid="silence-question">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="warn">{fa(clock(q.start))} تا {fa(clock(q.end))}</Badge>
              <span className="text-xs" style={{ color: "var(--text-3)" }}>{fa(Math.round(q.len * 10) / 10)} ثانیه</span>
              {data.url && (
                <Button size="sm" variant="secondary" type="button" onClick={() => play(q)} data-testid="silence-play">
                  {playing === q.id ? "⏸ توقف" : "▶ بشنو"}
                </Button>
              )}
            </div>
            <p className="mt-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>{q.reason}</p>
            {(q.before || q.after) && (
              <p className="mt-1 text-sm leading-7" style={{ color: "var(--text)" }}>
                <span style={{ color: "var(--text-3)" }}>…</span> {q.before} <b style={{ color: "var(--warn)" }}>⏸ مکث ⏸</b> {q.after} <span style={{ color: "var(--text-3)" }}>…</span>
              </p>
            )}
            <div role="radiogroup" aria-label="تصمیم دربارهٔ این مکث" className="mt-2 flex flex-wrap gap-2">
              {ORDER.map((a) => {
                const on = choices[q.id] === a;
                return (
                  <button
                    key={a}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    title={ACTION_HINT[a]}
                    onClick={() => setChoices((c) => ({ ...c, [q.id]: a }))}
                    data-testid={`silence-${a}`}
                    className="rounded-lg px-3 py-1 text-sm"
                    style={{
                      border: `1px solid ${on ? "var(--brand)" : "var(--line)"}`,
                      background: on ? "var(--brand-soft)" : "transparent",
                      color: "var(--text)",
                      fontWeight: on ? 700 : 400,
                    }}
                  >
                    {ACTION_LABEL[a]}
                    {q.suggest === a ? " ★" : ""}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ul>

      {data.questions.length === 0 && (
        <Alert tone="ok">پرسشی نمانده است؛ مکث‌ها طبق تصمیم‌های بالا (و پاسخ‌های قبلیِ شما) برش می‌خورد.</Alert>
      )}

      {error && <div className="mt-2"><ErrorBox message={error} /></div>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => void save()} disabled={saving} data-testid="silence-save">
          {saving ? <Spinner size={16} /> : data.questions.length ? doneLabel : "ادامه"}
        </Button>
        {data.questions.length > 0 && (
          <Button type="button" variant="ghost" onClick={() => setChoices(seedChoices(data.questions))}>
            همه طبق پیشنهادِ ★
          </Button>
        )}
        {onCancel && <Button type="button" variant="ghost" onClick={onCancel}>بی‌خیال</Button>}
        <span className="text-xs" style={{ color: "var(--text-3)" }}>★ پیشنهادِ سیستم · پاسخ‌ها برای همین ویدیو یادآوری می‌شود</span>
      </div>
    </div>
  );
}
