import { Html, Line } from "@react-three/drei";
import { type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { MutableRefObject, ReactNode, createContext, useContext, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";

import { label } from "../api";
import { byId } from "../editor/model";
import type { Actor, Catalog, Environment, FreeCamera, LightRef, Motion, ProductAsset, ProductRef, PropRef, SceneDoc, Transform, Vec3 } from "../types";
import { lensToFovY, rad, sampleNum, sampleVec } from "./anim";
import type { Clock } from "./clock";
import { type ClipRig, type PreviewInfo, alignClip, extOf, loadClip, uploadUrl, useModel, usePreview } from "./loaders";
import { type EdSel, type ObjRef, PERSON_H, actionAt, refKey, transformOf } from "./model";

/**
 * اشیای نمای سه‌بعدی. مختصات همان Blender است (Z بالا، متر)؛ فایل‌های glTF/FBX (Y بالا) با ۹۰ درجه دورِ X برمی‌گردند
 * (همان کاری که واردکنندهٔ glTF ِ Blender می‌کند). هر شیء جایش را هر فریم از سند + زمان می‌خواند (useFrame)،
 * پس پخش/جابه‌جاییِ زمان بی‌رندرِ دوبارهٔ React است.
 */

export type Vp = {
  cat: Catalog;
  docRef: MutableRefObject<SceneDoc>;
  clock: Clock;
  objects: Map<string, THREE.Object3D>;
  /** شیئی که الان با گیزمو کشیده می‌شود (جایش را از سند نخواند) */
  dragging: MutableRefObject<string | null>;
  /** تا چند لحظه بعد از رها کردنِ گیزمو، کلیک = انتخاب نیست */
  guard: MutableRefObject<number>;
  pick: (s: EdSel) => void;
  sel: EdSel;
};

export const VpContext = createContext<Vp | null>(null);

export function useVp(): Vp {
  const v = useContext(VpContext);
  if (!v) throw new Error("VpContext");
  return v;
}

export function applyTransform(o: THREE.Object3D, tr: Transform) {
  o.position.set(tr.pos[0], tr.pos[1], tr.pos[2]);
  o.rotation.set(rad(tr.rot[0]), rad(tr.rot[1]), rad(tr.rot[2]), "ZYX");
  o.scale.set(tr.scale[0] || 1, tr.scale[1] || 1, tr.scale[2] || 1);
}

export function clickable(vp: Vp, s: EdSel) {
  return (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.delta > 5 || performance.now() < vp.guard.current) return;
    vp.pick(s);
  };
}

/** گروهی که جایش را از سند (transform + کلیدها) در زمانِ فعلی می‌گیرد و در فهرستِ اشیای نما ثبت می‌شود. */
function Animated({ objRef, children }: { objRef: ObjRef; children: ReactNode }) {
  const vp = useVp();
  const g = useRef<THREE.Group>(null);
  const key = refKey(objRef);
  useEffect(() => {
    const o = g.current;
    if (!o) return;
    o.userData.ref = objRef;
    vp.objects.set(key, o);
    return () => {
      if (vp.objects.get(key) === o) vp.objects.delete(key);
    };
  }, [key, vp.objects, objRef]);
  useFrame(() => {
    const o = g.current;
    if (!o || vp.dragging.current === key) return;
    applyTransform(o, transformOf(vp.docRef.current, vp.cat, objRef, vp.clock.t));
  });
  return (
    <group ref={g} onClick={clickable(vp, { type: "obj", ref: objRef })}>
      {children}
    </group>
  );
}

// ───────────────────────── مدلِ بارشده (Y بالا ⇐ Z بالا) با جا انداختن در اندازه

type Fit = "none" | { height: number } | { box: Vec3 };

function ModelNode({ info, fit, onLoaded }: { info: PreviewInfo; fit: Fit; onLoaded?: (scene: THREE.Object3D, anims: THREE.AnimationClip[]) => void }) {
  const { model } = useModel(info.url, info.format);
  const node = useMemo(() => {
    if (!model) return null;
    const outer = new THREE.Group();
    const inner = new THREE.Group();
    if (model.yUp) inner.rotation.x = Math.PI / 2;
    inner.add(model.scene);
    outer.add(inner);
    if (fit !== "none") {
      outer.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(outer);
      const size = box.getSize(new THREE.Vector3());
      let s = 1;
      if ("height" in fit) s = fit.height / Math.max(1e-6, size.z);
      else s = Math.min(fit.box[2] / Math.max(1e-6, size.z), 50);
      const c = box.getCenter(new THREE.Vector3());
      inner.position.set(-c.x * s, -c.y * s, -box.min.z * s);
      inner.scale.setScalar(s);
    }
    return outer;
  }, [model, fit]);
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    if (model && onLoaded) onLoaded(model.scene, model.animations);
    invalidate();
  }, [model, onLoaded, invalidate]);
  return node ? <primitive object={node} /> : null;
}

