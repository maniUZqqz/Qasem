import { boxToFrame, frameToBox, placement, sourceToFrame } from "./geom";
import type { Key } from "./keyframes";
import { MAX_KEYS } from "./keyframes";
import {
  AnyClip, Follow, MediaClip, Project, TextClip, Tracker, TrackerSample, clipEnd, clipSpeeds, clipLength, findClip, isMedia, propAt, uid,
} from "./model";

/**
 * ردیابیِ حرکت — سمتِ مرورگر. سرور (OpenCV) مسیرِ یک نقطه/ناحیه را در «ثانیه‌های منبع» می‌دهد (مرکز به‌صورتِ کسری از قابِ منبع).
 * این‌جا آن مسیر با جابه‌جایی/اندازه/برشِ قطعهٔ ردیابی‌شده روی «قابِ پروژه» می‌افتد و برای هر چیزِ وصل‌شده (ماسک، متن، استیکر، شکل)
 * به کلیدفریم/مسیر پخته می‌شود؛ سرور فقط همین کلیدها را می‌شناسد. وصل‌بودن یعنی: «همیشه به اندازهٔ (bx,by) از نقطهٔ ردیابی‌شده فاصله بدار».
 */
export type AspectOf = (ref: string) => number;

/** لحظهٔ تایم‌لاین که قطعهٔ c ثانیهٔ منبعِ s را نشان می‌دهد (null اگر بیرونِ بازهٔ استفاده‌شده است) */
export function timeOfSource(c: MediaClip, s: number): number | null {
  if (c.freeze || c.kind === "image") return null;
  if (s < c.start - 0.02 || s > c.end + 0.02) return null;
  const sp = clipSpeeds(c);
  const L = clipLength(c);
  let local: number;
  if (sp.length === 1) local = (s - c.start) / sp[0];
  else {
    const step = (c.end - c.start) / sp.length;
    let cum = 0;
    local = L;
    for (let i = 0; i < sp.length; i++) {
      const lo = c.start + i * step;
      if (s <= lo + step) {
        local = cum + (s - lo) / sp[i];
        break;
      }
      cum += step / sp[i];
    }
  }
  if (c.reverse) local = L - local;
  return c.at + Math.max(0, Math.min(L, local));
}

/** کلیدهای ساده‌شده (Ramer–Douglas–Peucker روی خطای مقدار) تا حداکثر `limit` کلید */
export function simplifySeries(pts: { t: number; v: number }[], limit = MAX_KEYS - 6): { t: number; v: number }[] {
  if (pts.length <= 2) return pts;
  const run = (eps: number): { t: number; v: number }[] => {
    const keep = new Set<number>([0, pts.length - 1]);
    const stack: [number, number][] = [[0, pts.length - 1]];
    while (stack.length) {
      const [a, b] = stack.pop()!;
      let worst = -1;
      let wi = -1;
      for (let i = a + 1; i < b; i++) {
        const u = (pts[i].t - pts[a].t) / Math.max(1e-9, pts[b].t - pts[a].t);
        const err = Math.abs(pts[a].v + (pts[b].v - pts[a].v) * u - pts[i].v);
        if (err > worst) { worst = err; wi = i; }
      }
      if (worst > eps && wi > 0) {
        keep.add(wi);
        stack.push([a, wi], [wi, b]);
      }
    }
    return [...keep].sort((x, y) => x - y).map((i) => pts[i]);
  };
  let eps = 0.0015;
  let out = run(eps);
  while (out.length > limit && eps < 0.2) {
    eps *= 1.5;
    out = run(eps);
  }
  return out;
}

const round = (x: number, d = 4) => Math.round(x * 10 ** d) / 10 ** d;

/** نمونه‌های ردیاب که روی قطعه‌های ویدیوییِ همان منبع می‌افتند: [{T: زمانِ تایم‌لاین, X, Y: نقطه روی قاب}] */
export function framePath(p: Project, tr: Tracker, aspectOf: AspectOf): { T: number; X: number; Y: number }[] {
  const fa = p.format.width / p.format.height;
  const sa = aspectOf(tr.ref) || fa;
  const out: { T: number; X: number; Y: number }[] = [];
  for (const t of p.tracks) {
    if (t.kind !== "video") continue;
    for (const c of t.clips) {
      if (!isMedia(c) || c.ref !== tr.ref || c.kind !== "video") continue;
      for (const s of tr.samples) {
        const T = timeOfSource(c, s.s);
        if (T === null) continue;
        const [X, Y] = sourceToFrame(c, T, s.x, s.y, fa, sa);
        out.push({ T, X, Y });
      }
    }
  }
  return out.sort((a, b) => a.T - b.T);
}

