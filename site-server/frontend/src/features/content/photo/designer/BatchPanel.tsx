import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, Card, SectionTitle, Spinner, fa } from "../../../../components/ui";
import type { Asset, Edit } from "../api";
import { designerApi, type DesignerInfo } from "./api";
import BrandForm from "./BrandForm";
import { Batch, BatchRow, Brand, StoreSettings, batchApi, emptyBrand, settingsApi } from "./brandApi";
import { COPY_FIELDS } from "./labels";
import "./designer.css";

const BATCH_COPY = ["headline", "subline", "price", "discount", "cta"];

/** «طراحیِ گروهی»: چند عکس + یک الگو/دستور + سبکِ برند ⇒ جدولِ نتیجه ⇒ ویرایشِ تکی ⇒ خروجیِ همه (zip). */
export default function BatchPanel({
  storeId,
  assets,
  onClose,
  onApplied,
  onOpenSettings,
}: {
  storeId: string;
  assets: Asset[];
  onClose: () => void;
  onApplied: (edit: Edit, openManual: boolean) => void;
  onOpenSettings: (tab: "ai" | "brand") => void;
}) {
  const [info, setInfo] = useState<DesignerInfo | null>(null);
  const [st, setSt] = useState<StoreSettings | null>(null);
  const [pick, setPick] = useState<number[]>([]);
  const [recipe, setRecipe] = useState("");
  const [prompt, setPrompt] = useState("");
  const [fmt, setFmt] = useState("");
  const [copy, setCopy] = useState<Record<string, string>>({});
  const [useAi, setUseAi] = useState(false);
  const [useBrand, setUseBrand] = useState(true);
  const [override, setOverride] = useState(false);
  const [brand, setBrand] = useState<Brand>(emptyBrand());
  const [batch, setBatch] = useState<Batch | null>(null);
  const [recent, setRecent] = useState<BatchRow[]>([]);
  const [off, setOff] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<"" | "start" | "zip" | "apply">("");
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const loadRecent = useCallback(() => batchApi.list(storeId).then(setRecent).catch(() => undefined), [storeId]);
  useEffect(() => {
    let live = true;
    Promise.all([designerApi.info(storeId), settingsApi.get(storeId)])
      .then(([i, s]) => {
        if (!live) return;
        setInfo(i);
        setSt(s);
        setUseAi(s.ai_assist);
        setBrand(s.brand);
        setUseBrand(s.brand_set);
      })
      .catch((e) => live && setErr(errorMessage(e)));
    void loadRecent();
    return () => {
      live = false;
    };
  }, [storeId, loadRecent]);

  // پیگیریِ گروهِ در حالِ انجام
  useEffect(() => {
    if (!batch?.id || (batch.state !== "QUEUED" && batch.state !== "RUNNING")) return;
    timer.current = window.setInterval(() => {
      batchApi.get(storeId, batch.id).then(setBatch).catch(() => undefined);
    }, 2200);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [batch?.id, batch?.state, storeId]);
  useEffect(() => {
    if (batch && !(batch.state === "QUEUED" || batch.state === "RUNNING")) void loadRecent();
  }, [batch?.state, batch, loadRecent]);

  const cap = useAi ? info?.limits.batch_ai ?? 12 : info?.limits.batch ?? 24;
  const toggle = (id: number) => setPick((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= cap ? p : [...p, id]));
  const usedFields = useMemo(() => new Set(recipe ? info?.recipes.find((r) => r.key === recipe)?.fields ?? [] : BATCH_COPY), [recipe, info]);

  async function start() {
    setErr(null);
    setBusy("start");
    try {
      const b = await batchApi.create(storeId, {
        assets: pick, prompt: prompt.trim(), recipe, format: fmt, mood: "auto",
        copy: Object.fromEntries(Object.entries(copy).filter(([, v]) => v.trim())),
        use_ai: useAi, use_brand: useBrand, ...(useBrand && override ? { brand } : {}),
      });
      setBatch(b);
      setOff(new Set());
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  }
  async function openBatch(id: number) {
    setErr(null);
    try {
      setBatch(await batchApi.get(storeId, id));
      setOff(new Set());
    } catch (e) {
      setErr(errorMessage(e));
    }
  }
  async function zip() {
    if (!batch) return;
    setBusy("zip");
    setErr(null);
    try {
      const ids = batch.items.filter((it) => it.design?.state === "READY" && !off.has(it.asset.id)).map((it) => it.asset.id);
      await batchApi.download(storeId, batch.id, ids);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  }
  async function edit(designId: number) {
    setBusy("apply");
    setErr(null);
    try {
      const r = await batchApi.apply(storeId, designId);
      onApplied(r.edit, true);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy("");
    }
  }
  async function remove() {
    if (!batch || !window.confirm("این طراحیِ گروهی و همهٔ پیش‌نمایش‌هایش پاک شود؟ (عکس‌های اصلیِ شما می‌مانند)")) return;
    await batchApi.remove(storeId, batch.id).catch((e) => setErr(errorMessage(e)));
    setBatch(null);
    void loadRecent();
  }

  const running = batch && (batch.state === "QUEUED" || batch.state === "RUNNING");
  const okCount = batch ? batch.items.filter((it) => it.design?.state === "READY" && !off.has(it.asset.id)).length : 0;

  return (
    <Card className="mb-6">
      <div data-testid="batch-panel">
      <SectionTitle action={<button type="button" className="dz-link" onClick={onClose} data-testid="batch-close">✕ بستن</button>}>طراحیِ گروهی</SectionTitle>
      <p className="dz-muted">یک الگو و سبکِ برند، روی چند عکس — بعد همه را یک‌جا مرور، تکی ویرایش و یک‌جا دریافت کنید.</p>
      {err && <div className="my-2"><Alert tone="bad">{err}</Alert></div>}

      {!batch && (
        <>
          <div className="dz-label">۱) عکس‌ها را انتخاب کنید <span className="dz-muted">({fa(pick.length)} از حداکثر {fa(cap)})</span></div>
          <div className="dz-chips mb-2">
            <button type="button" className="example-chip" onClick={() => setPick(assets.slice(0, cap).map((a) => a.id))} data-testid="batch-all">همه</button>
            <button type="button" className="example-chip" onClick={() => setPick([])}>هیچ‌کدام</button>
          </div>
          <div className="bt-pick" data-testid="batch-pick">
            {assets.map((a) => (
              <button key={a.id} type="button" className="bt-ph" aria-pressed={pick.includes(a.id)} onClick={() => toggle(a.id)} title={a.title} data-asset-pick={a.id}>
                <img src={a.thumb} alt={a.title} loading="lazy" />
                <b aria-hidden>✓</b>
              </button>
            ))}
          </div>

          <div className="dz-label">۲) چه طرحی؟</div>
          <div className="dz-recipes" data-testid="batch-recipes">
            {(info?.recipes ?? []).map((r) => (
              <button key={r.key} type="button" className={`dz-recipe ${recipe === r.key ? "is-on" : ""}`} onClick={() => { setRecipe(recipe === r.key ? "" : r.key); if (!fmt) setFmt(""); }} data-batch-recipe={r.key}>
                <b>{r.title}</b>
                <span>{r.help}</span>
              </button>
            ))}
          </div>
          <label className="dz-field mt-2">
            <span>یا با یک جمله بنویسید</span>
            <input className="u-input" value={prompt} maxLength={600} placeholder="مثلاً: تبلیغِ تخفیفِ پاییزه" onChange={(e) => setPrompt(e.target.value)} data-testid="batch-prompt" />
          </label>
          <div className="dz-copy mt-2">
            {COPY_FIELDS.filter((f) => usedFields.has(f.key)).map((f) => (
              <label key={f.key} className="dz-field">
                <span>{f.label} (برای همهٔ عکس‌ها)</span>
                <input className="u-input" value={copy[f.key] ?? ""} maxLength={120} placeholder={f.ph} onChange={(e) => setCopy({ ...copy, [f.key]: e.target.value })} />
              </label>
            ))}
            <p className="dz-muted wide">خالی بگذارید تا از دستور (یا هوش مصنوعی) گرفته شود. متنی که بنویسید روی همهٔ عکس‌ها یکسان می‌نشیند.</p>
          </div>

          <div className="dz-label">۳) سبکِ برند و هوش مصنوعی</div>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={useBrand} onChange={(e) => setUseBrand(e.target.checked)} data-testid="batch-use-brand" />
            سبکِ برند را اعمال کن {st && !st.brand_set && <span className="dz-muted">(هنوز ذخیره نشده — <button type="button" className="dz-link" onClick={() => onOpenSettings("brand")}>تنظیمش کنید</button>)</span>}
          </label>
          {useBrand && (
            <>
              <button type="button" className="dz-link" onClick={() => setOverride((v) => !v)} data-testid="batch-override">{override ? "▾ برگشت به سبکِ ذخیره‌شده" : "▸ تغییر برای این گروه"}</button>
              {override && info && st && <BrandForm value={brand} onChange={setBrand} fonts={info.fonts} assets={assets} hasStoreLogo={info.has_logo} positions={st.positions} tid="batch-brand" />}
            </>
          )}
          <label className="mt-2 flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={useAi} onChange={(e) => { setUseAi(e.target.checked); if (e.target.checked && pick.length > (info?.limits.batch_ai ?? 12)) setPick(pick.slice(0, info?.limits.batch_ai ?? 12)); }} data-testid="batch-use-ai" />
            از هوش مصنوعی هم کمک بگیر
          </label>
          <p className="dz-muted" data-testid="batch-ai-note">
            {useAi
              ? `هوش مصنوعی فقط الگو و متن را پیشنهاد می‌دهد: ${fa(st?.ai_cost.batch_per_photo ?? 1)} فراخوانی برای هر عکس (جمعاً ${fa(pick.length)} فراخوانی)، بدونِ نقد. سقفِ تعداد با آن ${fa(info?.limits.batch_ai ?? 12)} عکس است.`
              : `بدونِ هوش مصنوعی: هیچ فراخوانی‌ای زده نمی‌شود؛ طراحی با الگوها و قاعده‌های آماده انجام می‌شود. سقفِ تعداد ${fa(info?.limits.batch ?? 24)} عکس است.`}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button onClick={() => void start()} disabled={busy !== "" || !pick.length || (!prompt.trim() && !recipe)} data-testid="batch-run">
              {busy === "start" ? <Spinner size={16} /> : `✨ طراحیِ ${fa(pick.length)} عکس`}
            </Button>
            {!pick.length && <span className="text-sm" style={{ color: "var(--warn)" }}>دست‌کم یک عکس انتخاب کنید.</span>}
            {pick.length > 0 && !prompt.trim() && !recipe && <span className="text-sm" style={{ color: "var(--warn)" }}>یک الگو را بزنید یا دستور بنویسید.</span>}
          </div>
          {recent.length > 0 && (
            <div className="mt-3" data-testid="batch-recent">
              <div className="dz-label">گروه‌های قبلی</div>
              <div className="dz-chips">
                {recent.slice(0, 6).map((r) => (
                  <button key={r.id} type="button" className="example-chip" onClick={() => void openBatch(r.id)}>
                    {r.title} — {r.state === "READY" ? "آماده" : r.state === "FAILED" ? "ناموفق" : r.state === "CANCELLED" ? "لغو" : "در حال انجام"}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {batch && (
        <div data-testid="batch-result" data-state={batch.state}>
          <div className="dz-progress my-2">
            <div className="flex items-center justify-between gap-2">
              <b>{batch.title}</b>
              <Badge tone={batch.state === "READY" ? "ok" : batch.state === "FAILED" || batch.state === "CANCELLED" ? "warn" : "info"}>
                {batch.state === "READY" ? "آماده" : batch.state === "FAILED" ? "ناموفق" : batch.state === "CANCELLED" ? "لغو شد" : "در حالِ طراحی"}
              </Badge>
            </div>
            <div className="dz-bar"><i style={{ width: `${Math.round(batch.progress * 100)}%` }} /></div>
            <div className="dz-muted" data-testid="batch-msg">{batch.message} — {fa(batch.done)} از {fa(batch.total)}</div>
            {running && <button type="button" className="dz-link" onClick={() => void batchApi.cancel(storeId, batch.id).then(setBatch)} data-testid="batch-cancel">لغو</button>}
          </div>
          <div className="bt-grid" data-testid="batch-grid">
            {batch.items.map((it) => {
              const d = it.design;
              const ready = d?.state === "READY";
              return (
                <div key={it.asset.id} className={`bt-card ${off.has(it.asset.id) ? "is-off" : ""}`} data-batch-item={it.asset.id} data-state={d?.state ?? "WAIT"}>
                  {ready && d.preview ? <img src={d.preview} alt={it.asset.title} loading="lazy" /> : <img src={it.asset.thumb} alt={it.asset.title} loading="lazy" style={{ opacity: 0.45 }} />}
                  <div className="bt-body">
                    <b style={{ color: "var(--text)" }}>{it.asset.title}</b>
                    {!d && <span>در انتظار…</span>}
                    {d && !ready && d.state !== "FAILED" && <span><Spinner size={12} /> {d.message || "در حالِ طراحی…"}</span>}
                    {d?.state === "FAILED" && <span style={{ color: "var(--bad)" }}>ناموفق: {d.error || d.message}</span>}
                    {ready && (
                      <>
                        {d.score !== null && <span>امتیازِ بررسیِ خودکار: {fa(Math.round(d.score))} از ۱۰۰</span>}
                        {d.issues.length > 0 && <span style={{ color: "var(--warn)" }}>{d.issues[0]}</span>}
                        <label className="flex items-center gap-1">
                          <input type="checkbox" checked={!off.has(it.asset.id)} onChange={(e) => setOff((s) => { const n = new Set(s); if (e.target.checked) n.delete(it.asset.id); else n.add(it.asset.id); return n; })} />
                          در خروجی باشد
                        </label>
                        <button type="button" className="example-chip" disabled={busy !== ""} onClick={() => void edit(d.id)} data-testid={`batch-edit-${it.asset.id}`}>✎ ویرایش در ویرایشگر</button>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button onClick={() => void zip()} disabled={busy !== "" || !!running || !okCount} data-testid="batch-zip">
              {busy === "zip" ? <Spinner size={16} /> : `⬇ دریافتِ ${fa(okCount)} تصویر (zip)`}
            </Button>
            <Button variant="secondary" onClick={() => setBatch(null)} disabled={!!running} data-testid="batch-new">طراحیِ گروهیِ تازه</Button>
            <button type="button" className="dz-link" onClick={() => void remove()} disabled={!!running}>حذفِ این گروه</button>
          </div>
        </div>
      )}
      </div>
    </Card>
  );
}
