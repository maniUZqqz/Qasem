import { useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import { Alert, Badge, Card, SectionTitle, Select, Skeleton } from "./ui";

type Capability = {
  capability: string;
  label: string;
  provider: string | null;
  model: string | null;
  local: boolean | null;
  data_location: string | null;
  blocked: boolean;
  reason: string | null;
};

type Policy = {
  mode: string;
  mode_label: string;
  allow_customer_data_external: boolean;
  is_platform_default: boolean;
  modes: { value: string; label: string }[];
  capabilities: Capability[];
  /** Who would narrate under this policy — `engine`/`local` when available. */
  narration: { available: boolean; reason: string | null; engine?: string; local?: boolean };
  any_external: boolean;
};

const LOCATION_LABEL: Record<string, string> = {
  ON_PREMISE: "سرور ما",
  IRAN: "ایران",
  EU: "اروپا",
  US: "آمریکا",
  OTHER: "خارج",
  UNKNOWN: "نامشخص",
};

/**
 * Where this store's data is allowed to go, and where it actually goes.
 *
 * The second half is the part that earns the card. A setting that only says
 * "Local Only" without showing which capabilities stop working is a trap: the
 * owner switches it, video narration quietly disappears, and they spend a week
 * thinking the product is broken.
 */
export default function DataPolicyCard({ storeId }: { storeId: string | number }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get(`/stores/${storeId}/ai-policy/`)
      .then(({ data }) => alive && setPolicy(data))
      .catch(() => alive && setPolicy(null));
    return () => {
      alive = false;
    };
  }, [storeId]);

  async function update(patch: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.patch(`/stores/${storeId}/ai-policy/`, patch);
      setPolicy(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  if (policy === null) return <Skeleton className="h-52" />;

  const blocked = policy.capabilities.filter((c) => c.blocked);

  return (
    <Card>
      <SectionTitle>داده و حریم خصوصی</SectionTitle>

      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
            داده‌ی این فروشگاه کجا پردازش شود
          </span>
          <Select
            value={policy.mode}
            disabled={saving}
            onChange={(e) => update({ mode: e.target.value })}
          >
            {policy.modes.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </Select>
          {policy.is_platform_default && (
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              هنوز چیزی انتخاب نکرده‌اید؛ این مقدار پیش‌فرض سامانه است.
            </span>
          )}
        </label>

        {policy.any_external && (
          <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input
              type="checkbox"
              className="mt-1"
              checked={policy.allow_customer_data_external}
              disabled={saving}
              onChange={(e) => update({ allow_customer_data_external: e.target.checked })}
            />
            <span>
              پیام‌های خصوصی مشتری هم به سرویس بیرونی فرستاده شود
              <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                پیش‌فرض خاموش است. این داده‌ی مشتری شماست، نه داده‌ی فروشگاه.
              </span>
            </span>
          </label>
        )}

        {error && <Alert tone="bad">{error}</Alert>}

        {!policy.narration.available && (
          <Alert tone="warn" title="صداگذاری با این تنظیم کار نمی‌کند">
            {policy.narration.reason}
          </Alert>
        )}
        {policy.narration.available && policy.narration.engine && (
          <Alert tone={policy.narration.local ? "ok" : "info"} title="صداگذاری ویدیوها">
            با این سیاست، متن نریشن را «{policy.narration.engine}» می‌خواند —{" "}
            {policy.narration.local
              ? "روی همین سیستم، و متن از سرور بیرون نمی‌رود."
              : "یک سرویس بیرونی، پس متن نریشن به آن فرستاده می‌شود."}
          </Alert>
        )}

        {blocked.length > 0 && (
          <Alert tone="warn" title={`${blocked.length} قابلیت با این سیاست غیرفعال است`}>
            {blocked.map((c) => (
              <div key={c.capability}>
                {c.label}: {c.reason}
              </div>
            ))}
          </Alert>
        )}

        <div className="flex flex-col gap-2 border-t pt-3" style={{ borderColor: "var(--line)" }}>
          {policy.capabilities.map((row) => (
            <div key={row.capability} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                  {row.label}
                </div>
                <div className="truncate text-xs" style={{ color: "var(--text-3)" }}>
                  {row.blocked ? "غیرفعال" : row.model ?? "تنظیم نشده"}
                </div>
              </div>
              {row.blocked ? (
                <Badge tone="warn">⛔ مسدود</Badge>
              ) : (
                <Badge tone={row.local ? "ok" : "info"}>
                  {row.local
                    ? "🖥️ سرور ما"
                    : `☁️ ${LOCATION_LABEL[row.data_location ?? "UNKNOWN"]}`}
                </Badge>
              )}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
