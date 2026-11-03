import type { GroupLayer, Layer } from "./types";

/**
 * درختِ لایه‌ها (گروه‌ها). فهرستِ `layers` تخت می‌ماند (پایین ⇒ بالا)؛ درخت از روی `parent` ساخته می‌شود:
 * لایه‌های بی‌والد = سطحِ بالا؛ فرزندانِ گروه = لایه‌هایی با `parent === id` به ترتیبِ فهرست (مثلِ سرور: layers.py).
 * «ترتیبِ قانونی»: فرزندانِ هر گروه درست پیش از خودِ گروه می‌آیند (در نمایشِ فتوشاپی زیرِ سرگروه دیده می‌شوند).
 * همهٔ توابع خالص‌اند و آرایهٔ تازه برمی‌گردانند. بدونِ گروه هیچ‌چیز تغییر نمی‌کند (همان آرایه/ترتیب).
 */

/** بیشینهٔ عمقِ گروه‌های تودرتو (همان MAX_GROUP_DEPTH ِ سرور) */
export const MAX_GROUP_DEPTH = 4;
/** لایه‌هایی که «بریدن به لایهٔ زیرین» برایشان معنا دارد و می‌توانند هدفِ برش باشند */
export const CLIP_TYPES = new Set(["image", "text", "shape", "group"]);

/** والدِ مؤثر: شناسهٔ گروهِ موجود، وگرنه null (لایهٔ بی‌والد یا والدِ ناموجود ⇒ سطحِ بالا؛ پایه هرگز والد ندارد) */
export function parentIdOf(l: Layer, groupIds: Set<string>): string | null {
  if (l.type === "base") return null;
  const p = l.parent ?? null;
  return p !== null && p !== l.id && groupIds.has(p) ? p : null;
}

const groupIdSet = (layers: Layer[]) => new Set(layers.filter((l) => l.type === "group").map((l) => l.id));

export const hasGroups = (layers: Layer[]): boolean => layers.some((l) => l.type === "group");

/** والد ⇒ فرزندان (به ترتیبِ فهرست). کلیدِ null = سطحِ بالا */
export function childrenMap(layers: Layer[]): Map<string | null, Layer[]> {
  const gs = groupIdSet(layers);
  const m = new Map<string | null, Layer[]>();
  for (const l of layers) {
    const p = parentIdOf(l, gs);
    const arr = m.get(p);
    if (arr) arr.push(l);
    else m.set(p, [l]);
  }
  return m;
}

/** شناسهٔ همهٔ نوادگانِ یک گروه (تودرتو هم) */
export function descendantIds(layers: Layer[], id: string): string[] {
  const m = childrenMap(layers);
  const out: string[] = [];
  const walk = (pid: string) => {
    for (const c of m.get(pid) ?? []) {
      out.push(c.id);
      if (c.type === "group") walk(c.id);
    }
  };
  walk(id);
  return out;
}

/** نیاکانِ یک لایه (نزدیک‌ترین والد اول) */
export function ancestorsOf(layers: Layer[], id: string): GroupLayer[] {
  const by = new Map(layers.map((l) => [l.id, l]));
  const gs = groupIdSet(layers);
  const out: GroupLayer[] = [];
  let cur = by.get(id);
  for (let i = 0; cur && i < 12; i++) {
    const p = parentIdOf(cur, gs);
    if (!p) break;
    const g = by.get(p) as GroupLayer | undefined;
    if (!g) break;
    out.push(g);
    cur = g;
  }
  return out;
}

/** لایه (یا یکی از نیاکانش) پنهان است؟ — گروهِ پنهان فرزندانش را هم پنهان می‌کند */
export const effectivelyHidden = (layers: Layer[], l: Layer): boolean => !l.visible || ancestorsOf(layers, l.id).some((g) => !g.visible);
/** لایه یا یکی از گروه‌های بالاسرش قفل است؟ */
export const effectivelyLocked = (layers: Layer[], l: Layer): boolean => l.locked || ancestorsOf(layers, l.id).some((g) => g.locked);

/** عمقِ یک گروه: گروهِ سطحِ بالا = ۱ */
export const groupDepth = (layers: Layer[], id: string): number => ancestorsOf(layers, id).length + 1;

/** بلندیِ زیردرختِ یک لایه از نظرِ گروه‌های تودرتو: لایهٔ غیرِ گروه ۰، گروهِ بی‌گروهِ زیرین ۱، … */
export function groupHeight(layers: Layer[], id: string): number {
  const m = childrenMap(layers);
  const h = (x: Layer): number => (x.type !== "group" ? 0 : 1 + Math.max(0, ...(m.get(x.id) ?? []).map(h)));
  const l = layers.find((x) => x.id === id);
  return l ? h(l) : 0;
}

