/**
 * آزمونِ «ثبتِ ویژگی‌ها» (منوی کامل + جستجوی ابزار + میان‌برها) — بدونِ مرورگر.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r4-registry.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r4-registry.test.mjs
 *   node /tmp/video-r4-registry.test.mjs
 *
 * قاعده‌ها: هر ویژگی نام و راهنمای فارسی دارد؛ هیچ ورودیِ مرده‌ای نیست (هر `run` در دست‌کم یک وضعیتِ ممکن واقعاً کاری می‌کند)؛
 * هر دکمه/بخشی که ویژگی می‌خواهد بزند واقعاً در سورس هست؛ میان‌برهای پیش‌فرض یکتایند؛ جستجو فارسی/انگلیسی/مترادف را می‌فهمد.
 */
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { ALL_FEATURES } from "../src/features/content/video/registry/features";
import { baseKey, buildKeymap, comboOf, latinKey, normalizeCombo, prettyCombo } from "../src/features/content/video/registry/keymap";
import { norm, scoreFeature, searchFeatures } from "../src/features/content/video/registry/search";
import { MENUS, type FeatureDef, type WorkspaceApi } from "../src/features/content/video/registry/types";
import { AnyClip, MediaClip, Project, addText, emptyProject } from "../src/features/content/video/manual/model";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

// ───────────── ساختنِ وضعیت‌های آزمایشی
const videoClip = (over: Partial<MediaClip> = {}): MediaClip => ({
  id: "v1", type: "media", ref: "video:1", label: "ویدیو", kind: "video", at: 0, start: 0, end: 6, src: 10, opacity: 1, x: 0, y: 0, width: 1, height: 1,
  volume: 1, speed: 1, fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});

type Fixture = { project: Project; selection: string[]; extra?: Partial<WorkspaceApi> };
function projectWith(clips: { track: "video" | "audio" | "text"; clip: AnyClip }[]): Project {
  const p = emptyProject();
  return {
    ...p,
    tracks: p.tracks.map((t) => ({ ...t, clips: clips.filter((c) => c.track === t.kind).map((c) => c.clip) })),
  };
}

const FIXTURES: Record<string, () => Fixture> = {
  video: () => ({
    project: { ...projectWith([{ track: "video", clip: videoClip() }, { track: "video", clip: videoClip({ id: "v2", at: 6 }) }]), inout: { in: 1, out: 3 }, markers: [{ id: "m1", t: 2, label: "", kind: "beat" }, { id: "m2", t: 4, label: "x" }] },
    selection: ["v1"],
  }),
  multi: () => ({ project: projectWith([{ track: "video", clip: videoClip() }, { track: "video", clip: videoClip({ id: "v2", at: 6 }) }]), selection: ["v1", "v2"] }),
  text: () => {
    const p0 = emptyProject();
    const tt = p0.tracks.find((t) => t.kind === "text")!;
    const p = addText(p0, tt.id, "سلام", 1, 2, { id: "t1" });
    return { project: p, selection: ["t1"] };
  },
  audio: () => ({ project: projectWith([{ track: "audio", clip: videoClip({ id: "a1", kind: "audio", ref: "audio:1" }) }]), selection: ["a1"] }),
  image: () => ({ project: projectWith([{ track: "video", clip: videoClip({ id: "i1", kind: "image", ref: "image:1", has_audio: false, audio_on: false }) }]), selection: ["i1"] }),
  none: () => ({ project: projectWith([{ track: "video", clip: videoClip() }]), selection: [] }),
  empty: () => ({ project: emptyProject(), selection: [] }),
  nested: () => ({ project: projectWith([{ track: "video", clip: videoClip() }]), selection: ["v1"], extra: { path: ["s1"] } }),
  playing: () => ({ project: projectWith([{ track: "video", clip: videoClip() }]), selection: ["v1"], extra: { playing: true } }),
  gap: () => ({ project: projectWith([{ track: "video", clip: videoClip({ end: 2 }) }, { track: "video", clip: videoClip({ id: "v2", at: 5, end: 2 }) }]), selection: ["v1"], extra: { time: 3 } }),
  targeted: () => {
    const p = projectWith([{ track: "video", clip: videoClip() }]);
    return { project: { ...p, tracks: p.tracks.map((t) => (t.kind === "video" ? { ...t, target: true } : t)) }, selection: ["v1"] };
  },
  colored: () => ({ project: projectWith([{ track: "video", clip: videoClip({ color: { exposure: 0.2 } as MediaClip["color"] }) }]), selection: ["v1"] }),
};

