import { SAFE_GENERAL, SafeZone } from "./SafeZones";

const pct = (f: number) => `${(Math.max(0, Math.min(1, f)) * 100).toFixed(2)}%`;

/**
 * ناحیهٔ امن روی مانیتور. «عمومی» = همان دو کادرِ خط‌چینِ ۵٪ و ۱۰٪؛
 * ناحیهٔ پلتفرم = نوارهای قرمزِ نیمه‌شفاف روی حاشیه‌هایی که رابطِ برنامه می‌پوشاند (زیرنویس و لوگو را آن‌جا نگذارید).
 */
export default function SafeZoneLayer({ zoneKey, zone }: { zoneKey: string; zone?: SafeZone }) {
  if (zoneKey === SAFE_GENERAL) {
    return (
      <div className="sz-layer" data-testid="safezone-general" aria-hidden>
        <i style={{ position: "absolute", inset: "5%", border: "1px dashed rgba(255,255,255,.55)", pointerEvents: "none" }} />
        <i style={{ position: "absolute", inset: "10%", border: "1px dashed rgba(255,255,255,.35)", pointerEvents: "none" }} />
      </div>
    );
  }
  if (!zone) return null;
  const { top, bottom, left, right } = zone.margins;
  return (
    <div className="sz-layer" data-testid={`safezone-${zone.key}`} aria-hidden title={zone.hint}>
      <i className="sz-band" style={{ left: 0, right: 0, top: 0, height: pct(top) }} />
      <i className="sz-band" style={{ left: 0, right: 0, bottom: 0, height: pct(bottom) }} />
      <i className="sz-band" style={{ left: 0, width: pct(left), top: pct(top), bottom: pct(bottom) }} />
      <i className="sz-band" style={{ right: 0, width: pct(right), top: pct(top), bottom: pct(bottom) }} />
      <i className="sz-edge" style={{ left: pct(left), right: pct(right), top: pct(top), bottom: pct(bottom) }} />
      <span className="sz-label">{zone.title}</span>
    </div>
  );
}
