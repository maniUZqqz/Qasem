/**
 * مایع‌سازی (Liquify): نقشهٔ جابه‌جاییِ پروژه در فضای «عکس» (نه بوم).
 *
 * فرمتِ فایل (`liquify.bin`، همان backend/apps/photoedit/liquify.py):
 *   "LQF1" | uint16 gw | uint16 gh | gw·gh·2 عددِ int16 (dx، dy پیاپی؛ ردیف‌به‌ردیف، ردیفِ بالا اول) — همه little-endian
 *   مقدارِ v ⇒ آفستِ v/32767·0.25 در مختصاتِ نرمالِ عکس (dx کسری از پهنا، dy کسری از ارتفاع).
 * معنا: out(u, v) = src(u + dx, v + dy)، نقشه با قرارداد «مرکزِ سلول» و نمونه‌برداریِ دوخطی روی عکس کشیده می‌شود
 * (گرهٔ (i, j) در ((i+.5)/gw، (j+.5)/gh)). در GLSL همین‌طور (shaders.ts `liquify`).
 *
 * `state.liquify = {rev}` فقط یک «نشان» است: rev شمارهٔ نسخهٔ همین نقشه در `snaps` (مثلِ MaskStore) تا برگشت/جلو کار کند؛
 * rev = ۰ یعنی نقشهٔ صفر. بایت‌های سرور را فقط هنگامِ ذخیره می‌نویسیم.
 */

export const LQ_GRID = 192;
export const LQ_MAX = 0.25;
export const LQ_MAX_GRID = 1024;
const MAGIC = [0x4c, 0x51, 0x46, 0x31]; // "LQF1"

export type LqMode = "push" | "bloat" | "pucker" | "reconstruct";

/** گامِ هر نقطه (نسبت به شعاع) هنگامِ کشیدن */
const SPACING = 0.18;

export class LiquifyStore {
  /** اندازهٔ شبکه */
  gw = 0;
  gh = 0;
  /** (dx, dy) نرمال، ردیف‌به‌ردیف، بالا اول؛ طول gw·gh·2 */
  field = new Float32Array(0);
  /** با هر تغییرِ محتوا بالا می‌رود (موتور بر اساسِ آن دوباره آپلود می‌کند) */
  ver = 0;
  /** نسخهٔ جاری (همان state.liquify.rev؛ ۰ = صفر) */
  rev = 0;
  /** از آخرین ذخیره عوض شده؟ */
  dirty = false;
  /** روی سرور فایلی هست؟ (برای تصمیمِ DELETE) */
  onServer = false;
  /** اندازهٔ عکسِ اصل به پیکسل (برای دایره‌ای بودنِ قلم) */
  photoW = 1;
  photoH = 1;
  private snaps = new Map<number, Float32Array>();
  private maxRev = 0;
  private nzVer = -1;
  private nz = false;

  /** شبکه را برای عکسِ W×H می‌سازد (صفر) و همهٔ نسخه‌ها را دور می‌ریزد */
  init(W: number, H: number): void {
    this.photoW = Math.max(1, W);
    this.photoH = Math.max(1, H);
    this.gw = LQ_GRID;
    this.gh = Math.max(2, Math.min(LQ_MAX_GRID, Math.round((LQ_GRID * this.photoH) / this.photoW)));
    this.field = new Float32Array(this.gw * this.gh * 2);
    this.snaps.clear();
    this.snaps.set(0, new Float32Array(this.field.length));
    this.rev = 0;
    this.maxRev = 0;
    this.ver++;
    this.dirty = false;
  }

  /** هر خانه‌ای غیرصفر است؟ (موتور فقط آن‌وقت پاس را اجرا می‌کند) */
  get active(): boolean {
    if (this.nzVer !== this.ver) {
      this.nzVer = this.ver;
      let nz = false;
      for (let i = 0; i < this.field.length; i++) if (this.field[i] !== 0) { nz = true; break; }
      this.nz = nz;
    }
    return this.nz;
  }

  // ───────────────────────── قلم‌ها (مختصاتِ نرمالِ عکس؛ شعاع به «پهنای عکس»)

  private falloff(d: number): number {
    const t = Math.min(1, Math.max(0, d));
    return 1 - t * t * (3 - 2 * t);
  }

  /** حلقهٔ مشترک روی خانه‌های زیرِ قلم؛ fn(index, f، دورِ نرمال از مرکز) */
  private each(cx: number, cy: number, r: number, fn: (i: number, f: number, px: number, py: number) => void): void {
    const { gw, gh, photoW: W, photoH: H } = this;
    const rx = (r * W) / W; // شعاع به نرمالِ x
    const ry = (r * W) / H; // به نرمالِ y (قلم در پیکسل گرد است)
    const i0 = Math.max(0, Math.floor((cx - rx) * gw - 0.5));
    const i1 = Math.min(gw - 1, Math.ceil((cx + rx) * gw - 0.5));
    const j0 = Math.max(0, Math.floor((cy - ry) * gh - 0.5));
    const j1 = Math.min(gh - 1, Math.ceil((cy + ry) * gh - 0.5));
    for (let j = j0; j <= j1; j++) {
      const py = (j + 0.5) / gh;
      for (let i = i0; i <= i1; i++) {
        const px = (i + 0.5) / gw;
        const d = Math.hypot((px - cx) * W, (py - cy) * H) / (r * W);
        if (d >= 1) continue;
        fn((j * gw + i) * 2, this.falloff(d), px, py);
      }
    }
  }

