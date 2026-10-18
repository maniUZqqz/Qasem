import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorMessage, fetchAllPages } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Select,
  Spinner,
  PageHeader,
  fa,
} from "../../components/ui";
import { Product } from "../../types";
import { useFlags } from "../panel/FlagsContext";
import AdvancedModePanel from "./AdvancedModePanel";
import AutomationSettings from "./AutomationSettings";
import CaptionsPanel from "./CaptionsPanel";
import ImageStudioPanel from "./ImageStudioPanel";
import VideoStudioPanel from "./VideoStudioPanel";

/**
 * صفحه ۴ — تولید محتوا.
 *
 * `ایده‌ها پنل.md` این را «اصلی‌ترین صفحه» می‌نامد و چهار چیز از آن می‌خواهد:
 * تنظیم اتوماسیون و زمان‌بندی، انتخاب محصول، دو تب ویدیو و عکس، و دو حالت
 * ساده و پیشرفته.
 *
 * هیچ‌کدام صفحه‌ای نداشتند. استودیوها ساخته شده بودند ولی **زیر محصول**
 * پخش بودند: `/products/۱۲/video`، `/products/۱۲/images`. یعنی برای ساختن
 * محتوا اول باید می‌رفتی محصول را پیدا می‌کردی، بعد تب درست را. و
 * زمان‌بندی اصلاً هیچ‌جا نبود.
 *
 * اینجا همان پنل‌ها هستند — تغییری نکرده‌اند — ولی ترتیب کار عوض شده:
 * **اول انتخاب محصول، بعد انتخاب خروجی.** همان ترتیبی که آدم در ذهنش دارد.
 *
 * محصول انتخاب‌شده در آدرس می‌نشیند (`?product=12`)، پس لینکش فرستادنی است
 * و دکمه‌ی بازگشت مرورگر کار می‌کند.
 */

type Tab = "video" | "image" | "caption" | "advanced" | "automation";

type TabDef = { key: Tab; label: string; note: string };

/** هر زبانه یک قابلیتِ `studio.<key>` در `features/panel/registry.ts` است. */
const TABS: TabDef[] = [
  { key: "video", label: "ویدیو", note: "۵ ثانیه ۵ ثانیه ساخته و به هم چسبانده می‌شود" },
  { key: "image", label: "عکس و پوستر", note: "پوستر بیلبوردی یا نمایش محصول" },
  { key: "caption", label: "کپشن", note: "متن پست، با لحن برند خودتان" },
  { key: "advanced", label: "پیشرفته", note: "با ورودی اضافه — زاویه‌ی خاص، ویدیوی مرجع" },
  { key: "automation", label: "اتوماسیون و زمان‌بندی", note: "چه چیزی، کِی، و با تأیید یا بدون آن" },
];

export default function ContentStudioPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const { loading: flagsLoading, featureEnabled } = useFlags();

  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // زبانه‌های روشن. زبانه‌ی خواسته‌شده اگر روشن باشد، وگرنه اولین زبانه‌ی
  // روشن — زبانه‌ی پنهان هیچ‌وقت پیش‌فرض نمی‌شود.
  const tabs = TABS.filter((t) => featureEnabled(`studio.${t.key}`));
  const requested = params.get("tab");
  const current: TabDef | null =
    tabs.find((t) => t.key === requested) ?? (tabs.length ? tabs[0] : null);
  const tab = current?.key ?? null;
  const productId = params.get("product");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Every page, not the first one: a shop with more products than the
      // page size would get a dropdown that quietly omits the rest.
      setProducts(await fetchAllPages<Product>(`/products/?store=${id}`));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const product = useMemo(
    () => products.find((p) => String(p.id) === productId) ?? null,
    [products, productId],
  );

  // First product, chosen once, so the page is never a dropdown and nothing
  // else. Written into the URL rather than held in state so a refresh keeps it.
  useEffect(() => {
    if (!productId && products.length && tab) {
      setParams({ tab, product: String(products[0].id) }, { replace: true });
    }
  }, [productId, products, tab, setParams]);

  const go = (next: Partial<{ tab: Tab; product: string }>) => {
    const product = next.product ?? productId;
    const t = next.tab ?? tab;
    setParams({ ...(t ? { tab: t } : {}), ...(product ? { product } : {}) });
  };

  if (loading || flagsLoading) return <Spinner />;

  const needsProduct = !!current && tab !== "automation";

  return (
    <div>
      <PageHeader
        title="تولید محتوا"
        subtitle="یک محصول انتخاب کن، خروجی‌اش را بساز — یا بگذار خودکار ساخته شود."
        actions={
          <Link to={`/stores/${id}/queue`}>
            <Button variant="ghost">
              <Icon name="cpu" /> صف تولید
            </Button>
          </Link>
        }
      />

      <ErrorBox message={error} />

      {/* ------------------------------------------------- انتخاب محصول */}
      {needsProduct && (
        <Card className="mb-4">
          {products.length === 0 ? (
            <EmptyState
              icon="box"
              title="هنوز محصولی ثبت نشده"
              description="تولید محتوا از روی اطلاعات محصول انجام می‌شود، پس اول یک محصول اضافه کنید."
              action={
                <Link to={`/stores/${id}`}>
                  <Button>
                    <Icon name="plus" /> افزودن محصول
                  </Button>
                </Link>
              }
            />
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[220px] flex-1">
                <span
                  className="mb-1.5 block text-sm font-medium"
                  style={{ color: "var(--text-2)" }}
                >
                  محصول
                </span>
                <Select
                  value={productId ?? ""}
                  onChange={(e) => go({ product: e.target.value })}
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </div>
              {product && (
                <Link to={`/products/${product.id}`}>
                  <Button variant="ghost">
                    <Icon name="box" /> صفحه‌ی محصول
                  </Button>
                </Link>
              )}
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                {fa(products.length)} محصول
              </span>
            </div>
          )}
        </Card>
      )}

      {/* --------------------------------------------------------- تب‌ها */}
      <nav className="u-tabs mb-4">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => go({ tab: t.key })}
            className={`u-tab ${t.key === tab ? "active" : ""}`}
            aria-current={t.key === tab ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {current && (
        <p className="mb-4 text-xs" style={{ color: "var(--text-3)" }}>
          {current.note}
        </p>
      )}

      {/* ------------------------------------------------------- محتوا */}
      {!current ? (
        <Alert tone="warn">
          همه‌ی زبانه‌های استودیو خاموش‌اند — از ادمین ⇐ «صفحه‌های پنل» می‌شود روشنشان کرد.
        </Alert>
      ) : tab === "automation" ? (
        <AutomationSettings storeId={id!} products={products} />
      ) : !product ? (
        <Alert tone="info">برای ساختن محتوا اول یک محصول انتخاب کنید.</Alert>
      ) : tab === "video" ? (
        <VideoStudioPanel productId={product.id} storeId={id} />
      ) : tab === "image" ? (
        <ImageStudioPanel product={product} />
      ) : tab === "caption" ? (
        <CaptionsPanel productId={product.id} />
      ) : (
        <AdvancedModePanel productId={product.id} />
      )}
    </div>
  );
}
