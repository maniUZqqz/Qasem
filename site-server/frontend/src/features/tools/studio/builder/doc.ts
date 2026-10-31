/** مدلِ سند و عملیاتِ درختیِ ویرایشگرِ دیداری. رندر فقط سمتِ سرور است؛ این‌جا فقط داده جابه‌جا می‌شود. */

export type Rec = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
export type Device = "d" | "t" | "p";
export type StyleMap = Partial<Record<Device, Rec>>;
export type Block = { id: string; type: string; props: Rec; style: StyleMap; children?: Block[] };
export type Doc = { v: number; blocks: Block[]; extra_css?: string };

export type FieldSpec = {
  key: string;
  label: string;
  kind: string;
  options?: { value: string | number; label: string }[];
  min?: number;
  max?: number;
  unit?: string;
  device?: boolean;
  fields?: FieldSpec[];
  add_label?: string;
  item_label?: string;
  inline?: boolean;
  help?: string;
  dir?: string;
  accept?: string;
  only_if?: string;
  group?: string;
};

export type BlockSpec = {
  type: string;
  label: string;
  group: string;
  icon: string;
  hint: string;
  container: boolean;
  root: boolean;
  structural: boolean;
  hidden: boolean;
  advanced: boolean;
  scope: string[];
  fields: FieldSpec[];
  style: string[];
  defaults: Rec;
};

export type Catalog = {
  blocks: BlockSpec[];
  groups: { value: string; label: string }[];
  style: FieldSpec[];
  style_groups: { value: string; label: string }[];
  icons: Record<string, string>;
  icon_names: string[];
};

export type DropTarget = { parent: string | null; index: number; wrap: boolean };

