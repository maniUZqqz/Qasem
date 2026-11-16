import { useState } from "react";

import { Alert, Button, ErrorBox, Select, Spinner } from "../../components/ui";
import { bcApi, downloadBlob } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import { CharPicker, Section, useNotice } from "./common";

export default function ExportPage() {
  const { id, ov, sel, select } = useBrandChar();
  const [pose, setPose] = useState("stand");
  const [expression, setExpression] = useState("happy");
  const [bg, setBg] = useState("");
  const [crop, setCrop] = useState("full");
  const [busy, setBusy] = useState<string | null>(null);
  const n = useNotice();
  const cid = sel?.id ?? null;
  if (!sel || cid === null) return <Alert tone="info">اول در «استودیوی شخصیت» یک شخصیت بسازید.</Alert>;

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try {
      await fn();
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };
  const nm = sel.name.replace(/\s+/g, "-");
  const svg = () => act("svg", async () => {
    const r = await bcApi.svgFile(id, cid, { pose, expression, background: bg || undefined });
    await downloadBlob(r.urls.download, `${nm}-${pose}.svg`);
    n.ok(r.params.embedded ? "SVG آماده شد؛ این سبک (آدمک‌چوبی) برداری نیست و تصویرِ جاسازی‌شده دارد." : "SVG برداری دانلود شد.");
  });
  const sticker = () => act("sticker", async () => {
    const r = await bcApi.sticker(id, cid, { pose, expression, crop });
    await downloadBlob(r.urls.download, `${nm}-${pose}-sticker.png`);
    n.ok("استیکرِ PNGِ شفاف دانلود شد.");
  });
  const sheet = () => act("sheet", async () => {
    const r = await bcApi.sheet(id, cid);
    await downloadBlob(r.urls.download, `${nm}-model-sheet.png`);
    n.ok("برگهٔ مدل (PNG) دانلود شد.");
  });
  const pdf = () => act("pdf", async () => {
    const r = await bcApi.sheetPdf(id, cid);
    await downloadBlob(r.urls.download, `${nm}-model-sheet.pdf`);
    n.ok("برگهٔ مدل (PDF، سه صفحه) دانلود شد.");
  });
  const zip = () => act("zip", async () => {
    await downloadBlob(bcApi.exportPath(id, cid), `${nm}-brand-character.zip`, "post");
    n.ok("بستهٔ کامل دانلود شد.");
  });

  return (
    <div className="bc-root" data-testid="export-page">
      <Section title="شخصیت"><CharPicker chars={ov.characters} value={cid} onChange={select} /></Section>
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}
      {!sel.locked ? <Alert tone="warn" title="ظاهر هنوز قفل نیست">خروجی‌های نهایی بهتر است از نسخهٔ تأییدشده باشند؛ در «استودیوی شخصیت» «تأییدِ ظاهر» را بزنید.</Alert> : null}

      <Section title="تنظیماتِ خروجی" hint="ژست و حالت برای SVG و استیکر؛ برگه و بسته همهٔ ژست‌ها را دارند.">
        <div className="bc-fields">
          <label className="bc-label">ژست<Select value={pose} onChange={(e) => setPose(e.target.value)}>{ov.options.poses.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}</Select></label>
          <label className="bc-label">حالتِ چهره<Select value={expression} onChange={(e) => setExpression(e.target.value)}>{ov.options.expressions.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}</Select></label>
          <label className="bc-label">پس‌زمینهٔ SVG<Select value={bg} onChange={(e) => setBg(e.target.value)}><option value="">شفاف</option><option value="#ffffff">سفید</option>{sel.brand_colours.concat(ov.store.colors).slice(0, 4).map((c) => <option key={c} value={c}>{c}</option>)}</Select></label>
          <label className="bc-label">برشِ استیکر<Select value={crop} onChange={(e) => setCrop(e.target.value)}>{ov.options.crops.map((c) => <option key={c.key} value={c.key}>{c.fa}</option>)}</Select></label>
        </div>
      </Section>

      <div className="bc-uses">
        <div className="bc-use"><h3>SVG</h3><p>برداریِ ویرایش‌پذیر برای هر نرم‌افزارِ طراحی (سبک‌های تخت، چیبی و استیکر). در سبکِ آدمک‌چوبی تصویرِ جاسازی‌شده است.</p><Button type="button" onClick={() => void svg()} disabled={busy !== null}>{busy === "svg" ? <Spinner size={14} /> : null} دانلودِ SVG</Button></div>
        <div className="bc-use"><h3>استیکرِ PNG شفاف</h3><p>بدونِ پس‌زمینه برای تامنیل، استوری و ویدیو.</p><Button type="button" onClick={() => void sticker()} disabled={busy !== null}>{busy === "sticker" ? <Spinner size={14} /> : null} دانلودِ استیکر</Button></div>
        <div className="bc-use"><h3>برگهٔ مدل (PNG)</h3><p>هویت، کلیدِ رنگ، ۸ حالت، ۸ ژست و لحنِ برند در یک تصویر.</p><Button type="button" onClick={() => void sheet()} disabled={busy !== null}>{busy === "sheet" ? <Spinner size={14} /> : null} دانلودِ برگه</Button></div>
        <div className="bc-use"><h3>برگهٔ مدل (PDF)</h3><p>سه صفحه: برگهٔ مدل، چهار سبکِ کشیدن و همهٔ ۲۹ ژست.</p><Button type="button" onClick={() => void pdf()} disabled={busy !== null}>{busy === "pdf" ? <Spinner size={14} /> : null} دانلودِ PDF</Button></div>
        <div className="bc-use"><h3>بستهٔ کامل (ZIP)</h3><p>برگهٔ مدل، هشت SVG، هشت استیکر، سندِ شخصیت، پالت و لحنِ گفتار + راهنمای فارسی.</p><Button type="button" onClick={() => void zip()} disabled={busy !== null}>{busy === "zip" ? <Spinner size={14} /> : null} دانلودِ ZIP</Button></div>
      </div>
      <p className="bc-muted">شخصیت یک کارتونِ کشیده‌شده با کد است، نه آدمِ واقعی؛ هیچ مجوزِ شخص‌محوری لازم نیست. فونتِ متن‌ها همان وزیرمتنِ تامنیل‌ساز (SIL OFL) است.</p>
    </div>
  );
}
