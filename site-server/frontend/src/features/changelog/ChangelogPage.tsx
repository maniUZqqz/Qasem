import axios from "axios";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Card, EmptyState, PageHeader, Spinner } from "../../components/ui";
import { parseChangelog, type ChangelogEntry } from "../../components/versionInfo";

/**
 * «چه چیزی تازه است» — فهرستِ نسخه‌ها از `GET /api/v1/version/changelog/`.
 *
 * بیرون از `Layout` است و ورود نمی‌خواهد: نشانِ نسخه روی صفحهٔ ورود هم هست و
 * پیوندش باید برای کسی که هنوز وارد نشده هم باز شود. درخواست با axiosِ ساده است
 * (نه `api`)، چون توکنِ منقضی نباید یک صفحهٔ عمومی را به /login بپراند.
 */

type State =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "ready"; current: string; entries: ChangelogEntry[] };

export default function ChangelogPage() {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    const previous = document.title;
    document.title = "چه چیزی تازه است | NMarketing";
    return () => {
      document.title = previous;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    axios
      .get("/api/v1/version/changelog/", { timeout: 10000, headers: { Accept: "application/json" } })
      .then((r) => {
        if (!alive) return;
        const d = (r.data ?? {}) as { current?: unknown; entries?: unknown };
        setState({
          phase: "ready",
          current: typeof d.current === "string" ? d.current : "",
          entries: parseChangelog(d.entries),
        });
      })
      .catch(() => {
        if (alive) setState({ phase: "error" });
      });
    return () => {
      alive = false;
    };
  }, []);

  const current = state.phase === "ready" ? state.current : "";

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-10" data-testid="changelog-page">
      <PageHeader
        title="چه چیزی تازه است"
        subtitle={current ? `نسخهٔ فعلی: v${current}` : "فهرستِ تغییرهای هر نسخه، از تازه‌ترین"}
        actions={
          <Link to="/" className="u-btn u-btn-secondary u-btn-sm">
            بازگشت به پنل
          </Link>
        }
      />

      {state.phase === "loading" && (
        <div className="flex justify-center py-16" aria-busy="true">
          <Spinner />
        </div>
      )}

      {state.phase === "error" && (
        <Card>
          <EmptyState title="فهرست تغییرها در دسترس نیست">
            ارتباط با سرور برقرار نشد. چند لحظه بعد دوباره صفحه را باز کنید.
          </EmptyState>
        </Card>
      )}

      {state.phase === "ready" && state.entries.length === 0 && (
        <Card>
          <EmptyState title="هنوز چیزی ثبت نشده">برای این نسخه فهرستِ تغییرها نوشته نشده است.</EmptyState>
        </Card>
      )}

      {state.phase === "ready" && state.entries.length > 0 && (
        <ol className="space-y-4" aria-label="نسخه‌ها">
          {state.entries.map((e) => (
            <li key={e.version}>
              <Card>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-extrabold" style={{ color: "var(--text)", direction: "ltr" }}>
                    v{e.version}
                  </h2>
                  {e.version === current && <Badge tone="ok">نسخهٔ فعلی</Badge>}
                  {e.date && (
                    <span className="text-sm" style={{ color: "var(--text-3)" }}>
                      {e.date}
                    </span>
                  )}
                </div>
                {e.summary && (
                  <p className="mt-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                    {e.summary}
                  </p>
                )}
                {e.items.length > 0 && (
                  <ul className="mt-3 list-disc space-y-2 ps-5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                    {e.items.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                )}
              </Card>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