/** ترتیبِ قانونی: فرزندانِ هر گروه درست پیش از خودِ گروه. بی‌گروه ⇒ همان آرایه */
export function canonical(layers: Layer[]): Layer[] {
  if (!hasGroups(layers)) return layers;
  const m = childrenMap(layers);
  const out: Layer[] = [];
  const emit = (items: Layer[]) => {
    for (const l of items) {
      if (l.type === "group") emit(m.get(l.id) ?? []);
      out.push(l);
    }
  };
  emit(m.get(null) ?? []);
  return out;
}

/** نزدیک‌ترین لایهٔ هم‌سطحِ پایین‌تر که image|text|shape|group باشد (هدفِ برش)؛ null = نیست */
export function clipTarget(layers: Layer[], id: string): Layer | null {
  const gs = groupIdSet(layers);
  const me = layers.find((l) => l.id === id);
  if (!me || me.type === "base") return null;
  const par = parentIdOf(me, gs);
  let best: Layer | null = null;
  for (const l of layers) {
    if (l.id === id) break;
    if (parentIdOf(l, gs) === par && CLIP_TYPES.has(l.type)) best = l;
  }
  return best;
}

/** هم‌خواهرهای یک لایه (به ترتیبِ فهرست، خودش هم هست) */
export function siblingsOf(layers: Layer[], id: string): Layer[] {
  const gs = groupIdSet(layers);
  const me = layers.find((l) => l.id === id);
  if (!me) return [];
  const par = parentIdOf(me, gs);
  return layers.filter((l) => parentIdOf(l, gs) === par);
}

const withParent = (l: Layer, parent: string | null): Layer => {
  const c = { ...l } as Layer;
  if (parent) c.parent = parent;
  else delete (c as { parent?: string | null }).parent;
  return c;
};

/** آیا لایهٔ id را می‌شود زیرِ والدِ parent برد؟ (نه پایه، نه داخلِ خودش/نوادگانش، نه بیشتر از عمقِ مجاز) */
export function canMoveTo(layers: Layer[], id: string, parent: string | null): boolean {
  const me = layers.find((l) => l.id === id);
  if (!me || me.type === "base") return false;
  if (parent === null) return true;
  const g = layers.find((l) => l.id === parent);
  if (!g || g.type !== "group") return false;
  if (parent === id || descendantIds(layers, id).includes(parent)) return false;
  if (me.type === "group" && groupDepth(layers, parent) + groupHeight(layers, id) > MAX_GROUP_DEPTH) return false;
  return true;
}

/**
 * لایه را به والدِ تازه می‌برد؛ index = جایگاه میانِ فرزندانِ والدِ تازه (پایین = ۰، پس از برداشتنِ خودش).
 * ناممکن ⇒ همان آرایه.
 */
export function moveTo(layers: Layer[], id: string, parent: string | null, index: number): Layer[] {
  if (!canMoveTo(layers, id, parent)) return layers;
  const me = layers.find((l) => l.id === id)!;
  const rest = layers.filter((l) => l.id !== id);
  const moved = withParent(me, parent);
  const gs = groupIdSet(layers);
  // جایگاه در فهرستِ تخت: پس از آخرین «هم‌خواهرِ پایین‌تر»؛ اگر هیچ نبود، پیش از اولین هم‌خواهر یا درست پیش از گروه
  const sibs = rest.filter((l) => parentIdOf(l, gs) === parent);
  const at = Math.max(0, Math.min(sibs.length, index));
  const out = [...rest];
  let pos: number;
  if (at > 0) pos = out.indexOf(sibs[at - 1]) + 1;
  else if (sibs.length) pos = out.indexOf(sibs[0]);
  else if (parent) pos = out.findIndex((l) => l.id === parent);
  else pos = out.length;
  out.splice(Math.max(0, pos), 0, moved);
  return canonical(out);
}

/** نشانیِ لایه میانِ هم‌خواهرها (پایین = ۰) */
export function indexAmongSiblings(layers: Layer[], id: string): number {
  return siblingsOf(layers, id).findIndex((l) => l.id === id);
}

/** یک پله بالاتر (dir=+1) یا پایین‌تر (dir=-1) میانِ هم‌خواهرها */
export function moveSibling(layers: Layer[], id: string, dir: 1 | -1): Layer[] {
  const me = layers.find((l) => l.id === id);
  if (!me || me.type === "base") return layers;
  const sibs = siblingsOf(layers, id);
  const i = sibs.findIndex((l) => l.id === id);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= sibs.length) return layers;
  // پایه همیشه ته می‌ماند
  if (sibs[j].type === "base") return layers;
  const gs = groupIdSet(layers);
  return moveTo(layers, id, parentIdOf(me, gs), j);
}

