import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Badge, Button, ErrorBox, Spinner, fa } from "../../../components/ui";

/**
 * «دستورها» ِ یک سرورِ پردازش (۱۴۰۵/۰۸/۱۹): به‌روزرسانی و راه‌اندازیِ دوباره، راه‌اندازیِ دوباره، ساختِ ویرایشگرها،
 * وضعیت و لاگ. از راهِ خودِ برنامهٔ NMarketing روی آن کامپیوتر (هر ۲۰ ثانیه سر می‌زند) — بی نصبِ جدا.
 * دسترسیِ کامل به خودِ کامپیوتر (برای هر پروژه‌ای) جداست و این‌جا نیست.
 */

type Last = {
  id?: string;
  action?: string;
  label?: string;
  state?: "sent" | "running" | "done" | "expired";
  ok?: boolean | null;
  by?: string;
  at?: string;
  started_at?: string;
  finished_at?: string;
  output?: string;
};

type CommandsState = {
  supported: boolean;
  online: boolean;
  agent: string;
  min_agent: string;
  busy: boolean;
  last: Last;
  actions: { key: string; label: string }[];
};

const CONFIRM: Record<string, string> = {
  update: "برنامهٔ سرورِ پردازش آخرین نسخه را بگیرد و دوباره باز شود؟ کارِ در حالِ اجرا دوباره به صف برمی‌گردد.",
  restart: "برنامهٔ سرورِ پردازش بسته و دوباره باز شود؟ کارِ در حالِ اجرا دوباره به صف برمی‌گردد.",
  build: "ویرایشگرهای عکس/ویدیو/صدا روی آن کامپیوتر ساخته شوند؟ ممکن است چند دقیقه طول بکشد.",
};

const ORDER = ["update", "restart", "status", "logs", "build"];

function when(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function NodeCommands({ nodeId, nodeName, onClose }: { nodeId: number; nodeName: string; onClose: () => void }) {
  const [st, setSt] = useState<CommandsState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<CommandsState>(`/compute/nodes/${nodeId}/commands/`);
      if (!alive.current) return;
      setSt(data);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    }
  }, [nodeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const busy = !!st?.busy;
  useEffect(() => {
    const t = window.setInterval(() => void load(), busy ? 3000 : 20000);
    return () => window.clearInterval(t);
  }, [load, busy]);

  const send = async (action: string) => {
    if (CONFIRM[action] && !window.confirm(`«${nodeName}»: ${CONFIRM[action]}`)) return;
    setSending(action);
    try {
      await api.post(`/compute/nodes/${nodeId}/commands/`, { action });
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      if (alive.current) setSending(null);
    }
  };

  const last = st?.last || {};
  const actions = st ? [...st.actions].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key)) : [];

  return (
    <div className="space-y-2 py-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
          دستورها — «{nodeName}»
        </span>
        {st && (st.online ? <Badge tone="ok">برنامه روشن است</Badge> : <Badge tone="bad">خاموش</Badge>)}
        <span className="flex-1" />
        <Button size="sm" variant="secondary" onClick={() => void load()}>
          <Icon name="refresh" size={13} /> تازه‌سازی
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          <Icon name="x" size={13} /> بستن
        </Button>
      </div>
      <ErrorBox message={err} />
      {!st ? (
        !err && <Spinner size={16} />
      ) : (
        <>
          {!st.online && (
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              برنامهٔ NMarketing روی آن کامپیوتر بسته است یا کامپیوتر خاموش است؛ دستورها فقط وقتی برنامه روشن است اجرا می‌شوند.
            </div>
          )}
          {st.online && !st.supported && (
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              برنامهٔ آن کامپیوتر (نسخهٔ <span dir="ltr">{st.agent || "?"}</span>) هنوز دستورها را نمی‌شناسد؛ با اولین اجرای{" "}
              <code dir="ltr">START.bat</code> خودش به نسخهٔ <span dir="ltr">{st.min_agent}</span> یا تازه‌تر به‌روز می‌شود.
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {actions.map((a) => (
              <Button
                key={a.key}
                size="sm"
                variant={a.key === "update" ? "primary" : "secondary"}
                disabled={!st.online || !st.supported || st.busy || sending !== null}
                onClick={() => void send(a.key)}
              >
                {sending === a.key ? <Spinner size={12} /> : null} {a.label}
              </Button>
            ))}
          </div>
          {last.action && (
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
                <span>آخرین دستور: «{last.label || last.action}»</span>
                {last.state === "sent" ? (
                  <Badge tone="info">
                    <Spinner size={10} /> فرستاده شد؛ تا ۲۰ ثانیه برداشته می‌شود
                  </Badge>
                ) : last.state === "running" ? (
                  <Badge tone="info">
                    <Spinner size={10} /> در حالِ اجرا…
                  </Badge>
                ) : last.state === "expired" ? (
                  <Badge tone="warn">بی‌جواب ماند</Badge>
                ) : last.ok ? (
                  <Badge tone="ok">انجام شد</Badge>
                ) : (
                  <Badge tone="bad">ناموفق</Badge>
                )}
                <span style={{ color: "var(--text-3)" }}>
                  {when(last.at)}
                  {last.by ? ` — ${last.by}` : ""}
                </span>
              </div>
              {last.output ? (
                <pre
                  dir="ltr"
                  className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg p-2 text-xs"
                  style={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text-2)" }}
                >
                  {last.output}
                </pre>
              ) : null}
              {(last.action === "update" || last.action === "restart") && last.state === "done" && last.ok && (
                <div className="text-xs" style={{ color: "var(--text-3)" }}>
                  برنامه حدودِ {fa(15)} ثانیه بعد دوباره وصل می‌شود؛ نسخهٔ تازه در ردیفِ بالا دیده می‌شود.
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
