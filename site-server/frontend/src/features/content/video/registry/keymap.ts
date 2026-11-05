import type { FeatureDef } from "./types";

/**
 * لایهٔ میان‌برها:
 *  - `comboOf(e)`  رویدادِ صفحه‌کلید ⇒ رشتهٔ یکتا («Ctrl+Shift+K»). از روی کلیدِ فیزیکی (e.code) می‌خواند، پس با صفحه‌کلیدِ فارسی هم کار می‌کند.
 *  - `latinKey(e)` همان برای کدِ قدیمیِ فضای کار که با e.key کار می‌کند (روی صفحه‌کلیدِ فارسی «س» به‌جای S می‌داد و میان‌برها کار نمی‌کردند).
 *  - `buildKeymap` میان‌برهای پیش‌فرضِ ویژگی‌های تازه + تغییرهای کاربر را یک‌جا می‌کند و کلیدهای پیش‌فرضِ قدیمیِ تغییرداده‌شده را «خنثی» می‌کند.
 * ذخیرهٔ تغییرها فقط در مرورگرِ همین کاربر است (`nm.video.keys`).
 */

const CODE_NAMES: Record<string, string> = {
  Space: "Space", Comma: ",", Period: ".", Minus: "-", Equal: "=", Backslash: "\\", Slash: "/", BracketLeft: "[", BracketRight: "]",
  Semicolon: ";", Quote: "'", Backquote: "`", NumpadAdd: "+", NumpadSubtract: "-",
};
const NAMED = new Set([
  "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown", "Delete", "Backspace", "Enter", "Escape", "Tab", "Insert",
]);

/** نامِ کلیدِ فیزیکی (بدونِ تکیه به زبانِ صفحه‌کلید) یا "" اگر کلیدی نیست (فقط Ctrl/Shift/Alt) */
export function baseKey(e: Pick<KeyboardEvent, "code" | "key">): string {
  const c = e.code || "";
  let m: RegExpMatchArray | null;
  if ((m = c.match(/^Key([A-Z])$/))) return m[1];
  if ((m = c.match(/^Digit(\d)$/))) return m[1];
  if ((m = c.match(/^Numpad(\d)$/))) return m[1];
  if (/^F\d{1,2}$/.test(c)) return c;
  if (CODE_NAMES[c]) return CODE_NAMES[c];
  if (NAMED.has(c)) return c;
  const k = e.key || "";
  if (k === "Control" || k === "Shift" || k === "Alt" || k === "Meta") return "";
  if (k.length === 1) return /[a-z]/i.test(k) ? k.toUpperCase() : k;
  return NAMED.has(k) ? k : k === " " ? "Space" : "";
}

export function comboOf(e: Pick<KeyboardEvent, "code" | "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">): string {
  const key = baseKey(e);
  if (!key) return "";
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("Ctrl");
  if (e.altKey) parts.push("Alt");
  if (e.shiftKey) parts.push("Shift");
  parts.push(key);
  return parts.join("+");
}

/** کلیدِ لاتین برای کدِ قدیمی: اگر صفحه‌کلید فارسی/عربی است، از کلیدِ فیزیکی می‌خوانَد؛ وگرنه همان e.key */
export function latinKey(e: Pick<KeyboardEvent, "code" | "key">): string {
  const k = e.key;
  if (k.length !== 1 || /^[\x00-\x7f]$/.test(k)) return k;
  const b = baseKey(e);
  if (/^[A-Z]$/.test(b)) return b.toLowerCase();
  return b.length === 1 ? b : k;
}

