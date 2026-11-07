import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../../api/client";
import { Button, fa } from "../../../components/ui";
import {
  Env, FinishReply, HttpFail, Transport, UploadCancelled, UploadFailed, UploadState, fmtBytes, fmtEta, runUpload,
} from "./upload";

function asHttpFail(err: unknown): HttpFail {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status ?? 0;
    const e = (err.response?.data as { error?: { message?: string; code?: string; received?: number } } | undefined)?.error;
    return new HttpFail(status, e?.message ?? "", e?.code ?? "", e?.received);
  }
  return new HttpFail(0, "");
}

export function apiTransport<V>(storeId: string): Transport<V> {
  const base = `/stores/${storeId}/videos/uploads/`;
  const wrap = async <T,>(p: Promise<{ data: T }>): Promise<T> => {
    try {
      return (await p).data;
    } catch (e) {
      throw asHttpFail(e);
    }
  };
  return {
    start: (body) => wrap(api.post(base, body, { timeout: 30000 })),
    chunk: (uid, offset, blob, signal, onBytes) =>
      wrap(api.put(`${base}${uid}/`, blob, {
        params: { offset }, headers: { "Content-Type": "application/octet-stream" }, signal, timeout: 120000,
        onUploadProgress: (e) => onBytes(e.loaded ?? 0),
      })),
    status: (uid) => wrap(api.get(`${base}${uid}/`, { timeout: 20000 })),
    finish: (uid) => wrap(api.post<FinishReply<V>>(`${base}${uid}/finish/`, {}, { timeout: 120000 })),
    cancel: async (uid) => {
      try {
        await api.delete(`${base}${uid}/`, { timeout: 15000 });
      } catch { /* best effort */ }
    },
  };
}

export const browserEnv: Env = {
  sleep: (ms, signal) =>
    new Promise((resolve, reject) => {
      const t = window.setTimeout(resolve, ms);
      signal.addEventListener("abort", () => { window.clearTimeout(t); reject(new UploadCancelled()); }, { once: true });
    }),
  online: () => navigator.onLine !== false,
  waitOnline: (signal) =>
    new Promise((resolve, reject) => {
      if (navigator.onLine !== false) return resolve();
      const done = () => { cleanup(); resolve(); };
      const stop = () => { cleanup(); reject(new UploadCancelled()); };
      const poll = window.setInterval(() => { if (navigator.onLine !== false) done(); }, 3000);
      const cleanup = () => { window.removeEventListener("online", done); window.clearInterval(poll); signal.removeEventListener("abort", stop); };
      window.addEventListener("online", done);
      signal.addEventListener("abort", stop, { once: true });
    }),
  now: () => Date.now(),
};

export type VideoUpload<V = unknown> = {
  state: UploadState | null;
  active: boolean;
  /** پیامِ خطای آخر (فارسی) */
  error: string | null;
  /** فایل برای «دوباره امتحان» نگه داشته می‌شود */
  retryable: boolean;
  start: (file: File) => Promise<FinishReply<V> | null>;
  retry: () => Promise<FinishReply<V> | null>;
  cancel: () => void;
  dismiss: () => void;
};

/** هوکِ آپلودِ ادامه‌پذیر برای یک فروشگاه. `start` در موفقیت جوابِ سرور را می‌دهد، در خطا/لغو null (و پیامِ فارسی در `error`). */
export function useVideoUpload<V = unknown>(storeId: string): VideoUpload<V> {
  const [state, setState] = useState<UploadState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(false);
  const ctl = useRef<AbortController | null>(null);
  const lastFile = useRef<File | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; ctl.current?.abort(); }, []);

  const go = useCallback(async (file: File): Promise<FinishReply<V> | null> => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    lastFile.current = file;
    setError(null);
    setActive(true);
    setState({ phase: "starting", sent: 0, total: file.size, speed: 0, etaSec: null, attempt: 1, maxAttempts: 10, message: "در حالِ آماده‌سازی…", resumedFrom: null, fatal: false });
    try {
      const done = await runUpload<V>(file, { transport: apiTransport<V>(storeId), env: browserEnv, signal: c.signal, onState: (s) => alive.current && setState(s) });
      if (alive.current) { lastFile.current = null; setActive(false); }
      return done;
    } catch (e) {
      if (!alive.current) return null;
      setActive(false);
      if (e instanceof UploadCancelled) {
        lastFile.current = null;
        setState((s) => (s ? { ...s, phase: "cancelled", message: "آپلود لغو شد." } : s));
        return null;
      }
      const msg = e instanceof UploadFailed ? e.message : "آپلود انجام نشد؛ دوباره امتحان کنید.";
      setError(msg);
      setState((s) => (s ? { ...s, phase: "error", fatal: true, message: msg } : s));
      return null;
    }
  }, [storeId]);

  const cancel = useCallback(() => {
    ctl.current?.abort();
  }, []);
  const retry = useCallback(async () => (lastFile.current ? go(lastFile.current) : null), [go]);
  const dismiss = useCallback(() => { setState(null); setError(null); lastFile.current = null; }, []);
  return { state, active, error, retryable: !!lastFile.current && !active && !!error, start: go, retry, cancel, dismiss };
}

/** نوارِ پیشرفتِ آپلود: درصد، حجم، سرعت، زمانِ مانده، وضعیتِ تلاشِ دوباره / قطعیِ اینترنت و دکمه‌های لغو و «دوباره امتحان». */
export function UploadProgress({ up, compact = false }: { up: VideoUpload; compact?: boolean }) {
  const s = up.state;
  if (!s || s.phase === "done" || s.phase === "cancelled") return s?.phase === "cancelled" ? <p className="text-xs" style={{ color: "var(--text-3)" }} data-testid="upload-cancelled">آپلود لغو شد.</p> : null;
  const pct = s.total ? Math.min(100, Math.floor((s.sent / s.total) * 100)) : 0;
  const tone = s.phase === "error" ? "var(--bad)" : s.phase === "offline" || s.phase === "retrying" ? "var(--warn)" : "var(--brand)";
  const speed = s.speed > 1 ? ` · ${fmtBytes(s.speed)} بر ثانیه` : "";
  const eta = fmtEta(s.etaSec);
  return (
    <div className={compact ? "up-box up-compact" : "up-box"} data-testid="upload-progress" data-phase={s.phase} role="group" aria-label="پیشرفتِ آپلود" style={{ margin: "8px 0" }}>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} style={{ height: 8, borderRadius: 4, background: "var(--line)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone, transition: "width .3s" }} data-testid="upload-bar" />
      </div>
      <div className="text-xs" style={{ color: "var(--text-2)", marginTop: 4 }} data-testid="upload-text">
        {s.phase === "finishing" ? "در حالِ بررسیِ فایل…" : <>{fa(pct)}٪ — {fmtBytes(s.sent)} از {fmtBytes(s.total)}{speed}{eta && s.phase === "uploading" ? ` · حدود ${eta} مانده` : ""}</>}
      </div>
      {s.message && (
        <div className="text-xs" style={{ color: tone, marginTop: 2 }} role={s.phase === "error" ? "alert" : "status"} data-testid="upload-message">{s.message}</div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
        {up.active && <Button variant="secondary" onClick={up.cancel} data-testid="upload-cancel">لغو</Button>}
        {up.retryable && <Button onClick={() => void up.retry()} data-testid="upload-retry">ادامه / دوباره امتحان</Button>}
        {!up.active && s.phase === "error" && <Button variant="secondary" onClick={up.dismiss} data-testid="upload-dismiss">بستن</Button>}
      </div>
    </div>
  );
}
