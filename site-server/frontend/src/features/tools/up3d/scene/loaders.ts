import { useEffect, useState } from "react";
import * as THREE from "three";
import { BVHLoader } from "three/examples/jsm/loaders/BVHLoader.js";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

import { api } from "../../../../api/client";

/**
 * مدل‌های نمای ویرایشگر:
 *  - دارایی‌ای که خودش فایل دارد (بستهٔ کاربر: محیطِ model_file، محصولِ file، شخصِ file، کلیپِ BVH/FBX) ⇐ همان فایل
 *  - دارایی‌های رویه‌ایِ موتور (فقط داخلِ Blender ساخته می‌شوند) ⇐ GLB ِ سبکی که موتور یک بار می‌سازد و سرور نگه می‌دارد
 *    (POST asset-preview/… ⇐ کارِ «خروجیِ سه‌بعدی» با preview_glb روی کارگر) — تا آماده شود جانشینِ هم‌اندازه دیده می‌شود.
 * همه با JWT ِ پنل (axios) گرفته و با parse ِ همان loader ِ three باز می‌شوند.
 */

export type PreviewState = "file" | "ready" | "building" | "failed" | "none" | "unsupported" | "loading";

export type PreviewInfo = {
  state: PreviewState;
  url?: string;
  format?: string;
  size?: number;
  job?: number;
  message?: string;
  transform?: { scale?: number; rotation_deg?: number; offset?: number[] };
  height_m?: number;
};

export type PreviewKind = "environment" | "product" | "character" | "motion";

// ───────────────────────── وضعیتِ پیش‌نمایش (یک بار برای هر دارایی؛ «در حال ساخت» هر ۸ ثانیه دوباره)

const infoCache = new Map<string, PreviewInfo>();
const infoWaiters = new Map<string, Promise<PreviewInfo>>();
const subs = new Map<string, Set<(p: PreviewInfo) => void>>();
const requested = new Set<string>();

function emit(key: string, p: PreviewInfo) {
  infoCache.set(key, p);
  subs.get(key)?.forEach((fn) => fn(p));
}

async function fetchInfo(kind: PreviewKind, id: string, autoBuild: boolean): Promise<PreviewInfo> {
  const key = `${kind}/${id}`;
  try {
    let p = (await api.get<PreviewInfo>(`/up3d/asset-preview/${kind}/${id}/`)).data;
    if (p.state === "none" && autoBuild && !requested.has(key)) {
      requested.add(key);
      p = (await api.post<PreviewInfo>(`/up3d/asset-preview/${kind}/${id}/`, {})).data;
    }
    emit(key, p);
    if (p.state === "building") window.setTimeout(() => void fetchInfo(kind, id, false), 8000);
    return p;
  } catch {
    const p: PreviewInfo = { state: "unsupported" };
    emit(key, p);
    return p;
  }
}

/** وضعیتِ پیش‌نمایشِ یک دارایی؛ autoBuild ⇐ اگر نیست، ساختش در صفِ کارگر گذاشته می‌شود (یک بار). */
export function usePreview(kind: PreviewKind, id: string | undefined, autoBuild = true): PreviewInfo {
  const key = `${kind}/${id}`;
  const [info, setInfo] = useState<PreviewInfo>(() => infoCache.get(key) || { state: "loading" });
  useEffect(() => {
    if (!id) return;
    const set = subs.get(key) || new Set();
    subs.set(key, set);
    set.add(setInfo);
    const cached = infoCache.get(key);
    if (cached) setInfo(cached);
    else if (!infoWaiters.has(key)) {
      const pr = fetchInfo(kind, id, autoBuild).finally(() => infoWaiters.delete(key));
      infoWaiters.set(key, pr);
    }
    return () => {
      set.delete(setInfo);
    };
  }, [key, kind, id, autoBuild]);
  return info;
}