/** نقطهٔ ردیابی‌شده روی قاب در لحظهٔ t (درون‌یابیِ مسیر) یا null */
export function pointAt(p: Project, tr: Tracker, t: number, aspectOf: AspectOf): [number, number] | null {
  const path = framePath(p, tr, aspectOf);
  if (path.length === 0 || t < path[0].T - 0.2 || t > path[path.length - 1].T + 0.2) return null;
  if (t <= path[0].T) return [path[0].X, path[0].Y];
  for (let i = 0; i + 1 < path.length; i++) {
    if (t <= path[i + 1].T) {
      const u = (t - path[i].T) / Math.max(1e-9, path[i + 1].T - path[i].T);
      return [path[i].X + (path[i + 1].X - path[i].X) * u, path[i].Y + (path[i + 1].Y - path[i].Y) * u];
    }
  }
  const last = path[path.length - 1];
  return [last.X, last.Y];
}

const centerOf = (c: MediaClip, t: number): [number, number] => [c.x + c.width / 2 + propAt(c, "px", t), c.y + c.height / 2 + propAt(c, "py", t)];
const textAnchor = (c: TextClip): [number, number] => [c.x ?? 0.5, c.y ?? (c.position === "top" ? 0.12 : c.position === "middle" ? 0.5 : 0.86)];

/** یک چیز (قطعه/متن/ماسکِ یک قطعه) را به ردیاب وصل می‌کند؛ فاصلهٔ فعلی‌اش تا نقطهٔ ردیابی‌شده (در لحظهٔ `t`) ثابت می‌ماند */
export function attachTo(p: Project, target: { clipId: string; mask?: boolean }, trackerId: string, t: number, aspectOf: AspectOf): { project: Project; message?: string } {
  const tr = p.trackers?.find((x) => x.id === trackerId);
  const f = findClip(p, target.clipId);
  if (!tr || !f) return { project: p, message: "ردیاب یا قطعه پیدا نشد." };
  const path = framePath(p, tr, aspectOf);
  if (!path.length) return { project: p, message: "ردیاب روی هیچ قطعهٔ ویدیوییِ این پروژه نمی‌افتد (قطعهٔ ردیابی‌شده را روی تایم‌لاین نگه دارید)." };
  const at = Math.max(path[0].T, Math.min(path[path.length - 1].T, t));
  const pt = pointAt(p, tr, at, aspectOf) ?? [path[0].X, path[0].Y];
  const fa = p.format.width / p.format.height;
  let bx = 0;
  let by = 0;
  const c = f.clip;
  if (target.mask) {
    if (!isMedia(c) || !c.mask || c.mask.shape === "none") return { project: p, message: "این قطعه ماسک ندارد." };
    const [mx, my] = boxToFrame(placement(c, at), c.mask.cx, c.mask.cy, fa);
    bx = mx - pt[0];
    by = my - pt[1];
  } else if (isMedia(c)) {
    const [cx, cy] = centerOf(c, at);
    bx = cx - pt[0];
    by = cy - pt[1];
  } else if (c.type === "text") {
    const [ax, ay] = textAnchor(c);
    bx = ax - pt[0];
    by = ay - pt[1];
  }
  const follow: Follow = { tracker: trackerId, bx: round(bx, 5), by: round(by, 5) };
  const patch = (cl: AnyClip): AnyClip => {
    if (cl.id !== target.clipId) return cl;
    if (target.mask && isMedia(cl) && cl.mask) return { ...cl, mask: { ...cl.mask, follow } };
    return { ...cl, follow } as AnyClip;
  };
  const q: Project = { ...p, tracks: p.tracks.map((tk) => ({ ...tk, clips: tk.clips.map(patch) })) };
  return { project: bakeFollowers(q, aspectOf) };
}

export function detach(p: Project, clipId: string, mask = false): Project {
  const strip = (cl: AnyClip): AnyClip => {
    if (cl.id !== clipId) return cl;
    if (isMedia(cl)) {
      if (mask) {
        if (!cl.mask) return cl;
        const m = { ...cl.mask };
        delete m.follow;
        delete m.kx;
        delete m.ky;
        return { ...cl, mask: m };
      }
      const copy: MediaClip = { ...cl };
      delete copy.follow;
      const kf = { ...(copy.kf ?? {}) };
      delete kf.px;
      delete kf.py;
      copy.kf = Object.keys(kf).length ? kf : undefined;
      return copy;
    }
    const txt: TextClip = { ...cl };
    delete txt.follow;
    delete txt.path;
    return txt;
  };
  return { ...p, tracks: p.tracks.map((tk) => ({ ...tk, clips: tk.clips.map(strip) })) };
}

export const hasFollowers = (p: Project): boolean => !!p.trackers?.length && p.tracks.some((t) => t.clips.some((c) => !!(c as { follow?: Follow }).follow || (isMedia(c) && c.mask?.follow)));

