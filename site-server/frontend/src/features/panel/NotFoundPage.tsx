import { Navigate, generatePath, useLocation, useNavigate, useParams } from "react-router-dom";

import Layout from "../../components/Layout";
import { Spinner } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";
import { useFlags } from "./FlagsContext";
import { NotFoundCard } from "./NotFoundCard";
import { suggestPages } from "./notFound";
import PageTitle from "./PageTitle";
import { NOT_FOUND_TITLE } from "./tabTitle";

/**
 * «صفحه پیدا نشد».
 *
 * تا پیش از این، آدرسی که هیچ مسیری نداشت (`/panel/xyz`، یا آدرسِ قدیمیِ
 * `/stores/34/settings`) صفحه‌ی کاملاً خالی بود: نه منو، نه پیام، نه راهِ
 * برگشت — چون `Routes` وقتی چیزی جور نشود هیچ‌چیز نمی‌کشد. حالا:
 *
 *   • وارد شده: همین کارت *داخلِ قابِ پنل* (منو سرِ جایش است)؛
 *   • وارد نشده: کارتِ کوچکِ مستقل با پیوندِ ورود؛
 *   • دو آدرسِ قدیمی به جای جدیدشان هدایت می‌شوند (`LegacyRedirect`).
 */

/** آدرسِ قدیمی ⇐ آدرسِ جدید. `to` الگوی مسیر است و `:id` از همان آدرسِ قدیمی پر می‌شود؛ جست‌وجو و هش حفظ می‌شود. */
export function LegacyRedirect({ to }: { to: string }) {
  const params = useParams();
  const { search, hash } = useLocation();
  let target = to;
  try {
    target = generatePath(to, params as Record<string, string>);
  } catch {
    target = "/";
  }
  return <Navigate to={`${target}${search}${hash}`} replace />;
}

/** نسخهٔ داخلِ قاب (کاربرِ واردشده). */
function NotFoundInFrame() {
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  const { pageEnabled } = useFlags();
  const navigate = useNavigate();

  let storeId: string | null = null;
  try {
    storeId = localStorage.getItem("last-store");
  } catch {
    /* حالت خصوصی */
  }
  const fromUrl = /^\/stores\/(\d+)/.exec(pathname);
  if (fromUrl) storeId = fromUrl[1];

  const suggestions = suggestPages(pathname, {
    storeId,
    isStaff: !!user?.is_staff,
    enabled: (p) => pageEnabled(p.key),
  });
  const canGoBack = typeof window !== "undefined" && Number(window.history.state?.idx ?? 0) > 0;

  return (
    <>
      <PageTitle title={NOT_FOUND_TITLE} />
      <NotFoundCard
        signedIn
        path={`/panel${pathname}${search}`}
        storeId={storeId}
        suggestions={suggestions}
        canGoBack={canGoBack}
        onBack={() => navigate(-1)}
      />
    </>
  );
}

/** مسیرِ `*` در `App.tsx` — بیرون از `Layout`، چون وارد نشده‌ها نباید به ورود پرت شوند و پیامی نبینند. */
export default function NotFoundRoute() {
  const { user, loading } = useAuth();
  const { pathname, search } = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size={30} />
      </div>
    );
  }
  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <PageTitle title={NOT_FOUND_TITLE} />
        <NotFoundCard signedIn={false} path={`/panel${pathname}${search}`} />
      </div>
    );
  }
  return (
    <Layout>
      <NotFoundInFrame />
    </Layout>
  );
}
