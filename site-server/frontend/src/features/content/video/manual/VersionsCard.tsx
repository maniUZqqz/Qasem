import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import { Project, toApi } from "./model";

type Row = { name: string; label: string; saved_at: string; clips: number; length: number };

/** «نسخه‌های ذخیره‌شده»: نقطهٔ بازگشت برای پروژه. هر «ذخیرهٔ یک نقطه» یک نسخه می‌سازد؛ بازگرداندن، حالتِ فعلی را هم پیش از آن نگه می‌دارد. */
export default function VersionsCard({ storeId, projectId, root, onRestored }: { storeId: string; projectId: number | null; root: Project; onRestored: () => void }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const url = `/stores/${storeId}/editor/projects/${projectId}/versions/`;

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const { data } = await api.get<{ versions: Row[] }>(url);
      setRows(data.versions);
    } catch (err) {
      setMsg(errorMessage(err));
    }
  }, [projectId, url]);
  useEffect(() => {
    setRows(null);
    void load();
  }, [load]);

  if (!projectId) return <p className="ws-hint" data-testid="versions-none">پروژه بعد از اولین تغییر ذخیره می‌شود؛ بعد از آن می‌توانید نقطهٔ بازگشت بسازید.</p>;

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      await api.post(url, { label: "نقطهٔ ذخیره", data: toApi(root) });
      setMsg("یک نسخه ذخیره شد.");
      await load();
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function restore(name: string) {
    if (!window.confirm("پروژه به این نسخه برمی‌گردد (حالتِ فعلی هم به‌عنوان یک نسخه نگه داشته می‌شود). ادامه؟")) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.post(`${url}${name}/`);
      onRestored();
      setMsg("نسخه برگردانده شد.");
      await load();
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ws-card" data-testid="versions-card">
      <div className="ws-card-title">نسخه‌های ذخیره‌شده</div>
      <button type="button" className="ws-btn" onClick={() => void save()} disabled={busy} data-testid="version-save" title="الان یک نقطهٔ بازگشت بساز">
        {busy ? <Spinner size={12} /> : "◔"} ذخیرهٔ یک نقطه
      </button>
      {msg && <p className="ws-hint" data-testid="version-msg">{msg}</p>}
      {rows === null ? <Spinner size={14} /> : rows.length === 0 ? <p className="ws-hint">هنوز نسخه‌ای نیست. پیش از تغییرِ بزرگ «ذخیرهٔ یک نقطه» را بزنید.</p> : (
        <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 4 }}>
          {rows.map((r) => (
            <li key={r.name} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: ".78rem", color: "var(--text-2)" }} data-testid="version-row">
              <span style={{ flex: 1 }}>{r.label || "نسخه"} · <span dir="ltr">{r.saved_at}</span> · {fa(r.clips)} قطعه · {fa(Math.round(r.length))} ثانیه</span>
              <button type="button" className="ws-btn" disabled={busy} onClick={() => void restore(r.name)} data-testid="version-restore">بازگرداندن</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
