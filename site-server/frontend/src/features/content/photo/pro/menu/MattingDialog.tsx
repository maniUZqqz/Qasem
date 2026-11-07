import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../../api/client";
import { fa } from "../../../../../components/ui";
import type { Asset } from "../../api";
import { settingsApi, type MattingModelId } from "../../designer/brandApi";
import { MattingJob, MattingRow, MattingStatus, mattingApi } from "../mattingApi";
import "./effects.css";

const TONE: Record<string, string> = { installed: "#16a34a", downloading: "#d97706", queued: "#d97706", missing: "#6b7280", failed: "#dc2626" };
const JOB_FA: Record<string, string> = { queued: "در صف", running: "در حالِ کار", ready: "آماده", failed: "ناموفق", cancelled: "لغو شد" };

/**
 * «حذفِ پس‌زمینه با مدل» (دورِ ۸): انتخابِ مدل (RVM روی سایت · u2netp · IS-Net · BiRefNet-lite روی سرورِ پردازش)، اجرا، و «مقایسه»ی
 * یک عکس با همهٔ مدل‌ها کنار هم از راهِ صفِ ماندگار. وضعیتِ نصبِ هر مدل روی سرورِ پردازش دیده می‌شود.
 */
export default function MattingDialog({ storeId, asset, defaultModel, onClose, onOpenAsset }: {
  storeId: string;
  asset: { id: number; title: string };
  defaultModel: string;
  onClose: () => void;
  onOpenAsset?: (a: Asset) => void;
}) {
  const [st, setSt] = useState<MattingStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pick, setPick] = useState<string>(defaultModel || "rvm");
  const [jobs, setJobs] = useState<Record<string, MattingJob>>({});
  const [imgs, setImgs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const loading = useRef<Set<string>>(new Set());

  const touched = useRef(false);
  const refreshStatus = useCallback(() => {
    mattingApi.status(storeId).then((s) => {
      setSt(s);
      if (!touched.current) setPick(s.default || "rvm");
    }).catch((e) => setErr(errorMessage(e)));
  }, [storeId]);

  useEffect(() => {
    refreshStatus();
    const t = window.setInterval(refreshStatus, 20000);
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [refreshStatus, onClose]);

  // نتیجه‌های آماده را (با هدرِ ورود) بگیر
  useEffect(() => {
    for (const [m, j] of Object.entries(jobs)) {
      if (j.state === "ready" && j.url && !imgs[m] && !loading.current.has(m)) {
        loading.current.add(m);
        void mattingApi.blobUrl(j.url).then((u) => setImgs((cur) => ({ ...cur, [m]: u }))).catch(() => loading.current.delete(m));
      }
    }
  }, [jobs, imgs]);
  useEffect(() => () => Object.values(imgs).forEach((u) => URL.revokeObjectURL(u)), []); // eslint-disable-line react-hooks/exhaustive-deps

  // پرس‌وجوی کارهای در صف / در حال کار
  const active = Object.values(jobs).filter((j) => j.uid && (j.state === "queued" || j.state === "running")).map((j) => j.uid);
  useEffect(() => {
    if (!active.length) return;
    const t = window.setInterval(() => {
      mattingApi.jobs(storeId, active).then((r) => {
        setJobs((cur) => {
          const next = { ...cur };
          for (const j of r.jobs) next[j.model] = j;
          return next;
        });
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [active.join(","), storeId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(models: string[]) {
    setBusy(true);
    setErr(null);
    setNote(null);
    setImgs({});
    loading.current = new Set();
    try {
      const r = await mattingApi.run(storeId, asset.id, models);
      const next: Record<string, MattingJob> = {};
      for (const j of r.jobs) next[j.model] = j;
      setJobs(next);
      if (r.skipped.length) setNote(r.skipped.map((s) => `${s.model}: ${s.message}`).join("؛ "));
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const rows: MattingRow[] = st?.models ?? [];
  const compareIds = rows.filter((r) => r.where === "site" ? r.state === "installed" : r.state === "installed" || r.state === "downloading" || r.state === "queued").map((r) => r.id);
  const title = (id: string) => rows.find((r) => r.id === id)?.title ?? id;

  async function use(model: string, j: MattingJob) {
    setBusy(true);
    try {
      const a = await mattingApi.apply(storeId, asset.id, model, j.uid || undefined);
      setNote(`«${a.title}» به کتابخانه افزوده شد.`);
      if (onOpenAsset) onOpenAsset(a);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function makeDefault() {
    try {
      await settingsApi.put(storeId, { matting_model: pick as MattingModelId });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setErr(errorMessage(e));
    }
  }

  const shown = Object.keys(jobs);
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="matting-dialog">
      <div className="fx-dialog" style={{ width: "min(760px, 100%)", maxHeight: "92vh", overflow: "auto" }} role="dialog" aria-modal="true" aria-label="حذفِ پس‌زمینه با مدل" tabIndex={-1} ref={root} dir="rtl">
        <div className="fx-head"><b>حذفِ پس‌زمینه با مدل — «{asset.title}»</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div className="fx-form" style={{ padding: 14 }}>
          <p className="fx-note">یک مدل را انتخاب کنید یا همه را کنارِ هم امتحان کنید. مدل‌های سرورِ پردازش باید اول روی همان سرور دانلود شده باشند؛ تا آن موقع کارِ شما «در صف» می‌ماند و بعداً خودکار انجام می‌شود (به سرورِ سایت چیزی دانلود نمی‌شود).</p>
          {!st && !err && <p className="fx-note">در حالِ خواندنِ وضعیتِ مدل‌ها…</p>}
          {err && <p className="fx-err" role="alert" data-testid="matting-error">{err}</p>}
          {st && !st.node_known && <p className="fx-note" data-testid="matting-nonode">{st.update_text || st.message || "هیچ سرورِ پردازشی برای این کار ثبت نشده؛ فعلاً فقط مدلِ سایت (RVM) کار می‌کند."}</p>}
          {st && st.node_known && !st.node_online && <p className="fx-note" data-testid="matting-offline">سرورِ پردازش الان خاموش است؛ کارِ مدل‌های آن‌جا در صف می‌ماند.</p>}
          <div role="radiogroup" aria-label="مدلِ حذفِ پس‌زمینه" data-testid="matting-models" style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
            {rows.map((r) => (
              <label key={r.id} className="fx-row" data-model={r.id} style={{ alignItems: "flex-start", gap: 8, cursor: "pointer", border: pick === r.id ? "1px solid var(--accent, #6366f1)" : "1px solid transparent", borderRadius: 8, padding: 6 }}>
                <input type="radio" name="matting-model" checked={pick === r.id} onChange={() => { touched.current = true; setPick(r.id); }} data-testid={`matting-pick-${r.id}`} />
                <span style={{ flex: 1 }}>
                  <b>{r.title}</b> <span className="ws-muted" style={{ fontSize: 12 }}>({fa(r.size_mb)} مگابایت · {r.where === "site" ? "روی سایت" : "روی سرورِ پردازش"})</span>
                  <br /><span className="ws-muted" style={{ fontSize: 12 }}>{r.hint}</span>
                </span>
                <span data-testid={`matting-state-${r.id}`} data-state={r.state} style={{ color: TONE[r.state] ?? "inherit", fontSize: 12, fontWeight: 700, whiteSpace: "nowrap" }}>● {r.state_fa}</span>
              </label>
            ))}
          </div>
          {shown.length > 0 && (
            <div data-testid="matting-results" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 10, marginTop: 12 }}>
              {shown.map((m) => {
                const j = jobs[m];
                return (
                  <div key={m} data-result={m} data-jstate={j.state} style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 10, padding: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                    <b style={{ fontSize: 13 }}>{title(m)}</b>
                    <div style={{ background: "repeating-conic-gradient(#d4d4d8 0 25%, #fafafa 0 50%) 50% / 16px 16px", borderRadius: 8, minHeight: 120, display: "grid", placeItems: "center", overflow: "hidden" }}>
                      {imgs[m] ? <img src={imgs[m]} alt={`نتیجهٔ ${title(m)}`} style={{ maxWidth: "100%", maxHeight: 170 }} /> : <span className="ws-muted" style={{ fontSize: 12, padding: 8, textAlign: "center" }}>{JOB_FA[j.state]}{j.state === "running" ? "…" : ""}</span>}
                    </div>
                    <span className="ws-muted" style={{ fontSize: 12 }}>{j.state === "ready" ? `آماده${j.seconds ? ` · ${fa(j.seconds)} ثانیه` : ""}${j.device ? ` · ${j.device}` : ""}` : j.message}</span>
                    {j.state === "ready" && <button type="button" className="ws-btn primary" disabled={busy} onClick={() => void use(m, j)} data-testid={`matting-use-${m}`}>استفاده از این نتیجه</button>}
                  </div>
                );
              })}
            </div>
          )}
          {note && <p className="fx-note" data-testid="matting-note" style={{ marginTop: 8 }}>{note}</p>}
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" disabled={busy || !st} onClick={() => void run([pick])} data-testid="matting-run">اجرا با مدلِ انتخاب‌شده</button>
          <button type="button" className="ws-btn" disabled={busy || !st || compareIds.length < 2} onClick={() => void run(compareIds)} data-testid="matting-compare" title="همان عکس با همهٔ مدل‌های آماده (و منتظرِ دانلود) کنارِ هم">مقایسه</button>
          <button type="button" className="ws-btn" onClick={() => void makeDefault()} data-testid="matting-default">{saved ? "ذخیره شد ✓" : "این مدل پیش‌فرض باشد"}</button>
          <button type="button" className="ws-btn" onClick={onClose}>بستن</button>
        </div>
      </div>
    </div>
  );
}
