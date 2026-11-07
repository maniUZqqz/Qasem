/**
 * صفِ چندخروجی: چند خروجی (ریلز، یوتیوب، تلگرام، GIF، فقط صدا…) را یک‌جا انتخاب می‌کنید و یکی‌یکی به صفِ رندرِ سرور می‌روند.
 * سرور هم‌زمان حداکثر ۳ رندر را در صف می‌پذیرد؛ این‌جا هر خروجی تا جا باز شود منتظر می‌ماند و خطای یکی بقیه را نمی‌ایستاند.
 * منطقِ خالص (بدونِ React)؛ آزمون: tests/video-r5-queue.test.ts.
 */
export type QState = "wait" | "sending" | "sent" | "failed" | "cancelled";
export type QItem = { key: string; title: string; override: Record<string, unknown>; state: QState; message?: string };
export type Choice = { key: string; title: string; group: string; override: Record<string, unknown> };
export type SendResult = { ok: true } | { ok: false; full?: boolean; message: string };

export const FORMAT_CHOICES: Choice[] = [
  { key: "fmt:gif", title: "GIF متحرک", group: "خروجی‌های ویژه", override: { format: "gif" } },
  { key: "fmt:audio", title: "فقط صدا (M4A)", group: "خروجی‌های ویژه", override: { format: "audio" } },
  { key: "fmt:frame", title: "عکسِ فریمِ سرِ پخش (JPG)", group: "خروجی‌های ویژه", override: { format: "frame" } },
];

/** پریست‌های کاتالوگِ سرور + خروجی‌های ویژه، گروه‌بندی‌شده */
export function choicesFrom(presets: { key: string; title: string; group: string }[]): Choice[] {
  return [...presets.map((p) => ({ key: `preset:${p.key}`, title: p.title, group: p.group, override: { preset: p.key, format: "mp4" } })), ...FORMAT_CHOICES];
}

export function groupChoices(choices: Choice[]): { group: string; items: Choice[] }[] {
  const out: { group: string; items: Choice[] }[] = [];
  for (const c of choices) {
    let g = out.find((x) => x.group === c.group);
    if (!g) out.push((g = { group: c.group, items: [] }));
    g.items.push(c);
  }
  return out;
}

export function makeQueue(choices: Choice[], keys: string[], playhead = 0): QItem[] {
  return keys.flatMap((k) => {
    const c = choices.find((x) => x.key === k);
    if (!c) return [];
    const override = c.override.format === "frame" ? { ...c.override, frame_t: Math.max(0, Math.round(playhead * 100) / 100) } : { ...c.override };
    return [{ key: c.key, title: c.title, override, state: "wait" as QState }];
  });
}

export const WAIT_MS = 6000;
export const MAX_WAITS = 100;                // ≈ ۱۰ دقیقه برای هر خروجی

/**
 * خروجی‌ها را به ترتیب می‌فرستد. `send` یک درخواستِ رندر است؛ اگر صفِ سرور پر باشد (full) صبر و دوباره تلاش می‌کند.
 * `cancelled()` که درست شد، خروجی‌های نرسیده «لغو» می‌شوند (آنچه فرستاده شده در صفِ سرور می‌ماند).
 */
export async function runQueue(
  items: QItem[], send: (override: Record<string, unknown>) => Promise<SendResult>,
  o: { wait?: (ms: number) => Promise<void>; onChange?: (items: QItem[]) => void; cancelled?: () => boolean } = {},
): Promise<QItem[]> {
  const wait = o.wait ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const list = items.map((i) => ({ ...i }));
  const emit = () => o.onChange?.(list.map((i) => ({ ...i })));
  for (const it of list) {
    if (it.state !== "wait") continue;
    let waits = 0;
    for (;;) {
      if (o.cancelled?.()) { it.state = "cancelled"; it.message = "لغو شد"; emit(); break; }
      it.state = "sending"; it.message = waits ? "منتظرِ جا در صفِ رندر…" : undefined; emit();
      let r: SendResult;
      try {
        r = await send(it.override);
      } catch (e) {
        r = { ok: false, message: e instanceof Error ? e.message : "خطای ناشناخته" };
      }
      if (r.ok) { it.state = "sent"; it.message = "در صفِ رندر"; emit(); break; }
      if (r.full && waits < MAX_WAITS) { waits++; emit(); await wait(WAIT_MS); continue; }
      it.state = "failed"; it.message = r.full ? "صفِ رندر مدتِ زیادی پر ماند؛ بعداً دوباره بفرستید." : r.message; emit();
      break;
    }
  }
  for (const it of list) if (it.state === "wait") { it.state = "cancelled"; it.message = "لغو شد"; }
  emit();
  return list;
}

export const queueSummary = (items: QItem[]): string => {
  const n = (s: QState) => items.filter((i) => i.state === s).length;
  const parts = [`${n("sent")} فرستاده شد`, n("failed") ? `${n("failed")} ناموفق` : "", n("cancelled") ? `${n("cancelled")} لغو` : "", n("wait") + n("sending") ? `${n("wait") + n("sending")} در انتظار` : ""];
  return parts.filter(Boolean).join(" · ");
};
