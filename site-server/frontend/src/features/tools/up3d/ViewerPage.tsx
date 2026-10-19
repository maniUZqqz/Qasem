import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import Icon from "../../../components/Icon";
import { Card, ErrorBox, Field, Select, Spinner } from "../../../components/ui";
import { P, errMsg, fa, up3d } from "./api";
import { Muted } from "./shared";
import type { Job } from "./types";

/**
 * نمایشگرِ سه‌بعدی (وب / بازی): خروجیِ GLB ِ یک کار با انیمیشنِ پخته‌شده و دوربین‌های شات‌ها.
 *
 * حلقهٔ رندر بیرونِ React می‌چرخد؛ وضعیتِ پخش/سرعت/دوربین در ref است تا ۶۰ بار در ثانیه رندرِ React نخوریم،
 * و زمان/اسکراب مستقیم روی DOM نوشته می‌شود.
 */
export default function ViewerPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("در حالِ بار کردن…");
  const [cams, setCams] = useState<string[]>([]);
  const [camIdx, setCamIdx] = useState("free");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState("1");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const scrubRef = useRef<HTMLInputElement>(null);
  const playingRef = useRef(true);
  const speedRef = useRef(1);
  const camsRef = useRef<THREE.PerspectiveCamera[]>([]);
  const activeRef = useRef<THREE.Camera | null>(null);
  const freeRef = useRef<THREE.PerspectiveCamera | null>(null);
  const mixerRef = useRef<THREE.AnimationMixer | null>(null);
  const clipRef = useRef<THREE.AnimationClip | null>(null);
  const resizeRef = useRef<() => void>(() => undefined);

  playingRef.current = playing;
  speedRef.current = Number(speed) || 1;

  useEffect(() => {
    up3d
      .job(id!)
      .then(setJob)
      .catch((e) => setError(errMsg(e)));
  }, [id]);

  const glb = job ? (Object.entries(job.files || {}).find(([k]) => k.endsWith(".glb")) ?? [null, null])[1] : null;

  useEffect(() => {
    activeRef.current = camIdx === "free" ? freeRef.current : (camsRef.current[Number(camIdx)] ?? freeRef.current);
    resizeRef.current();
  }, [camIdx, cams]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !glb) return;
    const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x15171c);
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const sun = new THREE.DirectionalLight(0xfff1e0, 2.2);
    sun.position.set(-2, 4, 3);
    sun.castShadow = true;
    scene.add(sun);
    scene.add(new THREE.HemisphereLight(0xdde6ff, 0x3a2f28, 0.6));

    const free = new THREE.PerspectiveCamera(40, 1, 0.02, 100);
    free.position.set(0, 1.5, 3.2);
    freeRef.current = free;
    activeRef.current = free;
    const controls = new OrbitControls(free, cv);
    controls.target.set(0, 1.1, 0);
    controls.enableDamping = true;

    const resize = () => {
      const w = cv.clientWidth;
      const h = cv.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      for (const c of [free, ...camsRef.current]) {
        c.aspect = w / h;
        c.updateProjectionMatrix();
      }
    };
    resizeRef.current = resize;
    const ro = new ResizeObserver(resize);
    ro.observe(cv);

    let disposed = false;
    new GLTFLoader().load(
      glb,
      (g) => {
        if (disposed) return;
        scene.add(g.scene);
        const found: THREE.PerspectiveCamera[] = [];
        g.scene.traverse((o) => {
          if (o instanceof THREE.Mesh) {
            o.castShadow = true;
            o.receiveShadow = true;
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            for (const m of mats) if (m.transparent) m.depthWrite = false;
          }
          if (o instanceof THREE.PerspectiveCamera) found.push(o);
        });
        camsRef.current = found;
        setCams(found.map((c, i) => c.name || `شات ${fa(i + 1)}`));
        if (g.animations.length) {
          const mixer = new THREE.AnimationMixer(g.scene);
          mixerRef.current = mixer;
          clipRef.current = g.animations[0];
          g.animations.forEach((a) => mixer.clipAction(a).play());
        }
        setStatus(`${fa(g.animations.length)} انیمیشن · ${fa(found.length)} دوربین`);
        resize();
      },
      (ev) => {
        if (ev.total) setStatus(`بار کردن ${fa(Math.round((ev.loaded / ev.total) * 100))}٪`);
      },
      (err: unknown) => {
        setStatus("خطا در بار کردن: " + (err instanceof Error ? err.message : String(err)));
      },
    );

    const clock = new THREE.Clock();
    renderer.setAnimationLoop(() => {
      const dt = clock.getDelta() * speedRef.current;
      const mixer = mixerRef.current;
      const clip = clipRef.current;
      if (mixer && playingRef.current) {
        mixer.update(dt);
        if (clip && clip.duration > 0) {
          const t = mixer.time % clip.duration;
          if (scrubRef.current) scrubRef.current.value = String(Math.round((t / clip.duration) * 1000));
          if (timeRef.current) timeRef.current.textContent = t.toFixed(2);
        }
      }
      controls.update();
      renderer.render(scene, activeRef.current ?? free);
    });

    return () => {
      disposed = true;
      ro.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      // هندسه، متریال و بافت‌های GLB هم آزاد شوند؛ renderer.dispose() فقط کشِ خودش را خالی می‌کند
      scene.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        o.geometry.dispose();
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of mats) {
          for (const v of Object.values(m)) if (v instanceof THREE.Texture) v.dispose();
          m.dispose();
        }
      });
      scene.environment?.dispose();
      pmrem.dispose();
      renderer.dispose();
      mixerRef.current = null;
      clipRef.current = null;
      camsRef.current = [];
    };
  }, [glb]);

  if (!job) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-extrabold" style={{ color: "var(--text)" }}>
          نمایشگرِ سه‌بعدی (وب / بازی) — کار #{fa(job.id)}
        </h1>
        <div className="flex gap-2">
          {glb && (
            <a className="u-btn u-btn-secondary u-btn-sm" href={glb} download>
              <Icon name="download" size={14} />
              دانلودِ GLB
            </a>
          )}
          <Link className="u-btn u-btn-ghost u-btn-sm" to={P.job(job.id)}>
            بازگشت
          </Link>
        </div>
      </div>

      {!glb ? (
        <ErrorBox message="این کار خروجیِ GLB ندارد." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
          <Card padded={false} className="relative">
            <div style={{ position: "relative", height: "74vh" }}>
              <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
              <div
                className="text-sm"
                style={{ position: "absolute", top: 10, insetInlineEnd: 12, background: "rgb(0 0 0 / .5)", color: "#fff", padding: "4px 10px", borderRadius: 8 }}
              >
                {status}
              </div>
            </div>
          </Card>
          <div className="space-y-4">
            <Card>
              <h3 className="mb-2 font-bold" style={{ color: "var(--text)" }}>
                پخش
              </h3>
              <div className="flex items-center gap-3">
                <button type="button" className="u-btn u-btn-primary u-btn-sm" onClick={() => setPlaying((v) => !v)}>
                  {playing ? "⏸ مکث" : "▶ پخش"}
                </button>
                <span ref={timeRef} className="u3d-mono text-sm" style={{ color: "var(--text-2)" }}>
                  0.00
                </span>
              </div>
              <input
                ref={scrubRef}
                type="range"
                min={0}
                max={1000}
                defaultValue={0}
                className="mt-2 w-full"
                onInput={(e) => {
                  const mixer = mixerRef.current;
                  const clip = clipRef.current;
                  if (mixer && clip) mixer.setTime((Number(e.currentTarget.value) / 1000) * clip.duration);
                }}
              />
              <div className="mt-3">
                <Field label="سرعت">
                  <Select value={speed} onChange={(e) => setSpeed(e.target.value)}>
                    <option value="0.5">۰٫۵×</option>
                    <option value="1">۱×</option>
                    <option value="2">۲×</option>
                  </Select>
                </Field>
              </div>
            </Card>
            <Card>
              <h3 className="mb-2 font-bold" style={{ color: "var(--text)" }}>
                دوربین
              </h3>
              <Select value={camIdx} onChange={(e) => setCamIdx(e.target.value)}>
                <option value="free">آزاد (بچرخانید، بزرگ‌نمایی کنید)</option>
                {cams.map((name, i) => (
                  <option key={i} value={String(i)}>
                    {name}
                  </option>
                ))}
              </Select>
              <Muted className="mt-2">
                دوربین‌های شات‌ها همان‌هایی‌اند که موتور رندر کرد. در حالتِ آزاد با ماوس بچرخانید، با چرخ بزرگ‌نمایی کنید، با کلیدِ راست
                جابه‌جا کنید.
              </Muted>
            </Card>
            <Card>
              <h3 className="mb-2 font-bold" style={{ color: "var(--text)" }}>
                استفاده در بازی/نرم‌افزار
              </h3>
              <div className="space-y-2 text-sm" style={{ color: "var(--text-2)" }}>
                <p>این فایلِ GLB (glTF 2.0) کلِ صحنه است: کاراکتر با اسکلت و انیمیشنِ پخته‌شده، حالت‌های چهره (shape key)، محصول، محیط و دوربین‌ها.</p>
                <p>
                  مستقیم در <b>Unity</b> (glTFast)، <b>Unreal</b> (glTF importer)، <b>Godot</b>، <b>three.js</b>/<b>Babylon.js</b> و <b>Blender</b> باز می‌شود.
                </p>
                <Muted>نکته: موادِ رویه‌ای (چوب، مرمر…) در glTF به رنگِ ساده تبدیل می‌شوند؛ برای جزئیاتِ کامل، خروجیِ BLEND را بگیرید.</Muted>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
