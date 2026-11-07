import type { PathPt, Pt2, ShapePath } from "./types";

/**
 * کتابخانهٔ شکل‌های آماده (دورِ ۸): چندضلعی، ستاره و شکل‌های پُرکاربردِ فروشگاه (قلب، فلش، کادر گفتگو، ابر، تیک، علامتِ بعلاوه…).
 * هر شکل یک مسیرِ بستهٔ چندضلعی در جعبهٔ واحد [۰..۱]² است که کاملاً جعبه را می‌پوشاند (min = ۰ و max = ۱)؛ لایهٔ شکلِ `path`
 * با همین مسیر ساخته می‌شود و مثلِ هر مسیرِ قلم قابلِ تبدیل و ویرایش است. بدونِ دستگیره ⇒ همان چندضلعی هم در مرورگر هم روی سرور یکی کشیده می‌شود.
 */
export const SHAPE_MAX_POINTS = 160;

const r5 = (v: number): number => Math.round(v * 1e5) / 1e5;

/** نقطه‌ها را طوری مقیاس می‌دهد که جعبهٔ پیرامونشان دقیقاً [۰..۱]² شود */
export function fitUnitBox(poly: Pt2[]): Pt2[] {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  const w = Math.max(1e-9, x1 - x0);
  const h = Math.max(1e-9, y1 - y0);
  return poly.map(([x, y]) => [r5((x - x0) / w), r5((y - y0) / h)] as Pt2);
}

export const toPath = (poly: Pt2[]): ShapePath => ({
  closed: true,
  pts: fitUnitBox(poly).map(([x, y]): PathPt => ({ x, y, hi: null, ho: null })),
});

/** n‌ضلعیِ منظم؛ rotDeg = ۰ ⇒ یک رأس بالا */
export function regularPolygon(n: number, rotDeg = 0): Pt2[] {
  const k = Math.max(3, Math.min(SHAPE_MAX_POINTS, Math.round(n)));
  const out: Pt2[] = [];
  for (let i = 0; i < k; i++) {
    const a = ((i / k) * 360 - 90 + rotDeg) * (Math.PI / 180);
    out.push([Math.cos(a), Math.sin(a)]);
  }
  return out;
}

/** ستارهٔ n‌پر؛ inner = نسبتِ شعاعِ درونی به بیرونی (۰٫۱..۰٫۹) */
export function starPoly(n: number, inner = 0.45): Pt2[] {
  const k = Math.max(3, Math.min(SHAPE_MAX_POINTS / 2, Math.round(n)));
  const ri = Math.max(0.1, Math.min(0.9, inner));
  const out: Pt2[] = [];
  for (let i = 0; i < k * 2; i++) {
    const a = ((i / (k * 2)) * 360 - 90) * (Math.PI / 180);
    const r = i % 2 === 0 ? 1 : ri;
    out.push([Math.cos(a) * r, Math.sin(a) * r]);
  }
  return out;
}

function sample(n: number, f: (t: number) => Pt2): Pt2[] {
  const out: Pt2[] = [];
  for (let i = 0; i < n; i++) out.push(f((i / n) * Math.PI * 2));
  return out;
}

const heart = (): Pt2[] => sample(72, (t) => [16 * Math.sin(t) ** 3, -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t))]);
const drop = (): Pt2[] => sample(72, (t) => [Math.sin(t) * Math.sin(t / 2) ** 1.2 * 0.8, -Math.cos(t) * 0.95 - 0.1 * Math.cos(2 * t)]);
const burst = (): Pt2[] => starPoly(16, 0.78);
const cloud = (): Pt2[] => sample(96, (t) => {
  const r = 0.72 + 0.28 * Math.abs(Math.sin(t * 3.5));
  return [Math.cos(t) * r * 1.35, Math.sin(t) * r * 0.85];
});
const moon = (): Pt2[] => {
  const out: Pt2[] = [];
  // کمانِ بیرونی (دایرهٔ بزرگ) و کمانِ درونی (دایرهٔ کوچکِ جابه‌جاشده)
  for (let i = 0; i <= 40; i++) {
    const a = (-70 + (i / 40) * 320) * (Math.PI / 180);
    out.push([Math.cos(a), Math.sin(a)]);
  }
  for (let i = 40; i >= 0; i--) {
    const a = (-60 + (i / 40) * 300) * (Math.PI / 180);
    out.push([0.45 + Math.cos(a) * 0.78, Math.sin(a) * 0.78]);
  }
  return out;
};
const speech = (): Pt2[] => {
  const out: Pt2[] = [];
  const rr = 0.18;
  const corner = (cx: number, cy: number, a0: number): void => {
    for (let i = 0; i <= 8; i++) {
      const a = (a0 + (i / 8) * 90) * (Math.PI / 180);
      out.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
    }
  };
  corner(0.82, 0.18, -90);
  corner(0.82, 0.62, 0);
  out.push([0.5, 0.8], [0.3, 1.0], [0.34, 0.8]);
  corner(0.18, 0.62, 90);
  corner(0.18, 0.18, 180);
  return out;
};

export type ShapeDef = { id: string; title: string; en: string; syn: string[]; aspect: number; poly: () => Pt2[]; dialog?: "polygon" | "star" };

