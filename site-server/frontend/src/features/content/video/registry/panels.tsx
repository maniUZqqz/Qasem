import { useEffect, useMemo, useState } from "react";

import { Badge, fa } from "../../../../components/ui";
import { comboOf, prettyCombo } from "./keymap";
import { resetOverrides, setKeyCapture, setOverride, useKeymap, useOverrides } from "./keystore";
import { norm } from "./search";
import { MENUS, PanelDef, PanelProps } from "./types";
import { ALL_FEATURES } from "./features";

/** تاریخچهٔ تغییرها: هر گام یک خط؛ روی هر کدام بزنید تا به همان لحظه برگردید (گام‌های جلوتر خاکستری و قابلِ برگشت‌اند) */
function HistoryPanel({ api }: PanelProps) {
  const { entries, index } = api.history;
  const rows = useMemo(() => entries.map((e, i) => ({ label: e.label, i })).reverse(), [entries]);
  return (
    <div data-testid="history-panel">
      <p className="ws-hint">{fa(entries.length - 1)} تغییر ثبت شده است. روی هر خط بزنید تا پروژه به همان لحظه برگردد؛ دوباره یک تغییرِ تازه بدهید، گام‌های جلوتر پاک می‌شوند.</p>
      <ol className="rg-hist" reversed>
        {rows.map(({ label, i }) => (
          <li key={i}>
            <button type="button" className={`rg-hist-row ${i === index ? "is-now" : ""} ${i > index ? "is-future" : ""}`} onClick={() => api.jumpHistory(i)} data-testid="history-row" aria-current={i === index}>
              <span className="rg-hist-n">{fa(i)}</span>
              <span className="rg-hist-l">{label}</span>
              {i === index && <Badge tone="brand">الان</Badge>}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** ویرایشِ میان‌برها: برای هر ویژگی یک کلیدِ دلخواه؛ تداخل را می‌گوید و پیشنهادِ جابه‌جایی می‌دهد */
function ShortcutEditor({ props }: PanelProps) {
  const km = useKeymap(ALL_FEATURES);
  const overrides = useOverrides();
  const [q, setQ] = useState("");
  const [capturing, setCapturing] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; combo: string; other: string } | null>(null);
  const rows = useMemo(() => {
    const query = norm(q);
    return ALL_FEATURES.filter((f) => !query || norm(`${f.title} ${f.en ?? ""} ${(f.words ?? []).join(" ")}`).includes(query));
  }, [q]);
  const changed = Object.keys(overrides).length;

  useEffect(() => {
    if (!capturing) return;
    setKeyCapture(true);
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") {
        setCapturing(null);
        return;
      }
      const combo = comboOf(e);
      if (!combo) return;
      const other = km.owner(combo, capturing);
      if (other) setPending({ id: capturing, combo, other: other.id });
      else setOverride(capturing, combo);
      setCapturing(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      setKeyCapture(false);
    };
  }, [capturing, km]);

  return (
    <div data-testid="shortcut-editor">
      <p className="ws-hint">
        روی «تغییر» بزنید و کلیدِ دلخواه را فشار دهید (Esc = انصراف). تغییرها فقط در همین مرورگر ذخیره می‌شود. روی صفحه‌کلیدِ فارسی هم کار می‌کند.
      </p>
      <div className="rg-ke-top">
        <input className="u-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در ابزارها…" aria-label="جستجو در ابزارها" data-testid="ke-search" />
        <button type="button" className={`ws-btn ${props?.reset ? "is-on" : ""}`} disabled={!changed} onClick={() => resetOverrides()} data-testid="ke-reset">
          بازگرداندنِ همه به پیش‌فرض {changed ? `(${fa(changed)})` : ""}
        </button>
      </div>
      {pending && (
        <div className="rg-ke-warn" role="alert" data-testid="ke-conflict">
          «{prettyCombo(pending.combo)}» الان برای «{ALL_FEATURES.find((f) => f.id === pending.other)?.title}» است. جابه‌جا شود؟
          <button type="button" className="ws-btn" onClick={() => { setOverride(pending.other, ""); setOverride(pending.id, pending.combo); setPending(null); }}>بله، به این ابزار بده</button>
          <button type="button" className="ws-btn" onClick={() => setPending(null)}>انصراف</button>
        </div>
      )}
      <table className="rg-ke">
        <tbody>
          {rows.map((f) => {
            const eff = km.effective(f.id);
            const mod = Object.prototype.hasOwnProperty.call(overrides, f.id);
            return (
              <tr key={f.id} data-feature={f.id}>
                <td className="rg-ke-menu">{MENUS.find((m) => m.id === f.menu)?.title}</td>
                <td className="rg-ke-title">{f.title}</td>
                <td className="rg-ke-key" dir="ltr">
                  {capturing === f.id ? <i className="rg-ke-wait">کلید را بزنید…</i> : eff ? <kbd>{prettyCombo(eff)}</kbd> : <span className="rg-ke-none">—</span>}
                </td>
                <td className="rg-ke-act">
                  <button type="button" className="ws-btn" onClick={() => { setPending(null); setCapturing(f.id); }} data-testid="ke-change">تغییر</button>
                  {eff && <button type="button" className="ws-btn" onClick={() => setOverride(f.id, "")} aria-label="برداشتنِ میان‌بر" title="برداشتنِ میان‌بر">×</button>}
                  {mod && <button type="button" className="ws-btn" onClick={() => setOverride(f.id, null)} title="برگرداندن به پیش‌فرض">↺</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export const CORE_PANELS: PanelDef[] = [
  { id: "history", title: "تاریخچهٔ تغییرها", size: "sm", Component: HistoryPanel },
  { id: "shortcuts", title: "ویرایشِ میان‌برها", size: "lg", Component: ShortcutEditor },
];
