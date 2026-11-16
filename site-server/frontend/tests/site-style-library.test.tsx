/**
 * انتخابگرِ سبکِ ویرایشگرِ دیداری با ۸۹ سبک: جست‌وجو، گروه‌ها، «روشن/تیره»، «نمایشِ بیشتر»، منبعِ سبک (دست‌ساز/خودکار از ui-ux-pro-max) — رندرِ react-dom/server.
 * (رفتارِ زنده، یعنی تایپ و کلیک، در آزمونِ مرورگرِ واقعیِ apps/projects/browser_checks/check_panel_pages.py سنجیده می‌شود.)
 *
 *   cd frontend && node_modules/.bin/esbuild tests/site-style-library.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --loader:.css=empty --outfile=/tmp/site-style-library.test.cjs
 *   node /tmp/site-style-library.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";

import { StylePicker } from "../src/features/tools/studio/builder/designKit";
import type { Doc } from "../src/features/tools/studio/builder/doc";
import type { StyleT, ThemeColors, ThemeOptions, ThemeT } from "../src/features/tools/studio/builder/types";

const GROUPS = ["عمومی", "اپ و موبایل", "داشبورد و تحلیل", "سیستم‌های طراحی", "الگوی صفحهٔ فرود (قدیمی)"];
const colors = (): ThemeColors => ({ primary: "#126F85", on_primary: "#ffffff", bg: "#f2f4f7", surface: "#ffffff", text: "#161b2e", muted: "#5b6275", line: "#e1e5ec", accent: "#e0a526" }) as ThemeColors;

const styles: StyleT[] = Array.from({ length: 89 }, (_, i) => ({
  key: i < 14 ? `hand-${i}` : `ux-gen-${i}`,
  label: `سبکِ شمارهٔ ${i}`,
  en: `Style number ${i}`,
  mood: "حس",
  desc: "توضیح",
  tags: ["برچسب"],
  theme: { colors: colors(), font_body: "vazirmatn", font_head: "vazirmatn", button: "round", radius: 14, width: 1120 },
  tokens: { page_bg: "var(--bg)", card_bg: "var(--card)" },
  sections: {},
  uiux: { style_id: `row-${i}`, font_pairing: "Minimal Swiss", palette: "SaaS (General)" },
  source: i < 14 ? "hand" : "generated",
  group: GROUPS[i < 14 ? 0 : 1 + (i % 4)],
  status: i === 20 ? "deprecated" : "active",
  rtl: i === 21 ? "caveats" : "full",
  dark: i % 5 === 0,
}));
const options: ThemeOptions = { fonts: [{ value: "vazirmatn", label: "وزیرمتن", family: "Vazirmatn" }], styles, presets: [], buttons: [{ value: "round", label: "گرد" }] };
const theme: ThemeT = { colors: colors(), font_body: "vazirmatn", font_head: "vazirmatn", button: "round", radius: 14, width: 1120, style: "ux-gen-30" };
const doc = { v: 1, blocks: [] } as unknown as Doc;

let passed = 0;
function t(name: string, fn: () => void) {
  fn();
  passed += 1;
  console.log("ok   " + name);
}

const html = renderToStaticMarkup(<StylePicker slug="demo" theme={theme} doc={doc} target="page" options={options} onApply={() => undefined} />);

t("۸۹ سبک: فقط ۲۴ کارتِ اول کشیده می‌شود و «نمایشِ بیشتر» هست", () => {
  assert.equal((html.match(/class="nbe-style /g) ?? []).length, 24);
  assert.match(html, /نمایشِ بیشتر/);
  assert.match(html, /۸۹ سبک \(۲۴ تای اول\)/);
});

t("جست‌وجو و گروه‌ها و روشن/تیره هست", () => {
  assert.match(html, /data-testid="style-search"/);
  assert.match(html, /placeholder="جست‌وجوی ۸۹ سبک/);
  for (const g of GROUPS) assert.ok(html.includes(`data-group="${g}"`), g);
  assert.match(html, />روشن</);
  assert.match(html, />تیره</);
});

t("سبکِ فعلی (خودکار) جزئیات، منبعِ ردیف و جفتِ قلمِ لاتین را می‌گوید", () => {
  assert.match(html, /data-testid="style-source"/);
  assert.match(html, /ساخته‌شده خودکار از ردیفِ/);
  assert.match(html, /row-30/);
  assert.match(html, /Minimal Swiss/);
  assert.match(html, /SaaS \(General\)/);
});

t("برچسبِ «الگوی قدیمی» و «راست‌به‌چپ: با احتیاط» روی کارت‌ها", () => {
  const all = renderToStaticMarkup(<StylePicker slug="demo" theme={{ ...theme, style: undefined }} doc={doc} target="page" options={{ ...options, styles: styles.slice(0, 24).map((s, i) => ({ ...s, status: i === 20 ? "deprecated" : "active", rtl: i === 21 ? "caveats" : "full" })) }} onApply={() => undefined} />);
  assert.match(all, /الگوی قدیمی/);
  assert.match(all, /راست‌به‌چپ: با احتیاط/);
});

t("پیوندِ همهٔ داده‌ها و نامِ منبع و مجوز", () => {
  assert.match(html, /ui-ux-pro-max-skill/);
  assert.match(html, /MIT/);
  assert.match(html, /منبع‌های طراحی/);
});

console.log(`${passed}/${passed} passed`);
