/**
 * کانال‌ها (نوبت ۷): هر کانالِ ترکیبِ فعلی (قرمز، سبز، آبی، شفافیت، روشنایی) به‌صورتِ تصویرِ خاکستری؛
 * هر کدام را می‌شود دید و به‌عنوانِ انتخاب بارگذاری کرد (روشن = انتخاب‌شده).
 */
export type ChannelId = "r" | "g" | "b" | "a" | "l";

export const CHANNELS: { id: ChannelId; fa: string; en: string; tip: string }[] = [
  { id: "r", fa: "قرمز", en: "Red", tip: "هرچه یک نقطه قرمزتر باشد روشن‌تر است" },
  { id: "g", fa: "سبز", en: "Green", tip: "هرچه یک نقطه سبزتر باشد روشن‌تر است" },
  { id: "b", fa: "آبی", en: "Blue", tip: "هرچه یک نقطه آبی‌تر باشد روشن‌تر است" },
  { id: "a", fa: "شفافیت", en: "Alpha", tip: "نقطه‌های دیدنی سفید و شفاف‌ها سیاه‌اند" },
  { id: "l", fa: "روشنایی", en: "Luminosity", tip: "روشنیِ دیده‌شده توسطِ چشم (سیاه‌وسفیدِ عکس)" },
];

/** مقدارِ خاکستری (۰ تا ۲۵۵) هر پیکسلِ RGBA برای کانالِ ch */
export function channelGray(data: ArrayLike<number>, ch: ChannelId, invert = false): Uint8ClampedArray {
  const n = Math.floor(data.length / 4);
  const out = new Uint8ClampedArray(n);
  for (let i = 0; i < n; i++) {
    const o = i * 4;
    let v: number;
    if (ch === "r") v = data[o];
    else if (ch === "g") v = data[o + 1];
    else if (ch === "b") v = data[o + 2];
    else if (ch === "a") v = data[o + 3];
    else v = Math.round(0.2126 * data[o] + 0.7152 * data[o + 1] + 0.0722 * data[o + 2]);
    out[i] = invert ? 255 - v : v;
  }
  return out;
}

/** بومِ خاکستریِ w×h از کانالِ ch (برای نمایش و انتخاب) */
export function channelCanvas(data: ArrayLike<number>, w: number, h: number, ch: ChannelId, invert = false): HTMLCanvasElement {
  const g = channelGray(data, ch, invert);
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const img = new ImageData(w, h);
  for (let i = 0; i < g.length; i++) {
    const o = i * 4;
    img.data[o] = img.data[o + 1] = img.data[o + 2] = g[i];
    img.data[o + 3] = 255;
  }
  c.getContext("2d")!.putImageData(img, 0, 0);
  return c;
}