/** ساختِ دوباره (بعد از شکست) */
export async function rebuildPreview(kind: PreviewKind, id: string) {
  const key = `${kind}/${id}`;
  const p = (await api.post<PreviewInfo>(`/up3d/asset-preview/${kind}/${id}/`, { force: true })).data;
  emit(key, p);
  if (p.state === "building") window.setTimeout(() => void fetchInfo(kind, id, false), 8000);
}

// ───────────────────────── بار کردنِ مدل‌ها

export type LoadedModel = { scene: THREE.Object3D; animations: THREE.AnimationClip[]; yUp: boolean };

const modelCache = new Map<string, Promise<LoadedModel>>();

async function getBuffer(url: string): Promise<ArrayBuffer> {
  if (url.startsWith("/api/v1/")) {
    const r = await api.get<ArrayBuffer>(url.slice("/api/v1".length), { responseType: "arraybuffer" });
    return r.data;
  }
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.arrayBuffer();
}

function parse(buf: ArrayBuffer, format: string): Promise<LoadedModel> {
  const f = format.toLowerCase();
  if (f === "glb" || f === "gltf") {
    return new Promise((resolve, reject) => {
      new GLTFLoader().parse(buf, "", (g) => resolve({ scene: g.scene, animations: g.animations || [], yUp: true }), reject);
    });
  }
  if (f === "fbx") {
    const obj = new FBXLoader().parse(buf, "");
    // FBX ِ بیشترِ نرم‌افزارها سانتی‌متر است؛ اندازهٔ نهایی را جانشین/fit درست می‌کند
    return Promise.resolve({ scene: obj, animations: obj.animations || [], yUp: true });
  }
  if (f === "obj") {
    const text = new TextDecoder().decode(buf);
    return Promise.resolve({ scene: new OBJLoader().parse(text), animations: [], yUp: true });
  }
  return Promise.reject(new Error(`قالبِ ${format} در مرورگر باز نمی‌شود`));
}

export function loadModel(url: string, format: string): Promise<LoadedModel> {
  const key = `${url}|${format}`;
  let p = modelCache.get(key);
  if (!p) {
    p = getBuffer(url).then((b) => parse(b, format));
    p.catch(() => modelCache.delete(key));
    modelCache.set(key, p);
  }
  return p;
}

