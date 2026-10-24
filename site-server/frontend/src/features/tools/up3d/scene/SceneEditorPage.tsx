import { Component, ReactNode, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Link, useParams } from "react-router-dom";

import { ErrorBox, Spinner } from "../../../../components/ui";
import { P, actionFor, clone, errMsg, fa, label, up3d } from "../api";
import { IssueCount } from "../editor/BottomPanels";
import { byId } from "../editor/model";
import { hasQuality } from "../editor/QualityPanel";
import { ToastProvider, useCatalog, usePoll, useToast } from "../shared";
import type { Estimate, Issue, Item, Project, QualityOverride, SceneDoc, Transform, UploadResult, Vec3 } from "../types";
import { round3, sampleNum, sampleVec } from "./anim";
import { Clock, useClockPlaying } from "./clock";
import HelpPanel from "./HelpPanel";
import Library from "./Library";
import {
  type EdSel,
  type ObjRef,
  addActor,
  addCamera,
  addKey,
  addLight,
  addProduct,
  addProp,
  deleteKey,
  docDur,
  ensureItemIds,
  findKey,
  moveKey,
  removeObject,
  shotAt,
  writeTransform,
} from "./model";
import Outliner from "./Outliner";
import RenderDrawer from "./RenderDrawer";
import SceneInspector, { type Ed } from "./SceneInspector";
import SceneTimeline, { type DropTarget } from "./SceneTimeline";
import Viewport, { type DragPayload, type GizmoMode, type ViewportApi } from "./Viewport";
import "./editor.css";

/**
 * «ویرایشگرِ آزاد»ِ پروژهٔ سه‌بعدی — مثلِ Blender/Unreal ولی ساده:
 *   نمای سه‌بعدی (انتخاب، گیزمو، گام، قاب گرفتن، نمای دوربین) · فهرستِ صحنه + کتابخانه (کشیدن به صحنه)
 *   بازرس (جا/چرخش/اندازه، ظاهر، نور، دوربین، کلیدها) · خطِ زمان (حرکت‌ها، کلیدها، نماها؛ پخش/جابه‌جایی)
 * سند همان سندِ صحنهٔ پروژه است (up3d.scene/1 + فیلدهای اختیاریِ ویرایشگر) و با «ذخیره» نسخهٔ تازه می‌شود؛
 * «رندر» همان جریانِ کیفیت/کارگر/اول-GPU ِ صفحهٔ گام‌به‌گام است.
 */

const SNAP_T = (t: number) => Math.round(t * 20) / 20;

function useThrottledTime(clock: Clock, ms: number): number {
  const ref = useRef({ t: clock.t, at: 0 });
  const get = () => {
    const now = performance.now();
    if (!clock.playing || now - ref.current.at > ms) ref.current = { t: clock.t, at: now };
    return ref.current.t;
  };
  return useSyncExternalStore(clock.subscribe, get);
}

/** تمام‌صفحه با portal به body: قابِ پنل (انیمیشنِ u-rise) transform دارد و position:fixed را زندانی می‌کرد.
 *  پیام‌های کوتاه هم داخلِ همین لایه (ToastProvider ِ خودش) تا زیرِ ویرایشگر پنهان نمانند. */
export default function SceneEditorPage() {
  return createPortal(
    <ToastProvider>
      <Guard>
        <SceneEditor />
      </Guard>
    </ToastProvider>,
    document.body,
  );
}

/** خطای پیش‌بینی‌نشده در نما/بازرس کلِ پنل را سفید نکند: پیام + بارگذاریِ دوباره (سند روی سرور سالم است). */
class Guard extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="u3e-root" style={{ display: "grid", placeItems: "center" }}>
        <div className="u3e-help-card" style={{ padding: 20, maxWidth: 520 }}>
          <b>ویرایشگر به خطا خورد</b>
          <p className="u3e-hint">{this.state.error}</p>
          <p className="u3e-hint">تغییرهای ذخیره‌شده سالم‌اند. صفحه را دوباره بار کنید.</p>
          <button type="button" className="u3e-btn primary" onClick={() => window.location.reload()}>
            بارگذاریِ دوباره
          </button>
        </div>
      </div>
    );
  }
}

