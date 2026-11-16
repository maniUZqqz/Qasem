import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Button, ErrorBox, Spinner, fa } from "../../components/ui";
import { RenderItem, TemplateRow, bcApi, downloadBlob } from "./api";

/** «قالب‌های پست و استوری با شخصیتِ برند» در استودیوی تصویر: ۱۰ قالبِ آماده؛ یک کلیک می‌سازد و در کتابخانهٔ ادیتورِ عکس می‌نشیند. */
export default function BrandTemplatesCard({ storeId }: { storeId: string }) {
  const nav = useNavigate();
  const [items, setItems] = useState<TemplateRow[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<Record<string, RenderItem>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    bcApi
      .templates(storeId)
      .then((r) => setItems(r.character ? r.items : []))
      .catch(() => setItems([]));
  }, [storeId]);

  if (items === null) return null;
  if (!items.length)
    return (
      <div className="u-card p-4 mb-4" data-testid="brand-templates-empty">
        <b>قالب‌های پست و استوری با شخصیتِ برند</b>
        <p style={{ margin: "6px 0 10px", fontSize: 12.5, color: "var(--text-3)" }}>هنوز شخصیتی نساخته‌اید. با شخصیتِ برند، ۱۰ قالبِ آمادهٔ پست و استوری با لحنِ برند دارید.</p>
        <Link className="u-btn u-btn-secondary u-btn-sm" to={`/stores/${storeId}/brand-character/studio`}>
          ساختنِ شخصیتِ برند
        </Link>
      </div>
    );

  const make = async (t: TemplateRow) => {
    setBusy(t.id);
    setError(null);
    try {
      const r = await bcApi.renderTemplate(storeId, t.id, {});
      setOut((m) => ({ ...m, [t.id]: r }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="u-card p-4 mb-4" data-testid="brand-templates">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <b style={{ color: "var(--text)" }}>قالب‌های پست و استوری با شخصیتِ برند</b>
        <Link className="u-btn u-btn-ghost u-btn-sm" to={`/stores/${storeId}/brand-character/scenes`}>
          ویرایشِ متن و همهٔ ژست‌ها
        </Link>
      </div>
      <p style={{ margin: "4px 0 10px", fontSize: 12.5, color: "var(--text-3)" }}>متنِ حباب از لحنِ برند می‌آید؛ نتیجه در کتابخانهٔ ادیتورِ عکس می‌نشیند.</p>
      {error ? <ErrorBox message={error} /> : null}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((t) => (
          <Button key={t.id} type="button" variant="secondary" size="sm" disabled={busy !== null} onClick={() => void make(t)} title={`${t.size_fa} · ${fa(t.w)}×${fa(t.h)}`}>
            {busy === t.id ? <Spinner size={13} /> : null} {t.fa}
          </Button>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10, marginTop: 10 }}>
        {Object.entries(out).map(([k, r]) =>
          r.asset?.thumb ? (
            <div key={k} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <img src={r.asset.thumb} alt={k} loading="lazy" style={{ width: "100%", borderRadius: 10, border: "1px solid var(--line)" }} />
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                <Button type="button" variant="ghost" size="sm" onClick={() => void downloadBlob(r.urls.download, `${k}.png`)}>
                  دانلود
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/stores/${storeId}/photo-editor?asset=${r.asset!.id}&mode=manual`)}>
                  ادیتورِ عکس
                </Button>
              </div>
            </div>
          ) : null,
        )}
      </div>
    </div>
  );
}
