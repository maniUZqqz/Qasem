import { label } from "../api";
import { MOVES_FA, byId } from "../editor/model";
import type {
  Actor,
  Catalog,
  Environment,
  FreeCamera,
  Item,
  KeyFrame,
  LightRef,
  LightType,
  ProductAsset,
  ProductRef,
  PropRef,
  SceneDoc,
  Transform,
  Vec3,
} from "../types";
import { IDENTITY, lensToFovY, rad, round3, roundVec, sampleNum, sampleVec, smootherstep, transformAt, unwrapRot } from "./anim";

/**
 * مدلِ ویرایشگرِ آزاد: «اشیا»ی صحنه (محیط، آدم‌ها، محصول‌ها، اشیای تزئینی، نورها، دوربین‌ها)،
 * جای هر شیء در هر زمان (transform + کلیدها)، و همهٔ تغییرهای سند (افزودن/حذف/کلید/جابه‌جایی).
 *
 * سند همان up3d.scene/1 است: آدمِ بی‌transform روی جایگاهِ آماده (mark) و محصولِ بی‌transform روی سطحِ آماده
 * می‌ایستد؛ با اولین جابه‌جایی در ویرایشگر transform می‌گیرد و از آن پس جای آزاد دارد.
 */

export type ObjKind = "environment" | "actor" | "product" | "prop" | "light" | "camera";
export type ObjRef = { kind: ObjKind; id: string };

export type EdSel =
  | { type: "obj"; ref: ObjRef }
  | { type: "key"; ref: ObjRef; t: number }
  | { type: "action"; id: string }
  | { type: "shot"; id: string }
  | { type: "target"; id: string }
  | null;

export const KIND_FA: Record<ObjKind, string> = {
  environment: "محیط",
  actor: "آدم",
  product: "محصول",
  prop: "شیء",
  light: "نور",
  camera: "دوربین",
};

export const LIGHT_FA: Record<LightType, string> = { point: "نورِ نقطه‌ای", spot: "نورافکن", area: "نورِ سطحی (سافت‌باکس)", sun: "خورشید" };

export const refKey = (r: ObjRef) => `${r.kind}:${r.id}`;
export const sameRef = (a: ObjRef | null | undefined, b: ObjRef | null | undefined) => !!a && !!b && a.kind === b.kind && a.id === b.id;

/** قدِ تقریبیِ آدم (متر) — برای جانشین و نمای آماده */
export const PERSON_H = 1.72;

type Rec = Actor | ProductRef | PropRef | LightRef | FreeCamera;

export function record(doc: SceneDoc, ref: ObjRef): Rec | undefined {
  switch (ref.kind) {
    case "actor":
      return doc.actors.find((a) => a.id === ref.id);
    case "product":
      return doc.products.find((p) => p.id === ref.id);
    case "prop":
      return (doc.props || []).find((p) => p.id === ref.id);
    case "light":
      return (doc.lights || []).find((p) => p.id === ref.id);
    case "camera":
      return (doc.cameras || []).find((p) => p.id === ref.id);
    default:
      return undefined;
  }
}

export function keysOf(doc: SceneDoc, ref: ObjRef): KeyFrame[] {
  const r = record(doc, ref);
  return (r && "keys" in r && r.keys) || [];
}

/** همهٔ اشیا به ترتیبِ فهرستِ صحنه */
export function listObjects(doc: SceneDoc): ObjRef[] {
  return [
    { kind: "environment", id: doc.environment.id },
    ...doc.actors.map((a) => ({ kind: "actor" as const, id: a.id })),
    ...doc.products.map((p) => ({ kind: "product" as const, id: p.id })),
    ...(doc.props || []).map((p) => ({ kind: "prop" as const, id: p.id })),
    ...(doc.lights || []).map((p) => ({ kind: "light" as const, id: p.id })),
    ...(doc.cameras || []).map((p) => ({ kind: "camera" as const, id: p.id })),
  ];
}

export function objLabel(doc: SceneDoc, cat: Catalog, ref: ObjRef): string {
  const r = record(doc, ref);
  switch (ref.kind) {
    case "environment":
      return label(byId(cat, "environment", doc.environment.id));
    case "actor": {
      const a = r as Actor | undefined;
      return a?.name || label(byId(cat, "character", a?.character)) || ref.id;
    }
    case "product": {
      const p = r as ProductRef | undefined;
      return p?.name || label(byId(cat, "product", p?.asset)) || ref.id;
    }
    case "prop": {
      const p = r as PropRef | undefined;
      return p?.name || label(byId(cat, "product", p?.asset)) || ref.id;
    }
    case "light": {
      const l = r as LightRef | undefined;
      return l?.name || (l ? LIGHT_FA[l.type] : ref.id);
    }
    case "camera": {
      const c = r as FreeCamera | undefined;
      return c?.name || `دوربینِ آزاد ${ref.id.replace(/\D/g, "") || ""}`.trim();
    }
  }
}