export function newId(): string {
  const a = new Uint8Array(4);
  crypto.getRandomValues(a);
  return Array.from(a, (x) => x.toString(16).padStart(2, "0")).join("");
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

export function specOf(cat: Catalog, type: string): BlockSpec | undefined {
  return cat.blocks.find((b) => b.type === type);
}

export function makeBlock(cat: Catalog, type: string): Block {
  const spec = specOf(cat, type);
  const b: Block = { id: newId(), type, props: clone(spec?.defaults ?? {}), style: {} };
  if (type === "columns") {
    const n = Number(b.props.count) || 2;
    b.children = Array.from({ length: n }, () => makeBlock(cat, "column"));
  } else if (spec?.container) {
    b.children = [];
  }
  return b;
}

export function refreshIds(b: Block): Block {
  b.id = newId();
  (b.children ?? []).forEach(refreshIds);
  return b;
}

export type Found = { block: Block; parent: Block | null; list: Block[]; index: number };

export function find(doc: Doc, id: string): Found | null {
  const walk = (list: Block[], parent: Block | null): Found | null => {
    for (let i = 0; i < list.length; i += 1) {
      const b = list[i];
      if (b.id === id) return { block: b, parent, list, index: i };
      if (b.children) {
        const r = walk(b.children, b);
        if (r) return r;
      }
    }
    return null;
  };
  return walk(doc.blocks, null);
}

export function isInside(block: Block, id: string): boolean {
  if (block.id === id) return true;
  return (block.children ?? []).some((c) => isInside(c, id));
}

export function updateBlock(doc: Doc, id: string, fn: (b: Block) => void): Doc {
  const d = clone(doc);
  const f = find(d, id);
  if (f) fn(f.block);
  return d;
}

export function setPath(obj: Rec, path: string, value: unknown): void {
  const keys = path.split(".");
  let cur: Rec = obj;
  for (const k of keys.slice(0, -1)) cur = cur[k];
  cur[keys[keys.length - 1]] = value;
}

export function setProp(doc: Doc, id: string, path: string, value: unknown): Doc {
  return updateBlock(doc, id, (b) => setPath(b.props, path, value));
}

export function setStyle(doc: Doc, id: string, device: Device, key: string, value: unknown): Doc {
  return updateBlock(doc, id, (b) => {
    const row: Rec = { ...(b.style?.[device] ?? {}) };
    if (value === "" || value === null || value === undefined || value === false) delete row[key];
    else row[key] = value;
    b.style = { ...(b.style ?? {}), [device]: row };
    if (!Object.keys(row).length) delete b.style[device];
  });
}

/** تعدادِ ستون را عوض می‌کند؛ محتوای ستونِ حذف‌شده به ستونِ آخر می‌رود و گم نمی‌شود. */
export function setColumnCount(doc: Doc, cat: Catalog, id: string, count: number): Doc {
  return updateBlock(doc, id, (b) => {
    const kids = b.children ?? [];
    while (kids.length < count) kids.push(makeBlock(cat, "column"));
    while (kids.length > count) {
      const gone = kids.pop() as Block;
      const last = kids[kids.length - 1];
      last.children = [...(last.children ?? []), ...(gone.children ?? [])];
    }
    b.children = kids;
    b.props.count = count;
  });
}

export function removeBlock(doc: Doc, id: string): Doc {
  const d = clone(doc);
  const f = find(d, id);
  if (f) f.list.splice(f.index, 1);
  return d;
}

export function duplicateBlock(doc: Doc, id: string): { doc: Doc; id: string | null } {
  const d = clone(doc);
  const f = find(d, id);
  if (!f) return { doc, id: null };
  const copy = refreshIds(clone(f.block));
  f.list.splice(f.index + 1, 0, copy);
  return { doc: d, id: copy.id };
}

export function moveSibling(doc: Doc, id: string, dir: -1 | 1): Doc {
  const d = clone(doc);
  const f = find(d, id);
  if (!f) return doc;
  const j = f.index + dir;
  if (j < 0 || j >= f.list.length) return doc;
  [f.list[f.index], f.list[j]] = [f.list[j], f.list[f.index]];
  return d;
}

function targetList(d: Doc, parent: string | null): Block[] | null {
  if (parent === null) return d.blocks;
  const f = find(d, parent);
  if (!f) return null;
  f.block.children = f.block.children ?? [];
  return f.block.children;
}

/** گذاشتنِ بلوکِ تازه؛ اگر بلوکی که باید داخلِ بخش باشد در ریشه بیفتد، خودش یک بخش می‌گیرد. */
export function insertBlock(doc: Doc, cat: Catalog, block: Block, t: DropTarget): { doc: Doc; id: string } {
  const d = clone(doc);
  const list = targetList(d, t.parent);
  if (!list) return { doc, id: block.id };
  const needsWrap = t.parent === null && t.wrap;
  const item = needsWrap ? { ...makeBlock(cat, "section"), children: [block] } : block;
  list.splice(Math.max(0, Math.min(t.index, list.length)), 0, item);
  return { doc: d, id: block.id };
}

export function moveBlock(doc: Doc, cat: Catalog, id: string, t: DropTarget): Doc {
  const d = clone(doc);
  const f = find(d, id);
  if (!f) return doc;
  if (t.parent && isInside(f.block, t.parent)) return doc; // داخلِ خودش نمی‌رود
  const sameList = (t.parent === null && f.parent === null) || t.parent === f.parent?.id;
  const [moving] = f.list.splice(f.index, 1);
  const list = targetList(d, t.parent);
  if (!list) return doc;
  let index = t.index;
  if (sameList && index > f.index) index -= 1;
  const needsWrap = t.parent === null && t.wrap;
  list.splice(Math.max(0, Math.min(index, list.length)), 0, needsWrap ? { ...makeBlock(cat, "section"), children: [moving] } : moving);
  return d;
}

/** کجا افزودن با یک کلیک: بعد از بلوکِ انتخاب‌شده، وگرنه ته صفحه */
export function clickTarget(doc: Doc, cat: Catalog, type: string, selected: string | null): DropTarget {
  const spec = specOf(cat, type);
  const f = selected ? find(doc, selected) : null;
  if (spec?.root || !f) {
    let rootIndex = doc.blocks.length;
    if (f) {
      let cur: Found | null = f;
      while (cur?.parent) cur = find(doc, cur.parent.id);
      if (cur) rootIndex = cur.index + 1;
    }
    return { parent: null, index: rootIndex, wrap: !spec?.root };
  }
  const sel = f.block;
  if (specOf(cat, sel.type)?.container) return { parent: sel.id, index: (sel.children ?? []).length, wrap: false };
  if (f.parent) {
    if (specOf(cat, f.parent.type)?.container) return { parent: f.parent.id, index: f.index + 1, wrap: false };
  }
  return { parent: null, index: f.parent ? doc.blocks.length : f.index + 1, wrap: true };
}

export function ancestors(doc: Doc, id: string): Block[] {
  const out: Block[] = [];
  let f = find(doc, id);
  while (f?.parent) {
    out.unshift(f.parent);
    f = find(doc, f.parent.id);
  }
  return out;
}

/** مقدارِ مؤثرِ یک تنظیم در این دستگاه: تبلت از رایانه ارث می‌برد، گوشی از تبلت و رایانه. */
export function styleValue(style: StyleMap | undefined, device: Device, key: string): unknown {
  const order: Device[] = device === "p" ? ["p", "t", "d"] : device === "t" ? ["t", "d"] : ["d"];
  for (const dev of order) {
    const v = style?.[dev]?.[key];
    if (v !== undefined) return v;
  }
  return undefined;
}

/** رنگِ روی رنگِ اصلی: سفید یا تیره، هر کدام خواناتر است. */
export function readableOn(hex: string): string {
  return luminance(hex) > 0.45 ? "#0f172a" : "#ffffff";
}

export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const f = (i: number) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(0) + 0.7152 * f(2) + 0.0722 * f(4);
}

export function contrastRatio(a: string, b: string): number {
  const x = luminance(a);
  const y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

export function mix(a: string, b: string, t: number): string {
  const pa = a.replace("#", "");
  const pb = b.replace("#", "");
  const out = [0, 2, 4].map((i) => {
    const x = parseInt(pa.slice(i, i + 2), 16);
    const y = parseInt(pb.slice(i, i + 2), 16);
    return Math.round(x + (y - x) * t)
      .toString(16)
      .padStart(2, "0");
  });
  return `#${out.join("")}`;
}
