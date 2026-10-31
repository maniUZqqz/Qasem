/** گامِ اولِ کاربرِ تازه‌کار: انتخابِ قالب؛ بعدش مستقیم داخلِ ویرایشگر. */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, pUrl, studioError } from "../api";
import type { Catalog } from "./doc";
import { StarterGrid } from "./panels";
import type { PageRow, StarterT } from "./types";
import "./builder.css";

type CatalogResp = { catalog: Catalog; starters: StarterT[]; pages: PageRow[]; project: { name: string; has_cart: boolean } };

export default function StartPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<CatalogResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .get<CatalogResp>(`/studio/projects/${slug}/builder/catalog/`)
      .then((r) => setData(r.data))
      .catch((err) => setError(studioError(err)));
  }, [slug]);

  async function pick(s: StarterT) {
    if (!data) return;
    setBusy(true);
    setError(null);
    try {
      const existing = s.slug === "" ? data.pages.find((p) => p.slug === "") : undefined;
      if (existing) {
        // فروشگاهِ آماده از قبل صفحهٔ اصلی دارد: همان را با قالب پر می‌کنیم
        await api.post(`/studio/projects/${slug}/builder/pages/${existing.id}/starter/`, { starter: s.key, setup_chrome: true });
        navigate(pUrl(slug, `builder/page/${existing.id}`));
      } else {
        const { data: d } = await api.post<{ page: { id: number } }>(`/studio/projects/${slug}/builder/pages/`, { starter: s.key, setup_chrome: true });
        navigate(pUrl(slug, `builder/page/${d.page.id}`));
      }
    } catch (err) {
      setError(studioError(err));
      setBusy(false);
    }
  }

  return (
    <div className="nbe nbe-start" dir="rtl" data-testid="start-page">
      <div className="nbe-start-in">
        <h1>{data ? `«${data.project.name}» را از کجا شروع کنیم؟` : "…"}</h1>
        <p>یک قالب انتخاب کن. بعد هر متن و تصویری را مستقیم روی صفحه عوض می‌کنی؛ همه‌چیز با کشیدن و زدن.</p>
        {error && <p className="nbe-warn">{error}</p>}
        {data && <StarterGrid starters={data.starters} icons={data.catalog.icons} onPick={(s) => void pick(s)} busy={busy} hasCart={data.project.has_cart} />}
      </div>
    </div>
  );
}
