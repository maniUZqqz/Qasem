import { num } from "../../format";

export type BarItem = { key: string; label: string; count: number };

/**
 * Horizontal bars: the label and the count above, the bar proportional to the biggest count.
 * Honest by construction - an empty list says so instead of drawing nothing.
 */
export default function HBars({ items, empty = "هنوز چیزی ثبت نشده." }: { items: BarItem[]; empty?: string }) {
  const shown = items.filter((i) => i.count > 0);
  if (!shown.length) {
    return (
      <p className="py-6 text-center text-sm" style={{ color: "var(--text-3)" }}>
        {empty}
      </p>
    );
  }
  const max = Math.max(...shown.map((i) => i.count), 1);
  return (
    <ul className="space-y-2.5">
      {shown.map((item) => (
        <li key={item.key} data-testid={`bar-${item.key}`}>
          <div className="mb-1 flex items-center justify-between gap-3 text-sm">
            <span style={{ color: "var(--text-2)" }}>{item.label}</span>
            <span className="u-num font-bold" style={{ color: "var(--text)" }}>
              {num(item.count)}
            </span>
          </div>
          <div className="u-meter" role="presentation">
            <span style={{ width: `${Math.max(3, (item.count / max) * 100)}%`, background: "var(--brand)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