function SceneEditor() {
  const { id } = useParams<{ id: string }>();
  const pid = Number(id);
  const toast = useToast();
  const { cat, error: catError } = useCatalog();
  const [proj, setProj] = useState<Project | null>(null);
  const [doc, setDocState] = useState<SceneDoc | null>(null);
  const docRef = useRef<SceneDoc>(null as unknown as SceneDoc);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const loadedVersion = useRef<number | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<EdSel>(null);
  const [mode, setMode] = useState<GizmoMode>("translate");
  const [snap, setSnap] = useState(true);
  const [cameraView, setCameraView] = useState(false);
  const [showFrame, setShowFrame] = useState(true);
  const [viewLens, setViewLens] = useState(35);
  const [sideTab, setSideTab] = useState<"outliner" | "library">("library");
  const [drawer, setDrawer] = useState(false);
  const [help, setHelp] = useState(false);
  const [saving, setSaving] = useState(false);
  const undoRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const [, setHist] = useState(0);
  const vTimer = useRef(0);
  const clock = useMemo(() => new Clock(), []);
  const playing = useClockPlaying(clock);
  const tInspector = useThrottledTime(clock, 250);
  const apiRef = useRef<ViewportApi | null>(null);
  // رندر (همان state ِ بخشِ «کیفیت و رندر»)
  const [profile, setProfile] = useState("");
  const [quality, setQuality] = useState<QualityOverride | null>(null);
  const [est, setEst] = useState<Record<string, Estimate>>({});

  const setDoc = useCallback((d: SceneDoc) => {
    docRef.current = d;
    setDocState(d);
  }, []);
  const setDirtyBoth = (v: boolean) => {
    dirtyRef.current = v;
    setDirty(v);
  };

  // ───────── بار کردن و پولینگ (کارها، نسخه‌ها)
  const load = useCallback(
    async (force: boolean) => {
      try {
        const p = await up3d.project(pid);
        setProj(p);
        setError(null);
        if (p.document && (force || !dirtyRef.current) && p.version !== loadedVersion.current) {
          setDoc(p.document);
          loadedVersion.current = p.version;
          undoRef.current = [];
          redoRef.current = [];
          setHist((x) => x + 1);
          dirtyRef.current = false;
          setDirty(false);
          setIssues(p.report?.issues || []);
        }
      } catch (e) {
        setError(errMsg(e));
      }
    },
    [pid, setDoc],
  );
  const activeJobs = !!proj?.jobs.some((j) => !j.final);
  usePoll(() => load(false), drawer || activeJobs ? 4000 : 20000, [pid, drawer, activeJobs]);

  useEffect(() => {
    if (!cat || !proj || profile) return;
    const pick = cat.render_profile.find((p) => p.id === "animatic") || cat.render_profile[0];
    if (pick) setProfile(pick.id);
  }, [cat, proj, profile]);

  // ───────── وارسیِ زنده
  const scheduleValidate = useCallback((next: SceneDoc) => {
    window.clearTimeout(vTimer.current);
    vTimer.current = window.setTimeout(async () => {
      try {
        setIssues((await up3d.validate(next)).issues);
      } catch {
        /* دورِ بعد */
      }
    }, 600);
  }, []);
  useEffect(() => () => window.clearTimeout(vTimer.current), []);

  // ───────── تغییرِ سند با تاریخچه
  const change = useCallback(
    (fn: (d: SceneDoc) => void) => {
      const cur = docRef.current;
      if (!cur) return;
      undoRef.current.push(JSON.stringify(cur));
      if (undoRef.current.length > 120) undoRef.current.shift();
      redoRef.current = [];
      const next = clone(cur);
      fn(next);
      ensureItemIds(next);
      setDoc(next);
      dirtyRef.current = true;
      setDirty(true);
      setHist((x) => x + 1);
      scheduleValidate(next);
    },
    [setDoc, scheduleValidate],
  );
  const undo = () => {
    const prev = undoRef.current.pop();
    if (!prev) return;
    redoRef.current.push(JSON.stringify(docRef.current));
    const d = JSON.parse(prev) as SceneDoc;
    setDoc(d);
    setDirtyBoth(true);
    setHist((x) => x + 1);
    scheduleValidate(d);
  };
  const redo = () => {
    const nxt = redoRef.current.pop();
    if (!nxt) return;
    undoRef.current.push(JSON.stringify(docRef.current));
    const d = JSON.parse(nxt) as SceneDoc;
    setDoc(d);
    setDirtyBoth(true);
    setHist((x) => x + 1);
    scheduleValidate(d);
  };

  // ───────── ذخیره / رندر
  const save = async (repair: boolean): Promise<boolean> => {
    const cur = docRef.current;
    if (!cur) return false;
    setSaving(true);
    try {
      const r = await up3d.saveScene(pid, { document: cur, repair, source: "scene-editor", note: repair ? "ویرایشگرِ آزاد · ترمیم" : "ویرایشگرِ آزاد" });
      setDoc(r.document);
      loadedVersion.current = r.version;
      setIssues(r.report.issues || []);
      setDirtyBoth(false);
      const ch = r.report.changes || [];
      toast(`نسخهٔ ${fa(r.version)} ذخیره شد${ch.length ? ` · ${fa(ch.length)} ترمیم` : ""}${r.valid ? "" : " · هنوز ایراد دارد"}`, !r.valid);
      await load(true);
      return r.valid;
    } catch (e) {
      toast(errMsg(e), true);
      return false;
    } finally {
      setSaving(false);
    }
  };
  const render = async (prof: string, allowCpu: boolean, q: QualityOverride | null) => {
    if (dirtyRef.current && !(await save(false))) {
      toast("صحنه ایراد دارد؛ اول «ترمیمِ خودکار» یا درست کردنِ ایرادها", true);
      return;
    }
    try {
      const j = await up3d.startJob(pid, actionFor("render", prof), { profile: prof, ...(allowCpu ? { allow_cpu: true } : {}), ...(hasQuality(q) ? { quality: q } : {}) });
      toast(j.waiting && j.waiting.eligible.length === 0 ? `کار #${fa(j.id)} ساخته شد ولی کارگرِ مناسبی آنلاین نیست` : `کار #${fa(j.id)} در صف گذاشته شد`, !!(j.waiting && j.waiting.eligible.length === 0));
      await load(false);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const cancelJob = async (jid: number) => {
    try {
      await up3d.cancelJob(jid);
      await load(false);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const allowCpu = async (jid: number) => {
    try {
      await up3d.allowCpu(jid);
      await load(false);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const upload = async (file: File): Promise<UploadResult | null> => {
    try {
      const r = await up3d.upload(file);
      toast("بارگذاری شد");
      return r;
    } catch (e) {
      toast(errMsg(e), true);
      return null;
    }
  };

  // ───────── پخش
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.25, (now - last) / 1000);   // نزدیک به زمانِ واقعی؛ بعد از برگشت به زبانه پرشِ بزرگ نه
      last = now;
      const d = docRef.current ? docDur(docRef.current) : 10;
      let nt = clock.t + dt;
      if (nt >= d) nt = 0;
      clock.set(nt);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, clock]);
  const togglePlay = () => clock.setPlaying(!clock.playing);

  // ───────── دوربینِ آزاد: کلید از نمای فعلی
  const ensureCamShot = (d: SceneDoc, camId: string, t: number) => {
    if (d.shots.some((s) => s.camera === camId)) return;
    if (!d.shots.length) {
      d.shots.push({ camera: camId, start: 0, duration: docDur(d), params: {} });
      return;
    }
    const s = shotAt(d, t);
    if (s) s.camera = camId;
  };
  const captureCamKey = (camId?: string) => {
    const pose = apiRef.current?.capture();
    if (!pose || !docRef.current) return;
    const t = round3(clock.t);
    let cid = camId || (sel && (sel.type === "obj" || sel.type === "key") && sel.ref.kind === "camera" ? sel.ref.id : sel?.type === "target" ? sel.id : undefined);
    cid = cid || docRef.current.cameras?.[0]?.id;
    change((d) => {
      let id2 = cid;
      if (!id2 || !(d.cameras || []).some((c) => c.id === id2)) id2 = addCamera(d).id;
      addKey(d, cat!, { kind: "camera", id: id2 }, t, pose);
      ensureCamShot(d, id2, t);
      cid = id2;
    });
    if (cid) setSel({ type: "key", ref: { kind: "camera", id: cid }, t });
    toast(`کلیدِ دوربین در ${fa(t.toFixed(2))} ثانیه`);
  };

  // ───────── رها کردن از کتابخانه (نما / خطِ زمان / زدنِ کارت)
  const pickActor = (): string | undefined => {
    const d = docRef.current;
    if (sel && (sel.type === "obj" || sel.type === "key") && sel.ref.kind === "actor") return sel.ref.id;
    if (sel?.type === "action") return d.actions.find((a) => a.id === sel.id)?.actor || undefined;
    return d.actors[0]?.id;
  };
  const insertShot = (d: SceneDoc, item: Omit<Item, "start">, t: number) => {
    const dur = docDur(d);
    d.shots.sort((a, b) => a.start - b.start);
    const cover = d.shots.find((s) => s.start <= t + 1e-6 && t < s.start + (s.duration || 0) - 1e-6);
    if (cover) {
      const end = cover.start + (cover.duration || 0);
      if (t - cover.start < 0.4) {
        Object.assign(cover, { ...item, start: cover.start, duration: cover.duration, id: cover.id });
        if (!item.camera) delete cover.camera;
        return cover;
      }
      cover.duration = round3(t - cover.start);
      const n: Item = { ...item, start: round3(t), duration: round3(end - t) };
      d.shots.push(n);
      return n;
    }
    const next = d.shots.find((s) => s.start > t);
    const n: Item = { ...item, start: round3(t), duration: round3(Math.max(0.6, (next ? next.start : dur) - t)) };
    d.shots.push(n);
    return n;
  };
  const addMotion = (motionId: string, actorId: string | undefined, t: number) => {
    const m = byId(cat!, "motion", motionId);
    if (!m) return;
    if (!actorId) {
      toast("اول یک آدم به صحنه بکشید", true);
      return;
    }
    let newId = "";
    change((d) => {
      let start = t;
      if (!m.layer) {
        // حرکت‌های بدنِ یک آدم روی هم نمی‌افتند: اگر جا نیست، بعد از قبلی
        for (const a of d.actions.filter((x) => x.actor === actorId).sort((x, y) => x.start - y.start)) {
          const am = byId(cat!, "motion", a.motion);
          if (am?.layer) continue;
          if (a.start < start + m.duration.default && start < a.start + (a.duration || 0)) start = round3(a.start + (a.duration || 0) + 0.05);
        }
      }
      const params: Record<string, unknown> = {};
      if (m.product?.param && d.products[0]) params[m.product.param] = d.products[0].id;
      const it: Item = { actor: actorId, motion: motionId, start: round3(start), duration: m.duration.default, params };
      d.actions.push(it);
      d.actions.sort((x, y) => x.start - y.start);
      ensureItemIds(d);
      newId = it.id || "";
      if (start + m.duration.default > docDur(d)) d.output.duration = Math.min(60, Math.ceil(start + m.duration.default + 0.5));
    });
    if (newId) setSel({ type: "action", id: newId });
  };
  const addShotPreset = (shotId: string, t: number) => {
    const sa = byId(cat!, "shot", shotId);
    const d0 = docRef.current;
    const selRef = sel && (sel.type === "obj" || sel.type === "key") ? sel.ref : null;
    let subject: string | undefined;
    if (sa?.subject !== "product" && selRef?.kind === "actor") subject = selRef.id;
    if (sa?.subject !== "actor" && selRef?.kind === "product") subject = selRef.id;
    subject = subject || (sa?.subject === "product" ? d0.products[0]?.id : d0.actors[0]?.id || d0.products[0]?.id);
    if (!subject) {
      toast("نمای آماده سوژه می‌خواهد (آدم یا محصول)؛ یا دوربینِ آزاد بسازید", true);
      return;
    }
    let nid = "";
    change((d) => {
      const n = insertShot(d, { shot: shotId, subject, move: (sa?.moves || ["static"])[0], params: {} }, t);
      ensureItemIds(d);
      nid = n.id || "";
    });
    if (nid) setSel({ type: "shot", id: nid });
  };
  const handleDrop = (p: DragPayload, at: Vec3 | null, t = clock.t) => {
    if (!cat || !docRef.current) return;
    const d0 = docRef.current;
    let newSel: EdSel = null;
    switch (p.kind) {
      case "environment":
        change((d) => {
          d.environment = { id: p.id, params: {} };
          const en = byId(cat, "environment", p.id);
          if (en?.default_lighting) d.lighting = { id: en.default_lighting, params: {} };
        });
        toast(`محیط: ${label(byId(cat, "environment", p.id))}`);
        return;
      case "lighting":
        change((d) => void (d.lighting = { id: p.id, params: {} }));
        toast(`نورپردازی: ${label(byId(cat, "lighting", p.id))}`);
        return;
      case "character": {
        const pos: Vec3 = at ? [at[0], at[1], at[2] > 0.3 ? 0 : at[2]] : [0.6 * d0.actors.length * (d0.actors.length % 2 ? 1 : -1), 0, 0];
        change((d) => void (newSel = { type: "obj", ref: addActor(d, cat, p.id, pos) }));
        break;
      }
      case "product": {
        const en = byId(cat, "environment", d0.environment.id);
        const sf = Object.values(en?.surfaces || {})[d0.products.length] as { pos?: number[] } | undefined;
        const pos: Vec3 = at || (sf?.pos ? [sf.pos[0], sf.pos[1], sf.pos[2]] : [0, -0.4, 0.9]);
        change((d) => void (newSel = { type: "obj", ref: addProduct(d, cat, p.id, pos) }));
        break;
      }
      case "prop":
        change((d) => void (newSel = { type: "obj", ref: addProp(d, p.id, at || [0.6, -0.8, 0]) }));
        break;
      case "light": {
        const base = at || [1.2, -1.8, 0];
        change((d) => void (newSel = { type: "obj", ref: addLight(d, p.id as "point", [base[0], base[1], Math.max(base[2] + 1.8, 2.2)]) }));
        break;
      }
      case "camera":
        change((d) => void (newSel = { type: "obj", ref: addCamera(d) }));
        toast("دوربینِ آزاد ساخته شد: نما را تنظیم کنید و «◆ کلید از همین نما» (K) بزنید");
        break;
      case "motion":
        addMotion(p.id, pickActor(), SNAP_T(t));
        return;
      case "shot":
        addShotPreset(p.id, SNAP_T(t));
        return;
      default:
        return;
    }
    if (newSel) setSel(newSel);
  };
  const handleTimelineDrop = (p: DragPayload, target: DropTarget, t: number) => {
    if (target.row === "actions" && p.kind === "motion") addMotion(p.id, target.actor, t);
    else if (target.row === "shots" && p.kind === "shot") addShotPreset(p.id, t);
    else if (target.row === "shots" && p.kind === "camera") {
      change((d) => {
        const camId = (d.cameras || [])[0]?.id || addCamera(d).id;
        insertShot(d, { camera: camId, params: {} }, t);
      });
      toast("شاتِ دوربینِ آزاد: نما را تنظیم کنید و «◆ از همین نما کلید بزن»");
    } else toast("این را در نما رها کنید", true);
  };

  // ───────── گیزمو ⇐ سند
  const onCommit = (ref: ObjRef, tr: Transform) => {
    const t = clock.t;
    change((d) => void writeTransform(d, cat!, ref, tr, t));
  };
  const onCommitCamera = (camId: string, part: "pos" | "target", v: Vec3) => {
    const t = round3(clock.t);
    change((d) => {
      const c = (d.cameras || []).find((x) => x.id === camId);
      if (!c) return;
      const i = findKey(c.keys, t);
      if (i >= 0) c.keys[i] = { ...c.keys[i], [part]: v };
      else {
        const pos = part === "pos" ? v : sampleVec(c.keys, t, "pos", [0, -3, 1.5]);
        const target = part === "target" ? v : sampleVec(c.keys, t, "target", [0, 0, 1.2]);
        addKey(d, cat!, { kind: "camera", id: camId }, t, { pos, target, lens: sampleNum(c.keys, t, c.lens || 35) });
      }
      ensureCamShot(d, camId, t);
    });
  };

  // ───────── حذف / کلید با میان‌بر
  const deleteSel = () => {
    if (!sel) return;
    if (sel.type === "obj") {
      if (sel.ref.kind === "environment") return;
      change((d) => removeObject(d, sel.ref));
      setSel(null);
    } else if (sel.type === "key") {
      change((d) => deleteKey(d, sel.ref, sel.t));
      setSel({ type: "obj", ref: sel.ref });
    } else if (sel.type === "action") {
      change((d) => void (d.actions = d.actions.filter((x) => x.id !== sel.id)));
      setSel(null);
    } else if (sel.type === "shot") {
      change((d) => void (d.shots = d.shots.filter((x) => x.id !== sel.id)));
      setSel(null);
    }
  };
  const keySel = () => {
    if (!sel || !cat) return;
    const ref = sel.type === "obj" || sel.type === "key" ? sel.ref : sel.type === "target" ? ({ kind: "camera", id: sel.id } as ObjRef) : null;
    if (!ref || ref.kind === "environment") {
      toast("یک شیء (آدم، محصول، شیء، نور یا دوربین) انتخاب کنید", true);
      return;
    }
    if (ref.kind === "camera") return captureCamKey(ref.id);
    const t = round3(clock.t);
    change((d) => addKey(d, cat, ref, t));
    setSel({ type: "key", ref, t });
    toast(`کلید در ${fa(t.toFixed(2))} ثانیه`);
  };
  const frameSel = () => {
    const ref = sel && (sel.type === "obj" || sel.type === "key") ? sel.ref : null;
    apiRef.current?.frame(ref && ref.kind !== "environment" ? ref : null);
  };

  // ───────── میان‌برها
  const keysRef = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keysRef.current = (e: KeyboardEvent) => {
    const tag = (document.activeElement?.tagName || "").toUpperCase();
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && k === "z" && !e.shiftKey) return void (e.preventDefault(), undo());
    if (ctrl && (k === "y" || (k === "z" && e.shiftKey))) return void (e.preventDefault(), redo());
    if (ctrl && k === "s") return void (e.preventDefault(), void save(false));
    if (ctrl) return;
    if (k === " " || e.code === "Space") return void (e.preventDefault(), togglePlay());
    if (k === "w") setMode("translate");
    else if (k === "e") setMode("rotate");
    else if (k === "r") setMode("scale");
    else if (k === "f") frameSel();
    else if (k === "k" || k === "i") keySel();
    else if (k === "c") setCameraView((v) => !v);
    else if (k === "g") setSnap((v) => !v);
    else if (k === "home") clock.set(0);
    else if (k === "escape") setSel(null);
    else if (k === "delete" || k === "backspace") {
      e.preventDefault();
      deleteSel();
    } else if (k === "?" || (e.shiftKey && k === "/")) setHelp((v) => !v);
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keysRef.current(e);
    const unload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    document.addEventListener("keydown", on);
    window.addEventListener("beforeunload", unload);
    return () => {
      document.removeEventListener("keydown", on);
      window.removeEventListener("beforeunload", unload);
    };
  }, []);

  if (!cat || !proj || !doc) {
    return (
      <div className="u3e-root">
        <div className="py-16 text-center">{catError || error ? <ErrorBox message={catError || error} /> : <Spinner />}</div>
      </div>
    );
  }

  const ed: Ed = {
    cat,
    doc,
    sel,
    t: tInspector,
    setSel,
    change,
    upload,
    capture: () => apiRef.current?.capture() || null,
    goTo: (pos, target) => apiRef.current?.goTo(pos, target),
    seek: (t) => clock.set(Math.max(0, Math.min(docDur(docRef.current), t))),
    cameraView,
    setCameraView,
  };
  const errCount = issues.filter((i) => i.level === "error").length;
  const selCamOrNone = !!(doc.cameras || []).length;

  return (
    <div className="u3e-root" data-testid="scene-editor">
      <header className="u3e-bar">
        <Link to={P.project(pid)} className="u3e-back" title="برگشت به صفحهٔ گام‌به‌گام">
          ←
        </Link>
        <div className="u3e-modes" role="tablist">
          <Link to={P.project(pid)} className="u3e-mode">
            گام‌به‌گام
          </Link>
          <span className="u3e-mode on" aria-current="page">
            ویرایشگرِ آزاد
          </span>
        </div>
        <b className="u3e-title" title={proj.title}>
          {proj.title}
        </b>
        <span className={`u3e-ver ${dirty ? "dirty" : ""}`}>{dirty ? "تغییرِ ذخیره‌نشده" : proj.version ? `نسخهٔ ${fa(proj.version)}` : ""}</span>
        <div className="u3e-tools">
          <div className="u3e-seg" role="group" aria-label="گیزمو">
            <button type="button" className={mode === "translate" ? "on" : ""} onClick={() => setMode("translate")} title="جابه‌جایی (W)">
              ✥ <small>W</small>
            </button>
            <button type="button" className={mode === "rotate" ? "on" : ""} onClick={() => setMode("rotate")} title="چرخش (E)">
              ⟳ <small>E</small>
            </button>
            <button type="button" className={mode === "scale" ? "on" : ""} onClick={() => setMode("scale")} title="اندازه (R)">
              ⤢ <small>R</small>
            </button>
          </div>
          <button type="button" className={`u3e-tbtn ${snap ? "on" : ""}`} onClick={() => setSnap(!snap)} title="گام (G): ۵ سانت، ۱۵ درجه، ۰٫۱">
            🧲
          </button>
          <button type="button" className={`u3e-tbtn ${showFrame ? "on" : ""}`} onClick={() => setShowFrame(!showFrame)} title="قابِ خروجی">
            ▭
          </button>
          <button type="button" className={`u3e-tbtn ${cameraView ? "on" : ""}`} onClick={() => setCameraView(!cameraView)} title="نگاه از دوربینِ ویدئو (C)" data-testid="camview">
            🎥
          </button>
          <select className="u3e-lens" value={viewLens} onChange={(e) => setViewLens(Number(e.target.value))} title="لنزِ نما (برای کلیدِ دوربین)">
            {[18, 24, 35, 50, 70, 85, 120].map((l) => (
              <option key={l} value={l}>
                {fa(l)}mm
              </option>
            ))}
          </select>
          <button type="button" className="u3e-btn" onClick={() => captureCamKey()} title="کلیدِ دوربین از همین نما در زمانِ فعلی" data-testid="camkey">
            ◆ از همین نما کلید بزن
          </button>
          {!selCamOrNone && <span className="u3e-tl-hint">(دوربینِ آزاد با اولین کلید ساخته می‌شود)</span>}
        </div>
        <div className="u3e-actions">
          <button type="button" className="u3e-tbtn" onClick={undo} disabled={!undoRef.current.length} title="برگشت (Ctrl+Z)">
            ↶
          </button>
          <button type="button" className="u3e-tbtn" onClick={redo} disabled={!redoRef.current.length} title="دوباره (Ctrl+Y)">
            ↷
          </button>
          <span className="u3e-issues" title={issues.map((i) => i.message).join("\n")}>
            ایراد <IssueCount issues={issues} />
          </span>
          {errCount > 0 && (
            <button type="button" className="u3e-btn" onClick={() => void save(true)} disabled={saving}>
              ترمیمِ خودکار
            </button>
          )}
          <button type="button" className="u3e-btn primary" onClick={() => void save(false)} disabled={saving} title="Ctrl+S" data-testid="save">
            {saving ? "…" : "ذخیره"}
          </button>
          <button type="button" className="u3e-btn accent" onClick={() => setDrawer(true)} data-testid="render">
            رندر
          </button>
          <button type="button" className="u3e-tbtn" onClick={() => setHelp(true)} title="راهنما (?)">
            ؟
          </button>
        </div>
      </header>

      <aside className="u3e-side">
        <div className="u3e-tabs">
          <button type="button" className={sideTab === "library" ? "on" : ""} onClick={() => setSideTab("library")}>
            کتابخانه
          </button>
          <button type="button" className={sideTab === "outliner" ? "on" : ""} onClick={() => setSideTab("outliner")}>
            صحنه
          </button>
        </div>
        <div className="u3e-side-b">
          {sideTab === "library" ? (
            <Library cat={cat} envId={doc.environment.id} lightingId={doc.lighting.id} onAdd={(p) => handleDrop(p, null)} />
          ) : (
            <Outliner cat={cat} doc={doc} sel={sel} onSelect={setSel} onFrame={(r) => apiRef.current?.frame(r)} onDelete={(r) => change((d) => removeObject(d, r))} />
          )}
        </div>
      </aside>

      <main className="u3e-view">
        <Viewport
          cat={cat}
          doc={doc}
          docRef={docRef}
          clock={clock}
          sel={sel}
          onSelect={(s) => {
            setSel(s);
            if (s && s.type === "obj" && sideTab === "library") setSideTab("library");
          }}
          mode={mode}
          snap={snap}
          cameraView={cameraView}
          showFrame={showFrame}
          viewLens={viewLens}
          onCommit={onCommit}
          onCommitCamera={onCommitCamera}
          apiRef={apiRef}
          onDrop={(p, at) => handleDrop(p, at)}
          onNotice={(text) => toast(text)}
        />
        {cameraView && <div className="u3e-viewtag">نمای دوربینِ ویدئو · C برای برگشت</div>}
      </main>

      <aside className="u3e-insp">
        <SceneInspector ed={ed} />
      </aside>

      <section className="u3e-tlwrap">
        <SceneTimeline
          cat={cat}
          doc={doc}
          clock={clock}
          sel={sel}
          issues={issues}
          onSelect={setSel}
          onTogglePlay={togglePlay}
          onMoveBlock={(list, bid, start, duration) =>
            change((d) => {
              const it = d[list].find((x) => x.id === bid);
              if (!it) return;
              it.start = start;
              it.duration = duration;
              d[list].sort((a, b) => a.start - b.start);
            })
          }
          onMoveKey={(ref, t0, t1) => {
            let nt = t1;
            change((d) => void (nt = moveKey(d, ref, t0, t1)));
            setSel({ type: "key", ref, t: nt });
            clock.set(nt);
          }}
          onDropAsset={handleTimelineDrop}
          onAddKey={(ref, t) => {
            clock.set(t);
            if (ref.kind === "camera") captureCamKey(ref.id);
            else {
              change((d) => addKey(d, cat, ref, t));
              setSel({ type: "key", ref, t: round3(t) });
            }
          }}
        />
      </section>

      {drawer && (
        <RenderDrawer
          cat={cat}
          proj={proj}
          aspect={doc.output.aspect}
          issues={issues}
          profile={profile}
          setProfile={setProfile}
          quality={quality}
          setQuality={setQuality}
          est={est}
          setEst={setEst}
          onRender={(p, cpu, q) => void render(p, cpu, q)}
          onCancel={(jid) => void cancelJob(jid)}
          onAllowCpu={(jid) => void allowCpu(jid)}
          onPickIssue={() => setDrawer(false)}
          onClose={() => setDrawer(false)}
        />
      )}
      {help && <HelpPanel onClose={() => setHelp(false)} />}
    </div>
  );
}