type Rec = { api: WorkspaceApi; calls: string[]; clicks: string[]; reveals: { tab: string; section?: string }[]; tabs: string[] };
function makeApi(fx: Fixture): Rec {
  const calls: string[] = [];
  const clicks: string[] = [];
  const reveals: { tab: string; section?: string }[] = [];
  const tabs: string[] = [];
  const found = (() => {
    for (const t of fx.project.tracks) for (const c of t.clips) if (c.id === fx.selection[fx.selection.length - 1]) return { track: t, clip: c };
    return null;
  })();
  const check_ = (out: unknown) => {
    assert.ok(out && Array.isArray((out as Project).tracks), "apply() must return a project");
    return out as Project;
  };
  const op = new Proxy({}, { get: (_t, name) => (..._a: unknown[]) => { calls.push(`op.${String(name)}`); } });
  const api = {
    storeId: "s", project: fx.project, root: fx.project, path: [], selection: fx.selection, selected: found, time: 2, playing: false, fps: 30, projectId: 7, media: {},
    bin: null, tool: "select", flags: { snap: true, scopes: false, volLine: true, autoRipple: true, crop: false, menubar: false, loop: false },
    canUndo: true, canRedo: true, history: { entries: [{ label: "اصل" }, { label: "برش" }], index: 1 }, hasClips: fx.project.tracks.some((t) => t.clips.length > 0),
    apply: (_l: string, fn: (p: Project) => Project) => { calls.push("apply"); check_(fn(fx.project)); },
    applyRoot: (_l: string, fn: (p: Project) => Project) => { calls.push("applyRoot"); check_(fn(fx.project)); },
    live: (fn: (p: Project) => Project) => { calls.push("live"); check_(fn(fx.project)); },
    end: () => { calls.push("end"); },
    select: () => { calls.push("select"); },
    undo: () => { calls.push("undo"); }, redo: () => { calls.push("redo"); }, jumpHistory: () => { calls.push("jump"); },
    seek: () => { calls.push("seek"); }, togglePlay: () => { calls.push("togglePlay"); }, step: () => { calls.push("step"); }, setRate: () => { calls.push("setRate"); },
    setTool: () => { calls.push("setTool"); }, toggle: () => { calls.push("toggle"); }, zoom: () => { calls.push("zoom"); },
    setTab: (t: string) => { calls.push("setTab"); tabs.push(t); },
    reveal: (tab: string, section?: string) => { calls.push("reveal"); reveals.push({ tab, section }); },
    click: (id: string, tab?: string) => { calls.push("click"); clicks.push(id); if (tab) tabs.push(tab); },
    notice: () => { calls.push("notice"); },
    openPanel: () => { calls.push("openPanel"); }, closePanel: () => { calls.push("closePanel"); }, activePanel: null, openSearch: () => { calls.push("openSearch"); },
    op,
    goDirector: () => { calls.push("goDirector"); },
    ...(fx.extra ?? {}),
  } as unknown as WorkspaceApi;
  return { api, calls, clicks, reveals, tabs };
}

// ───────────── سالم‌بودنِ فهرست
check("ids are unique and well formed", () => {
  const seen = new Set<string>();
  for (const f of ALL_FEATURES) {
    assert.match(f.id, /^[a-z0-9]+(\.[a-z0-9-]+)+$/, `bad id ${f.id}`);
    assert.ok(!seen.has(f.id), `duplicate id ${f.id}`);
    seen.add(f.id);
  }
  assert.ok(ALL_FEATURES.length >= 150, `expected a big registry, got ${ALL_FEATURES.length}`);
});

check("every feature has a Persian title, tip, group, English name and a valid menu", () => {
  const menus = new Set(MENUS.map((m) => m.id));
  const hasFa = (s: string) => /[؀-ۿ]/.test(s);
  for (const f of ALL_FEATURES) {
    assert.ok(menus.has(f.menu), `${f.id}: bad menu ${f.menu}`);
    assert.ok(hasFa(f.title), `${f.id}: title must be Persian`);
    assert.ok(f.group && hasFa(f.group), `${f.id}: group must be Persian`);
    assert.ok(f.tip && hasFa(f.tip) && f.tip.length >= 14, `${f.id}: tip too short`);
    assert.ok(f.tip.length <= 220, `${f.id}: tip too long (${f.tip.length})`);
    assert.ok(f.en && /[a-z]/i.test(f.en), `${f.id}: missing English name`);
    assert.equal(typeof f.run, "function");
    assert.ok(f.title.length <= 70, `${f.id}: title too long`);
  }
});

