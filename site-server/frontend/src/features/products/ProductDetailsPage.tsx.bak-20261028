import { ChangeEvent, FormEvent, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
  TextArea,
  fa,
} from "../../components/ui";
import { useProduct } from "./ProductLayout";

/** مشخصات، عکس‌ها و ویژگی‌های محصول — همان چیزهایی که کاربر خودش وارد
 *  می‌کند. هرچه AI می‌سازد، در تب‌های دیگر است. */
export default function ProductDetailsPage() {
  const { product, reload } = useProduct();
  const [draft, setDraft] = useState(product);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attrKey, setAttrKey] = useState("");
  const [attrValue, setAttrValue] = useState("");

  const id = product.id;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/products/${id}/`, {
        name: draft.name,
        price: draft.price,
        stock_quantity: draft.stock_quantity,
        description: draft.description,
        brand: draft.brand,
      });
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const uploadImage = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("image", file);
      await api.post(`/products/${id}/images/`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  const deleteImage = async (imageId: number) => {
    setBusy(true);
    try {
      await api.delete(`/products/${id}/images/${imageId}/`);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const addAttribute = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/products/${id}/attributes/`, { key: attrKey, value: attrValue });
      setAttrKey("");
      setAttrValue("");
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      <Card>
        <SectionTitle>مشخصات محصول</SectionTitle>
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-3">
          <Field label="نام">
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </Field>
          <Field label="قیمت (تومان)">
            <Input
              type="number"
              min="0"
              value={draft.price}
              onChange={(e) => setDraft({ ...draft, price: e.target.value })}
            />
          </Field>
          <Field
            label="موجودی انبار"
            hint={
              product.reserved_quantity > 0
                ? `${fa(product.reserved_quantity)} تا برای سفارش‌های پرداخت‌نشده رزرو شده، پس ${fa(
                    product.available_quantity,
                  )} تا قابل فروش است.`
                : "همین عدد قابل فروش است؛ با تأیید هر سفارش خودکار کم می‌شود."
            }
          >
            <Input
              type="number"
              min="0"
              value={draft.stock_quantity}
              onChange={(e) =>
                setDraft({ ...draft, stock_quantity: Number(e.target.value) || 0 })
              }
            />
          </Field>
          <Field label="برند">
            <Input
              value={draft.brand}
              onChange={(e) => setDraft({ ...draft, brand: e.target.value })}
            />
          </Field>
          <div className="sm:col-span-3">
            <Field label="توضیحات">
              <TextArea
                rows={3}
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
          </div>
          <div>
            <Button type="submit" disabled={busy}>
              <Icon name="check" size={15} />
              ذخیره تغییرات
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <SectionTitle>تصاویر محصول</SectionTitle>
          <label className="u-btn u-btn-primary u-btn-sm cursor-pointer">
            <Icon name="upload" size={15} />
            آپلود تصویر
            <input type="file" accept="image/*" className="hidden" onChange={uploadImage} />
          </label>
        </div>
        {product.images.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            تصویری آپلود نشده — برای تحلیل بصری AI حداقل یک عکس اضافه کنید.
          </p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {product.images.map((img) => (
              <div key={img.id} className="group relative">
                <img
                  src={img.image}
                  alt={img.alt_text || product.name}
                  className="h-28 w-28 rounded-xl object-cover"
                  style={{ border: "1px solid var(--line)" }}
                />
                <button
                  onClick={() => void deleteImage(img.id)}
                  className="u-btn u-btn-danger absolute top-1.5 left-1.5 opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
                  style={{ padding: 5, borderRadius: 8 }}
                  title="حذف تصویر"
                  aria-label="حذف تصویر"
                >
                  <Icon name="x" size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle>ویژگی‌ها</SectionTitle>
        {product.attributes.length > 0 && (
          <ul className="mb-4 space-y-1 text-sm" style={{ color: "var(--text-2)" }}>
            {product.attributes.map((attr) => (
              <li key={attr.id}>
                <span className="font-semibold" style={{ color: "var(--text)" }}>
                  {attr.key}:
                </span>{" "}
                {attr.value}
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={addAttribute} className="flex flex-wrap items-end gap-3">
          <div className="w-40">
            <Field label="عنوان">
              <Input value={attrKey} onChange={(e) => setAttrKey(e.target.value)} required />
            </Field>
          </div>
          <div className="w-56">
            <Field label="مقدار">
              <Input value={attrValue} onChange={(e) => setAttrValue(e.target.value)} required />
            </Field>
          </div>
          <Button type="submit" variant="secondary" disabled={busy}>
            <Icon name="plus" size={15} />
            افزودن
          </Button>
        </form>
      </Card>
    </div>
  );
}
