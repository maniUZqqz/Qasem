// تامنیل‌ساز: منطقِ خالصِ سمتِ مرورگر (ایده ⇒ spec، spec ِ پیش‌فرض) — ساخت: esbuild --bundle --platform=node ⇒ node
import { applyIdea, aspectStyle, defaultSpec, EMPTY_CONTENT } from "../src/features/content/thumbs/api";
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

const base = defaultSpec("youtube");
ok(base.format === "youtube" && base.style === "face_text", "پیش‌فرض");
ok(base.background.kind === "auto" && base.subject.asset === null && base.logo.show, "پیش‌فرضِ پس‌زمینه و سوژه");
ok(Object.keys(base.content).sort().join() === Object.keys(EMPTY_CONTENT).sort().join(), "کلیدهای محتوا");
ok(defaultSpec("story", "neon").style === "neon", "سبکِ دلخواه");

const idea: Idea = {
  id: "i1", title: "*۷* اشتباهِ رایج", subtitle: "قبل از شروع", kicker: "فهرست", number: "۷", badge: "", tagline: "", credits: "", cta: "", label_a: "", label_b: "",
  style: "number_list", style_title: "عدد / لیست", format: "ig_portrait", formula: "list_mistakes", formula_label: "فهرستِ اشتباه‌ها", source: "rules",
  concept: "", bg_prompt_en: "", mood: "dark", needs_second: false,
  spec_patch: { format: "ig_portrait", style: "number_list", content: { title: "*۷* اشتباهِ رایج", number: "۷" }, colors: { mood: "dark" } },
};
const withPics = { ...base, subject: { ...base.subject, asset: 12 }, colors: { ...base.colors, accent: "#ff0000", use_brand: false } };
const a = applyIdea(withPics, idea, false);
ok(a.format === "ig_portrait" && a.style === "number_list", "قالب و سبکِ ایده");
ok(a.content.title === "*۷* اشتباهِ رایج" && a.content.number === "۷" && a.content.subtitle === "", "متن‌ها (فیلدهای نیامده خالی)");
ok(a.subject.asset === 12, "عکسِ سوژه می‌ماند");
ok(a.colors.mood === "dark" && a.colors.accent === "#ff0000" && a.colors.use_brand === false, "رنگ‌ها: فقط حال‌وهوا عوض می‌شود");
ok(applyIdea(withPics, idea, true).format === "youtube", "keepFormat");
ok(withPics.style === "face_text", "ورودی تغییر نمی‌کند");
ok(aspectStyle({ width: 1080, height: 1920 }).aspectRatio === "1080 / 1920" && aspectStyle(undefined).aspectRatio === "16 / 9", "نسبتِ تصویر");

console.log(fails ? `thumbs-spec: ${fails} FAIL از ${total}` : `thumbs-spec: همهٔ ${total} بررسی درست`);
if (fails) process.exit(1);
