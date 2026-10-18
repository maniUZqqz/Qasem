import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import JobProgress from "../../components/JobProgress";
import {
  Button,
  Card,
  Chip,
  ErrorBox,
  Field,
  SectionTitle,
  TextArea,
} from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { CompetitorInfo, Job, MarketResearch } from "../../types";

const CONFIDENCE_LABEL: Record<MarketResearch["confidence"], string> = {
  LOW: "اطمینان پایین (ورودی واقعی کم بود)",
  MEDIUM: "اطمینان متوسط",
  HIGH: "اطمینان بالا",
};

function ListSection({ title, items }: { title: string; items?: string[] }) {
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

function CompetitorCard({ competitor }: { competitor: CompetitorInfo }) {
  const facts: [string, string][] = [
    ["برند", competitor.brand],
    ["محصول رقیب", competitor.product],
    ["قیمت", competitor.price],
    ["کجا می‌فروشد", competitor.where_sells],
    ["چطور می‌فروشد", competitor.how_sells],
  ];
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h5 className="text-sm font-bold text-slate-800">
          🏪 {competitor.name || competitor.brand || "رقیب"}
        </h5>
        {competitor.source && (
          <span className="text-[10px] text-slate-400">منبع: {competitor.source}</span>
        )}
      </div>
      <dl className="space-y-1 text-xs text-slate-600">
        {facts
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} className="flex gap-1">
              <dt className="shrink-0 font-semibold text-slate-500">{label}:</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {competitor.strengths.length > 0 && (
          <div className="rounded bg-green-50 p-2">
            <span className="text-[10px] font-bold text-green-700">نقاط قوت رقیب</span>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-[11px] text-green-800">
              {competitor.strengths.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
        )}
        {competitor.weaknesses.length > 0 && (
          <div className="rounded bg-red-50 p-2">
            <span className="text-[10px] font-bold text-red-700">نقاط ضعف رقیب</span>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-[11px] text-red-800">
              {competitor.weaknesses.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MarketPanel({ productId }: { productId: number }) {
  const [research, setResearch] = useState<MarketResearch | null>(null);
  const [notes, setNotes] = useState("");

  const fetchResearch = useCallback(async () => {
    try {
      const { data } = await api.get<MarketResearch | null>(
        `/products/${productId}/market-analysis/`,
      );
      setResearch(data ?? null);
    } catch {
      setResearch(null);
    }
  }, [productId]);

  useEffect(() => {
    void fetchResearch();
  }, [fetchResearch]);

  const { job, error, running, startedAt, begin, track, resume, cancel, fail } =
    useJobRunner(fetchResearch);

  // re-attach to an in-flight analysis after refresh/navigation (beter.md #2)
  useEffect(() => {
    void resume({ type: "market_analysis", productId });
  }, [resume, productId]);

  const analyze = async () => {
    begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/products/${productId}/market-analysis/`,
        { research_inputs: notes },
      );
      track(data.job_id, data.job);
    } catch (err) {
      fail(errorMessage(err));
    }
  };

  const conclusions = research?.conclusions;

  return (
    <Card>
      <SectionTitle>📊 تحلیل بازار و رقبا</SectionTitle>
      <ErrorBox message={error} />

      <div className="mb-4 space-y-3">
        <p className="rounded-lg bg-violet-50 px-4 py-2 text-xs leading-5 text-violet-800">
          🔎 قیمت و اطلاعات رقبا <b>خودکار</b> از دیجی‌کالا و ترب جستجو می‌شود — لازم نیست
          چیزی وارد کنید. AI اجازه ندارد رقیب یا قیمتی از خودش بسازد.
        </p>
        <Field label="یادداشت‌های خودت (اختیاری)">
          <TextArea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="اگر اطلاعات خاصی از رقبا داری، این‌جا اضافه کن…"
          />
        </Field>
        <Button onClick={analyze} disabled={running}>
          {running ? "در حال تحلیل بازار…" : research ? "تحلیل مجدد بازار" : "تحلیل بازار و رقبا"}
        </Button>
      </div>

      {running && (
        <JobProgress
          job={job}
          startedAt={startedAt}
          onCancel={() => void cancel()}
          fallbackLabel="در حال شروع تحلیل بازار…"
        />
      )}

      {research && conclusions && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-bold text-slate-700">سطح اطمینان:</span>
            <Chip>{CONFIDENCE_LABEL[research.confidence]}</Chip>
          </div>
          {conclusions.strategy_summary && (
            <p className="rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
              {conclusions.strategy_summary}
            </p>
          )}
          {(research.web_results?.items?.length ?? 0) > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-bold text-slate-700">
                🔎 نتایج واقعی جستجوی وب ({research.web_results.items!.length} مورد)
              </h4>
              <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-slate-100 p-2">
                {research.web_results.items!.slice(0, 16).map((item, i) => (
                  <a
                    key={i}
                    href={item.url || undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded px-2 py-1 text-xs hover:bg-slate-50"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-slate-700">{item.title}</span>
                      <span className="shrink-0 text-violet-700">
                        {item.price_toman != null
                          ? `${item.price_toman.toLocaleString("fa-IR")} تومان`
                          : "🌐"}
                        <span className="mr-1 text-slate-400">({item.source})</span>
                      </span>
                    </span>
                    {item.snippet && (
                      <span className="mt-0.5 line-clamp-1 block text-[10px] text-slate-400">
                        {item.snippet}
                      </span>
                    )}
                  </a>
                ))}
              </div>
            </div>
          )}
          <ListSection title="مشاهدات (از داده‌های واقعی)" items={research.observations} />

          {(conclusions.competitors?.length ?? 0) > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-bold text-slate-700">
                🏁 رقبا و مقایسه ({conclusions.competitors!.length} رقیب شناسایی شد)
              </h4>
              <div className="grid gap-3 lg:grid-cols-2">
                {conclusions.competitors!.map((competitor, i) => (
                  <CompetitorCard key={i} competitor={competitor} />
                ))}
              </div>
            </div>
          )}
          <ListSection
            title="⚖️ مقایسه محصول ما با رقبا"
            items={conclusions.comparison}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <ListSection title="جایگاه رقبا" items={conclusions.competitor_positioning} />
            <ListSection title="پیام‌های رایج بازار" items={conclusions.common_messaging} />
            <ListSection title="الگوهای محتوا" items={conclusions.content_patterns} />
            <ListSection title="مشاهدات قیمتی" items={conclusions.pricing_observations} />
            <ListSection title="نگرانی‌های رایج مشتری" items={conclusions.common_customer_concerns} />
            <ListSection title="خلأهای محتوایی" items={conclusions.content_gaps} />
            <ListSection
              title="فرصت‌های تمایز"
              items={conclusions.differentiation_opportunities}
            />
          </div>
          <p className="text-xs text-slate-400">
            آخرین تحلیل: {new Date(research.created_at).toLocaleString("fa-IR")}
          </p>
        </div>
      )}

      {!research && !running && (
        <p className="text-sm text-slate-400">
          هنوز تحلیل بازاری انجام نشده. (نیازمند اتصال به Ollama در سیستم اصلی)
        </p>
      )}
    </Card>
  );
}
