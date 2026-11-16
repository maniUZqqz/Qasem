import { useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import { Button, Select, Spinner } from "../../components/ui";
import { bcApi } from "./api";

type StoreRow = { id: number; name: string };

/** در سایت‌ساز، بلوکِ «سربرگِ شخصیتِ برند»: تصویر (در رسانهٔ همین پروژه)، تیتر، توضیح و حباب از شخصیتِ فروشگاه پر می‌شود و پروژه به آن فروشگاه بسته می‌شود. */
export default function BrandHeroFill({ slug, onApply }: { slug: string; onApply: (props: Record<string, unknown>) => void }) {
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [store, setStore] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<StoreRow[] | { results: StoreRow[] }>("/stores/")
      .then((r) => {
        const rows = Array.isArray(r.data) ? r.data : r.data.results ?? [];
        setStores(rows);
        setStore((cur) => cur || String(rows[0]?.id ?? ""));
      })
      .catch(() => setStores([]));
  }, []);

  const go = async () => {
    if (!store) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await bcApi.useSiteHero(store, { project_slug: slug, pose: "wave" });
      onApply({ image: r.image, image_alt: r.image_alt, title: r.title, subtitle: r.subtitle, bubble: r.bubble });
      setMsg(r.bound ? "پر شد؛ پروژه هم به این فروشگاه بسته شد (متنِ هوش مصنوعیِ سایت با لحنِ برند نوشته می‌شود)." : "پر شد.");
    } catch (e) {
      setMsg(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="nbe-note" data-testid="brand-hero-fill" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <b>از شخصیتِ برند پر کن</b>
      <Select value={store} onChange={(e) => setStore(e.target.value)} aria-label="فروشگاه">
        {stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </Select>
      <Button type="button" size="sm" onClick={() => void go()} disabled={busy || !store}>
        {busy ? <Spinner size={13} /> : null} تصویر، تیتر و حباب را بگذار
      </Button>
      {msg ? <span>{msg}</span> : null}
    </div>
  );
}
