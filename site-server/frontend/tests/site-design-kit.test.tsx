/**
 * «سبکِ طراحی و قطعه‌های آماده» در ویرایشگرِ دیداری — رندرِ انتخابگرِ سبک و کتابخانهٔ قطعه‌ها به HTML (react-dom/server، بی مرورگر):
 * هر ۱۴ سبک کارتِ خودش را دارد، نامِ فارسی و انگلیسی، دکمهٔ اعمال، گزینه‌های «چیدمان» و «رنگِ برند»، نسبتِ مبدأ/مجوزِ هر قطعه،
 * فیلترِ دسته و محدودهٔ قطعه (سربرگ/پابرگ/صفحه) و نشانِ «جورِ این سبک».
 *
 *   cd frontend && node_modules/.bin/esbuild tests/site-design-kit.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/site-design-kit.test.cjs
 *   node /tmp/site-design-kit.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import { ComponentsPanel, StylePicker } from "../src/features/tools/studio/builder/designKit";
import type { Catalog, CompMeta, Doc } from "../src/features/tools/studio/builder/doc";
import type { StyleT, ThemeColors, ThemeOptions, ThemeT } from "../src/features/tools/studio/builder/types";

const KEYS: [string, string, string][] = [
  ["glassmorphism", "شیشه‌ای", "Glassmorphism"],
  ["claymorphism", "خمیری", "Claymorphism"],
  ["neumorphism", "نرم‌برجسته", "Neumorphism"],
  ["neo-brutalism", "نئوبروتالیسم", "Neo-brutalism"],
  ["bento-grid", "شبکهٔ بنتو", "Bento grid"],
  ["minimalism", "مینیمال", "Minimalism"],
  ["aurora", "شفق (گرادیانِ مش)", "Aurora / gradient mesh"],
  ["dark-luxury", "لوکسِ تیره", "Dark luxury"],
  ["soft-pastel", "پاستلیِ نرم", "Soft pastel"],
  ["corporate-clean", "رسمی و تمیز", "Corporate clean"],
  ["editorial", "مجله‌ای", "Editorial / magazine"],
  ["retro-y2k", "رترو و Y2K", "Retro / Y2K"],
  ["swiss", "سوئیسی (بین‌المللی)", "Swiss / International"],
  ["organic", "ارگانیک", "Organic / biophilic"],
];

const colors = (over: Partial<ThemeColors> = {}): ThemeColors =>
  ({ primary: "#126F85", on_primary: "#ffffff", bg: "#f2f4f7", surface: "#ffffff", text: "#161b2e", muted: "#5b6275", line: "#e1e5ec", accent: "#e0a526", ...over }) as ThemeColors;

const style = (k: string, label: string, en: string): StyleT => ({
  key: k,
  label,
  en,
  mood: `حس‌وحالِ ${label}`,
  desc: `توضیحِ سبکِ ${label}`,
  tags: [k],
  theme: { colors: colors(), font_body: "vazirmatn", font_head: "vazirmatn", button: "round", radius: 14, width: 1120 },
  tokens: { page_bg: "var(--bg)", card_bg: "var(--card)", card_bd: "1px solid var(--line)", card_sh: "0 8px 24px rgba(0,0,0,.08)", card_r: "16px" },
  sections: { hero: "center" },
  uiux: { style_id: k },
});

const options: ThemeOptions = {
  fonts: [{ value: "vazirmatn", label: "وزیرمتن", family: "Vazirmatn" }],
  styles: KEYS.map(([k, l, e]) => style(k, l, e)),
  presets: [],
  buttons: [{ value: "round", label: "گرد" }],
};
const theme: ThemeT = { colors: colors(), font_body: "vazirmatn", font_head: "vazirmatn", button: "round", radius: 14, width: 1120, style: "bento-grid" };
const doc = { v: 1, blocks: [] } as unknown as Doc;

const src = (adapted: boolean): CompMeta["src"] =>
  adapted
    ? { origin: "adapted", library: "Magic UI", author: "dillionverma", license: "MIT", copyright: "Copyright (c) Magic UI", source_url: "https://github.com/magicuidesign/magicui", listing_url: "https://21st.dev/dillionverma/marquee", pattern_ref: "" }
    : { origin: "own", library: "", author: "", license: "", copyright: "", source_url: "", listing_url: "", pattern_ref: "hero" };
const comp = (key: string, cat: string, label: string, adapted: boolean, scope: string[], styles: string[]): CompMeta => ({
  key,
  type: `c_${key}`,
  cat,
  label,
  desc: `توضیحِ ${label}`,
  tags: ["برچسب"],
  styles,
  root: scope[0] === "header" ? "header" : scope[0] === "footer" ? "footer" : "section",
  scope,
  src: src(adapted),
});
const catalog = {
  blocks: [],
  groups: [],
  style: [],
  style_groups: [],
  icons: {},
  icon_names: [],
  components: {
    categories: [
      { key: "hero", label: "سربرگِ بزرگ", icon: "layout", count: 1 },
      { key: "features", label: "ویژگی‌ها", icon: "star", count: 1 },
      { key: "navbar", label: "سربرگِ سایت", icon: "menu", count: 1 },
    ],
    items: [
      comp("hero_center_glow", "hero", "هیروی مرکزی با درخشش", false, ["page"], ["bento-grid", "aurora"]),
      comp("feat_bento_showcase", "features", "بنتوی با پیوندِ نمایشی", true, ["page"], ["bento-grid"]),
      comp("nav_classic", "navbar", "سربرگِ کلاسیک", false, ["header"], ["minimalism"]),
    ],
  },
} as unknown as Catalog;

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}
const has = (html: string, text: string, msg = "در HTML نیست") => assert.ok(html.includes(text), `${msg}: «${text}»`);
const count = (html: string, text: string) => html.split(text).length - 1;

const noop = () => undefined;
const picker = (t: ThemeT, o: ThemeOptions = options) => renderToStaticMarkup(<StylePicker slug="p" theme={t} doc={doc} target="page" options={o} onApply={noop} />);
const panel = (target: string, t: ThemeT = theme, c: Catalog = catalog) =>
  renderToStaticMarkup(<ComponentsPanel catalog={c} target={target} theme={t} slug="p" onAdd={noop} onDragStart={noop} />);

check("انتخابگرِ سبک: هر ۱۴ سبک یک کارت دارد (نامِ فارسی + انگلیسی)", () => {
  const html = picker(theme);
  assert.equal(count(html, 'data-style="'), 14, "تعدادِ کارت‌ها");
  for (const [k, l, e] of KEYS) {
    has(html, `data-style="${k}"`, "کارتِ سبک");
    has(html, l, "نامِ فارسی");
    has(html, e, "نامِ انگلیسی");
  }
});
check("انتخابگرِ سبک: سبکِ فعلی علامت می‌خورد و جزئیات و دکمهٔ اعمال دارد", () => {
  const html = picker(theme);
  has(html, "pick on");
  has(html, 'data-testid="style-detail"');
  has(html, "دوباره اعمال کن");
  has(html, "برداشتنِ سبک");
});
check("انتخابگرِ سبک: گزینهٔ چیدمان و «رنگِ اصلیِ برندم همان بماند» و منبعِ ui-ux-pro-max (MIT)", () => {
  const html = picker(theme);
  has(html, "چیدمانِ بخش‌های همین صفحه هم با سبک جور شود");
  has(html, "رنگِ اصلیِ برندم همان بماند");
  has(html, "ui-ux-pro-max-skill");
  has(html, "MIT");
});
check("انتخابگرِ سبک: بی‌سبک ⇒ همهٔ کارت‌ها هستند ولی «برداشتنِ سبک» و جزئیات نیست", () => {
  const html = picker({ ...theme, style: undefined });
  assert.equal(count(html, 'data-style="'), 14);
  assert.ok(!html.includes('data-testid="apply-style"'));
  assert.ok(!html.includes("برداشتنِ سبک"));
});
check("انتخابگرِ سبک: بدونِ فهرستِ سبک چیزی نمی‌کشد", () => {
  assert.equal(picker(theme, { ...options, styles: [] }), "");
});

check("قطعه‌ها: روی «صفحه» فقط قطعه‌های صفحه؛ سربرگ فقط سربرگ", () => {
  const page = panel("page");
  has(page, 'data-part="hero_center_glow"');
  has(page, 'data-part="feat_bento_showcase"');
  assert.ok(!page.includes('data-part="nav_classic"'), "سربرگ نباید در صفحه بیاید");
  const head = panel("header");
  has(head, 'data-part="nav_classic"');
  assert.ok(!head.includes('data-part="hero_center_glow"'));
});
check("قطعه‌ها: دسته‌ها فقط برای محدودهٔ فعلی؛ جست‌وجو و دکمهٔ پیش‌نمایش", () => {
  const page = panel("page");
  has(page, 'data-cat="hero"');
  has(page, 'data-cat="features"');
  assert.ok(!page.includes('data-cat="navbar"'));
  has(page, "جست‌وجوی قطعه…");
  has(page, "پیش‌نمایش");
});
check("قطعه‌ها: مبدأ و مجوزِ هر قطعه دیده می‌شود (بازنویسی‌شده از Magic UI · MIT / طراحیِ خودمان)", () => {
  const page = panel("page");
  has(page, "بازنویسی‌شده از Magic UI · MIT");
  has(page, "طراحیِ خودمان");
});
check("قطعه‌ها: نشانِ «جورِ این سبک» فقط برای قطعه‌های جورِ سبکِ فعلی", () => {
  assert.equal(count(panel("page"), "جورِ این سبک"), 2);
  assert.equal(count(panel("page", { ...theme, style: undefined }), "جورِ این سبک"), 0);
  assert.equal(count(panel("page", { ...theme, style: "aurora" }), "جورِ این سبک"), 1);
});
check("قطعه‌ها: قطعه‌های جورِ سبک پیش از ناجور می‌آیند", () => {
  const html = panel("page", { ...theme, style: "aurora" });
  assert.ok(html.indexOf('data-part="hero_center_glow"') < html.indexOf('data-part="feat_bento_showcase"'));
});
check("قطعه‌ها: بی‌فهرست پیامِ فارسی می‌دهد", () => {
  has(panel("page", theme, { ...catalog, components: undefined } as unknown as Catalog), "فهرستِ قطعه‌ها نیامد");
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err}` : ""}`);
console.log(`${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
