import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Badge, Button, ErrorBox, Spinner, fa } from "../../../components/ui";

/**
 * «کنترل از راهِ دور» ِ یک سرورِ پردازش (۱۴۰۵/۰۸/۱۹).
 *
 * سرورِ پردازش IP ندارد؛ پس از یک بار اجرای Setup-Remote.bat روی خودش، یک تونل به همین سایت باز نگه می‌دارد و سایت از
 * همان راه دستورهای ثابت را اجرا می‌کند (nm_control.py روی آن کامپیوتر). این‌جا فقط همین دستورهای ثابت هست؛
 * دسترسیِ کامل (فایل‌ها، دستورِ دلخواه) فقط برای مدیرِ سرور از خطِ فرمان است (nm-node).
 */

type Last = {
  action?: string;
  label?: string;
  running?: boolean;
  stale?: boolean;
  by?: string;
  started_at?: string;
  finished_at?: string;
  exit_code?: number | null;
  ok?: boolean;
  output?: string;
};

type RemoteState = {
  enrolled: boolean;
  tunnel_up?: boolean;
  banner?: string;
  listen_port?: number;
  user?: string;
  home?: string;
  windows?: string;
  enrolled_at?: string;
  last?: Last;
  actions: { key: string; label: string }[];
};

/** دستورهایی که کارِ جاری را می‌بُرند: پیش از فرستادن تأیید بخواه */
const CONFIRM: Record<string, string> = {
  stop: "برنامهٔ سرورِ پردازش بسته شود؟ کارِ در حالِ اجرا دوباره به صف برمی‌گردد.",
  restart: "برنامهٔ سرورِ پردازش بسته و دوباره باز شود؟ کارِ در حالِ اجرا دوباره به صف برمی‌گردد.",
  update: "برنامه بسته شود، آخرین نسخه گرفته شود و دوباره باز شود؟ کارِ در حالِ اجرا دوباره به صف برمی‌گردد.",
  build: "ویرایشگرهای عکس/ویدیو/صدا روی آن کامپیوتر دوباره ساخته شوند؟ ممکن است چند دقیقه طول بکشد.",
};

const ORDER = ["status", "update", "restart", "start", "stop", "logs", "build"];

function when(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function NodeRemote({ nodeId, nodeName, onClose }: { nodeId: number; nodeName: string; onClose: () => void }) {
  const [st, setSt] = useState<RemoteState | null>(null);
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
      const { data } = await api.get<RemoteState>(`/compute/nodes/${nodeId}/remote/`);
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

  // تا دستور در حالِ اجراست هر ۳ ثانیه؛ وگرنه هر ۲۰ ثانیه (وضعیتِ تونل)
  const running = !!st?.last?.running;
  useEffect(() => {
    const t = window.setInterval(() => void load(), running ? 3000 : 20000);
    return () => window.clearInterval(t);
  }, [load, running]);

  const send = async (action: string) => {
    if (CONFIRM[action] && !window.confirm(`«${nodeName}»: ${CONFIRM[action]}`)) return;
    setSending(action);
    try {
      await api.post(`/compute/nodes/${nodeId}/control/`, { action });
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      if (alive.current) setSending(null);
    }
  };

  const head = (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
        کنترل از راهِ دور — «{nodeName}»
      </span>
      {st?.enrolled &&
        (st.tunnel_up ? (
          <Badge tone="ok">وصل است</Badge>
        ) : (
          <Badge tone="bad">قطع است</Badge>
        ))}
      <span className="flex-1" />
      <Button size="sm" variant="secondary" onClick={() => void load()}>
        <Icon name="refresh" size={13} /> تازه‌سازی
      </Button>
      <Button size="sm" variant="ghost" onClick={onClose}>
        <Icon name="x" size={13} /> بستن
      </Button>
    </div>
  );

  if (!st) {
    return (
      <div className="space-y-2 py-1">
        {head}
        <ErrorBox message={err} />
        {!err && <Spinner size={16} />}
      </div>
    );
  }

  if (!st.enrolled) {
    return (
      <div className="space-y-2 py-1">
        {head}
        <ErrorBox message={err} />
        <div className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          این سرور هنوز کنترل از راهِ دور ندارد. فقط <b>یک بار</b> روی خودِ آن کامپیوتر، در همان پوشه‌ای که{" "}
          <code dir="ltr">START.bat</code> هست، فایلِ <code dir="ltr">Setup-Remote.bat</code> را دو بار کلیک کنید و
          پیامِ ویندوز («Yes») را تأیید کنید. بعد از آن از همین‌جا می‌شود برنامه را بست، باز کرد، به‌روز کرد و وضعیتش را دید —
          بی آن‌که کسی پشتِ آن کامپیوتر باشد.
        </div>
      </div>
    );
  }

  const last = st.last || {};
  const actions = [...st.actions].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));

  return (
    <div className="space-y-2 py-1">
      {head}
      <ErrorBox message={err} />
      {!st.tunnel_up && (
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          آن کامپیوتر خاموش است یا اینترنتش قطع است. تونل با روشن شدنِ ویندوز خودش وصل می‌شود (حتی پیش از باز شدنِ برنامه).
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {actions.map((a) => (
          <Button
            key={a.key}
            size="sm"
            variant={a.key === "update" ? "primary" : a.key === "stop" ? "danger" : "secondary"}
            disabled={!st.tunnel_up || running || sending !== null}
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
            {last.running ? (
              <Badge tone="info">
                <Spinner size={10} /> در حالِ اجرا…
              </Badge>
            ) : last.stale ? (
              <Badge tone="warn">بی‌پاسخ ماند</Badge>
            ) : last.ok ? (
              <Badge tone="ok">انجام شد</Badge>
            ) : (
              <Badge tone="bad">ناموفق{last.exit_code != null ? ` (کد ${fa(last.exit_code)})` : ""}</Badge>
            )}
            <span style={{ color: "var(--text-3)" }}>
              {when(last.started_at)}
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
        </div>
      )}
      <div className="text-xs" style={{ color: "var(--text-3)" }} dir="auto">
        {st.home ? (
          <>
            پوشهٔ برنامه: <code dir="ltr">{st.home}</code> —{" "}
          </>
        ) : null}
        کاربرِ ویندوز: <code dir="ltr">{st.user}</code>
        {st.enrolled_at ? ` — راه‌اندازی: ${when(st.enrolled_at)}` : ""}
      </div>
    </div>
  );
}