  private clampAt(k: number): void {
    const f = this.field;
    if (f[k] > LQ_MAX) f[k] = LQ_MAX; else if (f[k] < -LQ_MAX) f[k] = -LQ_MAX;
    if (f[k + 1] > LQ_MAX) f[k + 1] = LQ_MAX; else if (f[k + 1] < -LQ_MAX) f[k + 1] = -LQ_MAX;
  }

  /** کشیدن: محتوای زیرِ قلم به اندازهٔ (dx, dy) نرمال حرکت می‌کند ⇒ آفستِ −(dx, dy)·falloff (مثلِ liquify.brush_forward) */
  forward(cx: number, cy: number, r: number, dx: number, dy: number, strength: number): void {
    this.each(cx, cy, r, (k, f) => {
      this.field[k] -= dx * f * strength;
      this.field[k + 1] -= dy * f * strength;
      this.clampAt(k);
    });
    this.touch();
  }

  /** باد کردن: آفست (c − p)·strength·falloff (مثلِ brush_bloat)؛ strength منفی = جمع کردن */
  bloat(cx: number, cy: number, r: number, strength: number): void {
    this.each(cx, cy, r, (k, f, px, py) => {
      this.field[k] += (cx - px) * f * strength;
      this.field[k + 1] += (cy - py) * f * strength;
      this.clampAt(k);
    });
    this.touch();
  }

  /** بازسازی: آفست به سمتِ صفر (field ·= 1 − strength·falloff، مثلِ brush_reconstruct) */
  reconstruct(cx: number, cy: number, r: number, strength: number): void {
    this.each(cx, cy, r, (k, f) => {
      const m = 1 - Math.min(1, Math.max(0, f * strength));
      this.field[k] *= m;
      this.field[k + 1] *= m;
    });
    this.touch();
  }

  /** فاصلهٔ بین دو نقطهٔ قلم (نرمالِ عکس) برای کشیدنِ پیوسته */
  spacing(r: number): number {
    return Math.max(0.0005, r * SPACING);
  }

  resetAll(): void {
    this.field.fill(0);
    this.touch();
  }

  touch(): void {
    this.ver++;
    this.dirty = true;
  }

  // ───────────────────────── نسخه‌ها (برگشت/جلو)

  /** حالتِ فعلی را نسخهٔ تازه می‌کند و شمارهٔ آن را برمی‌گرداند (این را در state.liquify.rev بگذارید) */
  commit(): number {
    this.maxRev = Math.max(this.maxRev, this.rev) + 1;
    this.rev = this.maxRev;
    this.snaps.set(this.rev, Float32Array.from(this.field));
    // فقط ۶۰ نسخهٔ آخر (نسخهٔ ۰ همیشه می‌ماند)
    const keys = [...this.snaps.keys()].filter((k) => k !== 0).sort((a, b) => a - b);
    while (keys.length > 60) this.snaps.delete(keys.shift()!);
    return this.rev;
  }

  /** نقشه را به نسخهٔ rev برمی‌گرداند (۰ = صفر)؛ اگر نسخه‌اش مانده باشد true */
  restore(rev: number): boolean {
    const s = this.snaps.get(rev);
    if (!s || s.length !== this.field.length) return false;
    this.field.set(s);
    this.rev = rev;
    this.maxRev = Math.max(this.maxRev, rev);
    this.touch();
    return true;
  }

  // ───────────────────────── فایل (LQF1)

  encode(): Uint8Array {
    const { gw, gh } = this;
    const out = new Uint8Array(8 + gw * gh * 4);
    out.set(MAGIC, 0);
    const dv = new DataView(out.buffer);
    dv.setUint16(4, gw, true);
    dv.setUint16(6, gh, true);
    for (let i = 0; i < gw * gh * 2; i++) {
      const v = Math.max(-32767, Math.min(32767, Math.round((this.field[i] / LQ_MAX) * 32767)));
      dv.setInt16(8 + i * 2, v, true);
    }
    return out;
  }

  /** بایت‌های LQF1 ⇒ شبکه و میدان؛ rev = شمارهٔ نسخه‌ای که این فایل به آن می‌خورد. نامعتبر ⇒ false */
  load(buf: ArrayBuffer, rev: number): boolean {
    const b = new Uint8Array(buf);
    if (b.length < 8 || MAGIC.some((m, i) => b[i] !== m)) return false;
    const dv = new DataView(buf);
    const gw = dv.getUint16(4, true);
    const gh = dv.getUint16(6, true);
    if (gw < 2 || gh < 2 || gw > LQ_MAX_GRID || gh > LQ_MAX_GRID || b.length !== 8 + gw * gh * 4) return false;
    this.gw = gw;
    this.gh = gh;
    this.field = new Float32Array(gw * gh * 2);
    for (let i = 0; i < gw * gh * 2; i++) this.field[i] = (dv.getInt16(8 + i * 2, true) * LQ_MAX) / 32767;
    this.snaps.clear();
    this.snaps.set(0, new Float32Array(this.field.length));
    this.snaps.set(rev, Float32Array.from(this.field));
    this.rev = rev;
    this.maxRev = rev;
    this.onServer = true;
    this.dirty = false;
    this.ver++;
    return true;
  }
}
