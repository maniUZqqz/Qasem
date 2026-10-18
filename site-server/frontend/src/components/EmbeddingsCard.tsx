import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import Icon from "./Icon";
import { Alert, Badge, Button, Card, ErrorBox, Meter, SectionTitle, fa } from "./ui";

/**
 * جست‌وجوی برداری محصولات.
 *
 * اندپوینتش از فاز ۷.۵ بود و هیچ دکمه‌ای نداشت — سند حتی دستورش را
 * نوشته بود («`POST /stores/{id}/embeddings/rebuild/`») که یعنی راهِ
 * استفاده‌اش، باز کردن ترمینال بود.
 *
 * وقتی خاموش است، این کارت **دلیل خاموش بودن را می‌گوید و دکمه را
 * غیرفعال می‌کند** — نه اینکه دکمه‌ای بگذارد که فشارش خطا بدهد. خاموشی
 * اینجا نقص نیست: ایجنت فروش بدون بردار هم با جست‌وجوی کلیدواژه‌ای کار
 * می‌کند، و همین را هم می‌گوید.
 */

type State = {
  enabled: boolean;
  model: string;
  products: number;
  embedded: number;
};

export default function EmbeddingsCard({ storeId }: { storeId: string | number }) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<State>(`/stores/${storeId}/embeddings/`);
      setState(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rebuild = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.post(`/stores/${storeId}/embeddings/rebuild/`);
      setNotice("ساخت بردارها در صف نشست — در «صف تولید» پیشرفتش را می‌بینید.");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!state) return null;

  const missing = Math.max(0, state.products - state.embedded);

  return (
    <Card>
      <SectionTitle
        action={
          <Badge tone={state.enabled ? "ok" : "neutral"}>
            {state.enabled ? "روشن" : "خاموش"}
          </Badge>
        }
      >
        جست‌وجوی برداری محصولات
      </SectionTitle>

      <ErrorBox message={error} />

      <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
        با این، ایجنت فروش «کاپشن گرم برای سفر» را به محصولی وصل می‌کند که اسمش
        این کلمه‌ها را ندارد. برای کاتالوگ بزرگ معنی دارد؛ برای ده محصول، جست‌وجوی
        کلیدواژه‌ای هم کافی است.
      </p>

      {!state.enabled ? (
        <Alert tone="info" title="خاموش است — و این ایراد نیست">
          ایجنت فروش با جست‌وجوی کلیدواژه‌ای کار می‌کند و چیزی از دست نمی‌رود. برای
          روشن کردن، مدل <code dir="ltr">{state.model}</code> باید روی سرور نصب و{" "}
          <code dir="ltr">EMBEDDINGS_ENABLED</code> فعال شود.
        </Alert>
      ) : (
        <div className="mt-3 space-y-3">
          <div>
            <div
              className="mb-1.5 flex items-center justify-between text-sm"
              style={{ color: "var(--text-2)" }}
            >
              <span>
                <span className="u-num">{fa(state.embedded)}</span> از{" "}
                <span className="u-num">{fa(state.products)}</span> محصول بردار دارد
              </span>
              <span className="text-xs" style={{ color: "var(--text-3)" }} dir="ltr">
                {state.model}
              </span>
            </div>
            <Meter used={state.embedded} total={state.products || 1} />
          </div>

          {missing > 0 && (
            <p className="text-sm" style={{ color: "var(--warn)" }}>
              {fa(missing)} محصول هنوز بردار ندارد — تا ساخته نشود، از جست‌وجوی برداری
              بیرون می‌ماند.
            </p>
          )}

          {notice && (
            <p className="text-sm" style={{ color: "var(--ok)" }}>
              {notice}
            </p>
          )}

          <Button variant="secondary" onClick={rebuild} disabled={busy}>
            <Icon name="refresh" size={15} />
            {busy ? "در حال شروع…" : "ساخت دوباره‌ی بردارها"}
          </Button>
        </div>
      )}
    </Card>
  );
}