/** یک نمونهٔ مستقل از مدل (برای چند بار در صحنه) — اسکلت‌دار هم درست کپی می‌شود. */
export function useModel(url: string | undefined, format: string | undefined): { model: LoadedModel | null; error: string | null } {
  const [model, setModel] = useState<LoadedModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setModel(null);
    setError(null);
    if (!url || !format) return;
    loadModel(url, format)
      .then((m) => {
        if (!alive) return;
        const scene = cloneSkinned(m.scene);
        scene.traverse((o) => {
          const mesh = o as THREE.Mesh;
          if (mesh.isMesh) {
            mesh.castShadow = true;
            mesh.receiveShadow = true;
          }
        });
        setModel({ scene, animations: m.animations, yUp: m.yUp });
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [url, format]);
  return { model, error };
}

// ───────────────────────── کلیپِ حرکت (BVH/FBX) برای «آدمکِ خطی»

export type ClipRig = { root: THREE.Object3D; clip: THREE.AnimationClip; height: number; yUp: boolean };

const clipCache = new Map<string, Promise<ClipRig>>();

export function loadClip(url: string, format: string): Promise<ClipRig> {
  const key = `${url}|${format}`;
  let p = clipCache.get(key);
  if (!p) {
    p = getBuffer(url).then((buf) => {
      if (format === "bvh") {
        const res = new BVHLoader().parse(new TextDecoder().decode(buf));
        const root = new THREE.Group();
        root.add(res.skeleton.bones[0]);
        return { root, clip: res.clip, height: 0, yUp: true };
      }
      const obj = new FBXLoader().parse(buf, "");
      return { root: obj, clip: obj.animations[0], height: 0, yUp: true };
    });
    p.catch(() => clipCache.delete(key));
    clipCache.set(key, p);
  }
  return p;
}

const SIDE_L = /(^|[^a-z])(l|left)([^a-z]|$)|left|^l(shoulder|clavicle|collar|humerus|upperarm|arm)/i;
const SIDE_R = /(^|[^a-z])(r|right)([^a-z]|$)|right|^r(shoulder|clavicle|collar|humerus|upperarm|arm)/i;
const SHOULDER = /shoulder|clavicle|collar|upperarm|humerus|arm/i;

/**
 * هم‌ترازیِ اسکلتِ کلیپ با آدمِ صحنه — همان body_frame_align ِ موتور: بالا = لگن ⇐ سر، راست = شانهٔ راست منهای چپ
 * ⇐ بالا +Z، جلو -Y، راستِ بازیگر -X (BVH ِ Blender Z-بالاست، Mixamo/CMU Y-بالا؛ هیچ‌کدام فرض نمی‌شود).
 * خروجی: چرخش، ارتفاع (بعد از چرخش) و جابه‌جایی تا لگن بالای مبدأ و پاها روی زمین باشند.
 */
export function alignClip(root: THREE.Object3D): { quat: THREE.Quaternion; height: number; offset: THREE.Vector3 } {
  root.updateMatrixWorld(true);
  const bones: THREE.Object3D[] = [];
  root.traverse((o) => {
    if ((o as THREE.Bone).isBone || o.type === "Bone") bones.push(o);
  });
  const quat = new THREE.Quaternion();
  if (!bones.length) return { quat, height: 1, offset: new THREE.Vector3() };
  const wp = (o: THREE.Object3D) => o.getWorldPosition(new THREE.Vector3());
  const hips = wp(bones[0]);
  const headBone = bones.find((b) => /head/i.test(b.name) && !/headtop|end/i.test(b.name)) || bones.reduce((a, b) => (wp(b).distanceTo(hips) > wp(a).distanceTo(hips) ? b : a));
  const up = wp(headBone).sub(hips).normalize();
  const sh = (re: RegExp) => bones.find((b) => SHOULDER.test(b.name) && re.test(b.name.replace(/^.*[:|]/, "")));
  const r = sh(SIDE_R);
  const l = sh(SIDE_L);
  let right = r && l ? wp(r).sub(wp(l)) : new THREE.Vector3(-1, 0, 0);
  right.sub(up.clone().multiplyScalar(right.dot(up)));
  if (right.lengthSq() < 1e-8) right = new THREE.Vector3(1, 0, 0).sub(up.clone().multiplyScalar(up.x));
  right.normalize();
  const fwd = new THREE.Vector3().crossVectors(up, right).normalize();
  const S = new THREE.Matrix4().makeBasis(right, fwd, up);
  const T = new THREE.Matrix4().makeBasis(new THREE.Vector3(-1, 0, 0), new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, 1));
  const M = T.multiply(S.transpose());
  quat.setFromRotationMatrix(M);
  let lo = Infinity;
  let hi = -Infinity;
  for (const b of bones) {
    const p = wp(b).applyQuaternion(quat);
    lo = Math.min(lo, p.z);
    hi = Math.max(hi, p.z);
  }
  const h = Number.isFinite(hi - lo) && hi - lo > 1e-6 ? hi - lo : 1;
  const hp = hips.clone().applyQuaternion(quat);
  return { quat, height: h, offset: new THREE.Vector3(-hp.x, -hp.y, -lo) };
}

/** نشانیِ فایلِ بارگذاری‌شده (مدلِ «مدلِ خودِ شما») — /3d/files/uploads/ عمومی است */
export function uploadUrl(path: unknown): string | null {
  if (typeof path !== "string" || !path) return null;
  const name = path.split(/[\\/]/).pop();
  if (!name || !/uploads/.test(path)) return null;
  return `/3d/files/uploads/${name}`;
}

export function extOf(path: string): string {
  return (path.split(".").pop() || "").toLowerCase();
}