/** لایه را در یک گروهِ تازه می‌پیچد؛ گروه جای لایه را می‌گیرد. ⇒ { layers, groupId } */
export function wrapInGroup(layers: Layer[], id: string, group: GroupLayer): { layers: Layer[]; groupId: string } | null {
  const me = layers.find((l) => l.id === id);
  if (!me || me.type === "base") return null;
  const gs = groupIdSet(layers);
  const par = parentIdOf(me, gs);
  if (me.type === "group" && (par ? groupDepth(layers, par) : 0) + 1 + groupHeight(layers, id) > MAX_GROUP_DEPTH) return null;
  const g: GroupLayer = { ...group };
  if (par) g.parent = par;
  if (me.clip) g.clip = true;
  const inner = { ...me, parent: g.id } as Layer;
  inner.clip = false;
  const idx = layers.findIndex((l) => l.id === id);
  const out = [...layers];
  out.splice(idx, 1, inner, g);
  return { layers: canonical(out), groupId: g.id };
}

/** گروه را باز می‌کند: فرزندان به والدِ گروه می‌روند (همان جای گروه، همان ترتیب)؛ خودِ گروه حذف می‌شود */
export function ungroupLayers(layers: Layer[], gid: string): Layer[] {
  const g = layers.find((l) => l.id === gid);
  if (!g || g.type !== "group") return layers;
  const gs = groupIdSet(layers);
  const par = parentIdOf(g, gs);
  const kids = layers.filter((l) => parentIdOf(l, gs) === gid);
  const kidIds = new Set(kids.map((k) => k.id));
  const out: Layer[] = [];
  for (const l of layers) {
    if (l.id === gid) out.push(...kids.map((k) => withParent(k, par)));
    else if (!kidIds.has(l.id)) out.push(l);
  }
  return canonical(out);
}

/** حذفِ یک لایه همراهِ نوادگانش (گروه ⇒ با فرزندان). ⇒ { layers, removed } */
export function removeWithDescendants(layers: Layer[], id: string): { layers: Layer[]; removed: Layer[] } {
  const ids = new Set([id, ...descendantIds(layers, id)]);
  return { layers: layers.filter((l) => !ids.has(l.id)), removed: layers.filter((l) => ids.has(l.id)) };
}

/** رونوشتِ عمیقِ یک لایه (گروه ⇒ با همهٔ نوادگان)؛ شناسه‌ها نو، parent ها نگاشته؛ ⇒ رونوشت‌ها (ترتیبِ قانونی، سرگروه آخر) */
export function cloneSubtree(layers: Layer[], id: string, newId: () => string): { clones: Layer[]; map: Map<string, string> } {
  const src = layers.find((l) => l.id === id);
  if (!src) return { clones: [], map: new Map() };
  const ids = new Set([id, ...descendantIds(layers, id)]);
  const map = new Map<string, string>();
  for (const l of layers) if (ids.has(l.id)) map.set(l.id, newId());
  const clones: Layer[] = [];
  for (const l of layers) {
    if (!ids.has(l.id)) continue;
    const c = JSON.parse(JSON.stringify(l)) as Layer;
    c.id = map.get(l.id)!;
    if (l.id === id) {
      const p = l.parent ?? null;
      if (p) c.parent = p;
      else delete (c as { parent?: string | null }).parent;
    } else if (l.parent && map.has(l.parent)) c.parent = map.get(l.parent)!;
    clones.push(c);
  }
  return { clones: canonical(clones), map };
}

/** همهٔ گروه‌های یک سطح که فرزندِ مستقیمِ این والداند (برای نمایشِ درخت) */
export type Row = { layer: Layer; depth: number; kids: number; hidden: boolean };

/** سطرهای پنلِ لایه‌ها: بالاترین لایه اول؛ فرزندانِ گروهِ بسته نیامده‌اند */
export function treeRows(layers: Layer[]): Row[] {
  const m = childrenMap(layers);
  const rows: Row[] = [];
  const walk = (pid: string | null, depth: number, hiddenAbove: boolean) => {
    const items = [...(m.get(pid) ?? [])].reverse();
    for (const l of items) {
      const kids = l.type === "group" ? (m.get(l.id) ?? []).length : 0;
      const hidden = hiddenAbove || !l.visible;
      rows.push({ layer: l, depth, kids, hidden });
      if (l.type === "group" && !(l as GroupLayer).collapsed) walk(l.id, depth + 1, hidden);
    }
  };
  walk(null, 0, false);
  return rows;
}

/** همهٔ لایه‌هایی که با گروهِ id جابه‌جا می‌شوند و مختصاتِ cx,cy دارند */
export function movableDescendants(layers: Layer[], id: string): Layer[] {
  const ids = new Set(descendantIds(layers, id));
  return layers.filter((l) => ids.has(l.id) && "cx" in l);
}
