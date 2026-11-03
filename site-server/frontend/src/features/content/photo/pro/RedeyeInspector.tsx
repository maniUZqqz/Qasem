import { fa } from "../../../../components/ui";
import type { Hist } from "./panelTypes";
import type { ProState, RedeyeLayer } from "./types";

/** بازرسِ لایهٔ «قرمزیِ چشم»: فهرستِ چشم‌ها (حذف)، شدت و تیره‌کردن. افزودنِ چشم با ابزارِ «قرمزیِ چشم» (R) روی عکس. */
export default function RedeyeInspector({ layer, hist }: { layer: RedeyeLayer; hist: Hist }) {
  const id = layer.id;
  const map = (fn: (l: RedeyeLayer) => RedeyeLayer) => (s: ProState): ProState => ({
    ...s, layers: s.layers.map((l) => (l.id === id && l.type === "redeye" ? fn(l) : l)),
  });
  const slider = (key: "amount" | "darken", label: string, testId: string) => (
    <label className="ws-slider">
      <span className="ws-slider-head">
        <span>{label}</span>
        <span className="ws-slider-val" dir="ltr">{fa(Math.round(layer[key] * 100))}</span>
      </span>
      <input
        type="range" min={0} max={1} step={0.01} value={layer[key]} aria-label={label} data-testid={testId}
        onChange={(e) => hist.live(map((l) => ({ ...l, [key]: Number(e.target.value) })))}
        onPointerUp={() => hist.end(label)} onKeyUp={() => hist.end(label)} onBlur={() => hist.end(label)}
      />
    </label>
  );
  return (
    <div data-testid="redeye-inspector">
      <div className="pn-sub">
        <div className="pn-sub-head"><span>قرمزیِ چشم</span><span className="pn-count" data-testid="redeye-count">{fa(layer.eyes.length)} چشم</span></div>
        <p className="pn-hint">با ابزارِ «قرمزیِ چشم» (R) روی مردمکِ قرمز کلیک کنید؛ هر کلیک یک چشم به این لایه می‌افزاید (تا ۱۶ تا).</p>
        {layer.eyes.length > 0 && (
          <ol className="pn-list" data-testid="redeye-eyes" style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
            {layer.eyes.map((e, i) => (
              <li key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }} data-eye={i}>
                <span>چشم {fa(i + 1)}</span>
                <span dir="ltr" style={{ opacity: 0.7 }}>{fa(Math.round(e.x * 1000) / 10)}٪ ، {fa(Math.round(e.y * 1000) / 10)}٪ · r {fa(Math.round(e.r * 1000) / 10)}٪</span>
                <span style={{ flex: 1 }} />
                <button type="button" className="pn-btn" data-testid={`eye-del-${i}`} aria-label={`حذفِ چشم ${i + 1}`}
                  onClick={() => hist.apply("حذفِ چشم", map((l) => ({ ...l, eyes: l.eyes.filter((_, k) => k !== i) })))}>
                  حذف
                </button>
              </li>
            ))}
          </ol>
        )}
        {slider("amount", "شدتِ اصلاح", "redeye-amount")}
        {slider("darken", "تیره‌کردنِ مردمک", "redeye-darken")}
        <div className="pn-actions">
          <button type="button" className="pn-btn" disabled={!layer.eyes.length} data-testid="redeye-clear"
            onClick={() => hist.apply("پاک کردنِ چشم‌ها", map((l) => ({ ...l, eyes: [] })))}>
            پاک کردنِ همهٔ چشم‌ها
          </button>
        </div>
      </div>
    </div>
  );
}
