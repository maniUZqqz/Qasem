import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../api/client";
import { Badge, Button, EmptyState, ErrorBox, Spinner, fa } from "../../../components/ui";
import { LibraryAsset, ProductRow, thumbsApi } from "./api";

/**
 * انتخابِ عکس برای تامنیل: کتابخانهٔ ادیتورِ عکس، آپلودِ تازه، یا عکسِ یک محصول.
 * هر سه یک «عکسِ کتابخانه» (PhotoAsset) می‌سازند و شناسه‌اش به طرح می‌رود.
 */
export default function ImagePicker({
  storeId,
  products,
  title,
  onPick,
  onClose,
}: {
  storeId: string;
  products: ProductRow[];
  title: string;
  onPick: (asset: LibraryAsset) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"library" | "products">("library");
  const [assets, setAssets] = useState<LibraryAsset[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    thumbsApi.library(storeId).then(setAssets).catch((e) => setError(errorMessage(e)));
  }, [storeId]);

  async function upload(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      const res = await thumbsApi.upload(storeId, files);
      if (res.errors.length) setError(res.errors.join(" "));
      if (res.assets.length) {
        setAssets((cur) => [...res.assets, ...(cur ?? [])]);
        onPick(res.assets[0]);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function fromProduct(p: ProductRow) {
    setBusy(true);
    setError(null);
    try {
      onPick(await thumbsApi.importRef(storeId, p.image_ref));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const withImages = products.filter((p) => p.image_ref);

  return (
    <div className="th-modal" role="dialog" aria-modal="true" aria-label={title}>
      <div className="th-modal-box">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-extrabold" style={{ color: "var(--text)" }}>{title}</h3>
          <Button size="sm" variant="ghost" onClick={onClose}>بستن</Button>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button type="button" className="dz-tab" aria-selected={tab === "library"} onClick={() => setTab("library")}>کتابخانهٔ عکس‌ها</button>
          <button type="button" className="dz-tab" aria-selected={tab === "products"} onClick={() => setTab("products")}>عکسِ محصول‌ها</button>
          <span className="flex-1" />
          <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => void upload(Array.from(e.target.files ?? []))} />
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? "در حالِ بارگذاری…" : "آپلودِ عکسِ تازه"}
          </Button>
        </div>
        <ErrorBox message={error} />
        {tab === "library" ? (
          assets === null ? (
            <Spinner size={18} />
          ) : assets.length === 0 ? (
            <EmptyState icon="image" title="کتابخانه خالی است" description="یک عکس آپلود کنید؛ برای «چهرهٔ بزرگ» بهتر است پس‌زمینه‌اش شفاف باشد (یا بعداً «حذفِ پس‌زمینه» را بزنید)." />
          ) : (
            <div className="th-pick-grid">
              {assets.map((a) => (
                <button key={a.id} type="button" className="th-pick" onClick={() => onPick(a)} title={a.title}>
                  {a.thumb ? <img src={a.thumb} alt={a.title} loading="lazy" /> : <span className="dz-noimg" />}
                  <span className="th-pick-cap">{a.title || `عکس ${fa(a.id)}`}</span>
                  {a.has_alpha && (
                    <span className="th-pick-badge"><Badge tone="ok">شفاف</Badge></span>
                  )}
                </button>
              ))}
            </div>
          )
        ) : withImages.length === 0 ? (
          <EmptyState icon="box" title="هیچ محصولی عکس ندارد" description="در صفحهٔ هر محصول عکس بگذارید." />
        ) : (
          <div className="th-pick-grid">
            {withImages.map((p) => (
              <button key={p.id} type="button" className="th-pick" onClick={() => void fromProduct(p)} disabled={busy}>
                <span className="dz-noimg" style={{ display: "grid", placeItems: "center", color: "var(--text-3)", fontSize: 12, padding: 8 }}>
                  {p.name}
                </span>
                <span className="th-pick-cap">{p.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