/** رشتهٔ دلخواه («ctrl + shift + k») ⇒ شکلِ استاندارد؛ "" اگر نامعتبر */
export function normalizeCombo(s: string): string {
  const raw = String(s || "").trim();
  if (!raw) return "";
  const parts = raw.split("+").map((x) => x.trim()).filter(Boolean);
  if (raw.endsWith("++") || raw === "+") parts.push("+");
  const mods = new Set<string>();
  let key = "";
  for (const p of parts) {
    const l = p.toLowerCase();
    if (l === "ctrl" || l === "cmd" || l === "meta" || l === "control") mods.add("Ctrl");
    else if (l === "alt" || l === "option") mods.add("Alt");
    else if (l === "shift") mods.add("Shift");
    else key = NAMED.has(p) ? p : l === "space" ? "Space" : p.length === 1 ? (/[a-z]/i.test(p) ? p.toUpperCase() : p) : p;
  }
  if (!key) return "";
  return [mods.has("Ctrl") ? "Ctrl" : "", mods.has("Alt") ? "Alt" : "", mods.has("Shift") ? "Shift" : "", key].filter(Boolean).join("+");
}

const ARROWS: Record<string, string> = { ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓", Backspace: "⌫", Escape: "Esc" };
/** نمایشِ زیبا برای رابط */
export function prettyCombo(c: string): string {
  return c.split("+").map((p) => ARROWS[p] ?? p).join("+");
}

// ───────── ذخیره
const KEY = "nm.video.keys";
export type KeyOverrides = Record<string, string>;
export function loadOverrides(): KeyOverrides {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    const out: KeyOverrides = {};
    for (const [id, v] of Object.entries(raw)) if (typeof v === "string") out[id] = normalizeCombo(v);
    return out;
  } catch {
    return {};
  }
}
export function saveOverrides(o: KeyOverrides): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(o));
  } catch {
    /* حافظهٔ مرورگر بسته است */
  }
}

export type Keymap = {
  /** ترکیب ⇒ ویژگی (فقط آن‌هایی که این لایه اجرا می‌کند: تازه‌ها و تغییرداده‌شده‌ها) */
  byCombo: Map<string, FeatureDef>;
  /** ترکیب‌های پیش‌فرضِ قدیمی که کاربر عوض کرده؛ باید نادیده گرفته شوند */
  suppressed: Set<string>;
  /** میان‌برِ مؤثرِ هر ویژگی ("" = بدونِ میان‌بر) */
  effective: (id: string) => string;
  /** کدام ویژگی این ترکیب را دارد (پیش‌فرض یا کاربر) — برای هشدارِ تداخل */
  owner: (combo: string, exceptId?: string) => FeatureDef | undefined;
};

export function buildKeymap(features: FeatureDef[], overrides: KeyOverrides): Keymap {
  const byCombo = new Map<string, FeatureDef>();
  const suppressed = new Set<string>();
  const eff = new Map<string, string>();
  for (const f of features) {
    const def = f.keys ? normalizeCombo(f.keys) : "";
    const has = Object.prototype.hasOwnProperty.call(overrides, f.id);
    const combo = has ? overrides[f.id] : def;
    eff.set(f.id, combo);
    if (has && f.legacy && def && def !== combo) suppressed.add(def);
    const runsHere = has || !f.legacy;
    if (combo && runsHere) byCombo.set(combo, f);
  }
  // اگر کاربر ترکیبی را به ویژگیِ دیگری داده که پیش‌فرضِ قدیمیِ ویژگیِ سوم بود، آن پیش‌فرض خنثی می‌شود (کاربر برنده است)
  return {
    byCombo,
    suppressed,
    effective: (id) => eff.get(id) ?? "",
    owner: (combo, exceptId) => features.find((f) => f.id !== exceptId && eff.get(f.id) === combo),
  };
}

/** آیا این رویداد در یک کادرِ نوشتن است؟ (همان قاعدهٔ کدِ قدیمی: لغزنده و تیک مجازند) */
export function typingTarget(t: EventTarget | null): boolean {
  if (typeof HTMLElement === "undefined" || !(t instanceof HTMLElement)) return false;
  if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return true;
  if (t instanceof HTMLInputElement && !["range", "checkbox"].includes(t.type)) return true;
  return t.isContentEditable;
}
