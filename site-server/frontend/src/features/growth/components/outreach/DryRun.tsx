import { Alert, Badge, Table, fa } from "../../../../components/ui";
import { faDateTime } from "../../format";
import { GUESS_LABEL, SOURCE_LABEL } from "../../outreach/labels";
import type { Attempt, ItemPlan } from "../../outreach/types";
import { Ltr } from "./shared";

/**
 * The dry run: exactly what will be POSTed to the form (names, values and where each value comes from).
 * Hidden page-given values (CSRF tokens ...) are not shown; they are sent as the page gives them.
 */
export function DryRunTable({ plan }: { plan: ItemPlan | null | undefined }) {
  const fields = plan?.fields ?? [];
  if (!plan || fields.length === 0) {
    return (
      <p className="rounded-xl p-3 text-sm" style={{ background: "var(--surface-2)", color: "var(--text-3)" }} data-testid="dryrun-empty">
        فرمی تحلیل نشده است، پس هنوز چیزی برای نمایش نیست. در صفحهٔ کمپین «آماده‌سازیِ فرم‌ها» را بزنید.
      </p>
    );
  }
  return (
    <div data-testid="dryrun-table">
      <Table>
        <thead>
          <tr>
            <th className="text-start">فیلد</th>
            <th className="text-start">مقدارِ ارسالی</th>
            <th className="text-start">از کجا</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => {
            const hidden = f.hidden || f.source === "hidden";
            return (
              <tr key={`${f.name}-${f.source}`}>
                <td>
                  <Ltr className="font-mono text-xs">{f.name}</Ltr>
                  {f.label && f.label !== f.name && (
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {f.label}
                    </div>
                  )}
                </td>
                <td className="max-w-[22rem]">
                  {hidden ? (
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      مقدارِ مخفیِ صفحه
                    </span>
                  ) : f.type === "textarea" || f.source === "message" ? (
                    <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-6" dir="auto" style={{ fontFamily: "inherit", margin: 0, color: "var(--text)" }}>
                      {f.value}
                    </pre>
                  ) : (
                    <span dir="auto" className="break-words">
                      {f.value || "—"}
                    </span>
                  )}
                </td>
                <td>
                  <Badge tone={hidden ? "neutral" : f.source === "message" ? "brand" : "info"}>{SOURCE_LABEL[f.source] ?? f.source}</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </div>
  );
}

/** Facts about the target form: where it posts, how, and what the analysis found. */
export function PlanFacts({ plan }: { plan: ItemPlan | null | undefined }) {
  if (!plan) return null;
  const detected = Object.entries(plan.detected ?? {}).filter(([, v]) => v !== false && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0));
  return (
    <div className="space-y-3" data-testid="plan-facts">
      <dl className="grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_minmax(0,1fr)]">
        {plan.page_url && (
          <>
            <dt style={{ color: "var(--text-3)" }}>صفحهٔ فرم</dt>
            <dd>
              <a href={plan.page_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-strong)" }}>
                <Ltr>{plan.page_url}</Ltr>
              </a>
            </dd>
          </>
        )}
        {plan.action_url && (
          <>
            <dt style={{ color: "var(--text-3)" }}>ارسال به</dt>
            <dd>
              <Ltr>{plan.action_url}</Ltr>
            </dd>
          </>
        )}
        {(plan.method || plan.enctype) && (
          <>
            <dt style={{ color: "var(--text-3)" }}>روش</dt>
            <dd>
              <Ltr>
                {plan.method ?? "POST"} {plan.enctype ?? ""}
              </Ltr>
            </dd>
          </>
        )}
        {plan.verdict && (
          <>
            <dt style={{ color: "var(--text-3)" }}>نتیجهٔ بررسی</dt>
            <dd>
              <Badge tone={plan.verdict === "eligible" ? "ok" : "warn"}>{plan.verdict === "eligible" ? "قابلِ ارسالِ خودکار" : "خودکار نمی‌شود"}</Badge>
            </dd>
          </>
        )}
      </dl>
      {(plan.reasons ?? []).length > 0 && (
        <Alert tone="warn" title="چرا خودکار نمی‌شود">
          <ul className="list-disc ps-5" data-testid="plan-reasons">
            {(plan.reasons ?? []).map((r) => (
              <li key={r.code}>{r.text}</li>
            ))}
          </ul>
        </Alert>
      )}
      {detected.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs" style={{ color: "var(--text-3)" }}>
          یافته‌ها:
          {detected.map(([k, v]) => (
            <Badge key={k}>
              <span dir="ltr">{typeof v === "boolean" ? k : `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`}</span>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

/** What happened when the item was sent: HTTP status, the page's answer, our reading of it, and the exact payload. */
export function AttemptBox({ attempt }: { attempt: Attempt }) {
  const guess = GUESS_LABEL[attempt.success_guess] ?? { label: attempt.success_guess, tone: "neutral" as const };
  const rows = Array.isArray(attempt.payload) ? attempt.payload : Object.entries(attempt.payload ?? {}).map(([name, value]) => ({ name, value: String(value) }));
  return (
    <div className="space-y-3 rounded-xl p-4" style={{ border: "1px solid var(--line-strong)", background: "var(--surface-2)" }} data-testid="attempt-box">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <b style={{ color: "var(--text)" }}>نتیجهٔ ارسال</b>
        <Badge tone={attempt.status_code >= 200 && attempt.status_code < 400 ? "ok" : "bad"}>
          HTTP <span dir="ltr">{attempt.status_code || "—"}</span>
        </Badge>
        <Badge tone={guess.tone}>{guess.label}</Badge>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          {faDateTime(attempt.attempted_at)} · {fa(Math.round(attempt.elapsed_ms))} میلی‌ثانیه
        </span>
      </div>
      {attempt.error && (
        <p className="text-sm" style={{ color: "var(--bad)" }}>
          {attempt.error}
        </p>
      )}
      {attempt.response_snippet && (
        <div>
          <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
            بخشی از پاسخِ سایت
          </div>
          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-6" dir="auto" style={{ fontFamily: "inherit", margin: 0, color: "var(--text-2)" }}>
            {attempt.response_snippet}
          </pre>
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-xs font-bold" style={{ color: "var(--text-3)" }}>
          دقیقاً چه چیزی فرستاده شد
        </summary>
        <div className="mt-2">
          <Table>
            <thead>
              <tr>
                <th className="text-start">فیلد</th>
                <th className="text-start">مقدار</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.name}-${i}`}>
                  <td>
                    <Ltr className="font-mono text-xs">{r.name}</Ltr>
                  </td>
                  <td className="break-words text-xs" dir="auto">
                    {r.value}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            به: <Ltr>{attempt.url}</Ltr>
          </p>
        </div>
      </details>
    </div>
  );
}
