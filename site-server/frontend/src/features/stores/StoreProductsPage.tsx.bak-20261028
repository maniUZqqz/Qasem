import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import OnboardingCard from "../../components/OnboardingCard";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  SectionTitle,
  TextArea,
  fa,
  toman,
} from "../../components/ui";
import { Feature, useFeature } from "../panel/FlagsContext";
import { useStore } from "./StoreLayout";

/** محصولات فروشگاه و افزودن محصول — کاری که هر روز انجام می‌شود. */
export default function StoreProductsPage() {
  const { products, storeId, reload, setError } = useStore();
  const canAdd = useFeature("products.add");
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("0");
  const [description, setDescription] = useState("");
  const [query, setQuery] = useState("");

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/products/", {
        store: Number(storeId),
        name,
        price: price || "0",
        stock_quantity: Number(stock) || 0,
        description,
      });
      setName("");
      setPrice("");
      setStock("0");
      setDescription("");
      setShowForm(false);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const shown = query.trim()
    ? products.filter((p) =>
        `${p.name} ${p.brand ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()),
      )
    : products;

  return (
    <div className="space-y-5">
      <Feature k="products.onboarding">
        <OnboardingCard storeId={storeId} />
      </Feature>

      <div className="flex flex-wrap items-center gap-2">
        {/* جست‌وجو فقط وقتی معنی دارد که فهرست به اندازه‌ی کافی بلند باشد؛
            یک فیلد جست‌وجو بالای سه محصول، فقط جا می‌گیرد. */}
        {products.length > 8 && (
          <div className="relative min-w-[220px] flex-1">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="جست‌وجو در محصولات…"
              style={{ paddingInlineStart: 36 }}
            />
            <span
              className="pointer-events-none absolute inset-y-0 flex items-center"
              style={{ insetInlineStart: 12, color: "var(--text-3)" }}
            >
              <Icon name="search" size={16} />
            </span>
          </div>
        )}
        {canAdd && (
          <Button
            variant={showForm ? "secondary" : "primary"}
            onClick={() => setShowForm((v) => !v)}
            className="mr-auto"
          >
            <Icon name={showForm ? "x" : "plus"} size={15} />
            {showForm ? "بستن فرم" : "افزودن محصول"}
          </Button>
        )}
      </div>

      {canAdd && showForm && (
        <Card>
          <SectionTitle>محصول جدید</SectionTitle>
          <form onSubmit={create} className="grid gap-4 sm:grid-cols-3">
            <Field label="نام محصول">
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="قیمت (تومان)">
              <Input
                type="number"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </Field>
            <Field label="موجودی">
              <Input
                type="number"
                min="0"
                value={stock}
                onChange={(e) => setStock(e.target.value)}
              />
            </Field>
            <div className="sm:col-span-3">
              <Field
                label="توضیحات"
                hint="هرچه اینجا بنویسید، ورودی تحلیل محصول و تولید محتواست."
              >
                <TextArea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
            </div>
            <div>
              <Button type="submit" disabled={busy || !name}>
                <Icon name="check" size={15} />
                {busy ? "در حال ساخت…" : "ساخت محصول"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      <div>
        <SectionTitle>محصولات ({fa(products.length)})</SectionTitle>
        {products.length === 0 ? (
          <Card>
            <EmptyState
              icon="box"
              title="هنوز محصولی ثبت نشده"
              action={
                canAdd && (
                  <Button onClick={() => setShowForm(true)}>
                    <Icon name="plus" size={15} />
                    اولین محصول را اضافه کن
                  </Button>
                )
              }
            >
              تحلیل، پوستر، کپشن و ویدیو همه از یک محصول شروع می‌شوند.
            </EmptyState>
          </Card>
        ) : shown.length === 0 ? (
          <Card>
            <EmptyState icon="search" title="محصولی با این نام پیدا نشد" />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((product) => (
              <Link key={product.id} to={`/products/${product.id}`} className="no-underline">
                <Card hover className="h-full">
                  {product.images.length > 0 ? (
                    <img
                      src={product.images[0].image}
                      alt=""
                      className="mb-3 h-32 w-full rounded-lg object-cover"
                      style={{ border: "1px solid var(--line)" }}
                    />
                  ) : (
                    <div
                      className="mb-3 grid h-32 w-full place-items-center rounded-lg"
                      style={{
                        background: "var(--surface-2)",
                        border: "1px dashed var(--line-strong)",
                        color: "var(--text-3)",
                      }}
                      title="بدون عکس — تحلیل بصری بدون عکس کار نمی‌کند"
                    >
                      <Icon name="image" size={22} />
                    </div>
                  )}
                  <h3 className="font-bold" style={{ color: "var(--text)" }}>
                    {product.name}
                  </h3>
                  <p className="u-num mt-1 text-sm" style={{ color: "var(--brand-strong)" }}>
                    {toman(Number(product.price))} تومان
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {/* قابل فروش، نه موجودی خام: کالایی که مشتری دارد پولش
                        را می‌فرستد دیگر برای نفر بعد نیست. */}
                    <Badge tone={product.available_quantity > 0 ? "ok" : "warn"}>
                      {product.available_quantity > 0
                        ? `${fa(product.available_quantity)} قابل فروش`
                        : "ناموجود"}
                    </Badge>
                    {product.reserved_quantity > 0 && (
                      <Badge tone="info">{fa(product.reserved_quantity)} رزرو</Badge>
                    )}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
