import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import JobProgress from "../../components/JobProgress";
import { Button, Card, Chip, ErrorBox, SectionTitle } from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { Intelligence, Job } from "../../types";

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <h4 className="mb-1 text-sm font-bold text-slate-700">{title}</h4>
      <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export default function IntelligencePanel({ productId }: { productId: number }) {
  const [intelligence, setIntelligence] = useState<Intelligence | null>(null);

  const fetchIntelligence = useCallback(async () => {
    try {
      // 200 + null = "never analyzed", a normal empty state (beter.md #10)
      const { data } = await api.get<Intelligence | null>(
        `/products/${productId}/intelligence/`,
      );
      setIntelligence(data ?? null);
    } catch {
      setIntelligence(null);
    }
  }, [productId]);

  useEffect(() => {
    void fetchIntelligence();
  }, [fetchIntelligence]);

  const { job, error, running, startedAt, begin, track, resume, cancel, fail } =
    useJobRunner(fetchIntelligence);

  // re-attach to an in-flight analysis after refresh/navigation (beter.md #2)
  useEffect(() => {
    void resume({ type: "product_analysis", productId });
  }, [resume, productId]);

  const analyze = async () => {
    // in synchronous mode this POST does not return until the whole analysis
    // is finished, so the progress box has to be up before we send it
    begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/products/${productId}/analyze/`,
      );
      track(data.job_id, data.job);
    } catch (err) {
      fail(errorMessage(err));
    }
  };

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>🧠 هوش محصول (تحلیل AI)</SectionTitle>
        <Button onClick={analyze} disabled={running}>
          {running ? "در حال تحلیل…" : intelligence ? "تحلیل مجدد" : "تحلیل با هوش مصنوعی"}
        </Button>
      </div>
      <ErrorBox message={error} />

      {running && (
        <JobProgress
          job={job}
          startedAt={startedAt}
          onCancel={() => void cancel()}
          fallbackLabel="در حال شروع تحلیل محصول…"
        />
      )}

      {!intelligence && !running && (
        <p className="text-sm text-slate-400">
          هنوز تحلیلی انجام نشده. دکمه «تحلیل با هوش مصنوعی» را بزنید (نیازمند اتصال به Ollama در
          سیستم اصلی).
        </p>
      )}

      {intelligence && (
        <div className="space-y-4">
          {intelligence.summary && (
            <p className="rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
              {intelligence.summary}
            </p>
          )}
          {intelligence.positioning && (
            <div>
              <h4 className="mb-1 text-sm font-bold text-slate-700">جایگاه در بازار</h4>
              <p className="text-sm text-slate-600">{intelligence.positioning}</p>
            </div>
          )}
          {intelligence.recommended_tone && (
            <div className="flex items-center gap-2 text-sm">
              <span className="font-bold text-slate-700">لحن پیشنهادی:</span>
              <Chip>{intelligence.recommended_tone}</Chip>
            </div>
          )}
          {intelligence.target_audience?.length > 0 && (
            <div>
              <h4 className="mb-1 text-sm font-bold text-slate-700">مخاطب هدف</h4>
              <div className="flex flex-wrap gap-2">
                {intelligence.target_audience.map((item, i) => (
                  <Chip key={i}>{item}</Chip>
                ))}
              </div>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <ListSection title="نقاط قوت فروش" items={intelligence.selling_points} />
            <ListSection title="نقاط ضعف" items={intelligence.weaknesses} />
            <ListSection title="اعتراض‌های احتمالی مشتری" items={intelligence.objections} />
            <ListSection title="زاویه‌های بازاریابی" items={intelligence.marketing_angles} />
            <ListSection title="ایده‌های محتوا" items={intelligence.content_ideas} />
            <ListSection title="موارد استفاده" items={intelligence.use_cases} />
          </div>
          <p className="text-xs text-slate-400">
            آخرین به‌روزرسانی: {new Date(intelligence.updated_at).toLocaleString("fa-IR")}
          </p>
        </div>
      )}
    </Card>
  );
}
