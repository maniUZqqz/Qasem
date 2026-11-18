import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../api/client";
import { Alert, Button, Spinner } from "./ui";

/**
 * «در صف تا روشن شدنِ سرورِ پردازش» — نشانهٔ درخواستِ هوش مصنوعی که هر دو مسیر (گره و متیس) جواب ندادند و سایت آن را در صفِ ماندگار گذاشته
 * (backend/apps/compute/deferred.py). پاسخِ همان لحظه همان پیش‌نویسِ فرمولی است + `queued`؛ این هوک وضعیت را هر ۵ ثانیه می‌پرسد،
 * شناسه را در localStorage نگه می‌دارد (با بستن و بازکردنِ صفحه هم ادامه می‌دهد) و وقتی نتیجه رسید `onResult` را صدا می‌زند.
 * نتیجه همان JSONِ پاسخِ همزمانِ همان ویژگی است.
 */

export type Queued = { uid: string; feature?: string; label?: string; message?: string; state?: string; detail?: string; meta?: Record<string, unknown> };
type Status = {
  uid: string;
  state: "queued" | "running" | "done" | "failed" | "cancelled";
  message?: string;
  detail?: string;
  label?: string;
  result?: unknown;
  error?: string;
  attempts?: number;
};

export const QUEUED_TEXT = "در صف تا روشن شدنِ سرورِ پردازش";
const POLL_MS = 5000;

function storageKey(feature: string, scope: string | number) {
  return `nm.queuedAi.${feature}.${scope}`;
}
function read(feature: string, scope: string | number): Queued | null {
  try {
    const raw = localStorage.getItem(storageKey(feature, scope));
    return raw ? (JSON.parse(raw) as Queued) : null;
  } catch {
    return null;
  }
}
function write(feature: string, scope: string | number, value: Queued | null) {
  try {
    if (value) localStorage.setItem(storageKey(feature, scope), JSON.stringify(value));
    else localStorage.removeItem(storageKey(feature, scope));
  } catch {
    /* حالتِ خصوصی: مهم نیست */
  }
}

export function QueuedAiBanner({
  queued,
  status,
  onCancel,
  onDismiss,
}: {
  queued: Queued | null;
  status: Status | null;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  if (!queued && !status) return null;
  const state = status?.state ?? "queued";
  if (state === "done") {
    return (
      <div data-testid="queued-ai" data-state="done">
        <Alert tone="ok" action={<Button size="sm" variant="secondary" onClick={onDismiss}>بستن</Button>}>
          {status?.message === "آماده شد" || !status?.message ? "نسخهٔ هوش مصنوعی رسید و جایگزین شد." : status.message}
        </Alert>
      </div>
    );
  }
  if (state === "failed" || state === "cancelled") {
    return (
      <div data-testid="queued-ai" data-state={state}>
        <Alert tone={state === "failed" ? "bad" : "neutral"} action={<Button size="sm" variant="secondary" onClick={onDismiss}>بستن</Button>}>
          {state === "cancelled" ? "درخواستِ صف‌دار لغو شد." : `درخواستِ صف‌دار انجام نشد: ${status?.error || status?.message || ""}`}
        </Alert>
      </div>
    );
  }
  const label = queued?.label || status?.label || "";
  return (
    <div data-testid="queued-ai" data-state={state}>
      <Alert
        tone="info"
        title={state === "running" ? "در حالِ اجرا روی سرورِ پردازش…" : QUEUED_TEXT}
        action={<Button size="sm" variant="secondary" onClick={onCancel}>لغو</Button>}
      >
        <span className="inline-flex items-center gap-2">
          <Spinner size={13} />
          {label ? `«${label}» ` : ""}
          خودکار اجرا می‌شود و نتیجه همین‌جا جای پیش‌نویسِ آماده می‌نشیند؛ می‌توانید صفحه را ببندید و بعداً برگردید.
          {status?.attempts ? ` (${status.attempts} بار امتحان شد؛ هنوز هوش مصنوعی در دسترس نبود.)` : ""}
        </span>
      </Alert>
    </div>
  );
}

/**
 * @param feature کلیدِ ویژگی (فقط برای ذخیرهٔ شناسه در مرورگر)
 * @param scope   شناسهٔ فروشگاه
 * @param onResult نتیجه رسید: `result` = همان JSON ِ پاسخِ همزمان
 */
export function useQueuedAi<T = unknown>(feature: string, scope: string | number, onResult: (result: T, status: Status, queued: Queued | null) => void) {
  const [queued, setQueuedState] = useState<Queued | null>(() => read(feature, scope));
  const [status, setStatus] = useState<Status | null>(null);
  const cb = useRef(onResult);
  cb.current = onResult;
  const queuedRef = useRef<Queued | null>(queued);
  queuedRef.current = queued;
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // شناسهٔ ذخیره‌شدهٔ فروشگاهِ دیگر (تغییرِ scope)
  useEffect(() => {
    setQueuedState(read(feature, scope));
    setStatus(null);
  }, [feature, scope]);

  const setQueued = useCallback(
    (q: Queued | null | undefined) => {
      write(feature, scope, q ?? null);
      setQueuedState(q ?? null);
      setStatus(null);
    },
    [feature, scope],
  );

  const clear = useCallback(() => {
    write(feature, scope, null);
    setQueuedState(null);
    setStatus(null);
  }, [feature, scope]);

  const uid = queued?.uid;
  useEffect(() => {
    if (!uid) return;
    let stop = false;
    const tick = async () => {
      if (stop || document.visibilityState !== "visible") return;
      try {
        const { data } = await api.get<Status>(`/compute/deferred/${uid}/`);
        if (stop || !alive.current) return;
        setStatus(data);
        if (data.state === "done") {
          write(feature, scope, null);
          stop = true;
          cb.current(data.result as T, data, queuedRef.current);
        } else if (data.state === "failed" || data.state === "cancelled") {
          write(feature, scope, null);
          stop = true;
        }
      } catch (e) {
        const code = (e as { response?: { status?: number } })?.response?.status;
        if (code === 404 && !stop && alive.current) {
          write(feature, scope, null);
          setQueuedState(null);                    // دیگر در صف نیست (پاک شده یا از ۷ روز گذشته)
          stop = true;
        } else if (!alive.current) {
          stop = true;
        } else {
          void errorMessage(e);                    // خطای گذرای شبکه: دور بعد دوباره
        }
      }
    };
    void tick();
    const t = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      stop = true;
      window.clearInterval(t);
    };
  }, [uid, feature, scope]);

  const cancel = useCallback(async () => {
    if (!uid) return;
    try {
      await api.post(`/compute/deferred/${uid}/cancel/`);
    } catch {
      /* همان وضعیتِ بعدی را نشان می‌دهد */
    }
    clear();
  }, [uid, clear]);

  const banner = <QueuedAiBanner queued={queued} status={status} onCancel={() => void cancel()} onDismiss={clear} />;
  return { queued, status, setQueued, clear, banner };
}
