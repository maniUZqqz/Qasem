import { useEffect, useState } from "react";

import { api } from "../api/client";
import Icon from "./Icon";
import { Badge, Card, SectionTitle, Skeleton } from "./ui";

type Step = {
  key: string;
  title: string;
  why: string;
  done: boolean;
  action: string;
  blocked_by: string[];
};

type Summary = {
  steps: Step[];
  done_count: number;
  total: number;
  complete: boolean;
  next: Step | null;
};

/**
 * What this store still needs, from its own rows.
 *
 * Disappears once everything is done rather than lingering as a permanent
 * "0 of 8" badge — a checklist that never goes away stops being read.
 */
export default function OnboardingCard({ storeId }: { storeId: string | number }) {
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get(`/stores/${storeId}/onboarding/`)
      .then(({ data }) => alive && setSummary(data))
      .catch(() => alive && setSummary(null));
    return () => {
      alive = false;
    };
  }, [storeId]);

  if (summary === null) return <Skeleton className="h-40" />;
  if (summary.complete) return null;

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-3">
        <SectionTitle>قدم‌های بعدی</SectionTitle>
        <Badge tone="info">
          {summary.done_count} از {summary.total}
        </Badge>
      </div>

      {summary.next && (
        <div
          className="mb-4 rounded-xl p-3"
          style={{
            background: "var(--brand-soft, var(--surface-2))",
            border: "1px solid color-mix(in srgb, var(--brand) 30%, transparent)",
          }}
        >
          <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
            {summary.next.title}
          </div>
          <div className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {summary.next.why}
          </div>
        </div>
      )}

      <ol className="flex flex-col gap-2">
        {summary.steps.map((step) => {
          const blocked = !step.done && step.blocked_by.length > 0;
          return (
            <li key={step.key} className="flex items-start gap-3">
              {/* دایره‌ی خالی / تیک / قفل — با آیکون و رنگِ توکن، نه ایموجی:
                  ایموجی روی هر سیستم‌عامل شکل و رنگ خودش را دارد و روی
                  زمینه‌ی تیره مثل لکه‌ی روشن می‌نشیند. */}
              <span
                className="mt-0.5 shrink-0 leading-none"
                style={{
                  color: step.done
                    ? "var(--ok)"
                    : blocked
                      ? "var(--text-3)"
                      : "var(--brand-strong)",
                }}
                aria-hidden
              >
                <Icon name={step.done ? "ok" : blocked ? "shield" : "clock"} size={16} />
              </span>
              <div className="min-w-0">
                <div
                  className="text-sm"
                  style={{
                    color: step.done ? "var(--text-3)" : "var(--text)",
                    textDecoration: step.done ? "line-through" : undefined,
                  }}
                >
                  {step.title}
                </div>
                {blocked && (
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    اول قدم قبلی را تمام کن
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
