import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, fa, toman } from "./ui";

type Referral = {
  code: string | null;
  friend_discount_percent?: number;
  signups?: number;
  paying?: number;
  earned_toman?: number;
  paid_toman?: number;
  pending_toman?: number;
};

/**
 * The shop's invite code. Phase 26.
 *
 * Signups and paying customers are shown side by side rather than as one
 * number. A referrer with twelve signups and nothing earned needs to see why —
 * a single "12 invites" figure next to an empty balance reads as a bug in our
 * accounting rather than as what actually happened.
 */
export default function ReferralCard({ storeId }: { storeId: string | number }) {
  const [referral, setReferral] = useState<Referral | null>(null);
  /** «ما از کجا آمدیم» — یک بار موقع ثبت‌نام نوشته می‌شود و هرگز عوض
   *  نمی‌شود. اندپوینتش بود و هیچ‌جا نمایش داده نمی‌شد. */
  const [origin, setOrigin] = useState<{
    channel: string | null;
    channel_title?: string;
    campaign?: string;
    source?: string;
    landing_path?: string;
    days_to_pay?: number | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${storeId}/referral/`);
      api
        .get(`/stores/${storeId}/attribution/`)
        .then((r) => setOrigin(r.data))
        .catch(() => setOrigin(null));
      setReferral(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`/stores/${storeId}/referral/`);
      setReferral(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!referral?.code) return;
    try {
      await navigator.clipboard.writeText(referral.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  if (referral === null) return null;

  return (
    <Card>
      <SectionTitle>معرفی به دوستان</SectionTitle>
      <ErrorBox message={error} />

      {!referral.code ? (
        <>
          <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            یک کد بسازید و به فروشگاه‌های دیگر بدهید. آن‌ها تخفیف می‌گیرند و
            وقتی مشترک شدند، سهم شما ثبت می‌شود.
          </p>
          <Button onClick={create} disabled={busy}>
            {busy ? "…" : "کد من را بساز"}
          </Button>
        </>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <code
              dir="ltr"
              className="rounded-lg px-3 py-2 font-mono text-sm"
              style={{ background: "var(--surface-2)", color: "var(--text)" }}
            >
              {referral.code}
            </code>
            <Button variant="secondary" onClick={copy}>
              {copied ? "کپی شد ✓" : "کپی"}
            </Button>
            {!!referral.friend_discount_percent && (
              <Badge tone="brand">
                {fa(referral.friend_discount_percent)}٪ تخفیف برای دوستتان
              </Badge>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral">{fa(referral.signups ?? 0)} نفر ثبت‌نام کردند</Badge>
            <Badge tone={referral.paying ? "ok" : "neutral"}>
              {fa(referral.paying ?? 0)} نفر مشترک شدند
            </Badge>
          </div>

          {(referral.earned_toman ?? 0) > 0 ? (
            <div className="mt-3">
              <Alert tone="ok" title={`سهم شما: ${toman(referral.earned_toman ?? 0)}`}>
                {(referral.pending_toman ?? 0) > 0
                  ? `${toman(referral.pending_toman ?? 0)} هنوز پرداخت نشده — برای تسویه با ما تماس بگیرید.`
                  : "همه‌ی سهم شما پرداخت شده است."}
              </Alert>
            </div>
          ) : (
            (referral.signups ?? 0) > 0 && (
              <p className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
                سهم وقتی ثبت می‌شود که کسی که با کد شما آمده، اشتراک بخرد — نه
                همان لحظه‌ی ثبت‌نام.
              </p>
            )
          )}
        </>
      )}

      {/* «ما از کجا آمدیم» — خواندنی محض. مشتری‌ای که بتواند انتساب خودش
          را عوض کند، می‌تواند عوض کند که ما به چه کسی بدهکاریم. */}
      {origin?.channel && (
        <div className="mt-4 pt-3" style={{ borderTop: "1px solid var(--line)" }}>
          <div className="mb-1.5 text-xs font-semibold" style={{ color: "var(--text-3)" }}>
            این فروشگاه از کجا آمد
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="neutral">{origin.channel_title || origin.channel}</Badge>
            {origin.campaign && (
              <span style={{ color: "var(--text-2)" }}>کمپین: {origin.campaign}</span>
            )}
            {origin.landing_path && (
              <span dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
                {origin.landing_path}
              </span>
            )}
            {origin.days_to_pay != null && (
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                {fa(origin.days_to_pay)} روز تا اولین پرداخت
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