// ───────────────────────── جای اشیا

function env(doc: SceneDoc, cat: Catalog): Environment | undefined {
  return byId(cat, "environment", doc.environment.id);
}

type Mark = { pos?: number[]; facing?: number };
type Surface = { pos?: number[]; yaw?: number };

const v3 = (a: number[] | undefined, d: Vec3 = [0, 0, 0]): Vec3 =>
  a && a.length >= 3 ? [Number(a[0]) || 0, Number(a[1]) || 0, Number(a[2]) || 0] : d;

/** جای پایه (بی‌کلید): transform ِ آزاد، وگرنه جایگاه/سطحِ آماده‌ٔ محیط (همان چیزی که compiler می‌کند). */
export function baseTransform(doc: SceneDoc, cat: Catalog, ref: ObjRef): Transform {
  const r = record(doc, ref);
  if (!r) return IDENTITY;
  if ("transform" in r && r.transform) return r.transform;
  const e = env(doc, cat);
  if (ref.kind === "actor") {
    const a = r as Actor;
    const mk = (e?.marks?.[a.mark] || e?.marks?.center || {}) as Mark;
    return { pos: v3(mk.pos), rot: [0, 0, Number(mk.facing) || 0], scale: [1, 1, 1] };
  }
  if (ref.kind === "product") {
    const p = r as ProductRef;
    const ids = Object.keys(e?.surfaces || {});
    const i = doc.products.indexOf(p);
    const sid = p.surface && e?.surfaces?.[p.surface] ? p.surface : ids[Math.min(Math.max(i, 0), ids.length - 1)];
    const sf = (e?.surfaces?.[sid] || {}) as Surface;
    return { pos: v3(sf.pos), rot: [0, 0, Number(sf.yaw) || 0], scale: [1, 1, 1] };
  }
  return IDENTITY;
}

export function transformOf(doc: SceneDoc, cat: Catalog, ref: ObjRef, t: number): Transform {
  return transformAt(baseTransform(doc, cat, ref), keysOf(doc, ref), t);
}

/** آدم‌ها همیشه ایستاده‌اند و هم‌اندازه: فقط جابه‌جایی و چرخش دورِ محورِ عمودی */
export function constrain(ref: ObjRef, tr: Transform): Transform {
  if (ref.kind === "actor") return { pos: tr.pos, rot: [0, 0, tr.rot[2]], scale: [1, 1, 1] };
  if (ref.kind === "light") return { pos: tr.pos, rot: tr.rot, scale: [1, 1, 1] };
  return tr;
}

const KEY_EPS = 1e-3;

export function findKey(keys: KeyFrame[] | undefined, t: number): number {
  return (keys || []).findIndex((k) => Math.abs(k.t - t) < KEY_EPS);
}

function sortKeys(keys: KeyFrame[]) {
  keys.sort((a, b) => a.t - b.t);
}

function cleanTr(tr: Transform): Transform {
  return { pos: roundVec(tr.pos), rot: roundVec(tr.rot), scale: roundVec(tr.scale) };
}

/**
 * جای تازه از گیزمو/بازرس: شیءِ کلیددار ⇐ کلید در همین زمان (ساخته یا به‌روز می‌شود)؛ بی‌کلید ⇐ جای ثابت.
 * خروجی: «key» اگر کلید نوشته شد، «base» اگر جای ثابت.
 */
export function writeTransform(doc: SceneDoc, cat: Catalog, ref: ObjRef, tr0: Transform, t: number): "key" | "base" {
  const r = record(doc, ref) as (Rec & { transform?: Transform; keys?: KeyFrame[] }) | undefined;
  if (!r || ref.kind === "camera") return "base";
  const tr = cleanTr(constrain(ref, tr0));
  if (r.keys && r.keys.length) {
    const i = findKey(r.keys, t);
    const prev = [...r.keys].reverse().find((k) => k.t < t - KEY_EPS && k.rot) || r.keys.find((k) => k.rot);
    const rot = unwrapRot(tr.rot, prev?.rot);
    if (i >= 0) r.keys[i] = { ...r.keys[i], pos: tr.pos, rot, scale: tr.scale };
    else {
      r.keys.push({ t: round3(t), pos: tr.pos, rot, scale: tr.scale, ease: "smooth" });
      sortKeys(r.keys);
    }
    return "key";
  }
  r.transform = tr;
  return "base";
}

