import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate, useOutletContext, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { Badge, Button, ErrorBox, Spinner } from "../../components/ui";
import { Product } from "../../types";
import { useFlags } from "../panel/FlagsContext";

/**
 * قاب صفحه‌ی محصول.
 *
 * پیش از این، `/products/:id` همه‌چیز را در یک صفحه می‌ریخت: مشخصات، عکس،
 * ویژگی‌ها، حالت پیشرفته، هوش محصول، تحلیل بازار، استودیو تصویر، کپشن و
 * استودیو ویدیو — روی هم حدود ۱۳۰۰ خط در یک اسکرول.
 *
 * دو چیز را خراب می‌کرد. اول اینکه پیدا کردن کاری که آمده‌ای انجام دهی،
 * یعنی اسکرول کردن از کنار شش کار دیگر. دوم اینکه هر بار باز کردن صفحه،
 * *همه‌ی* آن پنل‌ها را mount می‌کرد و هر کدام درخواست خودش را می‌فرستاد —
 * حتی وقتی فقط آمده بودی قیمت را عوض کنی.
 *
 * حالا هر کدام مسیر خودش را دارد. یعنی می‌شود لینکش را فرستاد، دکمه‌ی
 * بازگشت مرورگر کار می‌کند، و فقط چیزی بار می‌شود که باز کرده‌ای.
 *
 * محصول یک بار اینجا بار می‌شود و از راه `useProduct()` به زیرصفحه‌ها
 * می‌رسد، تا هفت زیرصفحه هفت بار همان درخواست را نزنند.
 */

type Ctx = { product: Product; reload: () => Promise<void> };

/** محصول و تابع تازه‌سازی‌اش، از قاب. */
export function useProduct() {
  return useOutletContext<Ctx>();
}

/** `key` همان کلیدِ صفحه در `features/panel/registry.ts` است؛ زبانه‌ی خاموش کشیده نمی‌شود. */
const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "product", to: "", label: "مشخصات", icon: "box", end: true },
  { key: "product_intelligence", to: "intelligence", label: "هوش محصول", icon: "sparkle" },
  { key: "product_market", to: "market", label: "تحلیل بازار", icon: "swords" },
  { key: "product_images", to: "images", label: "استودیو تصویر", icon: "image" },
  { key: "product_captions", to: "captions", label: "کپشن", icon: "subtitles" },
  { key: "product_video", to: "video", label: "استودیو ویدیو", icon: "film" },
  { key: "product_advanced", to: "advanced", label: "حالت پیشرفته", icon: "settings" },
];

export default function ProductLayout() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { pageEnabled } = useFlags();
  const [product, setProduct] = useState<Product | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const { data } = await api.get<Product>(`/products/${id}/`);
      setProduct(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const removeProduct = async () => {
    if (!product) return;
    const confirmed = window.confirm(
      `«${product.name}» و همهٔ محتوای تولیدشده‌اش (تحلیل، پوستر، کپشن، سناریو و ویدیو) ` +
        "برای همیشه حذف می‌شوند. مطمئنید؟",
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/products/${id}/`);
      navigate(`/stores/${product.store}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  if (!product) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  return (
    <div className="u-rise space-y-5">
      <div>
        <Link
          to={`/stores/${product.store}`}
          className="u-back"
        >
          <Icon name="back" size={15} />
          بازگشت به فروشگاه
        </Link>

        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            {product.images[0] ? (
              <img
                src={product.images[0].image}
                alt=""
                className="h-12 w-12 shrink-0 rounded-xl object-cover"
                style={{ border: "1px solid var(--line)" }}
              />
            ) : (
              <span
                className="grid h-12 w-12 shrink-0 place-items-center rounded-xl"
                style={{
                  background: "var(--surface-2)",
                  border: "1px solid var(--line)",
                  color: "var(--text-3)",
                }}
              >
                <Icon name="box" size={20} />
              </span>
            )}
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-extrabold" style={{ color: "var(--text)" }}>
                {product.name}
              </h1>
              <div className="mt-0.5 flex flex-wrap items-center gap-2">
                <Badge tone={product.available_quantity > 0 ? "ok" : "warn"}>
                  {product.available_quantity > 0
                    ? `${product.available_quantity} قابل فروش`
                    : "ناموجود"}
                </Badge>
                {/* رزرو یعنی کالا در انبار هست ولی مشتریِ در حال پرداخت
                    رویش حساب کرده — عددِ انبار و عددِ فروختنی یکی نیستند. */}
                {product.reserved_quantity > 0 && (
                  <Badge tone="info">
                    {product.reserved_quantity} رزرو از {product.stock_quantity} موجودی
                  </Badge>
                )}
                {product.brand && <Badge>{product.brand}</Badge>}
              </div>
            </div>
          </div>

          {/* a product added by mistake stays in the catalog forever otherwise —
              and the sales agent keeps offering it to customers */}
          <Button variant="secondary" disabled={busy} onClick={() => void removeProduct()}>
            <Icon name="trash" size={15} />
            حذف محصول
          </Button>
        </div>
      </div>

      <ErrorBox message={error} />

      <nav className="u-tabs">
        {TABS.filter((tab) => pageEnabled(tab.key)).map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}
          >
            <span className="flex items-center gap-1.5">
              <Icon name={tab.icon} size={15} />
              {tab.label}
            </span>
          </NavLink>
        ))}
      </nav>

      <div key={product.id} className="u-rise">
        <Outlet context={{ product, reload } satisfies Ctx} />
      </div>
    </div>
  );
}
