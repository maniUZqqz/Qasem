import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";

import { api, errorMessage, fetchAllPages } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { Button, ErrorBox, Spinner } from "../../components/ui";
import { Product, Store, StoreProfile } from "../../types";
import { Feature, useFlags } from "../panel/FlagsContext";

/**
 * قاب صفحه‌ی فروشگاه.
 *
 * صفحه‌ی قبلی هفت کارت را پشت سر هم می‌ریخت — چک‌لیست شروع، پروفایل
 * برند، فرم افزودن محصول، قوانین ایجنت فروش، سیاست داده، اعضا، و فهرست
 * محصولات. همان مشکل صفحه‌ی محصول، در صفحه‌ای که *اولین* چیزی است که
 * کاربر بعد از ورود می‌بیند.
 *
 * تفکیک بر اساس «هر چند وقت یک بار به این دست می‌زنی» است: محصولات هر
 * روز، پروفایل برند یک بار، اعضا و سیاست داده تقریباً هرگز. ریختن این سه
 * در یک ستون یعنی کاری که هر روز انجام می‌شود، زیر کارهایی دفن می‌شود که
 * سالی یک بار.
 */

export type StoreCtx = {
  store: Store;
  profile: StoreProfile;
  setProfile: (p: StoreProfile) => void;
  products: Product[];
  storeId: string;
  reload: () => Promise<void>;
  error: string | null;
  setError: (message: string | null) => void;
  notice: string | null;
  setNotice: (message: string | null) => void;
};

export function useStore() {
  return useOutletContext<StoreCtx>();
}

/** `key` همان کلیدِ صفحه در `features/panel/registry.ts` است؛ زبانه‌ی خاموش کشیده نمی‌شود. */
const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "products", to: "", label: "محصولات", icon: "box", end: true },
  { key: "brand", to: "brand", label: "پروفایل برند", icon: "sparkle" },
  { key: "voice", to: "voice", label: "صدا و گوینده", icon: "mic" },
  { key: "agent", to: "agent", label: "ایجنت فروش", icon: "chat" },
  { key: "connections", to: "connections", label: "اتصال شبکه‌ها", icon: "link" },
  { key: "team", to: "team", label: "اعضا و دسترسی", icon: "users" },
  { key: "data", to: "data", label: "سیاست داده", icon: "shield" },
];

export default function StoreLayout() {
  const { id } = useParams<{ id: string }>();
  const { pageEnabled } = useFlags();
  const [store, setStore] = useState<Store | null>(null);
  const [profile, setProfile] = useState<StoreProfile | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [storeRes, profileRes, productList] = await Promise.all([
        api.get<Store>(`/stores/${id}/`),
        api.get<StoreProfile>(`/stores/${id}/profile/`),
        fetchAllPages<Product>(`/products/?store=${id}`),
      ]);
      setStore(storeRes.data);
      setProfile(profileRes.data);
      setProducts(productList);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (!store || !profile || !id) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const ctx: StoreCtx = {
    store,
    profile,
    setProfile,
    products,
    storeId: id,
    reload,
    error,
    setError,
    notice,
    setNotice,
  };

  return (
    <div className="u-rise space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <Link
            to="/"
            className="u-back"
          >
            <Icon name="back" size={15} />
            بازگشت به داشبورد
          </Link>
          <h1
            className="mt-1 truncate text-2xl font-extrabold"
            style={{ color: "var(--text)" }}
          >
            {store.name}
          </h1>
          {store.business_type && (
            <p className="text-sm" style={{ color: "var(--brand-strong)" }}>
              {store.business_type}
            </p>
          )}
        </div>
        <Feature k="store.chat_button">
          <Link to={`/stores/${id}/chat`} className="no-underline">
            <Button>
              <Icon name="chat" size={16} />
              چت فروش (آزمایشی)
            </Button>
          </Link>
        </Feature>
      </div>

      <ErrorBox message={error} />
      {notice && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{
            background: "var(--ok-soft)",
            color: "var(--ok)",
            border: "1px solid color-mix(in srgb, var(--ok) 30%, transparent)",
          }}
        >
          {notice}
        </div>
      )}

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

      <Outlet context={ctx} />
    </div>
  );
}
