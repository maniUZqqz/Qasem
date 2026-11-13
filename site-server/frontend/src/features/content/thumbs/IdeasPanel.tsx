import { useEffect, useState } from "react";

import { errorMessage } from "../../../api/client";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, Select, Spinner, fa } from "../../../components/ui";
import { Archetype, FormatInfo, Idea, IdeasResult, ProductRow, thumbsApi } from "./api";

/**
 * «ایده»: موضوع یا محصول ⇒ عنوان‌های قلاب‌دار + مفهومِ تصویری + سبکِ پیشنهادی؛ و «مودبرد» ِ الگوهای رایج.
 * هوش مصنوعی خاموش/بی‌اعتبار بود ⇒ فرمول‌های آمادهٔ فارسی (با پیامِ روشن)؛ هر بار که برگردد، همان دکمه پیشنهادِ هوشمند می‌دهد.
 */
export default function IdeasPanel({
  storeId,
  format,
  formats,
  products,
  onUse,
  onUseStyle,
}: {
  storeId: string;
  format: string;
  formats: FormatInfo[];
  products: ProductRow[];
  onUse: (idea: Idea) => void;
  onUseStyle: (style: string, format: string) => void;
}) {
  const [topic, setTopic] = useState("");
  const [productId, setProductId] = useState("");
  const [ideaFormat, setIdeaFormat] = useState(format);
  const [number, setNumber] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [usePrice, setUsePrice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IdeasResult | null>(null);
  const [variation, setVariation] = useState(0);
  const [board, setBoard] = useState<Archetype[] | null>(null);
  const [boardNote, setBoardNote] = useState("");
  const [showBoard, setShowBoard] = useState(false);
  const [boardError, setBoardError] = useState<string | null>(null);

  useEffect(() => setIdeaFormat(format), [format]);

  useEffect(() => {
    if (!showBoard || board) return;
    thumbsApi.moodboard(storeId).then((r) => { setBoard(r.archetypes); setBoardNote(r.note); }).catch((e) => setBoardError(errorMessage(e)));
  }, [showBoard, board, storeId]);

  async function go(nextVariation = variation) {
    if (!topic.trim() && !productId) {
      setError("موضوع را بنویسید یا یک محصول انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await thumbsApi.ideas(storeId, {
        topic, product: productId || undefined, format: ideaFormat, count: 6, number: number || undefined, ai: useAi, use_price: usePrice, variation: nextVariation,
      });
      setResult(res);
      setVariation(nextVariation);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const productWithPrice = products.find((p) => String(p.id) === productId)?.has_price;

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-extrabold" style={{ color: "var(--text)" }}>ایده‌پردازی</h2>
          <p className="dz-muted">موضوع یا محصول را بدهید؛ عنوانِ قلاب‌دار، مفهومِ تصویری و سبکِ مناسبِ هر پلتفرم پیشنهاد می‌شود.</p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => setShowBoard((v) => !v)}>
          {showBoard ? "بستنِ مودبرد" : "مودبردِ الگوهای رایج"}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="dz-field wide">
          <span>موضوع</span>
          <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="مثلاً: برنامهٔ ورزشی شخصی برای مبتدی‌ها" onKeyDown={(e) => e.key === "Enter" && void go(0)} />
        </label>
        <label className="dz-field">
          <span>یا یک محصول</span>
          <Select value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">— بدونِ محصول —</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </label>
        <label className="dz-field">
          <span>برای کدام پلتفرم</span>
          <Select value={ideaFormat} onChange={(e) => setIdeaFormat(e.target.value)}>
            {formats.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
          </Select>
        </label>
        <label className="dz-field">
          <span>تعدادِ مورد (برای تامنیلِ فهرستی، اختیاری)</span>
          <Input inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, "").slice(0, 2))} placeholder="مثلاً ۷" />
        </label>
        <div className="flex flex-col justify-end gap-1">
          <label className="dz-field check"><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /><span>با هوش مصنوعی (اگر در دسترس باشد)</span></label>
          {productId && productWithPrice && (
            <label className="dz-field check"><input type="checkbox" checked={usePrice} onChange={(e) => setUsePrice(e.target.checked)} /><span>قیمتِ واقعیِ محصول روی نشان بیاید</span></label>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => void go(0)} disabled={busy}>{busy ? "در حالِ ایده‌پردازی…" : "ایده بده"}</Button>
        {result && <Button variant="secondary" onClick={() => void go(variation + 1)} disabled={busy}>ایده‌های دیگر</Button>}
        {busy && <Spinner size={16} />}
      </div>
      <div className="mt-2"><ErrorBox message={error} /></div>

      {result && (
        <div className="mt-4">
          <Alert tone={result.via === "rules" && result.ai.tried ? "warn" : "info"}>
            <span className="text-sm th-wrap">{result.message}</span>
          </Alert>
          <div className="th-ideas mt-3">
            {result.ideas.map((i) => (
              <div key={i.id} className="th-idea">
                <div className="mb-1 flex flex-wrap items-center gap-1">
                  <Badge tone={i.source === "ai" ? "brand" : "neutral"}>{i.source === "ai" ? "هوش مصنوعی" : i.formula_label}</Badge>
                  <Badge tone="info">{i.style_title}</Badge>
                  {i.number && <Badge>عدد {fa(i.number)}</Badge>}
                </div>
                <div className="th-idea-title">{i.title.replace(/\*/g, "")}</div>
                {i.subtitle && <div className="dz-muted">{i.subtitle}</div>}
                <p className="dz-muted" style={{ marginTop: 6 }}>{i.concept}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => onUse(i)}>استفاده از این ایده</Button>
                </div>
              </div>
            ))}
          </div>
          <p className="dz-muted mt-2">عنوان‌ها پیشنهادند؛ پیش از انتشار با واقعیتِ محتوا و کالای خودتان بسنجید. هیچ قیمت یا آماری ساخته نمی‌شود.</p>
        </div>
      )}

      {showBoard && (
        <div className="mt-5">
          <h3 className="mb-1 text-sm font-extrabold" style={{ color: "var(--text)" }}>مودبرد: الگوهای رایجِ چیدمان</h3>
          {boardNote && <p className="dz-muted mb-2">{boardNote}</p>}
          <ErrorBox message={boardError} />
          {!board ? (
            !boardError && <Spinner size={18} />
          ) : board.length === 0 ? (
            <EmptyState icon="image" title="الگویی نیست" />
          ) : (
            <div className="th-board">
              {board.map((a) => (
                <div key={a.key} className="th-arch">
                  <img src={a.sample} alt={a.title} loading="lazy" />
                  <div className="th-arch-body">
                    <div className="mb-1 flex flex-wrap items-center gap-1">
                      <b style={{ color: "var(--text)" }}>{a.title}</b>
                      <Badge tone="neutral">{a.origin_label}</Badge>
                    </div>
                    <p className="dz-muted">{a.pattern}</p>
                    <p className="dz-muted"><b>چرا جواب می‌دهد: </b>{a.why}</p>
                    <ul className="dz-muted" style={{ paddingInlineStart: 16, listStyle: "disc" }}>
                      {a.dos.map((d) => <li key={d}>{d}</li>)}
                      {a.donts.map((d) => <li key={d} style={{ color: "var(--warn)" }}>نه: {d}</li>)}
                    </ul>
                    <p className="dz-muted">متن: {a.text_rule} · رنگ: {a.palette}</p>
                    <Button size="sm" variant="secondary" onClick={() => onUseStyle(a.style, a.formats.includes(format) ? format : a.formats[0])}>
                      شروع با این الگو
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