/** کلید در زمانِ t با جای فعلی (اولین کلید: جای پایه هم کلید می‌شود تا شیء از همان‌جا راه بیفتد). */
export function addKey(doc: SceneDoc, cat: Catalog, ref: ObjRef, t: number, cam?: { pos: Vec3; target: Vec3; lens: number }) {
  if (ref.kind === "camera") {
    const c = record(doc, ref) as FreeCamera | undefined;
    if (!c || !cam) return;
    const k: KeyFrame = { t: round3(t), pos: roundVec(cam.pos), target: roundVec(cam.target), lens: round3(cam.lens), ease: "auto" };
    const i = findKey(c.keys, t);
    if (i >= 0) c.keys[i] = { ...c.keys[i], pos: k.pos, target: k.target, lens: k.lens };
    else {
      c.keys.push(k);
      sortKeys(c.keys);
    }
    return;
  }
  const r = record(doc, ref) as (Rec & { transform?: Transform; keys?: KeyFrame[] }) | undefined;
  if (!r) return;
  const cur = cleanTr(constrain(ref, transformOf(doc, cat, ref, t)));
  if (!r.keys || !r.keys.length) {
    r.transform = cleanTr(constrain(ref, baseTransform(doc, cat, ref)));
    r.keys = [];
  }
  const i = findKey(r.keys, t);
  if (i >= 0) r.keys[i] = { ...r.keys[i], pos: cur.pos, rot: cur.rot, scale: cur.scale };
  else {
    r.keys.push({ t: round3(t), pos: cur.pos, rot: cur.rot, scale: cur.scale, ease: "smooth" });
    sortKeys(r.keys);
  }
}

export function deleteKey(doc: SceneDoc, ref: ObjRef, t: number) {
  const r = record(doc, ref) as (Rec & { keys?: KeyFrame[]; transform?: Transform }) | undefined;
  if (!r?.keys) return;
  const i = findKey(r.keys, t);
  if (i < 0) return;
  const removed = r.keys.splice(i, 1)[0];
  if (!r.keys.length && ref.kind !== "camera") {
    // آخرین کلید رفت ⇐ شیء همان‌جا که بود ثابت می‌ماند
    if (removed.pos) r.transform = { pos: removed.pos, rot: removed.rot || [0, 0, 0], scale: removed.scale || [1, 1, 1] };
    delete r.keys;
  }
}

export function moveKey(doc: SceneDoc, ref: ObjRef, t0: number, t1: number): number {
  const r = record(doc, ref) as (Rec & { keys?: KeyFrame[] }) | undefined;
  if (!r?.keys) return t0;
  const i = findKey(r.keys, t0);
  if (i < 0) return t0;
  const nt = round3(Math.max(0, t1));
  const clash = findKey(r.keys, nt);
  if (clash >= 0 && clash !== i) r.keys.splice(clash, 1);
  const k = r.keys.find((x) => Math.abs(x.t - t0) < KEY_EPS);
  if (k) k.t = nt;
  sortKeys(r.keys);
  return nt;
}

// ───────────────────────── افزودن / حذف

