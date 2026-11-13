/**
 * «دانلودِ مدل‌ها» — رندرِ کارت‌ها به HTML (react-dom/server، بی مرورگر): گروه‌های تازه، مجوز، VRAM، «نیاز دارد»، دانلودِ خودکار،
 * Ollama کنارِ بسته‌ها و پیوندها.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-models-render.test.tsx --bundle --platform=node --format=cjs --jsx=automatic --outfile=/tmp/compute-models-render.test.cjs
 *   node /tmp/compute-models-render.test.cjs
 */
import assert from "node:assert/strict";

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import AutoModelsCard from "../src/features/tools/compute/AutoModelsCard";
import NodeModelsCard from "../src/features/tools/compute/NodeModelsCard";
import OllamaModelsCard from "../src/features/tools/compute/OllamaModelsCard";
import type { AutoSettings, ModelPackage, NodeModels, OllamaView } from "../src/features/tools/compute/nodeModels";

let checks = 0;
const has = (html: string, text: string, msg?: string) => {
  assert.ok(html.includes(text), `${msg ?? "در HTML نیست"}: «${text}»`);
  checks += 1;
};
const hasNot = (html: string, text: string) => {
  assert.ok(!html.includes(text), `نباید در HTML باشد: «${text}»`);
  checks += 1;
};

const pkg = (key: string, title: string, over: Partial<ModelPackage>): ModelPackage => ({
  key, title, title_en: "", note: "", optional: true, installed: false, state: "missing", queued_text: "", total_mb: 1000, missing_mb: 1000, in_comfyui: 0,
  license: "Apache-2.0", license_class: "open", license_text: "تجاری مجاز", commercial: true, vram_fit: "full", vram_text: "", vram_note: "", vram_gb: 8,
  features: [], needs: [], download_mb: 1000, fits: true, needs_restart: false, kind: "files", sources: [], provenance: "",
  auto: { mode: "manual", state: "", text: "" }, ...over,
});

const common = { key: "flux-common", title: "FLUX — رمزگذارها و VAE", installed: false, mb: 5222 };
const node: NodeModels = {
  node: { id: 5, name: "DESKTOP-TEST", online: true, enabled: true, agent: "2.11", last_seen: null, disk_free_mb: 95000, disk_total_gb: 511 },
  reported: true,
  running: true,
  progress: { bytes_done: 500, bytes_total: 1000, items_done: 1, items_total: 3 },
  waiting: null,
  error: "",
  auto: { enabled: true, reserve_gb: 25, wanted: 4, pending_mb: 17000, reported: true, states: {}, why: {} },
  groups: [
    { key: "image", title: "تصویر: ساختِ عکس با هوش مصنوعی", note: "FLUX و SDXL", packages: [
      pkg("flux-schnell", "FLUX.1 schnell (fp8) — تصویرِ سریع در ۴ گام", {
        vram_fit: "offload", needs: [common], download_mb: 16562, missing_mb: 11340, total_mb: 11340,
        features: [{ key: "image_studio", label: "ساختِ تصویر (استودیوی تصویر)", switch: true }],
        auto: { mode: "on", state: "waiting_window", text: "خودکار دانلود می‌شود" } }),
      pkg("flux-dev", "FLUX.1 dev (fp8) — بهترین کیفیتِ FLUX", {
        license: "FLUX.1 [dev] Non-Commercial", license_class: "noncommercial", license_text: "فقط غیرتجاری", commercial: false,
        state: "installed", installed: true, missing_mb: 0, auto: { mode: "never", state: "", text: "" } }),
      pkg("sdxl-base", "SDXL 1.0 پایه + VAEِ fp16", { auto: { mode: "off", state: "", text: "" } }),
    ] },
    { key: "video", title: "ویدیوی هوش مصنوعی و نرم‌کردنِ حرکت", note: "", packages: [
      pkg("ltx-video-distilled", "LTX-Video ۲B (distilled، fp8)", { license: "LTXV Open Weights License 0.X", license_class: "restricted", commercial: false }),
      pkg("frame-interp", "RIFE و FILM — نرم‌کردنِ حرکتِ ویدیو", { auto: { mode: "on", state: "installed", text: "" }, state: "installed", installed: true }),
    ] },
    { key: "upscale", title: "بزرگ‌کردن و ترمیمِ عکس", note: "", packages: [
      pkg("esrgan-x4plus", "Real-ESRGAN x4plus — بزرگ‌کردنِ ۴ برابریِ عکس", { auto: { mode: "on", state: "pending", text: "" } }),
      pkg("codeformer", "ترمیمِ چهره — CodeFormer", { license: "S-Lab License 1.0", license_class: "noncommercial", commercial: false, fits: false }),
    ] },
    { key: "control", title: "کنترل و ثبات (ControlNet و IP-Adapter)", note: "", packages: [
      pkg("ipadapter-sdxl", "IP-Adapter برای SDXL", { needs: [{ key: "nodes-ipadapter-plus", title: "نودِ ComfyUI — IPAdapter plus", installed: false, mb: 4 }] }),
      pkg("nodes-ipadapter-plus", "نودِ ComfyUI — IPAdapter plus", { kind: "node", needs_restart: true }),
    ] },
    { key: "depth", title: "عمق و سه‌بعدی", note: "", packages: [pkg("depth-anything-v2-small", "Depth Anything V2 Small — نقشهٔ عمق از یک عکس", {})] },
    { key: "voice", title: "صدا: گفتار، افکت و موسیقی", note: "", packages: [pkg("moss-tts", "گفتارِ فارسی و کلونِ صدا (MOSS-TTS)", { optional: false, installed: true, state: "installed", auto: { mode: "default", state: "", text: "" } })] },
    { key: "matting", title: "حذفِ پس‌زمینه (عکس و ویدیو)", note: "", packages: [pkg("photo-background", "حذفِ پس‌زمینهٔ عکس — BiRefNet سبک", { optional: false, installed: true, state: "installed" })] },
  ],
};

