import { useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../../../../api/client";
import { fa } from "../../../../../components/ui";
import type { Asset, Preset } from "../../api";
import { proApi } from "../../api";
import "../../designer/designer.css";

/**
 * «کارهای چندعکسی» (دورِ ۸): شیتِ تماس، ادغامِ HDR، پانوراما، پردازشگرِ تصویر (چند اندازه) و اجرای اکشن روی چند عکس.
 * عکس‌ها را از کتابخانهٔ فروشگاه تیک می‌زنید؛ نتیجه (به‌جز پردازشگر که zip است) یک عکسِ تازه در کتابخانه می‌شود و باز می‌شود.
 */
export type MultiMode = "sheet" | "hdr" | "pano" | "proc" | "action";

const META: Record<MultiMode, { title: string; hint: string; min: number; max: number; run: string }> = {
  sheet: { title: "شیتِ تماس", hint: "چند عکس را در یک صفحهٔ شبکه‌ای (با نام زیرِ هر عکس) می‌چیند؛ برای کاتالوگ و مرورِ سریع.", min: 1, max: 60, run: "ساختِ شیتِ تماس" },
  hdr: { title: "ادغامِ HDR (چند نوردهی)", hint: "۲ تا ۷ عکسِ هم‌کادر با نوردهیِ متفاوت (تیره، میانه، روشن) را به یک عکسِ متعادل تبدیل می‌کند؛ لرزشِ جزئیِ دست جبران می‌شود.", min: 2, max: 7, run: "ادغامِ نوردهی‌ها" },
  pano: { title: "پانوراما (دوختنِ چند عکس)", hint: "۲ تا ۶ عکسِ چپ‌به‌راست با ۲۰ تا ۴۰٪ منظرهٔ مشترک را به یک عکسِ پهن می‌دوزد؛ حاشیهٔ سیاه خودکار بریده می‌شود. ممکن است ۱۰ تا ۳۰ ثانیه طول بکشد.", min: 2, max: 6, run: "دوختنِ پانوراما" },
  proc: { title: "پردازشگرِ تصویر (چند اندازه)", hint: "هر عکسِ انتخاب‌شده را در همهٔ اندازه‌های تیک‌خورده می‌سازد و همه را در یک فایلِ zip می‌دهد (حداکثر ۸ عکس × ۶ اندازه در هر بار).", min: 1, max: 8, run: "ساختِ فایلِ zip" },
  action: { title: "اجرای اکشن روی چند عکس", hint: "اکشنِ ذخیره‌شده (نور و رنگ، برش، متن، لوگو و لایه‌های بی‌پیکسل) را روی هر عکسِ انتخاب‌شده اجرا می‌کند؛ برای هر عکس یک نسخهٔ تازه در کتابخانه ساخته می‌شود و اصل دست‌نخورده می‌ماند.", min: 1, max: 40, run: "اجرا روی عکس‌ها" },
};

const SIZES: { id: string; w: number; h: number; label: string }[] = [
  { id: "insta", w: 1080, h: 1080, label: "اینستاگرام مربع ۱۰۸۰×۱۰۸۰" },
  { id: "post", w: 1080, h: 1350, label: "پستِ عمودی ۱۰۸۰×۱۳۵۰" },
  { id: "story", w: 1080, h: 1920, label: "استوری ۱۰۸۰×۱۹۲۰" },
  { id: "banner", w: 1200, h: 630, label: "بنرِ وب و تلگرام ۱۲۰۰×۶۳۰" },
  { id: "market", w: 2000, h: 2000, label: "بازار و فروشگاه ۲۰۰۰×۲۰۰۰" },
  { id: "w800", w: 800, h: 0, label: "پهنای ۸۰۰ (ارتفاع آزاد)" },
  { id: "thumb", w: 400, h: 400, label: "بندانگشتی ۴۰۰×۴۰۰" },
];

export default function MultiDialog({ storeId, mode, assets, currentId, onClose, onOpenAsset, onNotice }: {
  storeId: string; mode: MultiMode; assets: Asset[]; currentId: number;
  onClose: () => void; onOpenAsset: (a: Asset) => void; onNotice: (text: string, tone?: "info" | "bad") => void;
}) {
  const m = META[mode];
  const [sel, setSel] = useState<number[]>([currentId]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [cols, setCols] = useState(5);
  const [cell, setCell] = useState(300);
  const [labels, setLabels] = useState(true);
  const [bg, setBg] = useState("#ffffff");
  const [sizeIds, setSizeIds] = useState<string[]>(["insta"]);
  const [custom, setCustom] = useState("");
  const [fmt, setFmt] = useState("jpeg");
  const [fit, setFit] = useState("contain");
  const [quality, setQuality] = useState(90);
  const [noUp, setNoUp] = useState(true);
  const [acts, setActs] = useState<Preset[] | null>(null);
  const [actId, setActId] = useState(0);
  const [prog, setProg] = useState<{ done: number; total: number; failed: string[] } | null>(null);
  const cancel = useRef(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, busy]);
  useEffect(() => {
    if (mode !== "action") return;
    let live = true;
    proApi.presets(storeId).then((l) => {
      if (!live) return;
      const a = l.filter((p) => p.kind === "action");
      setActs(a);
      if (a[0]) setActId(a[0].id);
    }).catch(() => live && setActs([]));
    return () => {
      live = false;
    };
  }, [mode, storeId]);

  const shown = useMemo(() => assets.slice(0, 200), [assets]);
  const toggle = (id: number) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= m.max ? s : [...s, id]));
  const customSizes = useMemo(() => {
    const out: { w: number; h: number }[] = [];
    for (const part of custom.split(/[,،\n]/)) {
      const mm = /^\s*(\d{2,4})\s*[x×*]\s*(\d{0,4})\s*$/i.exec(part.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))));
      if (mm) out.push({ w: Number(mm[1]), h: Number(mm[2] || 0) });
    }
    return out;
  }, [custom]);
  const sizes = useMemo(() => [...SIZES.filter((s) => sizeIds.includes(s.id)).map((s) => ({ w: s.w, h: s.h })), ...customSizes].slice(0, 6), [sizeIds, customSizes]);

  const ready = sel.length >= m.min && sel.length <= m.max && !busy && (mode !== "action" || actId > 0) && (mode !== "proc" || sizes.length > 0);

  const run = async () => {
    if (!ready) return;
    setErr("");
    cancel.current = false;
    try {
      if (mode === "sheet") {
        setBusy("در حالِ چیدنِ شیتِ تماس…");
        const a = await proApi.multiSheet(storeId, { assets: sel, cols, cell, labels, bg });
        onNotice(`«${a.title}» ساخته شد و باز می‌شود.`);
        onOpenAsset(a);
        onClose();
      } else if (mode === "hdr" || mode === "pano") {
        setBusy(mode === "hdr" ? "در حالِ ادغامِ نوردهی‌ها…" : "در حالِ دوختنِ پانوراما (چند ثانیه صبر کنید)…");
        const a = await proApi.multiMerge(storeId, sel, mode === "hdr" ? "hdr" : "panorama");
        onNotice(`«${a.title}» ساخته شد و باز می‌شود.`);
        onOpenAsset(a);
        onClose();
      } else if (mode === "proc") {
        setBusy("در حالِ ساختنِ اندازه‌ها…");
        const r = await proApi.multiProcessor(storeId, { assets: sel, sizes, fmt, quality, fit, no_upscale: noUp });
        const url = URL.createObjectURL(r.blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "photos-sizes.zip";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 4000);
        onNotice(`فایلِ zip با ${fa(r.count)} تصویر دانلود شد.`);
        onClose();
      } else {
        const failed: string[] = [];
        let last: Asset | null = null;
        for (let i = 0; i < sel.length; i++) {
          if (cancel.current) break;
          setProg({ done: i, total: sel.length, failed });
          setBusy(`عکسِ ${fa(i + 1)} از ${fa(sel.length)}…`);
          try {
            last = await proApi.multiAction(storeId, actId, sel[i]);
          } catch (e) {
            failed.push(`${assets.find((x) => x.id === sel[i])?.title ?? sel[i]}: ${errorMessage(e)}`);
          }
        }
        setProg({ done: sel.length, total: sel.length, failed });
        const ok = sel.length - failed.length;
        onNotice(`اکشن روی ${fa(ok)} عکس اجرا شد و نسخه‌های تازه در کتابخانه‌اند${failed.length ? ` (${fa(failed.length)} عکس ناموفق)` : ""}.`, failed.length && !ok ? "bad" : "info");
        if (!failed.length && last) {
          onOpenAsset(last);
          onClose();
        }
      }
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()} data-testid="multi-dialog" data-mode={mode}>
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label={m.title} tabIndex={-1} ref={root} dir="rtl" style={{ width: "min(720px, 100%)", maxHeight: "92vh", overflow: "auto" }}>
        <div className="fx-head"><b>{m.title}</b><button type="button" className="fx-x" onClick={onClose} disabled={!!busy} aria-label="بستن">✕</button></div>
        <div style={{ padding: 14, display: "grid", gap: 12 }}>
          <p className="ws-muted" style={{ fontSize: 12, margin: 0 }}>{m.hint}</p>

          {mode === "action" && (
            <label className="fx-row">
              <span>اکشن</span>
              {acts === null ? <span className="ws-muted">در حالِ بارگذاری…</span>
                : acts.length === 0 ? <span className="ws-muted" data-testid="multi-no-actions">اکشنی ذخیره نشده؛ در «ویرایش ‹ اکشن (ضبط و اجرا)» یکی بسازید و ذخیره کنید.</span>
                : <select value={actId} onChange={(e) => setActId(Number(e.target.value))} data-testid="multi-action">{acts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>}
            </label>
          )}

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6 }}>
              <b>عکس‌ها ({fa(sel.length)} انتخاب‌شده؛ {m.min === m.max ? `${fa(m.min)} عدد` : `${fa(m.min)} تا ${fa(m.max)}`})</b>
              <span>
                <button type="button" className="ws-chip" onClick={() => setSel(shown.slice(0, m.max).map((a) => a.id))} disabled={!!busy}>انتخابِ همه</button>{" "}
                <button type="button" className="ws-chip" onClick={() => setSel([])} disabled={!!busy}>هیچ</button>
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(86px, 1fr))", gap: 6, maxHeight: 220, overflow: "auto", padding: 2 }} role="listbox" aria-multiselectable="true" aria-label="عکس‌های فروشگاه">
              {shown.map((a) => {
                const on = sel.includes(a.id);
                return (
                  <button key={a.id} type="button" role="option" aria-selected={on} onClick={() => toggle(a.id)} title={a.title} data-testid="multi-photo" data-on={on ? "1" : "0"}
                    style={{ position: "relative", padding: 0, border: on ? "2px solid var(--accent, #6366f1)" : "2px solid transparent", borderRadius: 8, overflow: "hidden", background: "var(--bg-2, #f3f4f6)", cursor: "pointer", aspectRatio: "1 / 1" }}>
                    <img src={a.thumb} alt="" loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                    {on && <span style={{ position: "absolute", top: 3, insetInlineStart: 3, background: "var(--accent, #6366f1)", color: "#fff", borderRadius: 10, fontSize: 11, padding: "0 6px" }}>{fa(sel.indexOf(a.id) + 1)}</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {mode === "sheet" && (
            <div style={{ display: "grid", gap: 8 }}>
              <label className="fx-row"><span>ستون‌ها</span><span className="fx-range"><input type="range" min={1} max={10} value={cols} onChange={(e) => setCols(Number(e.target.value))} data-testid="sheet-cols" /><b dir="ltr">{fa(cols)}</b></span></label>
              <label className="fx-row"><span>اندازهٔ هر خانه</span><select value={cell} onChange={(e) => setCell(Number(e.target.value))}>{[160, 240, 300, 400, 500].map((c) => <option key={c} value={c}>{fa(c)} پیکسل</option>)}</select></label>
              <label className="fx-row"><span>زمینه</span><select value={bg} onChange={(e) => setBg(e.target.value)}><option value="#ffffff">سفید</option><option value="#f3f4f6">خاکستریِ روشن</option><option value="#111827">تیره</option></select></label>
              <label className="fx-row"><span>نامِ عکس زیرِ هر خانه</span><input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} data-testid="sheet-labels" /></label>
            </div>
          )}

          {mode === "proc" && (
            <div style={{ display: "grid", gap: 8 }}>
              <div role="group" aria-label="اندازه‌ها" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {SIZES.map((s) => (
                  <label key={s.id} className={`ws-chip${sizeIds.includes(s.id) ? " is-on" : ""}`} style={{ cursor: "pointer" }}>
                    <input type="checkbox" checked={sizeIds.includes(s.id)} onChange={() => setSizeIds((l) => (l.includes(s.id) ? l.filter((x) => x !== s.id) : [...l, s.id]))} style={{ marginInlineEnd: 4 }} data-testid={`proc-size-${s.id}`} />
                    {s.label}
                  </label>
                ))}
              </div>
              <label className="fx-row"><span>اندازهٔ دلخواه</span><input className="u-input" dir="ltr" value={custom} placeholder="مثلاً 1600x900, 500x" onChange={(e) => setCustom(e.target.value)} data-testid="proc-custom" /></label>
              <label className="fx-row"><span>جاگذاری</span><select value={fit} onChange={(e) => setFit(e.target.value)} data-testid="proc-fit"><option value="contain">جا بده (کاملِ عکس بماند)</option><option value="cover">قاب را پر کن (حاشیه بریده شود)</option><option value="width">با پهنا</option><option value="height">با ارتفاع</option></select></label>
              <label className="fx-row"><span>قالب</span><select value={fmt} onChange={(e) => setFmt(e.target.value)}><option value="jpeg">JPEG</option><option value="png">PNG</option><option value="webp">WebP</option></select></label>
              {fmt !== "png" && <label className="fx-row"><span>کیفیت</span><span className="fx-range"><input type="range" min={50} max={98} value={quality} onChange={(e) => setQuality(Number(e.target.value))} /><b dir="ltr">{fa(quality)}</b></span></label>}
              <label className="fx-row"><span>بزرگ‌تر از اصل نشود</span><input type="checkbox" checked={noUp} onChange={(e) => setNoUp(e.target.checked)} /></label>
            </div>
          )}

          {prog && (
            <div role="status" aria-live="polite" data-testid="multi-progress" style={{ fontSize: 12 }}>
              {fa(prog.done)} از {fa(prog.total)} انجام شد
              {prog.failed.length > 0 && <ul style={{ margin: "4px 0 0", paddingInlineStart: 18, color: "var(--danger, #b91c1c)" }}>{prog.failed.slice(0, 5).map((f, i) => <li key={i}>{f}</li>)}</ul>}
            </div>
          )}
          {err && <p role="alert" style={{ color: "var(--danger, #b91c1c)", margin: 0, fontSize: 13 }} data-testid="multi-error">{err}</p>}
          {busy && <p className="ws-muted" style={{ margin: 0, fontSize: 13 }} data-testid="multi-busy">{busy}</p>}
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" disabled={!ready} onClick={() => void run()} data-testid="multi-run">{m.run}</button>
          {busy && mode === "action" ? <button type="button" className="ws-btn" onClick={() => { cancel.current = true; }}>توقف</button> : <button type="button" className="ws-btn" onClick={onClose} disabled={!!busy}>بستن</button>}
        </div>
      </div>
    </div>
  );
}