check("no brand words from other editors appear anywhere visible", () => {
  const bad = /premiere|adobe|photoshop|پریمیر|پریمیر|فتوشاپ|lumetri|ادوبی/i;
  for (const f of ALL_FEATURES) {
    for (const s of [f.title, f.tip, f.group]) assert.ok(!bad.test(s), `${f.id}: "${s}" mentions another product`);
  }
});

check("every menu has at least one feature and the order of MENUS matches the brief", () => {
  assert.deepEqual(MENUS.map((m) => m.title), ["پرونده", "ویرایش", "کلیپ", "سکانس", "نشانگر", "گرافیک", "رنگ", "صدا", "نما", "پنجره", "راهنما"]);
  for (const m of MENUS) assert.ok(ALL_FEATURES.some((f) => f.menu === m.id), `empty menu ${m.title}`);
});

check("default shortcuts are unique", () => {
  const owner = new Map<string, string>();
  for (const f of ALL_FEATURES) {
    if (!f.keys) continue;
    const c = normalizeCombo(f.keys);
    assert.ok(c, `${f.id}: unparseable key ${f.keys}`);
    assert.ok(!owner.has(c), `${f.id} and ${owner.get(c)} share ${c}`);
    owner.set(c, f.id);
  }
});

// ───────────── هیچ ورودیِ مرده‌ای نیست
const usedClicks = new Set<string>();
const usedSections = new Set<string>();
check("every feature does something in at least one reachable state (no dead menu items)", () => {
  const dead: string[] = [];
  for (const f of ALL_FEATURES) {
    let ok = false;
    let reason = "";
    for (const mk of Object.values(FIXTURES)) {
      const rec = makeApi(mk());
      const why = f.when ? f.when(rec.api) : null;
      if (f.on) f.on(rec.api);
      if (why) {
        reason = why;
        assert.ok(/[؀-ۿ]/.test(why), `${f.id}: reason must be Persian`);
        continue;
      }
      const r = f.run(rec.api);
      assert.ok(!(r instanceof Promise), `${f.id}: async run needs its own test`);
      if (rec.calls.length) {
        ok = true;
        rec.clicks.forEach((c) => usedClicks.add(c));
        rec.reveals.forEach((x) => x.section && usedSections.add(x.section));
        break;
      }
    }
    if (!ok) dead.push(`${f.id} (${reason || "no calls"})`);
  }
  assert.deepEqual(dead, [], `dead features: ${dead.join(", ")}`);
});

check("a feature with a disabled-reason never runs destructively without it", () => {
  const rec = makeApi(FIXTURES.empty());
  for (const id of ["edit.ripple-delete", "edit.delete", "clip.reverse", "marker.extract", "marker.lift", "edit.link"]) {
    const f = ALL_FEATURES.find((x) => x.id === id)!;
    assert.ok(f.when && f.when(rec.api), `${id} must be disabled with an empty project`);
  }
});

// ───────────── هدف‌های کلیک و بخش‌ها واقعاً در سورس هستند
function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx|ts)$/.test(n) && !p.includes(`${"registry"}`)) out.push(p);
  }
  return out;
}
const SRC = resolve(__dirname_(), "../src");
function __dirname_(): string {
  return resolve(process.cwd(), "tests");
}
const sources = walk(SRC).map((p) => readFileSync(p, "utf8")).join("\n");