const sameKeys = (a: Key[] | undefined, b: Key[] | undefined) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** کلیدها/مسیرِ همهٔ چیزهای وصل‌شده را از ردیاب‌ها از نو می‌پزد (با هر تغییرِ پروژه صدا زده می‌شود؛ اگر چیزی عوض نشود همان پروژه برمی‌گردد) */
export function bakeFollowers(p: Project, aspectOf: AspectOf): Project {
  if (!hasFollowers(p)) return p;
  const fa = p.format.width / p.format.height;
  const cache = new Map<string, { T: number; X: number; Y: number }[]>();
  const pathOf = (id: string) => {
    if (!cache.has(id)) {
      const tr = p.trackers?.find((x) => x.id === id);
      cache.set(id, tr ? framePath(p, tr, aspectOf) : []);
    }
    return cache.get(id)!;
  };
  let changed = false;
  const tracks = p.tracks.map((tk) => ({
    ...tk,
    clips: tk.clips.map((c): AnyClip => {
      if (c.type === "text" && c.follow) {
        const path = pathOf(c.follow.tracker).filter((q) => q.T >= c.at - 0.3 && q.T <= clipEnd(c) + 0.3);
        if (path.length < 2) return c;
        const [ax, ay] = textAnchor(c);
        const dx = simplifySeries(path.map((q) => ({ t: q.T - c.at, v: q.X + c.follow!.bx - ax })));
        const dy = simplifySeries(path.map((q) => ({ t: q.T - c.at, v: q.Y + c.follow!.by - ay })));
        const times = [...new Set([...dx, ...dy].map((k) => round(Math.max(0, k.t), 3)))].sort((a, b) => a - b);
        const at = (arr: { t: number; v: number }[], t: number) => {
          if (t <= arr[0].t) return arr[0].v;
          for (let i = 0; i + 1 < arr.length; i++) if (t <= arr[i + 1].t) return arr[i].v + ((arr[i + 1].v - arr[i].v) * (t - arr[i].t)) / Math.max(1e-9, arr[i + 1].t - arr[i].t);
          return arr[arr.length - 1].v;
        };
        const next = times.slice(0, 80).map((t) => ({ t, dx: round(at(dx, t), 5), dy: round(at(dy, t), 5) }));
        if (JSON.stringify(next) === JSON.stringify(c.path ?? null)) return c;
        changed = true;
        return { ...c, path: next };
      }
      if (c.type !== "media") return c;
      let out: MediaClip = c;
      if (c.follow) {
        const path = pathOf(c.follow.tracker).filter((q) => q.T >= c.at - 0.3 && q.T <= clipEnd(c) + 0.3);
        if (path.length >= 2) {
          const [cx0, cy0] = [c.x + c.width / 2, c.y + c.height / 2];
          const kx = simplifySeries(path.map((q) => ({ t: q.T - c.at, v: q.X + c.follow!.bx - cx0 }))).map((k): Key => ({ t: round(Math.max(0, k.t), 3), v: round(k.v), e: "linear" }));
          const ky = simplifySeries(path.map((q) => ({ t: q.T - c.at, v: q.Y + c.follow!.by - cy0 }))).map((k): Key => ({ t: round(Math.max(0, k.t), 3), v: round(k.v), e: "linear" }));
          if (!sameKeys(kx, c.kf?.px) || !sameKeys(ky, c.kf?.py)) {
            out = { ...out, kf: { ...(out.kf ?? {}), px: kx, py: ky } };
            changed = true;
          }
        }
      }
      if (c.mask?.follow) {
        const f = c.mask.follow;
        const path = pathOf(f.tracker).filter((q) => q.T >= c.at - 0.3 && q.T <= clipEnd(c) + 0.3);
        if (path.length >= 2) {
          const pts = path.map((q) => {
            const [u, v] = frameToBox(placement(out, q.T), q.X + f.bx, q.Y + f.by, fa);
            return { t: q.T - c.at, u: u - c.mask!.cx, v: v - c.mask!.cy };
          });
          const kx = simplifySeries(pts.map((q) => ({ t: q.t, v: q.u }))).map((k): Key => ({ t: round(Math.max(0, k.t), 3), v: round(k.v), e: "linear" }));
          const ky = simplifySeries(pts.map((q) => ({ t: q.t, v: q.v }))).map((k): Key => ({ t: round(Math.max(0, k.t), 3), v: round(k.v), e: "linear" }));
          if (!sameKeys(kx, c.mask.kx) || !sameKeys(ky, c.mask.ky)) {
            out = { ...out, mask: { ...c.mask, kx, ky } };
            changed = true;
          }
        }
      }
      return out;
    }),
  }));
  return changed ? { ...p, tracks } : p;
}

/** پاسخِ کارِ ردیابی ⇒ ردیابِ تازه */
export function trackerFromResult(
  name: string, ref: string, size: [number, number], region: Tracker["region"],
  r: { samples: TrackerSample[]; lost_at: number | null; engine: string; s0: number; s1: number },
): Tracker {
  return { id: uid("k"), name, ref, size, region, s0: r.s0, s1: r.s1, lost_at: r.lost_at, engine: r.engine, samples: r.samples };
}
