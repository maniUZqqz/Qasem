import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { fa } from "./api";
import "../tools/studio/c21st.css";

/**
 * قطعه‌های آمادهٔ 21st.dev در «استودیوی طراحی» (جست‌وجو، پیش‌نمایش، درج): همان کاتالوگِ سایت‌ساز (فقط مجوزِ آزاد + تبدیل‌شده به HTMLِ امن).
 * پیش‌نمایش در iframe ِ بی‌اسکریپت (srcdoc) با پوستهٔ خنثی؛ «افزودن» یک بلوکِ c21 در فریمِ فعلی می‌گذارد؛ «ساختِ سایت از طرح» همان را با
 * ظاهرِ کاملش در سایت‌ساز می‌آورد (مجوز و مبدأ همراهِ قطعه می‌ماند).
 */
type Item = { id: string; title: string; library: string; author: string; license: string; cats: string[]; conv_key: string; description: string; preview: boolean };
type Cat = { key: string; label: string; count: number };
type Listing = { items: Item[]; total: number; categories: Cat[]; insertable: number };

export default function C21Panel({ onAdd }: { onAdd: (node: Record<string, any>, title: string) => unknown }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      api
        .get<Listing>("/studio/c21st/", { params: { q, cat, insertable: 1, page, size: 6 } })
        .then((r) => { if (alive) { setData(r.data); setError(null); } })
        .catch(() => { if (alive) setError("کاتالوگِ قطعه‌ها در دسترس نیست."); });
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [q, cat, page]);

  const togglePreview = async (key: string) => {
    if (open === key) { setOpen(null); setDoc(null); return; }
    setOpen(key);
    setDoc(null);
    try {
      const r = await api.get<{ doc: string }>(`/studio/c21st/preview/${key}/`);
      setDoc(r.data.doc);
    } catch {
      setDoc(null);
      setError("پیش‌نمایشِ این قطعه نیامد.");
    }
  };

  const add = async (it: Item) => {
    setBusy(it.id);
    setNote(null);
    try {
      const r = await api.get<{ block: { type: string; props: Record<string, any> } }>(`/studio/c21st/block/${it.conv_key}/`);
      await onAdd({ t: "block", type: r.data.block.type, props: r.data.block.props, style: {} }, it.title);
      setNote(`«${it.title}» به طرح اضافه شد؛ در سایتِ ساخته‌شده با ظاهرِ کاملش می‌آید.`);
    } catch {
      setError("افزودنِ این قطعه نشد.");
    } finally {
      setBusy(null);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / 6)) : 1;
  return (
    <div className="ds-c21" data-testid="ds-c21">
      <div className="c21-filters">
        <input className="c21-input" type="search" placeholder="جست‌وجو (مثلاً pricing، faq، hero)" aria-label="جست‌وجوی قطعه‌های 21st.dev" value={q}
               onChange={(e) => { setQ(e.target.value); setPage(1); }} data-testid="ds-c21-q" />
        <select className="c21-input" aria-label="دسته" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }}>
          <option value="">همهٔ دسته‌ها</option>
          {(data?.categories ?? []).map((c) => <option key={c.key} value={c.key}>{c.label} ({fa(c.count)})</option>)}
        </select>
      </div>
      <p className="c21-note">{data ? `${fa(data.total)} قطعهٔ قابلِ درج (مجوزِ آزاد، تبدیل‌شده)` : "در حالِ خواندن…"}</p>
      {error ? <p className="c21-warn" role="alert">{error}</p> : null}
      {note ? <p className="c21-note" role="status">{note}</p> : null}
      {data && !data.items.length ? <p className="c21-note">قطعه‌ای با این جست‌وجو پیدا نشد.</p> : null}
      {(data?.items ?? []).map((it) => (
        <div key={it.id} className="c21-item" data-c21={it.id}>
          <div className="c21-head">
            <b className="c21-title" dir="ltr">{it.title}</b>
            <span className="c21-badge ok">{it.license}</span>
          </div>
          <small className="c21-note" dir="ltr">{it.author}{it.library ? ` · ${it.library}` : ""}</small>
          <div className="c21-actions">
            <button type="button" className="c21-link" onClick={() => void togglePreview(it.conv_key)} data-testid="ds-c21-preview">{open === it.conv_key ? "بستنِ پیش‌نمایش" : "پیش‌نمایش"}</button>
            <button type="button" className="c21-btn" disabled={busy !== null} onClick={() => void add(it)} data-testid="ds-c21-add">افزودن به طرح</button>
          </div>
          {open === it.conv_key ? (
            doc ? <iframe title={`پیش‌نمایشِ ${it.title}`} sandbox="" srcDoc={doc} className="c21-frame" style={{ width: "100%", height: 260, border: "1px solid var(--line)", borderRadius: 8, background: "#fff" }} />
                : <p className="c21-note">در حالِ خواندن…</p>
          ) : null}
        </div>
      ))}
      {data && pages > 1 ? (
        <div className="c21-actions">
          <button type="button" className="c21-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>قبلی</button>
          <small className="c21-note">{fa(page)} از {fa(pages)}</small>
          <button type="button" className="c21-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>بعدی</button>
        </div>
      ) : null}
    </div>
  );
}