const auto: AutoSettings = {
  enabled: true, reserve_gb: 25, big_mb: 1536, wanted: ["flux-schnell", "esrgan-x4plus"],
  features: [
    { key: "image_studio", label: "ساختِ تصویر (استودیوی تصویر)", on: true, packages: [{ key: "flux-schnell", title: "FLUX.1 schnell" }], size_mb: 16626 },
    { key: "design_styles", label: "سبک‌های طراحی (SDXL، ControlNet، IP-Adapter)", on: false, packages: [{ key: "sdxl-base", title: "SDXL 1.0" }], size_mb: 7000 },
  ],
};

const ollama: OllamaView = {
  models: [
    { tag: "qwen3:8b", label: "Qwen3 — ۸ میلیاردی", size_mb: 5225, purpose: "سبک‌تر و سریع‌تر", vision: false, installed: true },
    { tag: "gemma3:12b", label: "Gemma 3 — ۱۲ میلیاردی (گوگل)", size_mb: 8164, purpose: "متنِ روزمره", vision: true, installed: false },
  ],
  extra: [{ tag: "my-own:7b", label: "my-own:7b", size_mb: 0, purpose: "روی سرور نصب است", vision: false, installed: true }],
  pulls: [],
  pull_nodes: [{ id: 5, name: "DESKTOP-TEST", online: true, agent: "2.11", pull_ready: true }],
  known: true,
};

