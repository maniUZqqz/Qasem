import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  SectionTitle,
  Spinner,
  Table,
  fa,
} from "../../components/ui";

/**
 * موتورهای AI — کدام قابلیت با چه چیزی کار می‌کند، و کدام‌ها زنده‌اند.
 *
 * `POST /ai/providers/health/` هر ارائه‌دهنده‌ی فعال را با یک فراخوانی
 * **واقعی** می‌زند و نتیجه را در دیتابیس می‌نویسد. ساخته و تست شده بود و
 * هیچ دکمه‌ای نداشت.
 *
 * **دکمه است نه زمان‌بند، و عمداً.** هر بار زدنش یعنی یک درخواست واقعی به
 * هر موتور — روی Ollama محلی یعنی بیدار کردن یک مدل ۳۲ میلیاردی و گرفتن
 * VRAM، و روی API یعنی هزینه. چیزی که پول و کارت گرافیک خرج می‌کند نباید
 * خودش هر چند دقیقه اجرا شود.
 *
 * فهرست از `‎/ai/status/` می‌آید که **قابلیت‌محور** است نه ردیف‌محور: سؤالِ
 * واقعی «تولید تصویر الان با چه چیزی انجام می‌شود» است، نه «چند ردیف در
 * جدول ارائه‌دهنده‌ها هست».
 */

type Capability = {
  capability: string;
  label: string;
  provider: string;
  kind: string;
  model: string;
  local: boolean | null;
  fallbacks: number;
};

type Status = {
  capabilities: Capability[];
  all_local: boolean;
  any_external: boolean;
};

type HealthRow = {
  id: number;
  name: string;
  capability: string;
  healthy: boolean;
  detail: string;
};

export default function ProvidersPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [health, setHealth] = useState<HealthRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Status>("/ai/status/");
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const probe = async () => {
    setChecking(true);
    setError(null);
    try {
      const { data } = await api.post<{ checked: number; results: HealthRow[] }>(
        "/ai/providers/health/",
      );
      setHealth(data.results);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setChecking(false);
    }
  };

  if (!status) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />

      {status.any_external && (
        <Alert tone="info" title="بعضی قابلیت‌ها بیرون از این سرور اجرا می‌شوند">
          سیاست داده‌ی هر فروشگاه جداگانه تصمیم می‌گیرد داده‌اش به کدام‌یک برود —
          فروشگاهِ «فقط لوکال» با پیام روشن fail می‌شود، نه اینکه بی‌صدا بیرون برود.
        </Alert>
      )}

      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionTitle>الان هر قابلیت با چه چیزی کار می‌کند</SectionTitle>
        </div>
        <Table>
          <thead>
            <tr>
              <th>قابلیت</th>
              <th>موتور</th>
              <th>مدل</th>
              <th>کجا</th>
              <th>جایگزین</th>
            </tr>
          </thead>
          <tbody>
            {status.capabilities.map((c) => (
              <tr key={c.capability}>
                <td style={{ color: "var(--text)", fontWeight: 500 }}>{c.label}</td>
                <td>{c.provider}</td>
                <td dir="ltr" className="u-num">
                  {c.model || "—"}
                </td>
                <td>
                  {/* آیکون + متن، نه فقط رنگ */}
                  {c.local === null ? (
                    <Badge>نامشخص</Badge>
                  ) : (
                    <Badge tone={c.local ? "ok" : "info"}>
                      <Icon name={c.local ? "cpu" : "cloud"} size={12} />
                      {c.local ? "روی همین سرور" : "بیرونی"}
                    </Badge>
                  )}
                </td>
                <td className="u-num">{c.fallbacks ? fa(c.fallbacks) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Alert tone="warn" title="هر بررسی یک فراخوانی واقعی است">
        روی موتور محلی یعنی بیدار کردن مدل و گرفتن VRAM؛ روی API یعنی هزینه. برای
        همین دکمه است، نه زمان‌بند.
      </Alert>

      <Button onClick={probe} disabled={checking}>
        <Icon name="refresh" size={15} />
        {checking ? "در حال بررسی…" : "بررسی زنده‌ی موتورها"}
      </Button>

      {health !== null &&
        (health.length === 0 ? (
          <Card>
            <EmptyState icon="cpu" title="موتور قابل بررسی‌ای ثبت نشده">
              وقتی موتوری در پنل ادمین جنگو تعریف شود اینجا می‌آید. تا آن موقع محصول
              از تنظیمات <code dir="ltr">.env</code> استفاده می‌کند — که جدول بالا
              همان را نشان می‌دهد.
            </EmptyState>
          </Card>
        ) : (
          <Card padded={false}>
            <Table>
              <thead>
                <tr>
                  <th>موتور</th>
                  <th>قابلیت</th>
                  <th>نتیجه</th>
                  <th>جزئیات</th>
                </tr>
              </thead>
              <tbody>
                {health.map((r) => (
                  <tr key={r.id}>
                    <td style={{ color: "var(--text)", fontWeight: 500 }}>{r.name}</td>
                    <td>{r.capability}</td>
                    <td>
                      <Badge tone={r.healthy ? "ok" : "bad"}>
                        <Icon name={r.healthy ? "ok" : "ban"} size={12} />
                        {r.healthy ? "سالم" : "ناسالم"}
                      </Badge>
                    </td>
                    <td style={{ color: r.healthy ? "var(--text-3)" : "var(--bad)" }}>
                      {r.detail || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        ))}
    </div>
  );
}
