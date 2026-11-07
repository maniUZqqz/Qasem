import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../../../../api/client";
import { Spinner, fa } from "../../../../../components/ui";
import type { Asset } from "../../api";
import { BLEND_MODES, type BlendMode } from "../types";
import "./effects.css";

export type FxParam =
  | { key: string; title: string; type: "range"; min: number; max: number; default: number; step: number; unit: string }
  | { key: string; title: string; type: "select"; options: [string, string][]; default: string }
  | { key: string; title: string; type: "color"; default: string }
  | { key: string; title: string; type: "bool"; default: boolean };
export type FxInfo = { id: string; group: string; title: string; kind: "layer" | "photo"; blend: string; needs_mask: boolean; note: string; params: FxParam[] };
export type FxResult = { asset: Asset; effect: string; kind: "layer" | "photo"; blend: BlendMode; title: string; size: [number, number]; opacity: number; layerOnly: boolean; hideSource: boolean };

let catalogCache: FxInfo[] | null = null;
const loadCatalog = async (store: string): Promise<FxInfo[]> => {
  if (!catalogCache) catalogCache = (await api.get<{ effects: FxInfo[] }>(`/stores/${store}/photo-editor/effects/`)).data.effects;
  return catalogCache;
};

/** اگر آماده‌سازیِ تصویر گیر کرد، به‌جای چرخشِ بی‌پایان پیامِ روشن بده */
const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T> =>
  Promise.race([p, new Promise<T>((_, rej) => window.setTimeout(() => rej(new Error("آماده‌سازیِ تصویر بیش از حد طول کشید؛ پنجره را ببندید و دوباره امتحان کنید.")), ms))]);

/** ≤ side پیکسل (برای پیش‌نمایشِ سریع) */
async function shrink(blob: Blob, side: number): Promise<Blob> {
  const bmp = await createImageBitmap(blob);
  const k = Math.min(1, side / Math.max(bmp.width, bmp.height));
  if (k >= 1) return blob;
  const cv = document.createElement("canvas");
  cv.width = Math.max(4, Math.round(bmp.width * k));
  cv.height = Math.max(4, Math.round(bmp.height * k));
  const x = cv.getContext("2d")!;
  x.imageSmoothingQuality = "high";
  x.drawImage(bmp, 0, 0, cv.width, cv.height);
  return await new Promise<Blob>((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("کوچک‌کردنِ تصویر نشد."))), "image/png"));
}

type Props = {
  storeId: string;
  effectId: string;
  /** تصویرِ مبدأ: ترکیبِ همهٔ لایه‌ها یا فقط لایهٔ فعال */
  getSource: (layerOnly: boolean) => Promise<Blob>;
  getMask: () => Promise<Blob | null>;
  canLayerOnly: boolean;
  onApplied: (r: FxResult) => void;
  onClose: () => void;
};

