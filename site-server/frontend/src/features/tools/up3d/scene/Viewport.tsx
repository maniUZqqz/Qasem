import { GizmoHelper, GizmoViewport, Grid, OrbitControls, TransformControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { DragEvent, MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { Catalog, SceneDoc, Transform, Vec3 } from "../types";
import { aspectRatio, deg, fovYToLens, lensToFovY, roundVec } from "./anim";
import type { Clock } from "./clock";
import { ActorView, CameraView, EnvironmentView, LightView, ProductView, PropView, VpContext, type Vp } from "./objects";
import { type EdSel, type ObjRef, cameraAt, refKey } from "./model";

/**
 * نمای سه‌بعدیِ ویرایشگر (react-three-fiber): مدار/جابه‌جایی/بزرگ‌نمایی، کف و شبکه، انتخاب با قابِ رنگی،
 * گیزمو (جابه‌جایی/چرخش/اندازه با گام)، «نمای دوربین» (همان قابی که رندر می‌شود) و راهنمای قابِ خروجی.
 * مختصات = Blender (Z بالا). دوربینِ نما هم Z بالا دارد.
 */

export type GizmoMode = "translate" | "rotate" | "scale";

export type DragPayload = { kind: "environment" | "character" | "product" | "prop" | "motion" | "shot" | "light" | "camera" | "lighting"; id: string };

export const DND_TYPE = "application/x-up3d-asset";

export type ViewportApi = {
  /** جا، نقطهٔ نگاه و لنزِ نمای فعلی (برای «از همین نما کلید بزن») */
  capture: () => { pos: Vec3; target: Vec3; lens: number };
  frame: (ref: ObjRef | null) => void;
  goTo: (pos: Vec3, target: Vec3) => void;
  /** نقطه‌ای روی کف/سطح زیرِ مکانِ موشی (برای رها کردن از کتابخانه) */
  pointAt: (clientX: number, clientY: number) => Vec3 | null;
};

type Props = {
  cat: Catalog;
  doc: SceneDoc;
  docRef: MutableRefObject<SceneDoc>;
  clock: Clock;
  sel: EdSel;
  onSelect: (s: EdSel) => void;
  mode: GizmoMode;
  snap: boolean;
  cameraView: boolean;
  showFrame: boolean;
  viewLens: number;
  onCommit: (ref: ObjRef, tr: Transform) => void;
  onCommitCamera: (camId: string, part: "pos" | "target", v: Vec3) => void;
  apiRef: MutableRefObject<ViewportApi | null>;
  onDrop: (p: DragPayload, at: Vec3 | null) => void;
  onNotice: (text: string) => void;
};

type Controls = THREE.EventDispatcher & { target: THREE.Vector3; update: () => void; enabled: boolean };

/** نسبتِ ارتفاعِ قابِ خروجی به ارتفاعِ نما (قاب در وسط، تا جایی که جا می‌شود) */
function frameScale(w: number, h: number, aspect: string): number {
  const ar = aspectRatio(aspect);
  const fh = Math.min(h, w / ar);
  return fh / Math.max(1, h);
}

/** زاویهٔ دیدِ عمودیِ کلِ نما تا داخلِ قاب دقیقاً لنزِ دوربین دیده شود */
function viewFov(lens: number, aspect: string, w: number, h: number): number {
  const half = Math.tan((lensToFovY(lens, aspect) * Math.PI) / 360);
  return (2 * Math.atan(half / frameScale(w, h, aspect)) * 180) / Math.PI;
}

function Rig({ docRef, cat, clock, cameraView, viewLens, aspect, apiRef }: { docRef: MutableRefObject<SceneDoc>; cat: Catalog; clock: Clock; cameraView: boolean; viewLens: number; aspect: string; apiRef: MutableRefObject<ViewportApi | null> }) {
  const { camera, size, scene, raycaster, gl } = useThree();
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const cam = camera as THREE.PerspectiveCamera;
  const wasView = useRef(cameraView);
  useEffect(() => {
    if (controls) controls.enabled = !cameraView;
    if (wasView.current && !cameraView && controls) {
      // برگشت از نمای دوربین: مدار از همان‌جا ادامه می‌یابد
      const p = cameraAt(docRef.current, cat, clock.t);
      if (p) controls.target.set(...p.target);
      controls.update();
    }
    wasView.current = cameraView;
  }, [cameraView, controls, docRef, cat, clock]);
  useFrame(() => {
    if (cameraView) {
      const p = cameraAt(docRef.current, cat, clock.t);
      if (p) {
        cam.position.set(...p.pos);
        cam.up.set(0, 0, 1);
        cam.lookAt(new THREE.Vector3(...p.target));
        const f = viewFov(p.lens, aspect, size.width, size.height);
        if (Math.abs(cam.fov - f) > 1e-3) {
          cam.fov = f;
          cam.updateProjectionMatrix();
        }
      }
    } else {
      const f = viewFov(viewLens, aspect, size.width, size.height);
      if (Math.abs(cam.fov - f) > 1e-3) {
        cam.fov = f;
        cam.updateProjectionMatrix();
      }
    }
  });
  useEffect(() => {
    apiRef.current = {
      capture: () => {
        const t = controls?.target || new THREE.Vector3(0, 0, 1);
        const lens = cameraView ? fovYToLens(2 * Math.atan(Math.tan((cam.fov * Math.PI) / 360) * frameScale(size.width, size.height, aspect)) * (180 / Math.PI), aspect) : viewLens;
        if (cameraView) {
          const dir = new THREE.Vector3();
          cam.getWorldDirection(dir);
          const p = cameraAt(docRef.current, cat, clock.t);
          const dist = p ? new THREE.Vector3(...p.target).distanceTo(cam.position) : 2;
          const tt = cam.position.clone().add(dir.multiplyScalar(dist));
          return { pos: roundVec([cam.position.x, cam.position.y, cam.position.z]), target: roundVec([tt.x, tt.y, tt.z]), lens: Math.round(lens * 10) / 10 };
        }
        return { pos: roundVec([cam.position.x, cam.position.y, cam.position.z]), target: roundVec([t.x, t.y, t.z]), lens };
      },
      frame: (ref) => {
        if (!controls) return;
        const o = ref ? scene.getObjectByProperty("uuid", findUuid(scene, ref)) : null;
        const box = new THREE.Box3();
        if (o) box.setFromObject(o);
        if (!o || box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(0, -0.2, 1), new THREE.Vector3(3, 3, 2));
        const c = box.getCenter(new THREE.Vector3());
        const r = Math.max(0.15, box.getSize(new THREE.Vector3()).length() / 2);
        const dir = cam.position.clone().sub(controls.target).normalize();
        const dist = r / Math.sin((cam.fov * Math.PI) / 360) * 1.15;
        controls.target.copy(c);
        cam.position.copy(c.clone().add(dir.multiplyScalar(dist)));
        controls.update();
      },
      goTo: (pos, target) => {
        if (!controls) return;
        cam.position.set(...pos);
        controls.target.set(...target);
        controls.update();
      },
      pointAt: (clientX, clientY) => {
        const rect = gl.domElement.getBoundingClientRect();
        const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
        raycaster.setFromCamera(ndc, cam);
        const hits = raycaster.intersectObjects(scene.children, true).filter((h) => {
          const m = h.object as THREE.Mesh;
          if (!m.isMesh || !h.face) return false;
          let o: THREE.Object3D | null = m;
          while (o) {
            if (o.userData?.noDrop) return false;
            o = o.parent;
          }
          const n = h.face.normal.clone().transformDirection(m.matrixWorld);
          return n.z > 0.6;
        });
        if (hits[0]) return roundVec([hits[0].point.x, hits[0].point.y, hits[0].point.z]);
        const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
        const p = new THREE.Vector3();
        return raycaster.ray.intersectPlane(plane, p) ? roundVec([p.x, p.y, 0]) : null;
      },
    };
  });
  return null;
}

/** frameloop="demand": فقط وقتی چیزی عوض شد نقاشی می‌شود (زمان، سند، انتخاب، مدار، گیزمو) — لپ‌تاپ داغ نمی‌شود. */
function Invalidator({ clock, deps }: { clock: Clock; deps: unknown[] }) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => clock.subscribe(() => invalidate()), [clock, invalidate]);
  useEffect(() => {
    invalidate();
    // مدل‌ها دیرتر بار می‌شوند: چند فریمِ دیگر هم
    const t = window.setInterval(() => invalidate(), 500);
    const stop = window.setTimeout(() => window.clearInterval(t), 4000);
    return () => {
      window.clearInterval(t);
      window.clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return null;
}

function findUuid(scene: THREE.Scene, ref: ObjRef): string {
  let id = "";
  scene.traverse((o) => {
    const r = o.userData?.ref as ObjRef | undefined;
    if (!id && r && r.kind === ref.kind && r.id === ref.id) id = o.uuid;
  });
  return id;
}

/** قابِ رنگیِ دورِ شیءِ انتخاب‌شده (هر فریم به‌روز، چون شیء ممکن است کلید داشته باشد) */
function SelectionBox({ objects, sel }: { objects: Map<string, THREE.Object3D>; sel: EdSel }) {
  const helper = useMemo(() => {
    const h = new THREE.Box3Helper(new THREE.Box3(), new THREE.Color("#f0b54a"));
    h.userData.noDrop = true;
    (h.material as THREE.LineBasicMaterial).depthTest = false;
    h.renderOrder = 10;
    return h;
  }, []);
  useFrame(() => {
    const ref = sel && (sel.type === "obj" || sel.type === "key") ? sel.ref : null;
    const o = ref && ref.kind !== "environment" ? objects.get(refKey(ref)) : null;
    helper.visible = !!o;
    if (o) {
      helper.box.setFromObject(o);
      if (helper.box.isEmpty()) helper.box.setFromCenterAndSize(o.getWorldPosition(new THREE.Vector3()), new THREE.Vector3(0.2, 0.2, 0.2));
      helper.box.expandByScalar(0.01);
    }
  });
  return <primitive object={helper} />;
}

function Gizmo({ vp, sel, mode, snap, onCommit, onCommitCamera, onNotice }: { vp: Vp; sel: EdSel; mode: GizmoMode; snap: boolean; onCommit: Props["onCommit"]; onCommitCamera: Props["onCommitCamera"]; onNotice: Props["onNotice"] }) {
  const [, force] = useState(0);
  // شیءِ گیزمو: شیءِ انتخاب‌شده، بدنهٔ دوربین، یا هدفِ دوربین
  let key: string | null = null;
  let ref: ObjRef | null = null;
  if (sel?.type === "obj" && sel.ref.kind !== "environment") {
    ref = sel.ref;
    key = refKey(sel.ref);
  } else if (sel?.type === "key" && sel.ref.kind !== "environment") {
    ref = sel.ref;
    key = refKey(sel.ref);
  } else if (sel?.type === "target") key = `target:${sel.id}`;
  const obj = key ? vp.objects.get(key) : undefined;
  useEffect(() => {
    // شیء تازه ساخته شده و هنوز در فهرست نیست ⇐ یک بارِ دیگر
    if (key && !obj) {
      const t = window.setTimeout(() => force((x) => x + 1), 60);
      return () => window.clearTimeout(t);
    }
  }, [key, obj]);
  const isCam = ref?.kind === "camera" || sel?.type === "target";
  const actor = ref?.kind === "actor";
  const light = ref?.kind === "light";
  let m: GizmoMode = mode;
  if (isCam) m = "translate";
  if ((actor || light) && mode === "scale") m = "translate";
  useEffect(() => {
    if (!key) return;
    if (isCam && mode !== "translate") onNotice("دوربین و هدفش فقط جابه‌جا می‌شوند (جهت = نقطهٔ نگاه)");
    else if ((actor || light) && mode === "scale") onNotice(actor ? "اندازهٔ آدم ثابت است؛ فقط جابه‌جایی و چرخش" : "اندازهٔ نور ثابت است؛ «اندازهٔ نور» در بازرس");
  }, [mode, key, isCam, actor, light, onNotice]);
  if (!obj || !key) return null;
  const k = key;
  return (
    <TransformControls
      object={obj}
      mode={m}
      size={0.8}
      translationSnap={snap ? 0.05 : null}
      rotationSnap={snap ? Math.PI / 12 : null}
      scaleSnap={snap ? 0.1 : null}
      showX={!(actor && m === "rotate")}
      showY={!(actor && m === "rotate")}
      onMouseDown={() => {
        vp.dragging.current = k;
      }}
      onMouseUp={() => {
        vp.guard.current = performance.now() + 250;
        const o = obj;
        vp.dragging.current = null;
        if (k.startsWith("target:")) {
          onCommitCamera(k.slice(7), "target", roundVec([o.position.x, o.position.y, o.position.z]));
          return;
        }
        if (ref?.kind === "camera") {
          onCommitCamera(ref.id, "pos", roundVec([o.position.x, o.position.y, o.position.z]));
          return;
        }
        if (!ref) return;
        const e = new THREE.Euler().setFromQuaternion(o.quaternion, "ZYX");
        onCommit(ref, {
          pos: [o.position.x, o.position.y, o.position.z],
          rot: [deg(e.x), deg(e.y), deg(e.z)],
          scale: [o.scale.x, o.scale.y, o.scale.z],
        });
      }}
    />
  );
}

export default function Viewport(props: Props) {
  const { cat, doc, docRef, clock, sel, onSelect, mode, snap, cameraView, showFrame, viewLens, apiRef } = props;
  const objects = useMemo(() => new Map<string, THREE.Object3D>(), []);
  const dragging = useRef<string | null>(null);
  const guard = useRef(0);
  const wrap = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 800, h: 500 });
  // از دست رفتنِ WebGL (کمبودِ حافظهٔ کارتِ گرافیک/مرورگر) ⇐ پیام + ساختنِ دوبارهٔ نما
  const [lost, setLost] = useState(false);
  const [canvasKey, setCanvasKey] = useState(0);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const vp: Vp = { cat, docRef, clock, objects, dragging, guard, pick: onSelect, sel };
  const clipMotionsFor = (actorId: string) => {
    const ids = new Set(doc.actions.filter((a) => a.actor === actorId).map((a) => a.motion));
    return cat.motion.filter((m) => ids.has(m.id) && m.source?.type === "clip");
  };
  const fs = frameScale(box.w, box.h, doc.output.aspect);
  const fh = box.h * fs;
  const fw = fh * aspectRatio(doc.output.aspect);
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    const raw = e.dataTransfer.getData(DND_TYPE);
    if (!raw) return;
    e.preventDefault();
    try {
      const p = JSON.parse(raw) as DragPayload;
      props.onDrop(p, apiRef.current?.pointAt(e.clientX, e.clientY) ?? null);
    } catch {
      /* کشیدنِ نامعتبر */
    }
  };
  const selCam = sel && (sel.type === "obj" || sel.type === "key") && sel.ref.kind === "camera" ? sel.ref.id : sel?.type === "target" ? sel.id : null;
  return (
    <div
      ref={wrap}
      className="u3e-viewport"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DND_TYPE)) e.preventDefault();
      }}
      onDrop={onDrop}
    >
      <Canvas
        key={canvasKey}
        onCreated={({ gl }) => {
          gl.domElement.addEventListener("webglcontextlost", () => setLost(true));
          // بی‌کارتِ گرافیک (رندرِ نرم‌افزاری) سایه خاموش تا نما روان بماند
          try {
            const ctx = gl.getContext();
            const ext = ctx.getExtension("WEBGL_debug_renderer_info");
            const name = ext ? String(ctx.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : "";
            if (/swiftshader|llvmpipe|software/i.test(name)) gl.shadowMap.enabled = false;
          } catch {
            /* بی‌اطلاع از کارت */
          }
        }}
        frameloop="demand"
        shadows
        dpr={[1, 1.75]}
        camera={{ position: [2.4, -4.4, 2.1], up: [0, 0, 1], fov: 40, near: 0.05, far: 150 }}
        onPointerMissed={(e) => {
          if (e.type === "click" && performance.now() > guard.current) onSelect(null);
        }}
        gl={{ preserveDrawingBuffer: true, antialias: true }}
      >
        <VpContext.Provider value={vp}>
          <Invalidator clock={clock} deps={[doc, sel, mode, cameraView, showFrame, viewLens, box.w, box.h]} />
          <color attach="background" args={["#1d2027"]} />
          <hemisphereLight args={["#f4f1ea", "#3b3f47", 1.1]} position={[0, 0, 5]} />
          <directionalLight position={[3, -4, 6]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} shadow-normalBias={0.03}>
            <orthographicCamera attach="shadow-camera" args={[-6, 6, 6, -6, 0.5, 30]} />
          </directionalLight>
          <Grid
            rotation={[Math.PI / 2, 0, 0]}
            position={[0, 0, 0.004]}
            args={[20, 20]}
            cellSize={0.5}
            cellThickness={0.6}
            sectionSize={1}
            sectionThickness={1}
            cellColor="#3d4350"
            sectionColor="#5b6475"
            fadeDistance={14}
            fadeStrength={1.5}
            infiniteGrid
            userData={{ noDrop: true }}
          />
          <mesh position={[0, 0, -0.002]} receiveShadow userData={{ floor: true }}>
            <planeGeometry args={[40, 40]} />
            <shadowMaterial opacity={0.25} />
          </mesh>
          <EnvironmentView doc={doc} cameraView={cameraView} />
          {doc.actors.map((a) => (
            <ActorView key={a.id} actor={a} clipMotions={clipMotionsFor(a.id)} />
          ))}
          {doc.products.map((p) => (
            <ProductView key={p.id} p={p} />
          ))}
          {(doc.props || []).map((p) => (
            <PropView key={p.id} p={p} />
          ))}
          {(doc.lights || []).map((l) => (
            <LightView key={l.id} l={l} />
          ))}
          {!cameraView &&
            (doc.cameras || []).map((c) => <CameraView key={c.id} cam={c} aspect={doc.output.aspect} duration={doc.output.duration} selected={selCam === c.id} />)}
          <SelectionBox objects={objects} sel={sel} />
          {!cameraView && <Gizmo vp={vp} sel={sel} mode={mode} snap={snap} onCommit={props.onCommit} onCommitCamera={props.onCommitCamera} onNotice={props.onNotice} />}
          <OrbitControls makeDefault enableDamping={false} target={[0, -0.2, 1.0]} maxDistance={60} />
          <Rig docRef={docRef} cat={cat} clock={clock} cameraView={cameraView} viewLens={viewLens} aspect={doc.output.aspect} apiRef={apiRef} />
          {!cameraView && (
            <GizmoHelper alignment="bottom-left" margin={[64, 64]}>
              <GizmoViewport labelColor="#111" axisHeadScale={0.9} />
            </GizmoHelper>
          )}
        </VpContext.Provider>
      </Canvas>
      {lost && (
        <div className="u3e-lost">
          <span>نمای سه‌بعدی از دست رفت (حافظهٔ گرافیکِ مرورگر). سند سالم است.</span>
          <button
            type="button"
            className="u3e-btn primary"
            onClick={() => {
              setLost(false);
              objects.clear();
              setCanvasKey((k) => k + 1);
            }}
          >
            ساختنِ دوبارهٔ نما
          </button>
        </div>
      )}
      {(showFrame || cameraView) && (
        <div
          className={`u3e-frame ${cameraView ? "cam" : ""}`}
          style={{ width: fw, height: fh, left: (box.w - fw) / 2, top: (box.h - fh) / 2 }}
          aria-hidden
        />
      )}
    </div>
  );
}