function Badge({ text, z }: { text: string; z: number }) {
  return (
    <Html position={[0, 0, z]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
      <div className="u3e-tag">{text}</div>
    </Html>
  );
}

// ───────────────────────── محیط

function EnvPlaceholder({ env, doc }: { env: Environment | undefined; doc: SceneDoc }) {
  const color = String((doc.environment.params || {}).backdrop_color || (doc.environment.params || {}).wall_color || "#d8cbbd");
  const furn = env?.furniture || {};
  return (
    <group>
      <mesh position={[0, 1.2, 1.6]} receiveShadow>
        <boxGeometry args={[8, 0.05, 3.2]} />
        <meshStandardMaterial color={color} roughness={0.9} />
      </mesh>
      {Object.entries(furn).map(([k, f]) => {
        const c = (f.center || [0, -0.5, 0]) as number[];
        const h = f.height || 0.9;
        if (f.size)
          return (
            <mesh key={k} position={[c[0], c[1], h / 2]} castShadow receiveShadow>
              <boxGeometry args={[f.size[0], f.size[1], h]} />
              <meshStandardMaterial color="#cfc6bb" roughness={0.6} />
            </mesh>
          );
        return (
          <group key={k} position={[c[0], c[1], 0]}>
            <mesh position={[0, 0, h - 0.015]} rotation={[Math.PI / 2, 0, 0]} castShadow receiveShadow>
              <cylinderGeometry args={[f.radius || 0.34, f.radius || 0.34, 0.03, 40]} />
              <meshStandardMaterial color="#e7e2dc" roughness={0.35} />
            </mesh>
            <mesh position={[0, 0, h / 2]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.03, 0.03, h, 12]} />
              <meshStandardMaterial color="#b8975a" metalness={0.6} roughness={0.3} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

/** جایگاه‌ها و سطح‌های آمادهٔ محیط (راهنمای جا انداختن) */
function EnvMarks({ env }: { env: Environment | undefined }) {
  if (!env) return null;
  return (
    <group>
      {Object.entries(env.marks || {}).map(([k, m]) => {
        const p = ((m as { pos?: number[] }).pos || [0, 0, 0]) as number[];
        return (
          <mesh key={`m-${k}`} position={[p[0], p[1], 0.003]}>
            <ringGeometry args={[0.22, 0.25, 40]} />
            <meshBasicMaterial color="#6aa9ff" transparent opacity={0.45} />
          </mesh>
        );
      })}
      {Object.entries(env.surfaces || {}).map(([k, s]) => {
        const p = ((s as { pos?: number[] }).pos || [0, 0, 0]) as number[];
        return (
          <mesh key={`s-${k}`} position={[p[0], p[1], p[2] + 0.002]}>
            <ringGeometry args={[0.035, 0.045, 24]} />
            <meshBasicMaterial color="#f0b54a" transparent opacity={0.7} />
          </mesh>
        );
      })}
    </group>
  );
}

/**
 * محیط: در مدارِ آزاد دیوارها از پشت دیده نمی‌شوند (مثلِ خانهٔ عروسکی، تا داخل پیدا باشد)؛
 * در «نمای دوربین» دو‌رو می‌شوند — همان چیزی که Blender رندر می‌کند (دوربینِ پشتِ دیوار ⇐ دیوار).
 */
export function EnvironmentView({ doc, cameraView }: { doc: SceneDoc; cameraView: boolean }) {
  const vp = useVp();
  const env = byId(vp.cat, "environment", doc.environment.id);
  const info = usePreview("environment", doc.environment.id);
  const has = info.state === "file" || info.state === "ready";
  const tr = info.transform;
  const ref: ObjRef = { kind: "environment", id: doc.environment.id };
  const holder = useRef<THREE.Group>(null);
  const tick = useRef(0);
  useFrame(() => {
    const g = holder.current;
    // هر ۲۰ فریم یک بار (مدل دیرتر بار می‌شود) یا با عوض شدنِ حالت
    if (!g || (g.userData.side === cameraView && tick.current++ % 20 !== 0)) return;
    g.userData.side = cameraView;
    g.traverse((o) => {
      const m = (o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
      for (const mm of Array.isArray(m) ? m : m ? [m] : []) {
        if (mm.userData.sideFor === cameraView) continue;
        if (mm.userData.side0 === undefined) mm.userData.side0 = mm.side;
        mm.side = cameraView ? THREE.DoubleSide : mm.userData.side0;
        mm.userData.sideFor = cameraView;
        mm.needsUpdate = true;
      }
    });
  });
  return (
    <group ref={holder} onClick={clickable(vp, { type: "obj", ref })}>
      {has ? (
        <group position={(tr?.offset as Vec3) || [0, 0, 0]} rotation={[0, 0, rad(tr?.rotation_deg || 0)]} scale={tr?.scale || 1}>
          <ModelNode info={info} fit="none" />
        </group>
      ) : (
        <EnvPlaceholder env={env} doc={doc} />
      )}
      <EnvMarks env={env} />
      {!has && info.state !== "loading" && (
        <Badge text={info.state === "building" ? "در حالِ ساختِ پیش‌نمایشِ محیط روی کارگر…" : info.state === "failed" ? "پیش‌نمایشِ محیط ساخته نشد (جانشینِ ساده)" : "محیط (جانشینِ ساده)"} z={2.6} />
      )}
    </group>
  );
}

// ───────────────────────── آدم

function Mannequin({ color }: { color: string }) {
  return (
    <group>
      {/* کپسولِ three در امتدادِ Y است ⇐ ۹۰ درجه دورِ X تا در دنیای Z-بالا بایستد */}
      <mesh position={[0, 0, 0.47]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <capsuleGeometry args={[0.09, 0.62, 6, 12]} />
        <meshStandardMaterial color="#8a8f99" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0, 1.18]} rotation={[Math.PI / 2, 0, 0]} castShadow>
        <capsuleGeometry args={[0.17, 0.42, 6, 16]} />
        <meshStandardMaterial color={color} roughness={0.6} />
      </mesh>
      <mesh position={[0, 0, 1.6]} castShadow>
        <sphereGeometry args={[0.11, 20, 16]} />
        <meshStandardMaterial color="#e2c2a6" roughness={0.6} />
      </mesh>
      {/* بینی: جلوی آدم (-Y) */}
      <mesh position={[0, -0.11, 1.6]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.025, 0.06, 10]} />
        <meshStandardMaterial color="#d9a988" />
      </mesh>
    </group>
  );
}

/** آدمکِ خطیِ کلیپِ BVH/FBX در طولِ قطعهٔ حرکتش (پیش‌نمایشِ واقعیِ mocap) */
function ClipStick({ actor, motion, height }: { actor: Actor; motion: Motion; height: number }) {
  const vp = useVp();
  const invalidate = useThree((s) => s.invalidate);
  const scene = useThree((s) => s.scene);
  const info = usePreview("motion", motion.id, false);
  const holder = useRef<THREE.Group>(null);
  const state = useRef<{ mixer: THREE.AnimationMixer; action: THREE.AnimationAction; root: THREE.Object3D; helper: THREE.SkeletonHelper } | null>(null);
  useEffect(() => {
    if (info.state !== "file" || !info.url) return;
    let alive = true;
    loadClip(info.url, info.format || extOf(info.url)).then((rig: ClipRig) => {
      if (!alive || !holder.current || !rig.clip) return;
      const root = cloneSkinned(rig.root);
      const al = alignClip(root);
      const k = (height * 0.96) / al.height;
      // اسکلت ⇐ چرخش به قابِ بازیگر ⇐ لگن بالای مبدأ، پا روی زمین ⇐ هم‌قدِ آدمِ صحنه
      const inner = new THREE.Group();
      inner.quaternion.copy(al.quat);
      inner.add(root);
      const mid = new THREE.Group();
      mid.position.copy(al.offset);
      mid.add(inner);
      const wrap = new THREE.Group();
      wrap.scale.setScalar(k);
      wrap.add(mid);
      holder.current.add(wrap);
      // SkeletonHelper خودش در فضای جهان می‌کشد (matrix = root.matrixWorld) ⇐ فرزندِ صحنه، نه فرزندِ آدم
      const helper = new THREE.SkeletonHelper(root);
      const mat = helper.material as THREE.LineBasicMaterial;
      mat.vertexColors = false;
      mat.color.set("#ff5a36");
      mat.depthTest = false;
      mat.needsUpdate = true;
      helper.renderOrder = 5;
      helper.userData.noDrop = true;
      helper.visible = false;
      scene.add(helper);
      const mixer = new THREE.AnimationMixer(root);
      const action = mixer.clipAction(rig.clip);
      action.play();
      state.current = { mixer, action, root: wrap, helper };
      invalidate();
    });
    return () => {
      alive = false;
      const s = state.current;
      if (s) {
        holder.current?.remove(s.root);
        scene.remove(s.helper);
      }
      state.current = null;
    };
  }, [info.state, info.url, info.format, height, invalidate, scene]);
  useFrame(() => {
    const s = state.current;
    if (!s || !holder.current) return;
    const act = actionAt(vp.docRef.current, actor.id, vp.clock.t);
    const on = !!act && act.motion === motion.id;
    holder.current.visible = on;
    s.helper.visible = on;
    if (!on || !act) return;
    const clipDur = s.action.getClip().duration || 1;
    const speed = Number((act.params || {}).speed) || 1;
    const local = (vp.clock.t - act.start) * speed;
    const loop = Boolean((act.params || {}).loop);
    s.mixer.setTime(loop ? local % clipDur : Math.min(local, clipDur - 1e-3));
  });
  return <group ref={holder} />;
}

export function ActorView({ actor, clipMotions }: { actor: Actor; clipMotions: Motion[] }) {
  const vp = useVp();
  const ch = byId(vp.cat, "character", actor.character);
  const info = usePreview("character", actor.character);
  const height = info.height_m || ch?.height_m || PERSON_H;
  const has = info.state === "file" || info.state === "ready";
  const ref = useMemo<ObjRef>(() => ({ kind: "actor", id: actor.id }), [actor.id]);
  const tagRef = useRef<HTMLDivElement>(null);
  const lastText = useRef("");
  useFrame(() => {
    const el = tagRef.current;
    if (!el) return;
    const act = actionAt(vp.docRef.current, actor.id, vp.clock.t);
    const m = act ? byId(vp.cat, "motion", act.motion) : undefined;
    const text = `${actor.name || label(ch) || actor.id}${m ? ` · ▶ ${label(m)}` : ""}`;
    if (text !== lastText.current) {
      el.textContent = text;
      el.classList.toggle("on", !!m);
      lastText.current = text;
    }
  });
  return (
    <Animated objRef={ref}>
      {has ? <ModelNode info={info} fit={info.state === "file" ? { height } : "none"} /> : <Mannequin color={ch?.gender === "male" ? "#4a6fa5" : "#a5577a"} />}
      {clipMotions.map((m) => (
        <ClipStick key={m.id} actor={actor} motion={m} height={height} />
      ))}
      <Html position={[0, 0, height + 0.18]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <div ref={tagRef} className="u3e-tag" />
      </Html>
    </Animated>
  );
}

// ───────────────────────── محصول و شیء

const COLOR_KEYS = ["liquid_color", "box_color", "can_color", "body_color", "color", "glass_color"];

function BoxPlaceholder({ pa, params, name }: { pa: ProductAsset | undefined; params: Record<string, unknown>; name: string }) {
  const d = (pa?.dimensions || [0.08, 0.08, 0.15]) as number[];
  const ck = COLOR_KEYS.find((k) => typeof params[k] === "string") || COLOR_KEYS.find((k) => pa?.params?.[k]?.default);
  const color = String((ck && (params[ck] || pa?.params?.[ck]?.default)) || "#d9cbb5");
  const round = pa?.builder === "can_drink" || pa?.builder === "cream_jar" || params.shape === "round";
  return (
    <group>
      {round ? (
        <mesh position={[0, 0, d[2] / 2]} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <cylinderGeometry args={[d[0] / 2, d[0] / 2, d[2], 32]} />
          <meshStandardMaterial color={color} roughness={0.35} metalness={0.1} />
        </mesh>
      ) : (
        <mesh position={[0, 0, d[2] / 2]} castShadow>
          <boxGeometry args={[d[0], d[1], d[2]]} />
          <meshStandardMaterial color={color} roughness={0.35} />
        </mesh>
      )}
      {name && <Badge text={name} z={d[2] + 0.06} />}
    </group>
  );
}

function ProductBody({ asset, params, name }: { asset: string; params: Record<string, unknown>; name: string }) {
  const vp = useVp();
  const pa = byId(vp.cat, "product", asset) as ProductAsset | undefined;
  const up = uploadUrl(params.model_path);
  const info = usePreview("product", asset, !up);
  const d = (pa?.dimensions || [0.08, 0.08, 0.15]) as number[];
  const h = Number(params.height_m) || d[2];
  if (up) return <ModelNode info={{ state: "file", url: up, format: extOf(up) }} fit={{ height: h }} />;
  if (info.state === "file") return <ModelNode info={info} fit={{ height: d[2] }} />;
  if (info.state === "ready") return <ModelNode info={info} fit="none" />;
  return <BoxPlaceholder pa={pa} params={params} name={name} />;
}

export function ProductView({ p }: { p: ProductRef }) {
  const ref = useMemo<ObjRef>(() => ({ kind: "product", id: p.id }), [p.id]);
  return (
    <Animated objRef={ref}>
      <ProductBody asset={p.asset} params={p.params || {}} name={p.name || ""} />
    </Animated>
  );
}

export function PropView({ p }: { p: PropRef }) {
  const ref = useMemo<ObjRef>(() => ({ kind: "prop", id: p.id }), [p.id]);
  return (
    <Animated objRef={ref}>
      <ProductBody asset={p.asset} params={p.params || {}} name="" />
    </Animated>
  );
}

// ───────────────────────── نور

export function LightView({ l }: { l: LightRef }) {
  const ref = useMemo<ObjRef>(() => ({ kind: "light", id: l.id }), [l.id]);
  const target = useMemo(() => {
    const o = new THREE.Object3D();
    o.position.set(0, 0, -1);
    return o;
  }, []);
  const spot = useRef<THREE.SpotLight>(null);
  const sun = useRef<THREE.DirectionalLight>(null);
  useEffect(() => {
    if (spot.current) spot.current.target = target;
    if (sun.current) sun.current.target = target;
  }, [target, l.type]);
  const color = l.color || "#ffffff";
  const k = l.type === "sun" ? 0.9 : 0.06;
  return (
    <Animated objRef={ref}>
      <primitive object={target} />
      {l.type === "point" && <pointLight color={color} intensity={l.power * k} distance={0} decay={2} />}
      {l.type === "area" && <pointLight color={color} intensity={l.power * k} distance={0} decay={2} />}
      {l.type === "spot" && <spotLight ref={spot} color={color} intensity={l.power * k} angle={rad((l.cone || 45) / 2)} penumbra={l.blend ?? 0.3} decay={2} distance={0} castShadow />}
      {l.type === "sun" && <directionalLight ref={sun} color={color} intensity={l.power * k} castShadow />}
      {/* نمادِ نور + جهتِ تابش (-Z) */}
      {l.type === "area" ? (
        <mesh>
          <planeGeometry args={[l.size || 1, l.size || 1]} />
          <meshBasicMaterial color={color} side={THREE.DoubleSide} transparent opacity={0.85} />
        </mesh>
      ) : (
        <mesh>
          <sphereGeometry args={[0.07, 16, 12]} />
          <meshBasicMaterial color={color} />
        </mesh>
      )}
      {l.type !== "point" && (
        <Line
          points={[
            [0, 0, 0],
            [0, 0, -0.6],
          ]}
          color="#f0b54a"
          lineWidth={2}
          dashed
          dashSize={0.06}
          gapSize={0.04}
        />
      )}
    </Animated>
  );
}

// ───────────────────────── دوربینِ آزاد: بدنه (جای فعلی)، هدف، مسیر و کلیدها

const UP = new THREE.Vector3(0, 0, 1);

export function CameraView({ cam, aspect, duration, selected }: { cam: FreeCamera; aspect: string; duration: number; selected: boolean }) {
  const vp = useVp();
  const body = useRef<THREE.Group>(null);
  const tgt = useRef<THREE.Mesh>(null);
  const ref = useMemo<ObjRef>(() => ({ kind: "camera", id: cam.id }), [cam.id]);
  const frustumCam = useMemo(() => {
    const c = new THREE.PerspectiveCamera(40, 1, 0.05, 0.55);
    c.up.copy(UP);
    return c;
  }, []);
  const helper = useMemo(() => new THREE.CameraHelper(frustumCam), [frustumCam]);
  useEffect(() => {
    const b = body.current;
    const t = tgt.current;
    if (b) {
      b.userData.ref = ref;
      vp.objects.set(refKey(ref), b);
    }
    if (t) {
      t.userData.target = cam.id;
      vp.objects.set(`target:${cam.id}`, t);
    }
    return () => {
      vp.objects.delete(refKey(ref));
      vp.objects.delete(`target:${cam.id}`);
    };
  }, [vp.objects, ref, cam.id]);
  const path = useMemo(() => {
    if (cam.keys.length < 2) return null;
    const pts: Vec3[] = [];
    const t0 = cam.keys[0].t;
    const t1 = Math.min(duration, cam.keys[cam.keys.length - 1].t);
    for (let i = 0; i <= 80; i++) pts.push(sampleVec(cam.keys, t0 + ((t1 - t0) * i) / 80, "pos", [0, -3, 1.5]));
    return pts;
  }, [cam.keys, duration]);
  useFrame(() => {
    const c = (vp.docRef.current.cameras || []).find((x) => x.id === cam.id);
    if (!c) return;
    const t = vp.clock.t;
    const pos = sampleVec(c.keys, t, "pos", [0, -3, 1.5]);
    const target = sampleVec(c.keys, t, "target", [0, 0, 1.2]);
    const lens = sampleNum(c.keys, t, c.lens || 35);
    if (body.current && vp.dragging.current !== refKey(ref)) {
      body.current.position.set(pos[0], pos[1], pos[2]);
    }
    if (tgt.current && vp.dragging.current !== `target:${cam.id}`) tgt.current.position.set(target[0], target[1], target[2]);
    if (body.current) {
      const tp = tgt.current ? tgt.current.position : new THREE.Vector3(...target);
      frustumCam.position.copy(body.current.position);
      frustumCam.lookAt(tp);
      body.current.quaternion.copy(frustumCam.quaternion);
      frustumCam.fov = lensToFovY(lens, aspect);
      const [a, b] = aspect.split(":").map(Number);
      frustumCam.aspect = a / b || 0.5625;
      frustumCam.updateProjectionMatrix();
      frustumCam.updateMatrixWorld();
      helper.update();
    }
  });
  const hasKeys = cam.keys.length > 0;
  return (
    <group visible={hasKeys}>
      <primitive object={helper} />
      <group ref={body} onClick={clickable(vp, { type: "obj", ref })}>
        <mesh position={[0, 0, 0.09]}>
          <boxGeometry args={[0.16, 0.11, 0.18]} />
          <meshStandardMaterial color={selected ? "#f0b54a" : "#3a3f4a"} />
        </mesh>
        <mesh position={[0, 0, -0.04]} rotation={[-Math.PI / 2, 0, 0]}>
          <coneGeometry args={[0.06, 0.09, 16, 1, true]} />
          <meshStandardMaterial color="#222" side={THREE.DoubleSide} />
        </mesh>
      </group>
      <mesh ref={tgt} onClick={clickable(vp, { type: "target", id: cam.id })}>
        <sphereGeometry args={[0.045, 16, 12]} />
        <meshBasicMaterial color="#e879b9" />
      </mesh>
      {path && <Line points={path} color="#f0b54a" lineWidth={1.5} />}
      {cam.keys.map((k) =>
        k.pos ? (
          <mesh
            key={k.t}
            position={k.pos}
            onClick={clickable(vp, { type: "key", ref, t: k.t })}
          >
            <octahedronGeometry args={[0.05]} />
            <meshBasicMaterial color="#f0b54a" />
          </mesh>
        ) : null,
      )}
    </group>
  );
}
