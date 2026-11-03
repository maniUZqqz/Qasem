/**
 * LUT ِ .cube: خواندن و اعمال (درون‌یابیِ سه‌خطی) برای پیش‌نمایشِ فوری. سرور همان فایل را با `lut3d` (tetrahedral) اعمال می‌کند؛
 * این‌جا تقریبی است — اختلافش در حدِ یکی دو پله از ۲۵۵ و برای قضاوتِ رنگ کافی؛ «پیش‌نمایشِ دقیق» همان خروجی را نشان می‌دهد.
 */
export type Lut = { size: number; table: Float32Array; dmin: [number, number, number]; dmax: [number, number, number]; title: string };

export function parseCube(text: string): Lut {
  let size = 0;
  let title = "";
  let dmin: [number, number, number] = [0, 0, 0];
  let dmax: [number, number, number] = [1, 1, 1];
  const rows: number[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const head = line.split(/\s+/)[0].toUpperCase();
    if (head === "TITLE") title = line.replace(/^TITLE\s*/i, "").replace(/^"|"$/g, "");
    else if (head === "LUT_3D_SIZE") size = parseInt(line.split(/\s+/)[1], 10);
    else if (head === "LUT_1D_SIZE") throw new Error("LUT یک‌بعدی پشتیبانی نمی‌شود");
    else if (head === "DOMAIN_MIN") dmin = line.split(/\s+/).slice(1, 4).map(Number) as [number, number, number];
    else if (head === "DOMAIN_MAX") dmax = line.split(/\s+/).slice(1, 4).map(Number) as [number, number, number];
    else if (/^[A-Za-z]/.test(head)) continue;
    else {
      const p = line.split(/\s+/).map(Number);
      if (p.length < 3 || p.some((x) => !Number.isFinite(x))) throw new Error("ردیفِ نادرست در LUT");
      rows.push(p[0], p[1], p[2]);
    }
  }
  if (size < 2 || rows.length !== size ** 3 * 3) throw new Error("جدولِ LUT کامل نیست");
  return { size, table: Float32Array.from(rows), dmin, dmax, title };
}

/** روی ImageData اعمال می‌کند؛ amount ۰..۱ (۱ = کاملِ LUT) */
export function applyLut(img: ImageData, lut: Lut, amount: number): void {
  const n = lut.size;
  const t = lut.table;
  const d = img.data;
  const k = Math.max(0, Math.min(1, amount));
  const rng = [lut.dmax[0] - lut.dmin[0], lut.dmax[1] - lut.dmin[1], lut.dmax[2] - lut.dmin[2]];
  const at = (r: number, g: number, b: number, c: number) => t[((b * n + g) * n + r) * 3 + c];
  for (let i = 0; i < d.length; i += 4) {
    const fr = Math.max(0, Math.min(1, (d[i] / 255 - lut.dmin[0]) / rng[0])) * (n - 1);
    const fg = Math.max(0, Math.min(1, (d[i + 1] / 255 - lut.dmin[1]) / rng[1])) * (n - 1);
    const fb = Math.max(0, Math.min(1, (d[i + 2] / 255 - lut.dmin[2]) / rng[2])) * (n - 1);
    const r0 = Math.floor(fr), g0 = Math.floor(fg), b0 = Math.floor(fb);
    const r1 = Math.min(n - 1, r0 + 1), g1 = Math.min(n - 1, g0 + 1), b1 = Math.min(n - 1, b0 + 1);
    const tr = fr - r0, tg = fg - g0, tb = fb - b0;
    for (let c = 0; c < 3; c++) {
      const c00 = at(r0, g0, b0, c) * (1 - tr) + at(r1, g0, b0, c) * tr;
      const c10 = at(r0, g1, b0, c) * (1 - tr) + at(r1, g1, b0, c) * tr;
      const c01 = at(r0, g0, b1, c) * (1 - tr) + at(r1, g0, b1, c) * tr;
      const c11 = at(r0, g1, b1, c) * (1 - tr) + at(r1, g1, b1, c) * tr;
      const out = (c00 * (1 - tg) + c10 * tg) * (1 - tb) + (c01 * (1 - tg) + c11 * tg) * tb;
      const mixed = d[i + c] / 255 * (1 - k) + out * k;
      d[i + c] = Math.max(0, Math.min(255, Math.round(mixed * 255)));
    }
  }
}
