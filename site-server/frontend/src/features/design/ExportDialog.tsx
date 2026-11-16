import { useCallback, useEffect, useState } from "react";

import Icon from "../../components/Icon";
import { Alert, Badge, Button, Select, Spinner } from "../../components/ui";
import { Check, Doc, ExportRow, Overview, apiError, designApi, downloadBlob, fa, sizeText } from "./api";
import { ChecksPanel } from "./parts";

const SINGLE: Record<string, string[]> = {
  catalog: ["print_pdf", "screen_pdf", "png_zip", "jpg_zip", "pptx"],
  deck: ["pptx", "ppsx", "screen_pdf", "png_zip", "jpg_zip"],
  ui: ["png_zip", "svg_zip", "screen_pdf", "tokens"],
};
const PRE: Record<string, string> = { print_pdf: "بلید ۳ میلی‌متر + علامت برش + عکس ۳۰۰ dpi + متنِ منحنی (فونت لازم نیست)", screen_pdf: "کم‌حجم، با فهرستِ کلیک‌پذیر و نشانک", png_zip: "هر صفحه یک PNG", jpg_zip: "هر صفحه یک JPG",
  pptx: "قابل‌ویرایش در PowerPoint و Google Slides؛ متنِ زنده راست‌به‌چپ", ppsx: "مستقیم به‌صورتِ نمایش باز می‌شود", svg_zip: "SVG با متنِ منحنی؛ در Figma و Inkscape باز می‌شود", tokens: "متغیرهای CSS و JSON (روشن/تیره)" };

function ExportItem({ storeId, e, onChange }: { storeId: string; e: ExportRow; onChange: (r: ExportRow) => void }) {
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className={`ds-exp is-${e.state.toLowerCase()}`}>
      <div className="ds-exp-main">
        <b>{e.label}</b>
        <span className="ds-muted">{e.state === "READY" ? `${sizeText(e.size_bytes)} · ${e.filename}` : e.state === "FAILED" ? e.error : e.message || "در حالِ ساخت…"}</span>
        {(e.state === "QUEUED" || e.state === "RUNNING") ? <progress max={1} value={Math.max(0.03, e.progress)} /> : null}
        {e.kind === "mp4" && e.state === "RUNNING" && e.info?.node?.message ? <span className="ds-muted">{String(e.info.node.message)}</span> : null}
        {e.state === "READY" && e.info?.encoder ? <span className="ds-muted">رمزگذاری: {e.info.encoder === "h264_nvenc" ? "کارتِ گرافیک (NVENC)" : "پردازنده"}</span> : null}
        {err ? <span className="ds-warn">{err}</span> : null}
      </div>
      <div className="ds-row">
        {e.state === "READY" ? (
          <Button size="sm" type="button" onClick={() => downloadBlob(`/stores/${storeId}/design/exports/${e.id}/download/`, e.filename).catch((x) => setErr(apiError(x)))}><Icon name="download" size={14} /> دانلود</Button>
        ) : null}
        {e.state === "FAILED" || e.state === "READY" ? (
          <Button size="sm" variant="ghost" type="button" onClick={() => designApi.deleteExport(storeId, e.id).then(() => onChange(e)).catch((x) => setErr(apiError(x)))} aria-label="حذف"><Icon name="trash" size={14} /></Button>
        ) : null}
      </div>
    </div>
  );
}