export function newId(doc: SceneDoc, prefix: string): string {
  const used = new Set<string>([
    ...doc.actors.map((x) => x.id),
    ...doc.products.map((x) => x.id),
    ...(doc.props || []).map((x) => x.id),
    ...(doc.lights || []).map((x) => x.id),
    ...(doc.cameras || []).map((x) => x.id),
  ]);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

const at = (pos: Vec3, yaw = 0): Transform => ({ pos: roundVec(pos), rot: [0, 0, yaw], scale: [1, 1, 1] });

export function addActor(doc: SceneDoc, cat: Catalog, character: string, pos: Vec3): ObjRef {
  const id = doc.actors.length === 0 && !doc.actors.some((a) => a.id === "host") ? "host" : newId(doc, "actor");
  const e = env(doc, cat);
  const marks = Object.keys(e?.marks || {});
  const free = marks.find((m) => !doc.actors.some((a) => a.mark === m)) || marks[0] || "center";
  doc.actors.push({ id, character, mark: free, params: {}, transform: at(pos) });
  return { kind: "actor", id };
}

export function addProduct(doc: SceneDoc, cat: Catalog, asset: string, pos: Vec3): ObjRef {
  const id = newId(doc, "p");
  const e = env(doc, cat);
  const surfs = Object.keys(e?.surfaces || {});
  const pa = byId(cat, "product", asset);
  doc.products.push({ id, asset, name: label(pa), surface: surfs[0], params: {}, transform: at(pos) });
  return { kind: "product", id };
}

export function addProp(doc: SceneDoc, asset: string, pos: Vec3, scale = 1): ObjRef {
  const id = newId(doc, "prop");
  doc.props = doc.props || [];
  doc.props.push({ id, asset, name: "", params: {}, transform: { pos: roundVec(pos), rot: [0, 0, 0], scale: [scale, scale, scale] } });
  return { kind: "prop", id };
}

const LIGHT_DEFAULT: Record<LightType, Partial<LightRef>> = {
  point: { power: 150, size: 0.3 },
  spot: { power: 400, size: 0.3, cone: 40, blend: 0.3 },
  area: { power: 150, size: 1.0 },
  sun: { power: 3, size: 0.2 },
};

export function addLight(doc: SceneDoc, type: LightType, pos: Vec3): ObjRef {
  const id = newId(doc, "light");
  doc.lights = doc.lights || [];
  // جهتِ تابش = -Z ِ شیء: پیش‌فرض رو به پایین و کمی به سمتِ صحنه
  const rot: Vec3 = type === "point" ? [0, 0, 0] : [50, 0, Math.round((Math.atan2(pos[0], -pos[1]) * 180) / Math.PI)];
  doc.lights.push({ id, type, color: "#ffffff", ...LIGHT_DEFAULT[type], power: LIGHT_DEFAULT[type].power || 100, transform: { pos: roundVec(pos), rot, scale: [1, 1, 1] } } as LightRef);
  return { kind: "light", id };
}

export function addCamera(doc: SceneDoc): ObjRef {
  const id = newId(doc, "cam");
  doc.cameras = doc.cameras || [];
  doc.cameras.push({ id, name: "", lens: 35, fstop: 4, keys: [] });
  return { kind: "camera", id };
}

/** حذفِ شیء + ارجاع‌هایش (حرکت‌ها/گفتارِ آن آدم، شات‌های آن دوربین) */
export function removeObject(doc: SceneDoc, ref: ObjRef) {
  switch (ref.kind) {
    case "actor":
      doc.actors = doc.actors.filter((a) => a.id !== ref.id);
      doc.actions = doc.actions.filter((a) => a.actor !== ref.id);
      doc.expressions = doc.expressions.filter((a) => a.actor !== ref.id);
      doc.gaze = doc.gaze.filter((a) => a.actor !== ref.id);
      doc.speech.forEach((s) => {
        if (s.actor === ref.id) s.actor = null;
      });
      break;
    case "product":
      doc.products = doc.products.filter((a) => a.id !== ref.id);
      break;
    case "prop":
      doc.props = (doc.props || []).filter((a) => a.id !== ref.id);
      break;
    case "light":
      doc.lights = (doc.lights || []).filter((a) => a.id !== ref.id);
      break;
    case "camera":
      doc.cameras = (doc.cameras || []).filter((a) => a.id !== ref.id);
      doc.shots.forEach((s) => {
        if (s.camera === ref.id) delete s.camera;
      });
      doc.shots = doc.shots.filter((s) => s.camera || s.shot);
      break;
    default:
  }
}

// ───────────────────────── دوربین در هر زمان (شاتِ آزاد یا نمای آماده — همان قاب‌بندیِ camera.py)

export type CamPose = { pos: Vec3; target: Vec3; lens: number; shot?: Item };

export function shotAt(doc: SceneDoc, t: number): Item | undefined {
  const shots = doc.shots;
  for (let i = shots.length - 1; i >= 0; i--) if (shots[i].start <= t + 1e-6) return shots[i];
  return shots[0];
}

const ANCHOR_Z: Record<string, number> = { eyes: 1.6, face: 1.57, head: 1.62, chest: 1.32, waist: 1.02, full: 0.9 };

export function cameraAt(doc: SceneDoc, cat: Catalog, t: number): CamPose | null {
  const sh = shotAt(doc, t);
  if (!sh) return null;
  if (sh.camera) {
    const c = (doc.cameras || []).find((x) => x.id === sh.camera);
    if (!c || !c.keys.length) return null;
    return {
      pos: sampleVec(c.keys, t, "pos", [0, -3, 1.5]),
      target: sampleVec(c.keys, t, "target", [0, 0, 1.2]),
      lens: sampleNum(c.keys, t, c.lens || 35),
      shot: sh,
    };
  }
  const sa = byId(cat, "shot", sh.shot);
  if (!sa) return null;
  const fr: Record<string, number | string | undefined> = { ...(sa.framing as unknown as Record<string, number>), ...(sh.params as Record<string, number> | undefined) };
  const subjActor = doc.actors.find((a) => a.id === sh.subject);
  const subjProd = doc.products.find((p) => p.id === sh.subject);
  if (!subjActor && !subjProd) return null;
  const ref: ObjRef = subjActor ? { kind: "actor", id: subjActor.id } : { kind: "product", id: subjProd!.id };
  const tr = transformOf(doc, cat, ref, t);
  const anchor = String(fr.anchor || (subjActor ? "eyes" : "product"));
  let p: Vec3;
  if (subjActor) {
    const ch = byId(cat, "character", subjActor.character);
    const k = (ch?.height_m || PERSON_H) / PERSON_H;
    p = [tr.pos[0], tr.pos[1], tr.pos[2] + (ANCHOR_Z[anchor] ?? 1.6) * k];
  } else {
    const pa = byId(cat, "product", subjProd!.asset) as ProductAsset | undefined;
    const h = (pa?.dimensions?.[2] || 0.15) * tr.scale[2];
    p = [tr.pos[0], tr.pos[1], tr.pos[2] + h / 2];
  }
  const H = Number(fr.height) || 0.9;
  const lens = Number(fr.lens) || 50;
  const vfov = rad(lensToFovY(lens, doc.output.aspect));
  const dist = H / 2 / Math.tan(vfov / 2);
  let a = rad(Number(fr.azimuth) || 0);
  let e = rad(fr.elevation == null ? 3 : Number(fr.elevation));
  const facing = subjActor ? rad(tr.rot[2]) : 0;
  const u = smootherstep(((t - sh.start) / Math.max(0.01, sh.duration || 1)) as number);
  const amt = Number(fr.move_amount) || 1;
  const move = sh.move || "static";
  let d = dist;
  const off: Vec3 = [0, 0, 0];
  if (move === "push_in") d = dist * (1 - 0.14 * amt * u);
  else if (move === "pull_out") d = dist * (0.86 + 0.14 * amt * u);
  else if (move === "orbit_left") a += rad(7 - 16 * amt * u);
  else if (move === "orbit_right") a += rad(-7 + 16 * amt * u);
  else if (move === "crane_up") {
    e += rad(-3 + 9 * amt * u);
    off[2] = -0.06 + 0.14 * amt * u;
  } else if (move === "crane_down") {
    e += rad(6 - 9 * amt * u);
    off[2] = 0.08 - 0.14 * amt * u;
  } else if (move === "slide_left" || move === "slide_right") off[0] = (move === "slide_right" ? 1 : -1) * (-0.12 + 0.24 * amt * u);
  const dir: Vec3 = [Math.sin(a + facing) * Math.cos(e), -Math.cos(a + facing) * Math.cos(e), Math.sin(e)];
  const drop = (0.5 - (Number(fr.anchor_pos) || 0.33)) * H;
  const look: Vec3 = [p[0], p[1], p[2] - drop];
  const pos: Vec3 = [look[0] + dir[0] * d + off[0], look[1] + dir[1] * d + off[1], look[2] + dir[2] * d + off[2]];
  return { pos, target: look, lens, shot: sh };
}

export function shotLabel(cat: Catalog, doc: SceneDoc, it: Item): string {
  if (it.camera) {
    const c = (doc.cameras || []).find((x) => x.id === it.camera);
    return `🎥 آزاد · ${c?.name || it.camera}`;
  }
  const s = byId(cat, "shot", it.shot);
  return `🎥 ${s ? label(s) : it.shot || ""} · ${MOVES_FA[it.move || ""] || it.move || ""}`;
}

/** حرکتی که این آدم در زمانِ t انجام می‌دهد (برای برچسبِ روی صحنه) */
export function actionAt(doc: SceneDoc, actor: string, t: number): Item | undefined {
  return doc.actions.find((a) => a.actor === actor && a.start <= t && t < a.start + (a.duration || 0));
}

export function docDur(doc: SceneDoc): number {
  return Number(doc.output.duration) || 10;
}

export function itemId(it: Item, i: number, prefix: string): string {
  return it.id || `${prefix}${i}`;
}

/** شناسه‌های قطعه‌ها (حرکت/شات) پیش از ذخیره ممکن است خالی باشند؛ همین‌جا یکتا می‌شوند */
export function ensureItemIds(doc: SceneDoc) {
  const fix = (items: Item[], prefix: string) => {
    const used = new Set(items.map((x) => x.id).filter(Boolean) as string[]);
    items.forEach((it) => {
      if (it.id) return;
      let n = 1;
      while (used.has(`${prefix}${n}`)) n++;
      it.id = `${prefix}${n}`;
      used.add(it.id);
    });
  };
  fix(doc.actions, "a");
  fix(doc.shots, "s");
}
