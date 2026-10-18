import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import Icon from "../../components/Icon";
import { Button, Card, EmptyState, Spinner } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";

/**
 * پرچم‌های پنل: کدام دسته/صفحه/قابلیت برای این کاربر روشن است.
 *
 * یک بار به ازای هر ورود از `GET /panel/flags/` خوانده می‌شود. کلیدی که در
 * پاسخ نیست یعنی «روشن» — و اگر درخواست شکست بخورد همه‌چیز روشن فرض
 * می‌شود: یک سوئیچِ ادمین نباید بتواند با یک خطای شبکه کلِ پنل را خاموش کند.
 */

type FlagsResponse = {
  sections?: { key: string; enabled: boolean }[];
  pages?: Record<string, boolean>;
  features?: Record<string, boolean>;
};

type Maps = {
  sections: Record<string, boolean>;
  pages: Record<string, boolean>;
  features: Record<string, boolean>;
};

const EMPTY: Maps = { sections: {}, pages: {}, features: {} };

function toMaps(data: FlagsResponse): Maps {
  const sections: Record<string, boolean> = {};
  for (const s of data.sections ?? []) sections[s.key] = s.enabled;
  return { sections, pages: data.pages ?? {}, features: data.features ?? {} };
}

export type FlagsValue = {
  /** تا پرچم‌های این کاربر نرسیده‌اند. */
  loading: boolean;
  sectionEnabled: (key: string) => boolean;
  pageEnabled: (key: string) => boolean;
  featureEnabled: (key: string) => boolean;
};

const FlagsContext = createContext<FlagsValue | null>(null);

export function FlagsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  // پرچم‌ها همراه شناسه‌ی کاربری که برایش خوانده شده نگه داشته می‌شوند؛ با
  // عوض شدن کاربر، در همان رندر «در حال بارگذاری» می‌شویم — نه یک فریم بعد.
  const [state, setState] = useState<{ userId: number; maps: Maps } | null>(null);

  useEffect(() => {
    if (userId === null) return;
    let cancelled = false;
    api
      .get<FlagsResponse>("/panel/flags/")
      .then(({ data }) => {
        if (!cancelled) setState({ userId, maps: toMaps(data) });
      })
      .catch(() => {
        if (!cancelled) setState({ userId, maps: EMPTY });
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const ready = userId !== null && state?.userId === userId;
  const maps = ready && state ? state.maps : EMPTY;
  const loading = userId !== null && !ready;

  const value = useMemo<FlagsValue>(
    () => ({
      loading,
      sectionEnabled: (key) => maps.sections[key] !== false,
      pageEnabled: (key) => maps.pages[key] !== false,
      featureEnabled: (key) => maps.features[key] !== false,
    }),
    [loading, maps],
  );

  return <FlagsContext.Provider value={value}>{children}</FlagsContext.Provider>;
}

export function useFlags(): FlagsValue {
  const ctx = useContext(FlagsContext);
  if (!ctx) throw new Error("useFlags must be used inside FlagsProvider");
  return ctx;
}

/** آیا این قابلیت (مثل `studio.video`) برای کاربر روشن است؟ */
export function useFeature(key: string): boolean {
  return useFlags().featureEnabled(key);
}

/** بچه‌ها فقط وقتی کشیده می‌شوند که قابلیت روشن باشد. */
export function Feature({ k, children }: { k: string; children: ReactNode }) {
  return useFeature(k) ? <>{children}</> : null;
}

/** به جای صفحه‌ی خاموش، یک کارتِ دوستانه — نه صفحه‌ی خالی، نه خطای ۴۰۴. */
export function PageGate({ k, children }: { k: string; children: ReactNode }) {
  const { loading, pageEnabled } = useFlags();
  if (loading) {
    return (
      <div className="py-10 text-center">
        <Spinner />
      </div>
    );
  }
  if (pageEnabled(k)) return <>{children}</>;
  return (
    <Card>
      <EmptyState
        icon="ban"
        title="این صفحه فعلاً غیرفعال است"
        action={
          <Link to="/" className="no-underline">
            <Button variant="secondary">
              <Icon name="back" size={15} />
              بازگشت به داشبورد
            </Button>
          </Link>
        }
      >
        از ادمین ⇐ «صفحه‌های پنل» می‌شود روشنش کرد.
      </EmptyState>
    </Card>
  );
}