/** aspect = ارتفاع ÷ پهنای جعبه (برای اندازهٔ اولیهٔ لایه) */
export const SHAPES: ShapeDef[] = [
  { id: "polygon", title: "چندضلعیِ منظم", en: "Polygon", syn: ["چندضلعی", "مثلث", "پنج ضلعی", "شش ضلعی", "polygon", "hexagon", "triangle"], aspect: 1, poly: () => regularPolygon(6), dialog: "polygon" },
  { id: "star", title: "ستاره", en: "Star", syn: ["ستاره", "پر", "star", "badge"], aspect: 1, poly: () => starPoly(5), dialog: "star" },
  { id: "triangle", title: "مثلث", en: "Triangle", syn: ["مثلث", "triangle"], aspect: 0.87, poly: () => regularPolygon(3) },
  { id: "diamond", title: "لوزی", en: "Diamond", syn: ["لوزی", "diamond", "rhombus"], aspect: 1, poly: () => regularPolygon(4) },
  { id: "hexagon", title: "شش‌ضلعی", en: "Hexagon", syn: ["شش ضلعی", "hexagon"], aspect: 0.87, poly: () => regularPolygon(6, 30) },
  { id: "heart", title: "قلب", en: "Heart", syn: ["قلب", "دل", "heart", "love"], aspect: 0.92, poly: heart },
  { id: "arrow", title: "فلش", en: "Arrow", syn: ["فلش", "پیکان", "arrow"], aspect: 0.6, poly: () => [[0, 0.3], [0.58, 0.3], [0.58, 0], [1, 0.5], [0.58, 1], [0.58, 0.7], [0, 0.7]] },
  { id: "speech", title: "کادرِ گفتگو", en: "Speech bubble", syn: ["کادر گفتگو", "حباب", "پیام", "speech bubble", "chat", "callout"], aspect: 0.8, poly: speech },
  { id: "cloud", title: "ابر", en: "Cloud", syn: ["ابر", "cloud"], aspect: 0.6, poly: cloud },
  { id: "check", title: "علامتِ تیک", en: "Check mark", syn: ["تیک", "درست", "check", "tick"], aspect: 0.75, poly: () => [[0, 0.55], [0.14, 0.41], [0.38, 0.65], [0.86, 0], [1, 0.14], [0.38, 0.93]] },
  { id: "plus", title: "بعلاوه", en: "Plus", syn: ["بعلاوه", "جمع", "plus", "cross"], aspect: 1, poly: () => [[0.35, 0], [0.65, 0], [0.65, 0.35], [1, 0.35], [1, 0.65], [0.65, 0.65], [0.65, 1], [0.35, 1], [0.35, 0.65], [0, 0.65], [0, 0.35], [0.35, 0.35]] },
  { id: "burst", title: "ستارهٔ تخفیف", en: "Sale burst", syn: ["تخفیف", "جایزه", "مهر", "burst", "sale badge", "seal"], aspect: 1, poly: burst },
  { id: "drop", title: "قطره", en: "Drop", syn: ["قطره", "آب", "drop", "teardrop"], aspect: 1.25, poly: drop },
  { id: "moon", title: "هلال", en: "Crescent", syn: ["هلال", "ماه", "crescent", "moon"], aspect: 1, poly: moon },
  { id: "bolt", title: "رعدوبرق", en: "Lightning", syn: ["رعدوبرق", "برق", "صاعقه", "lightning", "bolt"], aspect: 1.6, poly: () => [[0.55, 0], [0.12, 0.55], [0.45, 0.55], [0.3, 1], [0.88, 0.4], [0.55, 0.4], [0.75, 0]] },
  { id: "ribbon", title: "روبان", en: "Ribbon", syn: ["روبان", "نوار", "ribbon", "banner"], aspect: 0.35, poly: () => [[0, 0.1], [1, 0.1], [0.92, 0.5], [1, 0.9], [0, 0.9], [0.08, 0.5]] },
];

export function shapeById(id: string): ShapeDef | null {
  return SHAPES.find((s) => s.id === id) ?? null;
}

/** مسیرِ شکل با گزینه‌ها (برای چندضلعی/ستاره) */
export function buildShape(id: string, opts: { sides?: number; inner?: number } = {}): { path: ShapePath; aspect: number } | null {
  const def = shapeById(id);
  if (!def) return null;
  let poly: Pt2[];
  if (id === "polygon") poly = regularPolygon(opts.sides ?? 6);
  else if (id === "star") poly = starPoly(opts.sides ?? 5, opts.inner ?? 0.45);
  else poly = def.poly();
  const path = toPath(poly);
  // نسبتِ واقعیِ جعبه از خودِ شکل: منظم‌ها قبل از fitUnitBox نسبتِ طبیعی دارند
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  const natural = (y1 - y0) / Math.max(1e-9, x1 - x0);
  const aspect = def.dialog || id === "heart" || id === "cloud" || id === "drop" || id === "moon" || id === "speech" || id === "burst" ? natural : def.aspect;
  return { path, aspect: Math.max(0.15, Math.min(4, aspect)) };
}
