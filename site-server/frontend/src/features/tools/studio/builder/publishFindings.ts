/**
 * بررسیِ پیش از «انتشار»: متنِ نمونه، شمارهٔ ساختگی، پیوندِ خالی، تصویرِ بی‌توضیح یا انتخاب‌نشده.
 * سرور (builder/placeholders.py) هر مورد را با یک «نوع» می‌فرستد؛ این‌جا فقط گروه‌بندی و حافظهٔ «این‌ها را دیدم و می‌خواهم» است.
 */
export type Finding = {
  id: string;
  type: string;
  kind: string;
  text: string;
  target: string;
  page: number | null;
  page_title: string;
};

export const KIND_LABEL: Record<string, string> = {
  sample: "متنِ نمونه",
  contact: "شماره یا نشانیِ ساختگی",
  link: "پیوندِ خالی",
  media: "تصویر یا ویدیوی انتخاب‌نشده",
  alt: "تصویرِ بی‌توضیح",
};
export const KIND_ORDER = ["sample", "contact", "link", "media", "alt"];

export function isPlaceholderKind(kind?: string): boolean {
  return !!kind && kind in KIND_LABEL;
}

export type Warn = { id: string; type: string; text: string; kind?: string };

/** هشدارهای رندر ⇒ «هنوز نمونه است» جدا، پیشنهادهای دیگر جدا. */
export function splitWarnings<T extends Warn>(ws: T[]): { placeholders: T[]; general: T[] } {
  const placeholders: T[] = [];
  const general: T[] = [];
  for (const w of ws) (isPlaceholderKind(w.kind) ? placeholders : general).push(w);
  return { placeholders, general };
}

export function groupFindings(fs: Finding[]): { kind: string; label: string; items: Finding[] }[] {
  const out: { kind: string; label: string; items: Finding[] }[] = [];
  for (const kind of KIND_ORDER) {
    const items = fs.filter((f) => f.kind === kind);
    if (items.length) out.push({ kind, label: KIND_LABEL[kind], items });
  }
  return out;
}

function hash(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

export function fingerprint(f: Finding): string {
  return [f.target, f.page ?? "", f.id, f.kind, hash(f.text)].join(":");
}

const KEY = (slug: string) => `nbe-confirmed:${slug}`;

export function loadConfirmed(slug: string): Set<string> {
  try {
    const raw = localStorage.getItem(KEY(slug));
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

/** کاربر با چشمِ باز تأیید کرد: همین موردها دفعهٔ بعد مزاحم نمی‌شوند؛ موردِ تازه یا عوض‌شده دوباره می‌پرسد. */
export function rememberConfirmed(slug: string, fs: Finding[]): void {
  try {
    const all = loadConfirmed(slug);
    for (const f of fs) all.add(fingerprint(f));
    localStorage.setItem(KEY(slug), JSON.stringify([...all].slice(-400)));
  } catch {
    /* حافظهٔ مرورگر بسته است؛ فقط دفعهٔ بعد دوباره می‌پرسد */
  }
}

export function needsConfirm(fs: Finding[], confirmed: Set<string>): Finding[] {
  return fs.filter((f) => !confirmed.has(fingerprint(f)));
}
