import { useEffect, useMemo, useRef, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import { videoApi } from "../api";
import { Choice, FORMAT_CHOICES, QItem, choicesFrom, groupChoices, makeQueue, queueSummary, runQueue } from "../manual/r5queue";
import type { PanelProps } from "./types";

const digits = (s: string) => s.replace(/\d+/g, (m) => fa(Number(m)));
const STATE_TEXT: Record<QItem["state"], string> = { wait: "در انتظار", sending: "در حال فرستادن…", sent: "در صفِ رندر", failed: "ناموفق", cancelled: "لغو شد" };

/** صفِ چندخروجی: چند خروجی را یک‌جا انتخاب کنید؛ یکی‌یکی به صفِ رندر می‌روند (سرور هم‌زمان ۳ رندر می‌پذیرد، بقیه منتظر می‌مانند) */
export function OutputQueuePanel({ api }: PanelProps) {
  const [choices, setChoices] = useState<Choice[]>(FORMAT_CHOICES);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState<string[]>([]);
  const [items, setItems] = useState<QItem[]>([]);
  const [running, setRunning] = useState(false);
  const stop = useRef(false);
  useEffect(() => {
    let live = true;
    videoApi.catalogue(api.storeId).then((c) => { if (live) setChoices(choicesFrom(c.export.presets)); }).catch(() => null).finally(() => { if (live) setLoading(false); });
    return () => { live = false; stop.current = true; };
  }, [api.storeId]);
  const groups = useMemo(() => groupChoices(choices), [choices]);
  const toggle = (k: string) => setPicked((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
  const start = async () => {
    const queue = makeQueue(choices, picked, api.time);
    if (!queue.length) return;
    stop.current = false;
    setRunning(true);
    setItems(queue);
    const done = await runQueue(queue, (override) => api.op.renderOne(override), { onChange: setItems, cancelled: () => stop.current });
    setRunning(false);
    const bad = done.filter((i) => i.state === "failed").length;
    api.notice(bad ? digits(`${bad} خروجی فرستاده نشد؛ دلیلش کنارِ هر خروجی نوشته شده است.`) : "همهٔ خروجی‌ها در صفِ رندر هستند؛ از تبِ «خروجی» دنبال کنید.");
  };
  return (
    <div data-testid="outqueue-panel">
      <p className="ws-hint">خروجی‌هایی که می‌خواهید را تیک بزنید؛ همه با همین نسخهٔ پروژه ساخته می‌شوند. هر کدام که تمام شد در تبِ «خروجی» دانلودش می‌کنید.</p>
      {loading && <Spinner />}
      {groups.map((g) => (
        <fieldset key={g.group} className="oq-group" disabled={running}>
          <legend>{g.group}</legend>
          {g.items.map((c) => (
            <label key={c.key} className="fx-check">
              <input type="checkbox" checked={picked.includes(c.key)} onChange={() => toggle(c.key)} data-testid={`oq-pick-${c.key}`} />
              <span>{c.title}</span>
            </label>
          ))}
        </fieldset>
      ))}
      <div className="mk-top">
        <button type="button" className="ws-btn primary" disabled={running || picked.length === 0} onClick={() => void start()} data-testid="oq-start">
          {running ? "در حال فرستادن…" : picked.length ? digits(`فرستادنِ ${picked.length} خروجی به صفِ رندر`) : "اول خروجی‌ها را انتخاب کنید"}
        </button>
        {running && <button type="button" className="ws-btn" onClick={() => { stop.current = true; }} data-testid="oq-cancel">لغوِ باقی‌مانده‌ها</button>}
        <button type="button" className="ws-btn" onClick={() => api.setTab("out")} data-testid="oq-open-out">رفتن به تبِ خروجی</button>
      </div>
      {items.length > 0 && (
        <div data-testid="oq-list">
          <p className="ws-hint" data-testid="oq-summary">{digits(queueSummary(items))}</p>
          <ul className="oq-items">
            {items.map((i) => (
              <li key={i.key} data-state={i.state} data-testid="oq-item"><strong>{i.title}</strong> — {i.message ?? STATE_TEXT[i.state]}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
