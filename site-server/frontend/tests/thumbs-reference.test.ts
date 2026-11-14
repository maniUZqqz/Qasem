// تامنیل‌ساز: ایده‌ای که از «مرجع» آمده رنگ و سمتِ سوژه را هم اعمال می‌کند؛ ایدهٔ معمولی همان رفتارِ قبل را دارد.
// ساخت: esbuild --bundle --platform=node ⇒ node
import { applyIdea, defaultSpec } from "../src/features/content/thumbs/api";
import type { Idea } from "../src/features/content/thumbs/api";

let fails = 0;
let total = 0;
const ok = (c: unknown, msg: string) => {
  total++;
  if (!c) {
    fails++;
    console.log("FAIL:", msg);
  }
};

const base = defaultSpec("poster");
const plain: Idea = {
  id: "i1", title: "برنامهٔ شخصی", subtitle: "", kicker: "", number: "", badge: "", tagline: "", credits: "", cta: "", label_a: "", label_b: "",
  style: "cinema_poster", style_title: "پوسترِ سینمایی", format: "poster", formula: "x", formula_label: "x", source: "rules", concept: "", bg_prompt_en: "", mood: "cinema",
  needs_second: false, spec_patch: { format: "poster", style: "cinema_poster", content: { title: "برنامهٔ شخصی" }, colors: { mood: "cinema" } },
};
const mine = { ...base, colors: { ...base.colors, primary: "#111111", use_brand: true }, subject: { ...base.subject, asset: 7, side: "auto" as const } };

// ایدهٔ معمولی: رنگ‌ها و سوژه دست نمی‌خورند
const a = applyIdea(mine, plain, false);
ok(a.colors.primary === "#111111" && a.colors.use_brand === true, "رنگ‌های من می‌ماند");
ok(a.subject.side === "auto" && a.subject.asset === 7, "سوژهٔ من می‌ماند");
ok(a.colors.mood === "cinema" && a.style === "cinema_poster", "حال‌وهوا و سبک");

// از مرجع، رنگِ برند بماند: فقط حال‌وهوا و سمتِ سوژه
const refBrand: Idea = {
  ...plain,
  reference: { id: "abc", title: "پوستر", source: "commons", source_label: "پوسترِ آزاد", mood_fa: "سینمایی", image: "/media/x.jpg" },
  spec_patch: { ...plain.spec_patch, colors: { mood: "cinema", use_brand: true }, subject: { side: "left" } },
};
const b = applyIdea(mine, refBrand, false);
ok(b.subject.side === "left" && b.subject.asset === 7, "سمتِ سوژه از مرجع، خودِ عکسِ سوژه می‌ماند");
ok(b.colors.use_brand === true && b.colors.primary === "", "رنگِ برند ⇒ رنگ‌های دستیِ قبلی پاک (برند حکم می‌کند)");
ok(b.colors.mood === "cinema", "حال‌وهوای مرجع");

// از مرجع، رنگ‌ها هم از مرجع
const refColors: Idea = {
  ...refBrand,
  spec_patch: { ...plain.spec_patch, colors: { mood: "cinema", use_brand: false, primary: "#0f766e", secondary: "#ea580c", accent: "#ffd400" }, subject: { side: "right" } },
};
const c = applyIdea(mine, refColors, false);
ok(c.colors.use_brand === false && c.colors.primary === "#0f766e" && c.colors.secondary === "#ea580c" && c.colors.accent === "#ffd400", "رنگ‌های مرجع");
ok(c.subject.side === "right", "سمتِ راست");

// جانبِ قالب: keepFormat
ok(applyIdea(mine, refColors, true).format === base.format, "keepFormat");
// ایدهٔ بدونِ subject در patch
const noSide: Idea = { ...refBrand, spec_patch: { ...refBrand.spec_patch, subject: undefined } };
ok(applyIdea(mine, noSide, false).subject.side === "auto", "بدونِ subject در patch دست نمی‌زند");

console.log(fails ? `${fails} of ${total} FAILED` : `ok ${total}`);
process.exit(fails ? 1 : 0);