/** فرمِ یک فیلتر: پارامترها از سرور، پیش‌نمایشِ زنده (کم‌اندازه)، «اعمال» ⇒ لایهٔ تازه (یا عکسِ تازه برای کارهای اندازه/بوم). */
export default function EffectDialog({ storeId, effectId, getSource, getMask, canLayerOnly, onApplied, onClose }: Props) {
  const [info, setInfo] = useState<FxInfo | null>(null);
  const [vals, setVals] = useState<Record<string, number | string | boolean>>({});
  const [layerOnly, setLayerOnly] = useState(false);
  const [hideSource, setHideSource] = useState(true);
  const [blend, setBlend] = useState<BlendMode>("normal");
  const [opacity, setOpacity] = useState(100);
  const [full, setFull] = useState<Blob | null>(null);
  const [small, setSmall] = useState<Blob | null>(null);
  const [maskFull, setMaskFull] = useState<Blob | null>(null);
  const [maskSmall, setMaskSmall] = useState<Blob | null>(null);
  const [beforeUrl, setBeforeUrl] = useState("");
  const [afterUrl, setAfterUrl] = useState("");
  const [showBefore, setShowBefore] = useState(false);
  const [busy, setBusy] = useState<"" | "load" | "preview" | "apply">("load");
  const [err, setErr] = useState<string | null>(null);
  const [size, setSize] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const ctl = useRef<AbortController | null>(null);

  // اطلاعاتِ فیلتر + تصویرِ مبدأ
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const all = await loadCatalog(storeId);
        const fx = all.find((e) => e.id === effectId);
        if (!fx) throw new Error("این فیلتر روی سرور پیدا نشد.");
        const [src, mk] = await withTimeout(Promise.all([getSource(false), getMask()]), 45000);
        const [s, ms] = await Promise.all([shrink(src, 900), mk ? shrink(mk, 900) : Promise.resolve(null)]);
        if (!live) return;
        setInfo(fx);
        if ((fx.group.startsWith("سبکِ لایه") || fx.group.startsWith("تبدیلِ لایه")) && canLayerOnly) setLayerOnly(true);
        setVals(Object.fromEntries(fx.params.map((p) => [p.key, p.default])));
        setBlend(fx.blend as BlendMode);
        setFull(src);
        setSmall(s);
        setMaskFull(mk);
        setMaskSmall(ms);
        setBusy("");
        if (fx.needs_mask && !mk) setErr("این فیلتر روی ناحیهٔ انتخاب‌شده کار می‌کند؛ اول با ابزارِ انتخاب (کمند، مستطیل…) ناحیه‌ای را مشخص کنید.");
      } catch (e) {
        if (live) {
          setErr(errorMessage(e));
          setBusy("");
        }
      }
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, effectId]);

  useEffect(() => {
    if (!small) return;
    const u = URL.createObjectURL(small);
    setBeforeUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [small]);
  useEffect(
    () => () => {
      if (afterUrl) URL.revokeObjectURL(afterUrl);
    },
    [afterUrl],
  );

  // «فقط لایهٔ فعال» ⇒ مبدأ را دوباره بگیر
  useEffect(() => {
    if (!info) return;
    let live = true;
    (async () => {
      try {
        const src = await getSource(layerOnly);
        const s = await shrink(src, 900);
        if (live) {
          setFull(src);
          setSmall(s);
        }
      } catch (e) {
        if (live) setErr(errorMessage(e));
      }
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layerOnly]);

  const form = useCallback(
    (img: Blob, mask: Blob | null) => {
      const fd = new FormData();
      fd.append("effect", effectId);
      fd.append("params", JSON.stringify(vals));
      fd.append("image", img, "image.png");
      if (mask) fd.append("mask", mask, "mask.png");
      return fd;
    },
    [effectId, vals],
  );

  // پیش‌نمایشِ زنده (با تأخیر)
  useEffect(() => {
    if (!info || !small) return;
    if (info.needs_mask && !maskSmall) return;
    const t = window.setTimeout(async () => {
      ctl.current?.abort();
      const c = new AbortController();
      ctl.current = c;
      setBusy("preview");
      setErr(null);
      try {
        const r = await api.post<Blob>(`/stores/${storeId}/photo-editor/effects/preview/`, form(small, maskSmall), { responseType: "blob", signal: c.signal });
        if (c.signal.aborted) return;
        setAfterUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return URL.createObjectURL(r.data);
        });
        setSize(String(r.headers["x-result-size"] ?? ""));
        setBusy("");
      } catch (e) {
        if (c.signal.aborted || (e as { code?: string }).code === "ERR_CANCELED") return;
        // خطای پیش‌نمایش با بدنهٔ blob می‌آید؛ متنِ فارسی را بخوان
        let msg = errorMessage(e);
        const data = (e as { response?: { data?: Blob } }).response?.data;
        if (data instanceof Blob) {
          try {
            const j = JSON.parse(await data.text()) as { error?: { message?: string } };
            msg = j.error?.message ?? msg;
          } catch {
            /* همان پیامِ عمومی */
          }
        }
        setErr(msg);
        setBusy("");
      }
    }, 380);
    return () => window.clearTimeout(t);
  }, [info, small, maskSmall, form, storeId]);

  async function apply() {
    if (!info || !full) return;
    setBusy("apply");
    setErr(null);
    try {
      const fd = form(full, maskFull);
      fd.append("title", info.title);
      const r = await api.post<{ asset: Asset; effect: string; kind: "layer" | "photo"; blend: string; title: string; size: [number, number] }>(`/stores/${storeId}/photo-editor/effects/apply/`, fd);
      onApplied({ ...r.data, blend, opacity: opacity / 100, layerOnly, hideSource: layerOnly && hideSource } as FxResult);
    } catch (e) {
      let msg = errorMessage(e);
      const data = (e as { response?: { data?: { error?: { message?: string } } } }).response?.data;
      if (data?.error?.message) msg = data.error.message;
      setErr(msg);
      setBusy("");
    }
  }

  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const setVal = (k: string, v: number | string | boolean) => setVals((o) => ({ ...o, [k]: v }));
  const shown = useMemo(() => (showBefore || !afterUrl ? beforeUrl : afterUrl), [showBefore, afterUrl, beforeUrl]);

  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="effect-dialog" data-effect={effectId}>
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label={info?.title ?? "فیلتر"} tabIndex={-1} ref={root} dir="rtl">
        <div className="fx-head">
          <b data-testid="fx-title">{info?.title ?? "…"}</b>
          <button type="button" className="fx-x" onClick={onClose} aria-label="بستن" data-testid="fx-close">✕</button>
        </div>
        <div className="fx-body">
          <div className="fx-view">
            {shown ? <img src={shown} alt="پیش‌نمایش" data-testid="fx-preview" /> : <div className="fx-wait"><Spinner /></div>}
            {busy === "preview" && <span className="fx-busy"><Spinner size={14} /> در حالِ ساخت…</span>}
            <button type="button" className="fx-before" onPointerDown={() => setShowBefore(true)} onPointerUp={() => setShowBefore(false)} onPointerLeave={() => setShowBefore(false)} onKeyDown={(e) => e.key === " " && setShowBefore(true)} onKeyUp={() => setShowBefore(false)}>
              نگه‌دارید: قبل
            </button>
          </div>
          <div className="fx-form">
            {info?.note && <p className="fx-note">{info.note}</p>}
            {info?.params.map((p) => (
              <label key={p.key} className={`fx-row ${p.type === "bool" ? "is-check" : ""}`}>
                <span>{p.title}</span>
                {p.type === "range" && (
                  <span className="fx-range">
                    <input type="range" min={p.min} max={p.max} step={p.step} value={Number(vals[p.key] ?? p.default)} onChange={(e) => setVal(p.key, Number(e.target.value))} data-fx-param={p.key} />
                    <b dir="ltr">{fa(Number(vals[p.key] ?? p.default))}{p.unit}</b>
                  </span>
                )}
                {p.type === "select" && (
                  <select value={String(vals[p.key] ?? p.default)} onChange={(e) => setVal(p.key, e.target.value)} data-fx-param={p.key}>
                    {p.options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                )}
                {p.type === "color" && <input type="color" value={String(vals[p.key] ?? p.default)} onChange={(e) => setVal(p.key, e.target.value)} data-fx-param={p.key} />}
                {p.type === "bool" && <input type="checkbox" checked={!!(vals[p.key] ?? p.default)} onChange={(e) => setVal(p.key, e.target.checked)} data-fx-param={p.key} />}
              </label>
            ))}
            {info?.kind === "layer" && (
              <>
                <hr className="fx-hr" />
                {canLayerOnly && !info.group.startsWith("لایهٔ پرکننده") && (
                  <label className="fx-row is-check">
                    <span>فقط روی لایهٔ فعال (نه کلِ تصویر)</span>
                    <input type="checkbox" checked={layerOnly} onChange={(e) => setLayerOnly(e.target.checked)} data-testid="fx-layer-only" />
                  </label>
                )}
                {layerOnly && (
                  <label className="fx-row is-check">
                    <span>پنهان‌کردنِ لایهٔ اصلی بعد از اعمال</span>
                    <input type="checkbox" checked={hideSource} onChange={(e) => setHideSource(e.target.checked)} data-testid="fx-hide-source" />
                  </label>
                )}
                <label className="fx-row">
                  <span>حالتِ ترکیبِ لایهٔ نتیجه</span>
                  <select value={blend} onChange={(e) => setBlend(e.target.value as BlendMode)} data-testid="fx-blend">
                    {BLEND_MODES.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
                  </select>
                </label>
                <label className="fx-row">
                  <span>شفافیتِ لایهٔ نتیجه</span>
                  <span className="fx-range"><input type="range" min={5} max={100} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} /><b dir="ltr">{fa(opacity)}%</b></span>
                </label>
                <p className="fx-note">{maskFull ? "فقط روی ناحیهٔ انتخاب‌شده اعمال می‌شود." : "روی کلِ تصویر اعمال می‌شود (برای ناحیه، اول انتخابی بکشید)."} نتیجه یک لایهٔ تازه است؛ لایهٔ زیرین سالم می‌ماند و می‌شود آن را پنهان یا حذف کرد.</p>
              </>
            )}
            {info?.kind === "photo" && <p className="fx-note">نتیجه یک عکسِ تازه در کتابخانه می‌شود و همان‌جا باز می‌شود؛ عکسِ فعلی و ویرایش‌هایش دست‌نخورده می‌مانند.{size ? ` اندازهٔ پیش‌نمایش: ${size}` : ""}</p>}
            {err && <p className="fx-err" role="alert" data-testid="fx-error">{err}</p>}
          </div>
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" onClick={() => void apply()} disabled={busy === "apply" || busy === "load" || !info || (info.needs_mask && !maskFull)} data-testid="fx-apply">
            {busy === "apply" ? <Spinner size={14} /> : info?.kind === "photo" ? "ساختِ عکسِ تازه" : "اعمال (لایهٔ تازه)"}
          </button>
          <button type="button" className="ws-btn" onClick={() => info && setVals(Object.fromEntries(info.params.map((p) => [p.key, p.default])))}>بازنشانیِ مقدارها</button>
          <button type="button" className="ws-btn" onClick={onClose}>انصراف</button>
        </div>
      </div>
    </div>
  );
}