// ── کارتِ بسته‌ها: هر هفت گروه، مجوز، VRAM، نیازها، خودکار، دیسک
const html = renderToStaticMarkup(<NodeModelsCard node={node} onChanged={() => undefined} />);
for (const g of node.groups) has(html, g.title, "سرتیترِ گروه");
for (const id of ["image", "video", "upscale", "control", "depth", "voice", "matting"]) has(html, `id="models-group-${id}"`, "لنگرِ گروه");
has(html, "FLUX.1 schnell (fp8)");
has(html, "تجاری مجاز");
has(html, "فقط غیرتجاری");
has(html, "با شرط");
has(html, "۱۲ گیگابایت: با کمی کندی");
has(html, "در ۱۲ گیگابایت جا می‌شود");
has(html, "همراهش دانلود می‌شود:");
has(html, "FLUX — رمزگذارها و VAE");
has(html, "به کارِ این‌ها می‌آید:");
has(html, "خودکار — منتظرِ بازهٔ شبانه");
has(html, "خودکار — نصب شد");
has(html, "خودکار نیست");
has(html, "هرگز خودکار (مجوز)");
has(html, "پیش‌فرضِ سرور");
has(html, "جای دیسک کافی نیست");
has(html, "نودِ ComfyUI");
has(html, "نیاز به راه‌اندازیِ دوبارهٔ ComfyUI");
has(html, "۹۳ گیگابایت خالی از ۵۱۱ گیگابایت");
has(html, "دانلودِ خودکار روشن است: ۱۷ گیگابایت");
has(html, "دانلود در جریان است — ۵۰٪ — ۱ از ۳ فایل");
has(html, 'data-testid="model-pick-flux-schnell"');
has(html, 'data-testid="models-all-image"');
has(html, 'data-testid="models-download"');
has(html, "هیچ بسته‌ای انتخاب نشده.");
// «همهٔ نصب‌نشده‌ها» فقط برای گروه‌هایی که مجوزِ باز و جا دارند؛ گروهی که همه‌اش غیرتجاری یا جا ندارد دکمه‌ای ندارد
hasNot(html, 'data-testid="models-all-voice"');
has(html, "فقط مدل‌های «تجاری مجاز» با جای دیسکِ کافی را می‌گیرد");
// قدیمی‌ها (صدا و حذفِ پس‌زمینه) کنارِ تازه‌ها هستند و بدونِ نشانِ مجوز نمی‌افتند
has(html, "گفتارِ فارسی و کلونِ صدا (MOSS-TTS)");
has(html, "حذفِ پس‌زمینهٔ عکس — BiRefNet سبک");

// ── کارتِ دانلودِ خودکار
const ahtml = renderToStaticMarkup(<AutoModelsCard auto={auto} onChanged={() => undefined} />);
has(ahtml, "دانلودِ خودکارِ مدل‌ها");
has(ahtml, 'data-testid="auto-master"');
has(ahtml, 'data-testid="auto-feature-image_studio"');
has(ahtml, 'data-testid="auto-feature-design_styles"');
has(ahtml, "سبک‌های طراحی (SDXL، ControlNet، IP-Adapter)");
has(ahtml, "حدودِ ۱۶ گیگابایت");
has(ahtml, "هرگز خودکار نیستند");
has(ahtml, "الان ۲ بسته خودکار خواسته شده است");

// ── Ollama کنارِ بسته‌ها
const ohtml = renderToStaticMarkup(
  <MemoryRouter>
    <OllamaModelsCard ollama={ollama} onChanged={() => undefined} providersPage="/admin/providers" />
  </MemoryRouter>,
);
has(ohtml, "مدل‌های متن و بینایی (Ollama)");
has(ohtml, 'id="models-group-ollama"');
has(ohtml, "Qwen3 — ۸ میلیاردی");
has(ohtml, "Gemma 3 — ۱۲ میلیاردی (گوگل)");
has(ohtml, "نصب است");
has(ohtml, "نصب نیست");
has(ohtml, 'data-testid="ollama-pull-gemma3:12b"');
hasNot(ohtml, 'data-testid="ollama-pull-qwen3:8b"');
has(ohtml, "my-own:7b");
has(ohtml, 'href="/admin/providers"');
has(ohtml, "مدل‌های خودِ شما دست‌نخورده می‌مانند");

// سرورِ خاموش و بی گزارش
const off: NodeModels = { ...node, node: { ...node.node, online: false }, reported: false, running: false, progress: null, groups: [] };
const offHtml = renderToStaticMarkup(<NodeModelsCard node={off} onChanged={() => undefined} />);
has(offHtml, "این سرور خاموش است و هنوز فهرستِ مدل‌هایش را نفرستاده");

console.log(`compute-models-render: همهٔ ${checks} بررسی درست`);
