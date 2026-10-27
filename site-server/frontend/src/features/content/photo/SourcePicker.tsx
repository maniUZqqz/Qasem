import { useEffect, useState } from "react";

import { errorMessage } from "../../../api/client";
import { Badge, Button, EmptyState, ErrorBox, Spinner, fa } from "../../../components/ui";
import { Asset, Sources, photoApi } from "./api";

/** عکس‌هایی که از قبل در فروشگاه هست ⇐ کتابخانهٔ ادیتور (کپیِ ثابت؛ اصل دست نمی‌خورد). */
export default function SourcePicker({
  storeId,
  mode,
  onDone,
  onClose,
}: {
  storeId: string;
  mode: "products" | "generated";
  onDone: (assets: Asset[], errors: string[]) => void;
  onClose: () => void;
}) {
  const [sources, setSources] = useState<Sources | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    photoApi.sources(storeId).then(setSources).catch((e) => setError(errorMessage(e)));
  }, [storeId]);

  const toggle = (ref: string) =>
    setPicked((cur) => (cur.includes(ref) ? cur.filter((r) => r !== ref) : [...cur, ref]));

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const data = await photoApi.importRefs(storeId, picked);
      onDone(data.assets, data.errors);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const tile = (ref: string, url: string, caption: string, imported: boolean) => (
    <button
      key={ref}
      type="button"
      onClick={() => toggle(ref)}
      className="relative overflow-hidden rounded-lg text-start"
      style={{ border: `2px solid ${picked.includes(ref) ? "var(--brand)" : "var(--line)"}` }}
      data-ref={ref}
    >
      <img src={url} alt={caption} loading="lazy" className="h-24 w-full object-cover" />
      <span className="block truncate px-1 py-0.5 text-[11px]" style={{ color: "var(--text-2)" }}>
        {caption}
      </span>
      {imported && (
        <span className="absolute left-1 top-1">
          <Badge tone="info">در کتابخانه</Badge>
        </span>
      )}
      {picked.includes(ref) && (
        <span
          className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-full text-xs"
          style={{ background: "var(--brand)", color: "white" }}
        >
          ✓
        </span>
      )}
    </button>
  );

  let body;
  if (!sources) body = error ? null : <Spinner size={18} />;
  else if (mode === "products") {
    const withImages = sources.products.filter((p) => p.images.length > 0);
    body = withImages.length ? (
      <div className="flex flex-col gap-3">
        {withImages.map((p) => (
          <div key={p.id}>
            <div className="mb-1 text-sm font-medium" style={{ color: "var(--text)" }}>{p.name}</div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {p.images.map((i) => tile(i.ref, i.url, `عکسِ ${fa(i.id)}`, i.imported))}
            </div>
          </div>
        ))}
      </div>
    ) : (
      <EmptyState icon="box" title="هیچ محصولی عکس ندارد" description="در صفحهٔ هر محصول عکس بگذارید." />
    );
  } else {
    body = sources.generated.length ? (
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {sources.generated.map((g) => tile(g.ref, g.url, `${g.product_name} — ${g.kind_label}`, g.imported))}
      </div>
    ) : (
      <EmptyState icon="image" title="هنوز تصویری ساخته نشده" description="از «استودیو تصویر» ِ هر محصول بسازید." />
    );
  }

  return (
    <div className="mt-3 rounded-xl p-3" style={{ border: "1px solid var(--line)", background: "var(--surface-2)" }}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {mode === "products" ? "عکس‌های محصول‌ها" : "تصویرهای ساخته‌شده"}
        </span>
        <div className="flex gap-2">
          <Button size="sm" onClick={add} disabled={busy || picked.length === 0}>
            {busy ? "در حالِ افزودن…" : `افزودن ${fa(picked.length)} عکس به کتابخانه`}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>
            بستن
          </Button>
        </div>
      </div>
      <ErrorBox message={error} />
      {body}
    </div>
  );
}