export default function ExportDialog({ storeId, doc, ov, checks, onClose }: { storeId: string; doc: Doc; ov: Overview; checks: Check[]; onClose: () => void }) {
  const [rows, setRows] = useState<ExportRow[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opts, setOpts] = useState({ bleed: true, marks: true, dpi: 150, scale: 1 });
  const [video, setVideo] = useState({ seconds: 5, transition: "fade" });
  const kind = doc.kind;

  const load = useCallback(async () => {
    try {
      setRows(await designApi.exports(storeId, doc.id));
    } catch (e) {
      setError(apiError(e));
    }
  }, [storeId, doc.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const active = rows.some((r) => r.state === "QUEUED" || r.state === "RUNNING");
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(t);
  }, [active, load]);

  const start = async (k: string, params: Record<string, unknown> = {}) => {
    setBusy(k);
    setError(null);
    try {
      const r = await designApi.startExport(storeId, doc.id, k, params);
      setRows((x) => [r, ...x.filter((y) => y.id !== r.id)]);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setBusy(null);
    }
  };
  const startVideo = async () => {
    setBusy("mp4");
    setError(null);
    try {
      const r = await designApi.video(storeId, doc.id, video);
      setRows((x) => [r.export, ...x]);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setBusy(null);
    }
  };
  const paramsFor = (k: string): Record<string, unknown> => {
    if (k === "print_pdf") return { bleed: opts.bleed, marks: opts.marks, dpi: 300 };
    if (k === "png_zip" || k === "jpg_zip") return kind === "catalog" ? { dpi: opts.dpi } : { scale: opts.scale };
    return {};
  };

  return (
    <div className="ds-modal" role="dialog" aria-modal="true" aria-label="خروجی">
      <div className="ds-modal-card">
        <div className="ds-modal-head">
          <h2>خروجی و تحویل</h2>
          <Button variant="ghost" size="sm" type="button" onClick={onClose} aria-label="بستن"><Icon name="x" size={16} /></Button>
        </div>
        {error ? <Alert tone="bad">{error}</Alert> : null}

        <section>
          <h3>کدام فایل را به چه کسی بده؟</h3>
          <p className="ds-muted">«قاعدهٔ ۱: سورس را نگه دار. قاعدهٔ ۲: به دیگران خروجی بده.» هر کارت یک بستهٔ ZIP با راهنمای فارسی می‌سازد.</p>
          <div className="ds-recips">
            {ov.recipients.filter((r) => r.doc_kinds.includes(kind)).map((r) => (
              <div key={r.key} className="ds-recip">
                <b>{r.title}</b>
                <span>{r.what}</span>
                {r.note ? <small>{r.note}</small> : null}
                <Button size="sm" type="button" disabled={busy === r.pack} onClick={() => start(r.pack, r.pack === "pack_printer" ? { dpi: 300 } : {})}>{busy === r.pack ? <Spinner size={14} /> : <Icon name="download" size={14} />} ساختِ بسته</Button>
              </div>
            ))}
          </div>
        </section>

        {kind === "catalog" ? <section><ChecksPanel checks={checks} title="چک‌لیستِ چاپخانه" /><p className="ds-muted">رنگ‌ها RGB است؛ CMYK و PDF/X واقعی را چاپخانه از همین PDF می‌سازد (از او بپرس کدام نسخه را می‌خواهد).</p></section> : null}

        <section>
          <h3>فایل‌های تکی</h3>
          <div className="ds-opts">
            {kind === "catalog" ? (
              <>
                <label className="ds-check-row"><input type="checkbox" checked={opts.bleed} onChange={(e) => setOpts({ ...opts, bleed: e.target.checked })} /> بلید ۳ میلی‌متر</label>
                <label className="ds-check-row"><input type="checkbox" checked={opts.marks} onChange={(e) => setOpts({ ...opts, marks: e.target.checked })} /> علامتِ برش</label>
                <label className="ds-field"><span>کیفیتِ PNG/JPG</span><Select value={opts.dpi} onChange={(e) => setOpts({ ...opts, dpi: Number(e.target.value) })}><option value={72}>۷۲ dpi (وب)</option><option value={150}>۱۵۰ dpi</option><option value={300}>۳۰۰ dpi (چاپ)</option></Select></label>
              </>
            ) : (
              <label className="ds-field"><span>مقیاسِ PNG/JPG</span><Select value={opts.scale} onChange={(e) => setOpts({ ...opts, scale: Number(e.target.value) })}><option value={1}>۱×</option><option value={2}>۲× (شفاف‌تر)</option></Select></label>
            )}
          </div>
          <div className="ds-singles">
            {SINGLE[kind].map((k) => (
              <div key={k} className="ds-single">
                <div><b>{ov.exports[k]?.label ?? k}</b><span className="ds-muted">{PRE[k]}</span></div>
                <Button size="sm" variant="secondary" type="button" disabled={busy === k} onClick={() => start(k, paramsFor(k))}>{busy === k ? <Spinner size={14} /> : "بساز"}</Button>
              </div>
            ))}
          </div>
        </section>

        {kind === "deck" ? (
          <section>
            <h3>ویدیو از ارائه (MP4)</h3>
            <p className="ds-muted">اسلایدها روی کارتِ گرافیکِ سرورِ پردازش به ویدیو تبدیل می‌شوند؛ اگر سرور خاموش است، درخواست در صفِ ماندگار می‌ماند و با روشن شدنش ساخته می‌شود.</p>
            <div className="ds-opts">
              <label className="ds-field"><span>مدتِ هر اسلاید</span><Select value={video.seconds} onChange={(e) => setVideo({ ...video, seconds: Number(e.target.value) })}>{[3, 4, 5, 6, 8, 10].map((s) => <option key={s} value={s}>{fa(s)} ثانیه</option>)}</Select></label>
              <label className="ds-field"><span>گذار</span><Select value={video.transition} onChange={(e) => setVideo({ ...video, transition: e.target.value })}><option value="fade">محو</option><option value="fadeblack">محو از سیاه</option><option value="slideleft">لغزش به چپ</option><option value="slideright">لغزش به راست</option><option value="wipeleft">پاک‌کردن</option><option value="dissolve">حل‌شدن</option><option value="none">بدونِ گذار</option></Select></label>
              <Button type="button" disabled={busy === "mp4"} onClick={startVideo}>{busy === "mp4" ? <Spinner size={14} /> : <Icon name="film" size={14} />} ساختِ ویدیو</Button>
            </div>
          </section>
        ) : null}

        <section>
          <h3>ساخته‌شده‌ها {active ? <Spinner size={14} /> : null}</h3>
          {!rows.length ? <p className="ds-muted">هنوز خروجی نساخته‌ای.</p> : null}
          {rows.filter((r) => r.id > 0).map((r) => <ExportItem key={r.id} storeId={storeId} e={r} onChange={() => void load()} />)}
          {rows.some((r) => r.doc_rev !== doc.rev && r.state === "READY") ? <Badge tone="warn">بعضی خروجی‌ها پیش از آخرین ویرایش ساخته شده‌اند</Badge> : null}
        </section>
      </div>
    </div>
  );
}