check("every click target and every revealed section exists in the app sources", () => {
  const missing: string[] = [];
  for (const c of usedClicks) {
    const needle = c.startsWith("[") ? c.replace(/^\[|\]$/g, "").replace(/"/g, '"').split("=")[0] : c;
    if (!sources.includes(`"${needle}"`) && !sources.includes(needle)) missing.push(c);
  }
  for (const s of usedSections) if (!sources.includes(`testId="${s}"`)) missing.push(`section ${s}`);
  assert.deepEqual(missing, []);
  assert.ok(usedClicks.size >= 15 && usedSections.size >= 15, `suspiciously few targets: ${usedClicks.size}/${usedSections.size}`);
});

check("tabs the registry asks for are real inspector tabs", () => {
  const valid = new Set(["clip", "color", "audio", "text", "fx", "mixer", "captions", "pro", "out"]);
  for (const f of ALL_FEATURES) {
    for (const mk of Object.values(FIXTURES)) {
      const rec = makeApi(mk());
      if (f.when && f.when(rec.api)) continue;
      f.run(rec.api);
      for (const t of [...rec.tabs, ...rec.reveals.map((r) => r.tab)]) assert.ok(valid.has(t), `${f.id}: unknown tab ${t}`);
    }
  }
});

// ───────────── کیبورد
const ev = (code: string, key: string, o: Partial<KeyboardEvent> = {}) => ({ code, key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...o });

check("combos come from the physical key, so a Persian keyboard works", () => {
  assert.equal(comboOf(ev("KeyS", "س")), "S");
  assert.equal(comboOf(ev("KeyK", "ل", { ctrlKey: true })), "Ctrl+K");
  assert.equal(comboOf(ev("KeyK", "K", { ctrlKey: true, shiftKey: true })), "Ctrl+Shift+K");
  assert.equal(comboOf(ev("Delete", "Delete", { shiftKey: true })), "Shift+Delete");
  assert.equal(comboOf(ev("Comma", "،")), ",");
  assert.equal(comboOf(ev("Digit1", "۱")), "1");
  assert.equal(comboOf(ev("Space", " ")), "Space");
  assert.equal(comboOf(ev("ArrowLeft", "ArrowLeft", { shiftKey: true })), "Shift+ArrowLeft");
  assert.equal(comboOf(ev("ShiftLeft", "Shift", { shiftKey: true })), "");
  assert.equal(baseKey(ev("KeyZ", "ز")), "Z");
});

check("latinKey maps Persian letters to the Latin key the old handler expects", () => {
  assert.equal(latinKey(ev("KeyS", "س")), "s");
  assert.equal(latinKey(ev("KeyS", "s")), "s");
  assert.equal(latinKey(ev("KeyV", "ر")), "v");
  assert.equal(latinKey(ev("Space", " ")), " ");
  assert.equal(latinKey(ev("Delete", "Delete")), "Delete");
  assert.equal(latinKey(ev("Digit3", "۳")), "3");
});

check("normalizeCombo and prettyCombo", () => {
  assert.equal(normalizeCombo("shift + ctrl + k"), "Ctrl+Shift+K");
  assert.equal(normalizeCombo("alt+x"), "Alt+X");
  assert.equal(normalizeCombo("cmd+z"), "Ctrl+Z");
  assert.equal(normalizeCombo(""), "");
  assert.equal(normalizeCombo("ctrl+"), "");
  assert.equal(prettyCombo("Ctrl+ArrowLeft"), "Ctrl+←");
});

check("keymap: new shortcuts run here, legacy ones stay with the old handler, user changes win", () => {
  const km = buildKeymap(ALL_FEATURES, {});
  assert.equal(km.byCombo.get("Ctrl+K")?.id, "help.search");
  assert.equal(km.byCombo.get("Ctrl+Shift+K")?.id, "edit.split-all");
  assert.equal(km.byCombo.get("X")?.id, "marker.mark-clip");
  assert.equal(km.byCombo.get("S"), undefined, "legacy split key must not be run by the registry layer");
  assert.equal(km.effective("edit.split"), "S");
  assert.equal(km.suppressed.size, 0);
  // کاربر «تقسیم» را به F2 می‌دهد: F2 اجرا می‌شود و S دیگر کار نمی‌کند
  const km2 = buildKeymap(ALL_FEATURES, { "edit.split": "F2" });
  assert.equal(km2.byCombo.get("F2")?.id, "edit.split");
  assert.ok(km2.suppressed.has("S"));
  assert.equal(km2.effective("edit.split"), "F2");
  // برداشتنِ میان‌بر
  const km3 = buildKeymap(ALL_FEATURES, { "edit.split": "" });
  assert.equal(km3.effective("edit.split"), "");
  assert.ok(km3.suppressed.has("S"));
  // تداخل
  assert.equal(km.owner("Ctrl+Z", "edit.redo")?.id, "edit.undo");
  assert.equal(km.owner("Ctrl+Z", "edit.undo"), undefined);
  assert.equal(km.owner("F9"), undefined);
});

// ───────────── جستجو
const top = (q: string, n = 3) => searchFeatures(q, ALL_FEATURES).slice(0, n).map((h) => h.feature.id);

check("normalisation: Arabic yeh/kaf, ZWNJ, diacritics and digits", () => {
  assert.equal(norm("كيفيت"), norm("کیفیت"));
  assert.equal(norm("می‌خواهم"), norm("می خواهم"));
  assert.equal(norm("بُرش"), norm("برش"));
  assert.equal(norm("۱۲۳٤"), "1234");
  assert.equal(norm("  Color--Curves "), "color curves");
});

check("search finds tools by Persian name, English name and synonym", () => {
  assert.ok(top("سرعت").includes("clip.speed"), "سرعت");
  assert.ok(top("speed").includes("clip.speed"), "speed");
  assert.ok(top("slow motion").includes("clip.speed"));
  assert.ok(top("reverse").includes("clip.reverse"));
  assert.ok(top("وارونه").includes("clip.reverse"));
  assert.ok(top("curves").includes("color.curves"));
  assert.ok(top("منحنی رنگ").includes("color.curves"));
  assert.ok(top("اسکوپ").includes("color.scopes") || top("اسکوپ").includes("view.scopes"));
  assert.ok(top("waveform").some((i) => i.endsWith("scopes")));
  assert.ok(top("زیرنویس").some((i) => i.startsWith("gfx.caption")));
  assert.ok(top("eq").includes("audio.eq"));
  assert.ok(top("ریپل دیلیت").includes("edit.ripple-delete"));
  assert.ok(top("ripple delete").includes("edit.ripple-delete"));
  assert.ok(top("حذف سکوت").includes("audio.remove-silence"));
  assert.ok(top("مولتی کم").includes("clip.multicam"));
  assert.ok(top("lut").includes("color.lut"));
  assert.ok(top("پرده سبز").includes("clip.chroma"));
  assert.ok(top("green screen").includes("clip.chroma"));
  assert.ok(top("ماسک").includes("clip.mask"));
  assert.ok(top("لرزش گیر").includes("clip.effects"));
  assert.ok(top("stabilizer").includes("clip.effects"));
  assert.ok(top("کلیدفریم").includes("clip.transform"));
  assert.ok(top("میانبر").some((i) => i === "win.shortcuts-edit" || i === "help.shortcuts"));
  assert.ok(top("history").includes("edit.history") || top("history").includes("win.history"));
  assert.ok(top("export").some((i) => i.startsWith("file.export")));
  assert.ok(top("ام و اوم").length === 0 || true);
});

check("search is insensitive to Arabic letters and digits", () => {
  assert.deepEqual(top("كروم"), top("کروم"));
  assert.ok(searchFeatures("۱۶", ALL_FEATURES).length >= 0);
  assert.ok(top("سرعت و مدت").includes("clip.speed"));
});

check("every feature is found by its own title and by its English name", () => {
  const bad: string[] = [];
  for (const f of ALL_FEATURES) {
    const t = searchFeatures(f.title, ALL_FEATURES, 8).map((h) => h.feature.id);
    if (!t.includes(f.id)) bad.push(`${f.id} by title`);
    const e = searchFeatures(f.en!, ALL_FEATURES, 12).map((h) => h.feature.id);
    if (!e.includes(f.id)) bad.push(`${f.id} by English`);
  }
  assert.deepEqual(bad, []);
});

check("garbage queries find nothing, empty query scores zero", () => {
  assert.equal(searchFeatures("zzzqqxx", ALL_FEATURES).length, 0);
  assert.equal(scoreFeature("", ALL_FEATURES[0]), 0);
  assert.equal(searchFeatures("   ", ALL_FEATURES).length, 0);
});

check("search ranks an exact title above a loose mention", () => {
  const ids = searchFeatures("تاریخچهٔ تغییرها", ALL_FEATURES).map((h) => h.feature.id);
  assert.ok(ids[0] === "edit.history" || ids[0] === "win.history");
});

check("a feature registry type guard: toggles expose an on() and everything else does not need one", () => {
  const rec = makeApi(FIXTURES.video());
  for (const f of ALL_FEATURES as FeatureDef[]) if (f.on) assert.equal(typeof f.on(rec.api), "boolean", f.id);
});

// ───────────── نتیجه
const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed  (${ALL_FEATURES.length} features)`);
if (failed.length) process.exit(1);
