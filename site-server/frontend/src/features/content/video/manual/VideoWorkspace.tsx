import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import Workspace from "../../../../components/Workspace";
import { Badge, Spinner } from "../../../../components/ui";
import { useHistory } from "../../../../hooks/useHistory";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { Job } from "../../../../types";
import type { ToolInfo } from "../../ToolPicker";
import type { Bin as BinData, Catalogue, Check, LutRow, MatteRow, MatteStatus, MediaItem, ProjectRow, RenderWhere, SyncResult, TrackResult } from "../api";
import { videoApi } from "../api";
import { AudioEngine } from "./AudioEngine";
import Bin from "./Bin";
import type { LookDef } from "./color";
import ExactPreview from "./ExactPreview";
import Inspector, { InspectorTab } from "./Inspector";
import { KfChannel } from "./keyframes";
import { frameToSource } from "./geom";
import { Lut, parseCube } from "./lut";
import { BezierOverlay, RegionOverlay } from "./PickOverlay";
import type { FrameRect, SyncRow } from "./ProPanel";
import {
  AngleSource, autoRipple, beatFit, beatSnap, beatSplit, beatTimes, createMulticam, jlCut as jlCutOp, nestClips, removeCutAt, seqIdOf, setAngleAt,
  setMulticamAudio, unnestClip, viewOf, writeView,
} from "./ops";
import { SHAPES, defaultShape } from "./shapes";
import { attachTo, bakeFollowers, detach, trackerFromResult } from "./tracking";
import { fetchBeats, srcToTimeline, useDuckSpans } from "./mediaAnalysis";
import Monitor, { MonitorHandle } from "./Monitor";
import {
  AnyClip, AttrClip, AttrGroup, FORMATS, MediaClip, Project, ShapeKind, TextClip, addMarker, addMedia, addText, addTextClips, addTrack, clearMarkers, clipEnd, clipLength, copyAttrs,
  deleteClips, duplicateClips, emptyProject, extractAudio, findClip, freeSpot, freezeFrameAt, fromApi, isMedia, linkClips, liftRange, moveClips, pasteAttrs, projectLength,
  newMediaClip, nudgeEdge, overlaps, removeMarker, removeTrack, rippleTrim, splitMany, srcTimeAt, toApi, uid, unlinkClips, updateClip, updateTrack, withLinked,
} from "./model";
import { cuesOf, makeRoom, parseSrt, spanOf, splitAtSourceCuts, toSrt } from "./r4ops";
import { detectScenes } from "./reframeApi";
import Scopes from "./Scopes";
import QuickStart from "./QuickStart";
import ShortcutSheet from "./ShortcutSheet";
import TimelineView, { Tool } from "./TimelineView";
import TrimBar from "./TrimBar";
import { ALL_FEATURES, ALL_PANELS, comboOf, isKeyCapture, latinKey, pushRecent, typingTarget, useKeymap } from "../registry";
import type { FeatureDef, WorkspaceApi } from "../registry";
import CommandPalette from "../registry/CommandPalette";
import MenuBar from "../registry/MenuBar";
import PanelHost from "../registry/PanelHost";
import { directorApi } from "../director/api";
import type { FlagName } from "../registry/types";
import "./workspace.css";

type Props = {
  storeId: string;
  tools: ToolInfo[];
  /** ویدیویی که با «ویرایشِ دستی» از فهرست آمده: پروژهٔ تازه با همین قطعه شروع می‌شود */
  startRef?: string | null;
  onStartConsumed?: () => void;
  /** پروژه‌ای (مثلاً ساختهٔ «کارگردان») که باید همین‌جا باز شود */
  startProject?: number | null;
  onProjectOpened?: () => void;
  /** رفتن به «کارگردان» (حالتِ نیمه‌خودکار) از صفحهٔ شروع */
  onGoDirector?: () => void;
};

const TOOLS: { key: Tool; label: string; title: string }[] = [
  { key: "select", label: "V", title: "انتخاب (V). هنگامِ کشیدنِ لبهٔ قطعه: Ctrl = ریپل (بعدی‌ها جابه‌جا شوند)، Shift = رول (برشِ بین دو قطعه)، Alt = فقط همین قطعه (صدا/تصویرِ پیوندی نمی‌آید). همه‌چیز روی فریم می‌نشیند" },
  { key: "razor", label: "✂ C", title: "تیغه: روی قطعه کلیک کنید تا همان‌جا بریده شود (C)" },
  { key: "trackfwd", label: "A", title: "انتخابِ همهٔ قطعه‌ها از این نقطه به جلو (A)" },
  { key: "ripple", label: "B", title: "ریپل: لبه را ببرید، بقیه جلو/عقب می‌آیند (B). با ابزارِ «انتخاب» هم می‌شود: Ctrl نگه دارید و لبه را بکشید" },
  { key: "roll", label: "N", title: "رول: برشِ بینِ دو قطعه را جابه‌جا کنید (N). با ابزارِ «انتخاب» هم می‌شود: Shift نگه دارید و لبهٔ چسبیده را بکشید" },
  { key: "slip", label: "Y", title: "اسلیپ: همان طول، بازهٔ منبع عوض می‌شود (Y)" },
  { key: "slide", label: "U", title: "اسلاید: قطعه می‌لغزد و همسایه‌ها جبران می‌کنند (U)" },
  { key: "rate", label: "R", title: "تغییرِ سرعت با کشیدنِ لبه (R)" },
];

export default function VideoWorkspace({ storeId, tools, startRef, onStartConsumed, startProject, onProjectOpened, onGoDirector }: Props) {
  const hist = useHistory<Project>(emptyProject());
  const root = hist.state;
  /** توالی‌هایی که باز کرده‌ایم (از ریشه به عمق)؛ خالی = خودِ پروژه. هر ویرایش روی «نما»ی توالیِ بازِ فعلی می‌نشیند */
  const [path, setPath] = useState<string[]>([]);
  const project = useMemo(() => viewOf(root, path), [root, path]);
  const [luts, setLuts] = useState<LutRow[]>([]);
  const [lutData, setLutData] = useState<Record<string, Lut>>({});
  const [lutBusy, setLutBusy] = useState(false);
  const [mattes, setMattes] = useState<MatteRow[]>([]);
  const [matteStatus, setMatteStatus] = useState<MatteStatus | null>(null);
  const [matteMsg, setMatteMsg] = useState<string | null>(null);
  const [matteErr, setMatteErr] = useState<string | null>(null);
  const [where, setWhere] = useState<RenderWhere | null>(null);
  const [pickRegion, setPickRegion] = useState(false);
  const [region, setRegion] = useState<FrameRect | null>(null);
  const [editingMask, setEditingMask] = useState(false);
  const [cropMode, setCropMode] = useState(false);
  const [trackMsg, setTrackMsg] = useState<string | null>(null);
  const [trackErr, setTrackErr] = useState<string | null>(null);
  const [syncRows, setSyncRows] = useState<SyncRow[] | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [bin, setBin] = useState<BinData | null>(null);
  const [binLoading, setBinLoading] = useState(true);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [title, setTitle] = useState("پروژهٔ تازه");
  const [check, setCheck] = useState<Check | null>(null);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [selection, setSelection] = useState<string[]>([]);
  const [px, setPx] = useState(60);
  const [snapOn, setSnapOn] = useState(true);
  const [volLine, setVolLine] = useState(true);
  const [tool, setTool] = useState<Tool>("select");
  const [tab, setTab] = useState<InspectorTab>("clip");
  const [notice, setNotice] = useState<string | null>(null);
  const [proxyBusy, setProxyBusy] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [cat, setCat] = useState<Catalogue | null>(null);
  const [compare, setCompare] = useState<string | null>(null);
  const [clipboard, setClipboard] = useState<AttrClip | null>(null);
  const [clipsBoard, setClipsBoard] = useState<{ clip: AnyClip; kind: string }[]>([]);
  const [exact, setExact] = useState<{ t0: number; t1: number } | null>(null);
  const [scopesOpen, setScopesOpen] = useState(false);
  const [scopeVer, setScopeVer] = useState(0);
  const [beatsBusy, setBeatsBusy] = useState(false);
  const [renderStarting, setRenderStarting] = useState(false);
  const [help, setHelp] = useState(false);
  const [loopOn, setLoopOn] = useState(false);
  const loopRef = useRef(false);
  loopRef.current = loopOn;
  const [menubar, setMenubar] = useState<boolean>(() => {
    try { return localStorage.getItem("nm.video.menubar") === "1"; } catch { return false; }
  });
  const [searchOpen, setSearchOpen] = useState(false);
  const [editorSettings, setEditorSettings] = useState<{ ai_default: boolean; draft_days: number } | null>(null);
  useEffect(() => {
    const load = () => void directorApi.settings(storeId).then((v) => setEditorSettings({ ai_default: v.ai_default, draft_days: v.draft_days })).catch(() => undefined);
    load();
    window.addEventListener("nm-editor-settings-changed", load);
    return () => window.removeEventListener("nm-editor-settings-changed", load);
  }, [storeId]);
  const [panel, setPanel] = useState<{ id: string; props?: Record<string, unknown> } | null>(null);
  useEffect(() => {
    try { localStorage.setItem("nm.video.menubar", menubar ? "1" : "0"); } catch { /* حافظهٔ مرورگر بسته است */ }
  }, [menubar]);
  const lastSnap = useRef<number>(Date.now());
  const lastSaved = useRef<string>("");
  const idRef = useRef<number | null>(null);
  idRef.current = projectId;
  const totalRef = useRef(0);
  totalRef.current = projectLength(project);
  const monitor = useRef<MonitorHandle>(null);
  const engine = useMemo(() => new AudioEngine(), []);
  useEffect(() => {
    Object.assign(window, { __nmVideoEngine: engine });
    return () => engine.dispose();
  }, [engine]);

  const looks: LookDef[] = useMemo(() => (cat?.color.looks ?? []).map((l) => ({ key: l.key, title: l.title, params: l.params as LookDef["params"] })), [cat]);
  const duckSpans = useDuckSpans(storeId, project);

  // ───────────── بستهٔ رسانه
  const loadBin = useCallback(async () => {
    try {
      setBin(await videoApi.bin(storeId));
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setBinLoading(false);
    }
  }, [storeId]);
  const uploadRunner = useJobRunner(loadBin);
  const proxyRunner = useJobRunner(async () => {
    setProxyBusy(null);
    await loadBin();
  });

  const media = useMemo(() => {
    const m: Record<string, MediaItem> = {};
    for (const list of bin ? [bin.videos, bin.audio, bin.images, bin.stickers ?? []] : []) for (const it of list) m[it.ref] = it;
    return m;
  }, [bin]);

  // ───────────── آغاز: بسته + کاتالوگ + پروژه‌ها
  useEffect(() => {
    let stop = false;
    (async () => {
      void videoApi.catalogue(storeId).then((c) => !stop && setCat(c)).catch((err) => !stop && setNotice(errorMessage(err)));
      await loadBin();
      try {
        const rows = await videoApi.projects(storeId);
        if (stop) return;
        setProjects(rows);
        if (!startRef && rows.length) {
          const { project: row, check: ck } = await videoApi.project(storeId, rows[0].id);
          if (stop) return;
          const p = fromApi(row.data);
          hist.reset(p);
          lastSaved.current = JSON.stringify(toApi(p)) + "|" + (row.title || "");
          setProjectId(row.id);
          setTitle(row.title || "پروژه");
          setCheck(ck);
        }
      } catch (err) {
        setNotice(errorMessage(err));
      }
      setReady(true);
    })();
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId]);

  // «ویرایشِ دستی» از کارتِ یک ویدیو
  useEffect(() => {
    if (!ready || !startRef || !bin) return;
    const item = media[startRef];
    if (!item) return;
    const base = emptyProject();
    const vt = base.tracks.find((t) => t.kind === "video")!;
    let p = addMedia(base, vt.id, item, 0);
    const ar = item.width && item.height ? item.width / item.height : 9 / 16;
    p = { ...p, format: ar > 1.2 ? { ...p.format, width: 1920, height: 1080, preset: "wide" } : ar > 0.9 ? { ...p.format, width: 1080, height: 1080, preset: "square" } : p.format };
    hist.reset(p);
    lastSaved.current = "";
    setProjectId(null);
    setTitle(`ویرایشِ ${item.title}`.slice(0, 60));
    setTime(0);
    setSelection([vt.id && p.tracks.find((t) => t.id === vt.id)?.clips[0]?.id].filter(Boolean) as string[]);
    onStartConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, startRef, bin]);

  // ───────────── ذخیرهٔ خودکار
  const dataKey = useMemo(() => JSON.stringify(toApi(root)), [root]);
  const hasClips = root.tracks.some((t) => t.clips.length > 0);
  const saveRef = useRef<{ key: string; title: string }>({ key: "", title: "" });
  saveRef.current = { key: dataKey, title };
  const saveNow = useCallback(async (): Promise<number | null> => {
    const { key, title: tt } = saveRef.current;
    const data = JSON.parse(key);
    setSaving("saving");
    try {
      if (!idRef.current) {
        const res = await videoApi.createProject(storeId, tt, data);
        idRef.current = res.project.id;
        setProjectId(res.project.id);
        setProjects((cur) => [res.project, ...cur]);
        setCheck(res.check);
      } else {
        const res = await videoApi.saveProject(storeId, idRef.current, { title: tt, data });
        setCheck(res.check);
      }
      lastSaved.current = key + "|" + tt;
      setSaving("saved");
      // هر ~۱۰ دقیقه که پروژه در حالِ ویرایش است یک نسخهٔ خودکار (بازگشتِ ایمن)
      if (idRef.current && Date.now() - lastSnap.current > 600_000 && data?.tracks?.some((t: { clips?: unknown[] }) => (t.clips?.length ?? 0) > 0)) {
        lastSnap.current = Date.now();
        void api.post(`/stores/${storeId}/editor/projects/${idRef.current}/versions/`, { label: "خودکار", data }).catch(() => undefined);
      }
      return idRef.current;
    } catch (err) {
      setSaving("error");
      setNotice(errorMessage(err));
      return null;
    }
  }, [storeId]);
  useEffect(() => {
    if (!ready || (!hasClips && !idRef.current)) return;
    if (lastSaved.current === dataKey + "|" + title) return;
    const t = window.setTimeout(() => void saveNow(), 1100);
    return () => window.clearTimeout(t);
  }, [dataKey, title, ready, hasClips, saveNow]);

  async function openProject(id: number | null) {
    setPlaying(false);
    setSelection([]);
    setTime(0);
    setExact(null);
    setPath([]);
    if (!id) {
      hist.reset(emptyProject());
      setProjectId(null);
      idRef.current = null;
      setTitle("پروژهٔ تازه");
      setCheck(null);
      lastSaved.current = "";
      return;
    }
    try {
      const { project: row, check: ck } = await videoApi.project(storeId, id);
      const p = fromApi(row.data);
      hist.reset(p);
      lastSaved.current = JSON.stringify(toApi(p)) + "|" + (row.title || "");
      setProjectId(row.id);
      idRef.current = row.id;
      setTitle(row.title || "پروژه");
      setCheck(ck);
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  // یک پروژه از بیرون (کارگردان) خواسته شده: بعد از آماده‌شدنِ فضای کار باز می‌شود
  useEffect(() => {
    if (!ready || !startProject) return;
    void openProject(startProject).then(() => videoApi.projects(storeId).then(setProjects).catch(() => undefined));
    onProjectOpened?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, startProject]);

  async function deleteProject() {
    if (!projectId || !window.confirm("این پروژه حذف شود؟ (فایل‌های رندرشده هم می‌روند)")) return;
    await videoApi.deleteProject(storeId, projectId);
    setProjects((cur) => cur.filter((p) => p.id !== projectId));
    await openProject(null);
  }

  // ───────────── زمان و پخش (پخش را خودِ مانیتور می‌گرداند)
  const seek = useCallback((t: number) => setTime(Math.max(0, Math.min(Math.max(totalRef.current, 0.0001) + 20, t))), []);
  const togglePlay = () => {
    void engine.resume();
    if (!playing && rate < 0 && time <= 0) setRate(1);
    if (!playing && time >= totalRef.current - 0.01 && rate > 0) setTime(0);
    setPlaying((p) => !p);
  };
  const step = (frames: number) => {
    setPlaying(false);
    seek(time + frames * (1 / (project.format.fps || 30)));
  };

  // ───────────── ویرایش
  const primaryId = selection[selection.length - 1] ?? null;
  const selected = findClip(project, primaryId);
  const aspectOf = useCallback((ref: string) => {
    const it = media[ref];
    return it && it.width && it.height ? it.width / it.height : 0;
  }, [media]);
  /** هر ویرایش: ریپلِ خودکارِ بعدی‌ها هنگامِ کندکردن، پختنِ دوبارهٔ چیزهای وصل‌به‌ردیاب، و برگرداندنِ نما به ریشه */
  const through = (r: Project, fn: (v: Project) => Project, base?: Project): Project => {
    const v = viewOf(r, path);
    return writeView(r, path, bakeFollowers(autoRipple(base ?? v, fn(v)), aspectOf));
  };
  const live = (fn: (p: Project) => Project) => hist.live((r) => through(r, fn));
  const apply = (label: string, fn: (p: Project) => Project) => hist.apply(label, (r) => through(r, fn));
  /** تغییر در سطحِ ریشه (ردیاب‌ها، تنظیمِ ریپل) */
  const applyRoot = (label: string, fn: (p: Project) => Project) => hist.apply(label, fn);
  const edit = { live, end: hist.end, apply };
  const rippleOn = root.auto_ripple !== false;
  const linkedSel = !!selected && selected.clip.type === "media" && !!selected.clip.link && project.tracks.flatMap((t) => t.clips).filter((c) => isMedia(c) && c.link === (selected.clip as MediaClip).link).length > 1;

  function trackFor(kind: "video" | "audio" | "text") {
    return project.tracks.find((t) => t.kind === kind && !t.locked);
  }

  function addFromBin(item: MediaItem, trackId?: string, at?: number) {
    if (item.ref.startsWith("sticker:") && !trackId) {
      addSticker(item);
      return;
    }
    const kind = item.kind === "audio" ? "audio" : "video";
    const tr = project.tracks.find((t) => t.id === trackId && t.kind === kind && !t.locked) ?? (item.kind === "audio" ? (project.tracks.find((t) => t.kind === "audio" && !t.locked && t.role === "music") ?? trackFor("audio")) : trackFor("video"));
    if (!tr) return;
    const first = !hasClips;
    apply(`افزودن «${item.title}»`, (pr) => {
      let next = addMedia(pr, tr.id, item, at ?? time);
      if (first && item.kind === "video" && item.width && item.height) {
        const ar = item.width / item.height;
        next = { ...next, format: ar > 1.2 ? { ...next.format, width: 1920, height: 1080, preset: "wide" } : ar > 0.9 ? { ...next.format, width: 1080, height: 1080, preset: "square" } : next.format };
      }
      return next;
    });
  }

  /** متنِ تازه در سرِ پخش؛ همان انتخاب می‌شود تا ویژگی‌هایش در تبِ «متن» باز شود */
  function newText() {
    const tt = project.tracks.find((tr) => tr.kind === "text" && !tr.locked);
    if (!tt) return;
    const id = uid();
    apply("متن", (pr) => addText(pr, tt.id, "متنِ تازه", time, 2.5, { id }));
    setSelection([id]);
    setTab("text");
  }

  function splitHere(at = time) {
    const t = at;
    apply("تقسیم", (pr) => {
      if (selection.length) return splitMany(pr, withLinked(pr, selection), t);
      return splitMany(pr, pr.tracks.filter((tr) => !tr.locked).flatMap((tr) => tr.clips.map((c) => c.id)), t);
    });
  }

  function removeSelected(ripple: boolean) {
    if (!selection.length) return;
    const ids = selection;
    apply(ripple ? "حذفِ بی‌فاصله" : "حذف", (pr) => deleteClips(pr, ids, ripple));
    setSelection([]);
  }

  function nudge(frames: number) {
    if (!selection.length) return;
    const d = frames / (project.format.fps || 30);
    apply("جابه‌جاییِ فریمی", (pr) => moveClips(pr, withLinked(pr, selection), d));
  }

  function trimToPlayhead(side: "l" | "r") {
    const ids = selection.length ? selection : project.tracks.flatMap((t) => t.clips.filter((c) => time > c.at && time < clipEnd(c)).map((c) => c.id));
    if (!ids.length) return;
    apply(side === "l" ? "کوتاه تا سرِ پخش (ریپل)" : "کوتاه تا سرِ پخش (ریپل)", (pr) => {
      let next = pr;
      for (const id of withLinked(pr, ids)) next = rippleTrim(next, id, side, time);
      return next;
    });
  }

  function copyClips() {
    if (!selection.length) return;
    setClipsBoard(selection.map((id) => findClip(project, id)).filter((f): f is NonNullable<typeof f> => !!f).map((f) => ({ clip: f.clip, kind: f.track.kind })));
    setNotice(`${selection.length} قطعه کپی شد (Ctrl+V = چسباندن در سرِ پخش).`);
  }
  function pasteClips(prep?: (p: Project) => Project, label = "چسباندن") {
    if (!clipsBoard.length) return;
    const t0 = Math.min(...clipsBoard.map((x) => x.clip.at));
    apply(label, (pr0) => {
      const pr = prep ? prep(pr0) : pr0;
      let next = pr;
      const made: string[] = [];
      for (const { clip, kind } of clipsBoard) {
        const tr = next.tracks.find((t) => t.kind === kind && !t.locked && (!findClip(pr, clip.id) || findClip(pr, clip.id)?.track.id === t.id)) ?? next.tracks.find((t) => t.kind === kind && !t.locked);
        if (!tr) continue;
        const copy = { ...clip, id: `${clip.id}p${Math.random().toString(36).slice(2, 7)}`, at: time + (clip.at - t0), link: undefined } as AnyClip;
        const spot = freeSpot(tr, copy.at, clipLength(copy));
        if (spot === null) continue;
        copy.at = spot;
        made.push(copy.id);
        next = { ...next, tracks: next.tracks.map((t) => (t.id === tr.id ? { ...t, clips: [...t.clips, copy].sort((a, b) => a.at - b.at) } : t)) };
      }
      return next;
    });
  }

  async function importSubtitles(ref: string) {
    try {
      const lines = await videoApi.subtitles(storeId, ref);
      const src = project.tracks.flatMap((t) => t.clips).find((c): c is MediaClip => c.type === "media" && c.ref === ref && selection.includes(c.id));
      if (!src) return;
      const picked = lines.filter((l) => l.end > src.start && l.start < src.end);
      if (picked.length === 0) {
        setNotice("زیرنویسی برای بخشِ استفاده‌شدهٔ این قطعه نیست.");
        return;
      }
      apply("زیرنویس", (pr) => {
        const clips: Partial<TextClip>[] = picked.map((l) => {
          const a = Math.max(l.start, src.start);
          const b = Math.min(l.end, src.end);
          return { text: l.text, at: src.at + (a - src.start) / src.speed, duration: Math.max(0.3, (b - a) / src.speed), label: l.text.slice(0, 20) };
        });
        const tt = pr.tracks.find((t) => t.kind === "text" && !t.locked);
        return addTextClips(pr, tt?.id ?? null, clips);
      });
      setNotice(`${picked.length} خط زیرنویس به ترکِ متن آمد.`);
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  function insertCaptions(clips: Partial<TextClip>[]) {
    if (!clips.length) return;
    apply("زیرنویسِ خودکار", (pr) => {
      const cap = pr.tracks.find((t) => t.kind === "text" && t.caption);
      return addTextClips(pr, cap?.id ?? null, clips, { caption: true });
    });
    setNotice(`${clips.length} خط زیرنویس روی ترکِ «زیرنویس» آمد؛ هر خط را می‌شود ویرایش و سبکش را عوض کرد.`);
  }

  async function addBeatMarkers() {
    const c = selected && selected.clip.type === "media" ? selected.clip : null;
    if (!c) return;
    setBeatsBusy(true);
    try {
      const r = await fetchBeats(storeId, c.ref);
      const times = r.beats.filter((b) => b >= c.start && b <= c.end).map((b) => srcToTimeline(c, b));
      apply("نشانگرِ ضرب‌ها", (pr) => {
        let next = clearMarkers(pr, "beat");
        for (const t of times) next = addMarker(next, t, "", "beat");
        return next;
      });
      setNotice(`${times.length} ضرب علامت خورد${r.bpm ? ` (حدود ${Math.round(r.bpm)} ضرب در دقیقه)` : ""}. برش‌ها به این نشانگرها می‌چسبند.`);
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setBeatsBusy(false);
    }
  }

  function jlCut(kind: "J" | "L") {
    if (!selected || selected.clip.type !== "media") return;
    const r = jlCutOp(project, selected.clip.id, kind);
    if (!r.ok) {
      setNotice(r.message ?? "برش ممکن نشد.");
      return;
    }
    apply(kind === "J" ? "برش J" : "برش L", () => r.project);
    if (r.movedToTrack) setNotice("صدای درازشده با قطعهٔ همسایه‌اش روی یک ترک هم‌زمان می‌شد؛ به یک ترکِ صدای دیگر رفت.");
  }

  async function uploadVideo(file: File) {
    const body = new FormData();
    body.append("video", file);
    body.append("title", file.name);
    uploadRunner.begin();
    try {
      const { data } = await api.post(`/stores/${storeId}/videos/`, body);
      if (data.job_id) uploadRunner.track(data.job_id);
    } catch (err) {
      uploadRunner.fail(errorMessage(err));
    }
  }

  async function buildProxy(item: MediaItem) {
    setProxyBusy(item.ref);
    try {
      const r = await videoApi.proxy(storeId, item.ref);
      if (r.job_id) {
        proxyRunner.begin();
        proxyRunner.track(r.job_id);
      } else {
        setProxyBusy(null);
        await loadBin();
      }
    } catch (err) {
      setProxyBusy(null);
      setNotice(errorMessage(err));
    }
  }

  async function doRender(q: "draft" | "final", override?: Record<string, unknown>) {
    setRenderStarting(true);
    try {
      const id = await saveNow();
      if (!id) {
        setNotice("ذخیرهٔ پروژه نشد؛ رندر شروع نشد.");
        return;
      }
      await videoApi.render(storeId, id, q, { data: JSON.parse(saveRef.current.key), ...(override ? { export: override } : {}) });
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setRenderStarting(false);
    }
  }

  // ───────────── ابزارهای ویژه: LUT، مات، ردیاب، توالیِ تودرتو، مولتی‌کم، شکل و استیکر
  const loadLuts = useCallback(async () => {
    try {
      setLuts(await videoApi.luts(storeId));
    } catch {
      /* بعداً دوباره */
    }
  }, [storeId]);
  const loadMattes = useCallback(async () => {
    try {
      setMattes(await videoApi.mattes(storeId));
    } catch {
      /* بعداً دوباره */
    }
  }, [storeId]);
  useEffect(() => {
    void loadLuts();
    void loadMattes();
    void videoApi.matteStatus(storeId).then(setMatteStatus).catch(() => null);
    void videoApi.renderWhere(storeId).then(setWhere).catch(() => null);
  }, [storeId, loadLuts, loadMattes]);
  useEffect(() => {
    if (tab === "out") void videoApi.renderWhere(storeId).then(setWhere).catch(() => null);
    if (tab !== "pro") setPickRegion(false);
  }, [tab, storeId]);
  useEffect(() => {
    if (!selected || selected.clip.type !== "media" || selected.clip.mask?.shape !== "bezier") setEditingMask(false);
  }, [selected]);

  // LUT هایی که پروژه (و توالی‌هایش) به کار برده؛ متنشان یک بار خوانده می‌شود
  const usedLuts = useMemo(() => {
    const keys = new Set<string>();
    const visit = (tracks: Project["tracks"]) => tracks.forEach((t) => t.clips.forEach((c) => { if (isMedia(c) && c.lut) keys.add(c.lut.key); }));
    visit(root.tracks);
    Object.values(root.sequences ?? {}).forEach((q) => visit(q.tracks));
    return [...keys];
  }, [root]);
  const lutLoading = useRef(new Set<string>());
  useEffect(() => {
    for (const key of usedLuts) {
      if (lutData[key] || lutLoading.current.has(key)) continue;
      lutLoading.current.add(key);
      videoApi.lutText(storeId, key).then((txt) => setLutData((cur) => ({ ...cur, [key]: parseCube(txt) }))).catch(() => lutLoading.current.delete(key));
    }
  }, [usedLuts, lutData, storeId]);
  const matteMeta = useMemo(() => Object.fromEntries(mattes.map((m) => [m.key, { url: m.url, s0: m.s0 }])), [mattes]);

  async function importLut(file: File) {
    setLutBusy(true);
    try {
      const row = await videoApi.uploadLut(storeId, file);
      await loadLuts();
      setNotice(`LUT «${row.title}» (${row.size}³) وارد شد؛ قطعه‌ای را انتخاب و روی آن بزنید.`);
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setLutBusy(false);
    }
  }
  async function deleteLut(key: string) {
    try {
      await videoApi.deleteLut(storeId, key);
      const strip = (tracks: Project["tracks"]) => tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (isMedia(c) && c.lut?.key === key ? ({ ...c, lut: undefined } as MediaClip) : c)) }));
      applyRoot("حذفِ LUT", (r) => ({ ...r, tracks: strip(r.tracks), sequences: Object.fromEntries(Object.entries(r.sequences ?? {}).map(([k, q]) => [k, { ...q, tracks: strip(q.tracks) }])) }));
      await loadLuts();
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  const jobResult = async <T,>(id: number | null): Promise<T | null> => {
    if (id === null) return null;
    const { data } = await api.get<Job>(`/jobs/${id}/`);
    return (data.result as T | undefined) ?? null;
  };

  // ردیابی
  const trackJob = useRef<{ id: number | null; ref: string; size: [number, number]; region: { x: number; y: number; w: number; h: number } }>({ id: null, ref: "", size: [0, 0], region: { x: 0, y: 0, w: 0, h: 0 } });
  const trackRunner = useJobRunner(async () => {
    try {
      const r = await jobResult<TrackResult>(trackJob.current.id);
      if (!r || !r.samples?.length) throw new Error("مسیری برنگشت.");
      const n = (root.trackers?.length ?? 0) + 1;
      const t = trackerFromResult(`ردیاب ${n}`, trackJob.current.ref, trackJob.current.size, trackJob.current.region, r);
      applyRoot("ردیابِ تازه", (rt) => ({ ...rt, trackers: [...(rt.trackers ?? []), t] }));
      setNotice(`ردیاب ${n} ساخته شد (${r.samples.length} نمونه، ${r.engine.startsWith("node") ? "روی سرورِ پردازش" : "روی سرورِ سایت"})${r.lost_at !== null ? " — ردیابی در ثانیهٔ " + r.lost_at.toFixed(1) + " از دست رفت و همان‌جا تمام شد" : ""}. حالا چیزی را به آن وصل کنید.`);
    } catch (err) {
      setTrackErr(errorMessage(err));
    } finally {
      setTrackMsg(null);
    }
  });
  useEffect(() => {
    if (trackRunner.error) {
      setTrackErr(trackRunner.error);
      setTrackMsg(null);
    }
  }, [trackRunner.error]);

  async function startTrack(opts: { fps: number; seconds: number }) {
    const c = selected && isMedia(selected.clip) ? selected.clip : null;
    if (!c || c.kind !== "video" || !region) return;
    if (c.reverse || c.freeze) {
      setTrackErr("روی قطعهٔ وارونه یا فریمِ ثابت ردیابی ممکن نیست.");
      return;
    }
    const item = media[c.ref];
    const fa = project.format.width / project.format.height;
    const sa = item?.width && item?.height ? item.width / item.height : fa;
    const [ax, ay] = frameToSource(c, time, region.x, region.y, fa, sa);
    const [bx, by] = frameToSource(c, time, region.x + region.w, region.y + region.h, fa, sa);
    const reg = { x: Math.max(0, Math.min(ax, bx)), y: Math.max(0, Math.min(ay, by)), w: Math.max(0.02, Math.abs(bx - ax)), h: Math.max(0.02, Math.abs(by - ay)) };
    const s0 = Math.max(c.start, Math.min(c.end - 0.3, srcTimeAt(c, Math.max(c.at, Math.min(clipEnd(c), time)))));
    const s1 = Math.min(c.end, s0 + opts.seconds);
    setTrackErr(null);
    setTrackMsg("در حالِ ردیابی…");
    setPickRegion(false);
    try {
      trackRunner.begin();
      const r = await videoApi.track(storeId, { ref: c.ref, s0, s1, region: reg, fps: opts.fps });
      trackJob.current = { id: r.job_id, ref: c.ref, size: [item?.width ?? 0, item?.height ?? 0], region: reg };
      trackRunner.track(r.job_id);
    } catch (err) {
      trackRunner.fail(errorMessage(err));
      setTrackErr(errorMessage(err));
      setTrackMsg(null);
    }
  }
  function attachSelected(trackerId: string, mask: boolean) {
    if (!selected) return;
    const r = attachTo(project, { clipId: selected.clip.id, mask }, trackerId, time, aspectOf);
    if (r.message) setNotice(r.message);
    else apply(mask ? "اتصالِ ماسک به ردیاب" : "اتصال به ردیاب", () => r.project);
  }

  // مات (حذفِ پس‌زمینه)
  const matteJob = useRef<number | null>(null);
  const matteRunner = useJobRunner(async () => {
    try {
      const r = await jobResult<MatteRow>(matteJob.current);
      await loadMattes();
      if (r?.key && selected && isMedia(selected.clip)) {
        const id = selected.clip.id;
        apply("ماتِ حذفِ پس‌زمینه", (pr) => updateClip(pr, id, { matte: { key: r.key } }));
      }
      setNotice("ماتِ حذفِ پس‌زمینه ساخته و روی قطعه اعمال شد؛ برای دیدنِ تمیزیِ لبه‌ها «پیش‌نمایشِ دقیق» را بزنید.");
    } catch (err) {
      setMatteErr(errorMessage(err));
    } finally {
      setMatteMsg(null);
    }
  });
  useEffect(() => {
    if (matteRunner.error) {
      setMatteErr(matteRunner.error);
      setMatteMsg(null);
    }
  }, [matteRunner.error]);
  async function makeMatte(fps: number) {
    const c = selected && isMedia(selected.clip) ? selected.clip : null;
    if (!c || c.kind !== "video") return;
    setMatteErr(null);
    setMatteMsg("در حالِ ساختنِ مات روی سرورِ پردازش…");
    try {
      matteRunner.begin();
      const r = await videoApi.startMatte(storeId, { ref: c.ref, s0: c.start, s1: Math.min(c.end, c.start + (matteStatus?.max_seconds ?? 20)), fps });
      matteJob.current = r.job_id;
      matteRunner.track(r.job_id);
    } catch (err) {
      matteRunner.fail(errorMessage(err));
      setMatteErr(errorMessage(err));
      setMatteMsg(null);
    }
  }

  // مولتی‌کم
  const syncJob = useRef<{ id: number | null; labels: Record<string, string> }>({ id: null, labels: {} });
  const syncRunner = useJobRunner(async () => {
    try {
      const r = await jobResult<SyncResult>(syncJob.current.id);
      if (!r) throw new Error("جوابی نیامد.");
      setSyncRows(r.offsets.map((o) => ({ ref: o.ref, label: syncJob.current.labels[o.ref] ?? o.ref, offset: o.offset, confidence: o.confidence, ok: o.ok })));
    } catch (err) {
      setSyncErr(errorMessage(err));
    } finally {
      setSyncBusy(false);
    }
  });
  useEffect(() => {
    if (syncRunner.error) {
      setSyncErr(syncRunner.error);
      setSyncBusy(false);
    }
  }, [syncRunner.error]);
  const selectedVideos = (): MediaClip[] => {
    const seen = new Set<string>();
    const out: MediaClip[] = [];
    for (const id of selection) {
      const f = findClip(project, id);
      if (f && isMedia(f.clip) && f.clip.kind === "video" && !seqIdOf(f.clip) && !seen.has(f.clip.ref)) {
        seen.add(f.clip.ref);
        out.push(f.clip);
      }
    }
    return out;
  };
  async function syncAngles() {
    const vids = selectedVideos();
    if (vids.length < 2) return;
    setSyncErr(null);
    setSyncRows(null);
    setSyncBusy(true);
    try {
      syncRunner.begin();
      const r = await videoApi.syncAngles(storeId, vids.map((v) => v.ref));
      syncJob.current = { id: r.job_id, labels: Object.fromEntries(vids.map((v) => [v.ref, media[v.ref]?.title ?? v.label])) };
      syncRunner.track(r.job_id);
    } catch (err) {
      syncRunner.fail(errorMessage(err));
      setSyncErr(errorMessage(err));
      setSyncBusy(false);
    }
  }
  function makeMulticam(useSync: boolean) {
    const vids = selectedVideos();
    if (vids.length < 2) return;
    const angles: AngleSource[] = vids.map((v) => ({ ref: v.ref, label: (media[v.ref]?.title ?? v.label).slice(0, 30), duration: media[v.ref]?.duration || v.src || v.end, has_audio: !!(media[v.ref]?.has_audio ?? v.has_audio) }));
    const offsets = vids.map((v) => (useSync ? syncRows?.find((r) => r.ref === v.ref)?.offset ?? 0 : 0));
    const at = Math.min(...vids.map((v) => v.at));
    const gone = new Set(withLinked(project, selection));
    const base: Project = { ...project, tracks: project.tracks.map((t) => ({ ...t, clips: t.clips.filter((c) => !gone.has(c.id)) })) };
    const r = createMulticam(base, angles, offsets, at, Math.max(0, angles.findIndex((a) => a.has_audio)));
    if (!r) {
      setNotice("مولتی‌کم ساخته نشد.");
      return;
    }
    apply("ساختِ مولتی‌کم", () => r.project);
    setSelection([r.clipId]);
    setSyncRows(null);
    setNotice("مولتی‌کم ساخته شد؛ در تبِ «ابزارها» زاویه را انتخاب کنید یا با کلیدهای ۱ تا ۹ در حینِ پخش برش بزنید.");
  }
  const multicamSel = (() => {
    if (!selected || !isMedia(selected.clip)) return null;
    const sid = seqIdOf(selected.clip);
    const seq = sid ? root.sequences?.[sid] : undefined;
    return sid && seq?.multicam ? { sid, clip: selected.clip, info: seq.multicam } : null;
  })();
  function cutToAngle(angle: number) {
    if (!multicamSel) return;
    const tn = srcTimeAt(multicamSel.clip, Math.max(multicamSel.clip.at, Math.min(clipEnd(multicamSel.clip), time)));
    const r = setAngleAt(project, multicamSel.sid, tn, angle);
    if (r.message) setNotice(r.message);
    else apply(`برش به زاویهٔ ${angle + 1}`, () => r.project);
  }

  // توالیِ تودرتو
  function nestSelection() {
    const r = nestClips(project, selection, "توالیِ تودرتو");
    if (!r) return;
    apply("ساختِ توالیِ تودرتو", () => r.project);
    setSelection([r.clipId]);
    setNotice("توالیِ تودرتو ساخته شد؛ «باز کردن برای ویرایش» داخلش می‌برد.");
  }
  function openSeq(id: string) {
    setPlaying(false);
    setPath((p) => [...p, id]);
    setSelection([]);
    setTime(0);
    setExact(null);
  }
  function closeSeq() {
    setPlaying(false);
    setPath((p) => p.slice(0, -1));
    setSelection([]);
    setTime(0);
  }

  // قطعِ خودکار روی ضرب‌ها
  function beatCut(mode: "split" | "fit" | "snap", every: number) {
    const beats = beatTimes(project);
    if (!beats.length) {
      setNotice("اول ضرب‌ها را پیدا کنید.");
      return;
    }
    if (mode === "snap") {
      const r = beatSnap(project, beats);
      if (!r.snapped) setNotice("برشی نزدیکِ ضرب (تا ۰٫۲۵ ثانیه) پیدا نشد.");
      else {
        apply("چسباندنِ برش‌ها به ضرب", () => r.project);
        setNotice(`${r.snapped} برش به ضرب چسبید.`);
      }
      return;
    }
    if (!selection.length) {
      setNotice("اول قطعه(ها) را انتخاب کنید.");
      return;
    }
    if (mode === "split") {
      const r = beatSplit(project, selection, beats, every);
      if (!r.cuts) setNotice("ضربی داخلِ قطعهٔ انتخاب‌شده نیفتاد.");
      else {
        apply("برش روی ضرب‌ها", () => r.project);
        setNotice(`${r.cuts} برش روی ضرب‌ها خورد.`);
      }
    } else {
      const r = beatFit(project, selection, beats, every);
      if (!r.made) setNotice("جایی برای چیدنِ قطعه‌ها نبود (ضرب کم است یا قطعه‌ای از نوعِ صدا انتخاب شده).");
      else {
        apply("مونتاژِ روی ضرب", () => r.project);
        setNotice(`${r.made} قطعه روی بازه‌های بینِ ضرب‌ها نشست.`);
      }
    }
  }

  // شکل و استیکر: روی بالاترین ترکِ تصویر
  function placeOnTop(pr: Project, clip: MediaClip): Project {
    let q = pr;
    let tr = [...q.tracks].reverse().find((t) => t.kind === "video" && !t.locked);
    if (!tr || overlaps(tr, clip.at, clipLength(clip))) {
      q = addTrack(q, "video");
      tr = q.tracks.filter((t) => t.kind === "video").slice(-1)[0];
    }
    const tid = tr.id;
    return { ...q, tracks: q.tracks.map((t) => (t.id === tid ? { ...t, clips: [...t.clips, clip].sort((a, b) => a.at - b.at) } : t)) };
  }
  function overlayBox() {
    const bw = 0.4;
    return { width: bw, height: Math.min(0.9, (bw * project.format.width) / project.format.height), x: 0.3, y: 0.3 };
  }
  function addShape(kind: ShapeKind) {
    const box = overlayBox();
    const id = uid();
    const clip: MediaClip = {
      id, type: "media", ref: "shape", label: SHAPES.find((x) => x.key === kind)?.title ?? kind, kind: "image", at: time, start: 0, end: 3, src: 0, opacity: 1, ...box, y: Math.max(0, 0.5 - box.height / 2), volume: 1, speed: 1,
      fit: "stretch", fade_in: 0, fade_out: 0, audio_on: false, has_audio: false, effects: [], transition: null, shape: defaultShape(kind),
    };
    apply("شکل", (pr) => placeOnTop(pr, clip));
    setSelection([id]);
    setTab("clip");
  }
  function addSticker(item: MediaItem) {
    const box = overlayBox();
    const id = uid();
    const clip: MediaClip = { ...newMediaClip(item, time), id, end: 4, ...box, y: Math.max(0, 0.5 - box.height / 2), fit: "contain" };
    apply(`استیکر «${item.title}»`, (pr) => placeOnTop(pr, clip));
    setSelection([id]);
    setTab("clip");
  }

  const pickOverlay = pickRegion ? (
    <RegionOverlay rect={region} onRect={setRegion} />
  ) : editingMask && selected && isMedia(selected.clip) && selected.clip.mask?.shape === "bezier" ? (
    <BezierOverlay
      project={project} clip={selected.clip} time={time}
      onLive={(points) => { const c = selected.clip as MediaClip; live((pr) => updateClip(pr, c.id, { mask: { ...c.mask!, points } })); }}
      onEnd={(l) => hist.end(l)}
    />
  ) : undefined;

  // ───────────── کلیدهای میان‌بر
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return;
      if (t instanceof HTMLInputElement && !["range", "checkbox"].includes(t.type)) return;
      const ctrl = e.ctrlKey || e.metaKey;
      const rawKey = e.key;
      // روی صفحه‌کلیدِ فارسی هم «س» همان S است (کلیدِ فیزیکی)
      const k = latinKey(e);
      const lower = k.toLowerCase();
      if (rawKey === "?" || rawKey === "؟") { e.preventDefault(); setHelp((v) => !v); return; }
      if (ctrl && lower === "z") { e.preventDefault(); e.shiftKey ? hist.redo() : hist.undo(); return; }
      if (ctrl && lower === "y") { e.preventDefault(); hist.redo(); return; }
      if (ctrl && lower === "d" && selection.length) { e.preventDefault(); apply("تکرار", (pr) => duplicateClips(pr, selection)); return; }
      if (ctrl && e.shiftKey && lower === "c" && selected?.clip.type === "media") { e.preventDefault(); setClipboard(copyAttrs(selected.clip, ["transform", "color", "effects", "audio", "chroma", "blend"])); setNotice("ویژگی‌های قطعه کپی شد."); return; }
      if (ctrl && e.shiftKey && lower === "v") { e.preventDefault(); if (clipboard) apply("چسباندنِ ویژگی‌ها", (pr) => pasteAttrs(pr, selection, clipboard)); return; }
      if (ctrl && lower === "c") { e.preventDefault(); copyClips(); return; }
      if (ctrl && lower === "v") { e.preventDefault(); pasteClips(); return; }
      if (ctrl && lower === "a") { e.preventDefault(); setSelection(project.tracks.flatMap((tr) => tr.clips.map((c) => c.id))); return; }
      if (ctrl) return;
      if (k === " " || lower === "k") { e.preventDefault(); if (k === " " || playing) togglePlay(); else setPlaying(false); return; }
      if (lower === "l") { void engine.resume(); setRate((r) => (playing && r >= 1 && r < 4 ? r * 2 : 1)); setPlaying(true); return; }
      if (lower === "j") { void engine.resume(); setRate((r) => (playing && r <= -1 && r > -4 ? r * 2 : -1)); setPlaying(true); return; }
      if (e.altKey && (k === "ArrowLeft" || k === "ArrowRight")) { e.preventDefault(); nudge((k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 5 : 1)); return; }
      // «,» و «.» = جابه‌جاییِ فریم‌به‌فریمِ قطعهٔ انتخابی (Shift = ۱۰ فریم)؛ با Alt فقط لبهٔ شروعِ قطعه
      if ((e.code === "Comma" || e.code === "Period" || k === "," || k === "." || k === "<" || k === ">") && selection.length) {
        e.preventDefault();
        const back = e.code === "Comma" || k === "," || k === "<";
        const n = (back ? -1 : 1) * (e.shiftKey ? 10 : 1);
        apply(e.altKey ? "کوتاه‌کردنِ فریمیِ شروع" : "جابه‌جاییِ فریمی", (pr) => nudgeEdge(pr, selection, e.altKey ? "l" : "pos", n, project.format.fps || 30));
        return;
      }
      if (k === "ArrowLeft") { e.preventDefault(); e.shiftKey ? seek(time - 1) : step(-1); return; }
      if (k === "ArrowRight") { e.preventDefault(); e.shiftKey ? seek(time + 1) : step(1); return; }
      if (k === "ArrowUp" || k === "ArrowDown") {
        e.preventDefault();
        const pts = Array.from(new Set([0, ...project.tracks.flatMap((tr) => tr.clips.flatMap((c) => [c.at, clipEnd(c)])), ...(project.markers ?? []).map((m) => m.t)])).sort((a, b) => a - b);
        const next = k === "ArrowUp" ? [...pts].reverse().find((x) => x < time - 0.02) : pts.find((x) => x > time + 0.02);
        if (next !== undefined) seek(next);
        return;
      }
      if (k === "Home") { seek(0); return; }
      if (k === "End") { seek(totalRef.current); return; }
      if (k === "Escape") { setSelection([]); setExact(null); return; }
      if (lower === "s") { splitHere(); return; }
      if (k === "Delete" || k === "Backspace") { e.preventDefault(); removeSelected(e.shiftKey); return; }
      if (lower === "q") { trimToPlayhead("l"); return; }
      if (lower === "w") { trimToPlayhead("r"); return; }
      if (lower === "i") { apply("ورودی", (pr) => ({ ...pr, inout: { in: time, out: Math.max(pr.inout?.out ?? time + 5, time + 0.1) } })); return; }
      if (lower === "o") { apply("خروجی", (pr) => ({ ...pr, inout: { in: Math.min(pr.inout?.in ?? 0, time - 0.1 > 0 ? time - 0.1 : 0), out: time } })); return; }
      if (lower === "x" && e.altKey) { apply("پاک‌کردنِ ورودی/خروجی", (pr) => ({ ...pr, inout: null })); return; }
      if (lower === "m") { apply("نشانگر", (pr) => addMarker(pr, time, "")); return; }
      if (lower === "t") { newText(); return; }
      if (/^[1-9]$/.test(k) && multicamSel) { e.preventDefault(); cutToAngle(Number(k) - 1); return; }
      const toolKey: Record<string, Tool> = { v: "select", c: "razor", a: "trackfwd", b: "ripple", n: "roll", y: "slip", u: "slide", r: "rate" };
      if (toolKey[lower]) { setTool(toolKey[lower]); return; }
      if (k === "+" || k === "=") { setPx((v) => Math.min(400, v * 1.25)); return; }
      if (k === "-") { setPx((v) => Math.max(8, v / 1.25)); return; }
      if (k === "\\") { setPx(Math.max(8, Math.min(200, 700 / Math.max(5, totalRef.current)))); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

  const hasSubtitleSource = !!selected && selected.clip.type === "media" && selected.clip.kind === "video" && /^(video|edited|script):/.test(selected.clip.ref);
  const proxyNeeded = selected && selected.clip.type === "media" && media[selected.clip.ref]?.proxy === "needed";

  const tlButton = (label: string, title: string, onClick: () => void, extra: { disabled?: boolean; on?: boolean; test?: string; cls?: string } = {}) => (
    <button type="button" className={`ws-btn ${extra.cls ?? ""} ${extra.on ? "is-on" : ""}`} title={title} onClick={onClick} disabled={extra.disabled} data-testid={extra.test}>{label}</button>
  );

  const exactRange = () => {
    const io = project.inout;
    const a = io ? io.in : Math.max(0, time - 1);
    const b = io ? Math.min(io.out, a + 20) : Math.min(Math.max(totalRef.current, a + 1), a + 7);
    return { t0: a, t1: b };
  };

  const onGizmo = (id: string, patch: Partial<MediaClip> | Partial<TextClip>, final: boolean) => {
    if (final) apply("جابه‌جایی روی تصویر", (pr) => updateClip(pr, id, patch));
    else live((pr) => updateClip(pr, id, patch));
  };
  /** «برشِ قاب» (CropOverlay): پنجرهٔ برشِ منبع؛ هنگامِ کشیدن زنده، با رها شدن یک گامِ برگشت. extra = ویژگی‌های هم‌زمان (مثلاً fit) */
  const onReframe = (id: string, reframe: MediaClip["reframe"], final: boolean, extra?: Partial<MediaClip>) => {
    const patch: Partial<MediaClip> = { reframe, ...(extra ?? {}) };
    if (final) apply("برشِ قاب", (pr) => updateClip(pr, id, patch));
    else live((pr) => updateClip(pr, id, patch));
  };

  // ───────────── تشخیصِ برش‌ها (Scene edit detection)
  async function detectScenesOnSelection(sensitivity: "low" | "normal" | "high") {
    const c = selected && selected.clip.type === "media" && selected.clip.kind === "video" ? selected.clip : null;
    if (!c) { setNotice("اول یک ویدیو را روی تایم‌لاین انتخاب کنید."); return; }
    if (c.reverse || c.freeze || (c.ramp && c.ramp.length)) { setNotice("روی قطعهٔ وارونه، فریمِ ثابت یا دارای منحنیِ سرعت، برشِ خودکار نمی‌خورد."); return; }
    setNotice("در حالِ پیدا کردنِ برش‌ها…");
    try {
      const r = await detectScenes(storeId, c.ref, c.start, c.end, sensitivity);
      if (!r.cuts.length) { setNotice("برشی پیدا نشد؛ این قطعه یک نما است. اگر مطمئنید برش دارد «پرحساس» را امتحان کنید."); return; }
      const res = splitAtSourceCuts(project, c.id, r.cuts);
      if (!res.made) { setNotice("برش‌ها پیدا شد ولی جایی برای بریدن نبود."); return; }
      apply("تقسیم در برش‌های تشخیص‌داده‌شده", () => res.project);
      setNotice(`${res.made} برش پیدا و قطعه به ${res.made + 1} تکه تقسیم شد؛ هر تکه را می‌شود جدا ویرایش کرد (با «برگشت» همه برمی‌گردد).`);
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  // ───────────── زیرنویس SRT و نسخهٔ دومِ پروژه
  function exportSrtFile() {
    const cues = cuesOf(project);
    if (!cues.length) { setNotice("زیرنویسی روی تایم‌لاین نیست."); return; }
    const blob = new Blob(["\uFEFF", toSrt(cues)], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${(title || "captions").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 40)}.srt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 3000);
    setNotice(`${cues.length} خط زیرنویس در فایلِ SRT ذخیره شد.`);
  }
  function importSrtFile() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".srt,.txt,text/plain,application/x-subrip";
    input.onchange = () => {
      const f = input.files?.[0];
      if (!f) return;
      void f.text().then((text) => {
        const cues = parseSrt(text);
        if (!cues.length) { setNotice("در این فایل زیرنویسِ قابلِ خواندن پیدا نشد."); return; }
        insertCaptions(cues.map((c) => ({ text: c.text, at: c.start, duration: Math.max(0.3, c.end - c.start), label: c.text.slice(0, 20) })));
      });
    };
    input.click();
  }
  async function duplicateCurrentProject() {
    const id = await saveNow();
    if (!id) return;
    try {
      const res = await videoApi.createProject(storeId, `${title} (نسخه)`.slice(0, 200), JSON.parse(saveRef.current.key));
      setProjects((cur) => [res.project, ...cur]);
      await openProject(res.project.id);
      setNotice("نسخهٔ دوم ساخته شد و باز است؛ پروژهٔ اصلی همان‌طور مانده.");
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  // ───────────── «ثبتِ ویژگی‌ها»: منوی کامل، جستجوی ابزار و میان‌برهای قابل‌تغییر
  const km = useKeymap(ALL_FEATURES);
  const kmRef = useRef(km);
  kmRef.current = km;
  const apiRef = useRef<WorkspaceApi>(null as unknown as WorkspaceApi);
  const getApi = useCallback(() => apiRef.current, []);
  const flags: Record<FlagName, boolean> = { snap: snapOn, scopes: scopesOpen, volLine, autoRipple: rippleOn, crop: cropMode, menubar, loop: loopOn };
  function toggleFlag(f: FlagName) {
    if (f === "snap") setSnapOn((v) => !v);
    else if (f === "scopes") setScopesOpen((v) => !v);
    else if (f === "volLine") setVolLine((v) => !v);
    else if (f === "autoRipple") applyRoot("جابه‌جایی خودکارِ بعدی‌ها", (r) => ({ ...r, auto_ripple: r.auto_ripple === false ? undefined : false }));
    else if (f === "crop") setCropMode((v) => !v);
    else if (f === "loop") setLoopOn((v) => !v);
    else setMenubar((v) => !v);
  }
  /** یک دکمه یا کادرِ موجود در صفحه را (با data-testid یا انتخابگرِ CSS) می‌زند؛ تا ~۲ ثانیه منتظرِ آمدنش می‌ماند */
  function clickElement(target: string, inTab?: InspectorTab) {
    if (inTab) setTab(inTab);
    const css = target.startsWith("[") ? target : `[data-testid="${target}"]`;
    let tries = 0;
    const attempt = () => {
      const el = document.querySelector<HTMLElement>(css);
      if (el) {
        el.scrollIntoView({ block: "nearest" });
        if (el instanceof HTMLSelectElement) {
          el.focus();
          try { (el as HTMLSelectElement & { showPicker?: () => void }).showPicker?.(); } catch { /* مرورگر اجازه نداد */ }
        } else if (el instanceof HTMLInputElement && ["text", "number", "search"].includes(el.type)) {
          el.focus();
          el.select();
        } else el.click();
        return;
      }
      if (++tries < 16) window.setTimeout(attempt, 125);
      else setNotice("این بخش الان در دسترس نیست؛ شاید اول باید چیزی را انتخاب کنید.");
    };
    window.setTimeout(attempt, inTab ? 70 : 0);
  }
  function revealSection(t: InspectorTab, section?: string) {
    setTab(t);
    if (!section) return;
    for (const ms of [90, 280, 700]) window.setTimeout(() => window.dispatchEvent(new CustomEvent("nm-open-section", { detail: { testId: section } })), ms);
  }
  function shuttle(r: number) {
    void engine.resume();
    setRate((cur) => (playing && Math.sign(cur) === Math.sign(r) && Math.abs(cur) < 4 ? cur * 2 : r));
    setPlaying(true);
  }
  function gotoEdit(dir: -1 | 1) {
    const pts = Array.from(new Set([0, ...project.tracks.flatMap((tr) => tr.clips.flatMap((c) => [c.at, clipEnd(c)])), ...(project.markers ?? []).map((m) => m.t)])).sort((a, b) => a - b);
    const next = dir < 0 ? [...pts].reverse().find((x) => x < time - 0.02) : pts.find((x) => x > time + 0.02);
    if (next !== undefined) seek(next);
  }
  function copyAttributes() {
    if (selected?.clip.type !== "media") return;
    setClipboard(copyAttrs(selected.clip, ["transform", "color", "effects", "audio", "chroma", "blend"]));
    setNotice("ویژگی‌های قطعه کپی شد.");
  }
  function workspaceLayout(name: "edit" | "color" | "audio" | "graphics" | "export") {
    const titles = { edit: "تدوین", color: "رنگ", audio: "صدا", graphics: "گرافیک و زیرنویس", export: "خروجی" };
    setTab(({ edit: "clip", color: "color", audio: "audio", graphics: "text", export: "out" } as const)[name]);
    setScopesOpen(name === "color");
    if (name === "audio") setVolLine(true);
    setNotice(`چینشِ «${titles[name]}» آماده شد.`);
  }
  const wsApi: WorkspaceApi = {
    storeId, project, root, path, selection, selected, time, playing, fps: project.format.fps || 30, projectId, media, bin, tool, flags,
    canUndo: hist.canUndo, canRedo: hist.canRedo, history: { entries: hist.entries, index: hist.index }, hasClips, editorSettings,
    apply, applyRoot, live, end: hist.end, select: setSelection, undo: hist.undo, redo: hist.redo, jumpHistory: hist.jump,
    seek, togglePlay, step, setRate: shuttle, setTool, toggle: toggleFlag,
    zoom: (f) => setPx((v) => (f === "fit" ? Math.max(8, Math.min(200, 700 / Math.max(5, totalRef.current))) : Math.max(8, Math.min(400, v * f)))),
    setTab, reveal: revealSection, click: clickElement, notice: setNotice,
    openPanel: (id, props) => setPanel({ id, props }), closePanel: () => setPanel(null), activePanel: panel?.id ?? null, openSearch: () => setSearchOpen(true),
    op: {
      split: () => splitHere(),
      remove: removeSelected,
      nudge,
      trimToPlayhead,
      copy: copyClips,
      paste: pasteClips,
      jl: jlCut,
      newText,
      render: (q) => void doRender(q),
      openProject: (id) => void openProject(id),
      exactPreview: () => { setPlaying(false); setExact(exactRange()); },
      deleteProject: () => void deleteProject(),
      beats: () => void addBeatMarkers(),
      nest: nestSelection,
      closeSequence: closeSeq,
      uploadVideo: () => document.querySelector<HTMLElement>('[data-testid="bin-upload"]')?.click(),
      copyAttrs: copyAttributes,
      pasteAttrs: () => (clipboard ? apply("چسباندنِ ویژگی‌ها", (pr) => pasteAttrs(pr, selection, clipboard)) : setNotice("اول ویژگی‌های یک قطعه را کپی کنید.")),
      proxy: () => { if (selected?.clip.type === "media" && media[selected.clip.ref]) void buildProxy(media[selected.clip.ref]); },
      gotoEdit,
      workspace: workspaceLayout,
      pasteInsert: () => {
        if (!clipsBoard.length) { setNotice("اول چیزی را کپی کنید (Ctrl+C)."); return; }
        const span = spanOf(clipsBoard);
        const t0 = time;
        pasteClips((pr) => makeRoom(pr, t0, span), "چسباندنِ درج");
      },
      exportSrt: exportSrtFile,
      importSrt: importSrtFile,
      duplicateProject: () => void duplicateCurrentProject(),
      detectScenes: (sens) => void detectScenesOnSelection(sens),
      renderAs: (what) => {
        const io = project.inout && project.inout.out > project.inout.in + 0.05 ? { range: "inout" } : {};
        const t = Math.round(time * 100) / 100;
        const o: Record<string, unknown> = what === "range" ? { range: "inout" } : what === "gif" ? { format: "gif", ...io } : what === "audio" ? { format: "audio", ...io } : { format: "frame", frame_t: t };
        setTab("out");
        void doRender("final", o);
      },
      toggleAiDefault: () => {
        const next = !(editorSettings?.ai_default ?? true);
        void directorApi.saveSettings(storeId, { ai_default: next }).then((v) => {
          setEditorSettings({ ai_default: v.ai_default, draft_days: v.draft_days });
          setNotice(next ? "کمکِ هوش مصنوعی از این به بعد روشن شروع می‌شود (هر «بساز» چند درخواستِ کوچک به مدل می‌فرستد و از اعتبار کم می‌شود)." : "کمکِ هوش مصنوعی از این به بعد خاموش شروع می‌شود؛ فقط قالب‌های آماده کار می‌کنند و هزینه‌ای ندارد.");
        }).catch((err) => setNotice(errorMessage(err)));
      },
    },
    goDirector: onGoDirector ?? null,
  };
  apiRef.current = wsApi;
  const runFeature = useCallback((f: FeatureDef) => {
    const a = apiRef.current;
    const why = f.when ? f.when(a) : null;
    if (why) {
      a.notice(why);
      return;
    }
    pushRecent(f.id);
    try {
      const r = f.run(a);
      if (r && typeof (r as Promise<void>).catch === "function") (r as Promise<void>).catch((err) => a.notice(errorMessage(err)));
    } catch (err) {
      a.notice(errorMessage(err));
    }
  }, []);
  // میان‌برهای تازه و تغییرداده‌شده (کلیدِ فیزیکی ⇒ روی صفحه‌کلیدِ فارسی هم کار می‌کند). فاز capture تا پیش از کدِ قدیمی بیاید.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isKeyCapture()) return;
      const combo = comboOf(e);
      if (!combo) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest?.(".rg-panel, .rg-pal, .sq-modal")) return;
      const m = kmRef.current;
      const f = m.byCombo.get(combo);
      if (typingTarget(e.target) && !f?.inInputs) return;
      if (!f) {
        if (m.suppressed.has(combo)) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
        return;
      }
      e.preventDefault();
      e.stopImmediatePropagation();
      runFeature(f);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [runFeature]);

  return (
    <Workspace
      testId="video-workspace"
      title="فضای کارِ دستیِ ویدیو"
      actions={
        <>
          {uploadRunner.running && <span className="ws-muted"><Spinner size={12} /> {uploadRunner.job?.current_step_label || "در حالِ بررسی…"}</span>}
          {proxyRunner.running && <span className="ws-muted"><Spinner size={12} /> پیش‌نمایشِ سبک…</span>}
          <Badge tone={saving === "error" ? "bad" : "neutral"}>{saving === "saving" ? "ذخیره…" : saving === "saved" ? "ذخیره شد" : "پروژه"}</Badge>
          <button type="button" className="ws-btn" onClick={() => setSearchOpen(true)} title="هر ابزار را با نامِ فارسی یا انگلیسی پیدا کنید (Ctrl+K)" data-testid="open-search">جستجوی ابزار</button>
          <button type="button" className={`ws-btn ${menubar ? "is-on" : ""}`} onClick={() => toggleFlag("menubar")} aria-pressed={menubar} title="منوی کاملِ همهٔ ابزارها: پرونده، ویرایش، کلیپ، سکانس، نشانگر، گرافیک، رنگ، صدا…" data-testid="toggle-menubar">منوی کامل</button>
          <button type="button" className="ws-btn" onClick={() => setHelp(true)} title="راهنمای همهٔ میان‌برها (؟)" data-testid="open-shortcuts">؟ میان‌برها</button>
        </>
      }
    >
      {notice && (
        <div className="px-3 py-1 text-xs" style={{ color: "var(--warn)", background: "var(--warn-soft)" }} dir="rtl" data-testid="ws-notice">
          {notice} <button type="button" className="ws-link" onClick={() => setNotice(null)}>×</button>
        </div>
      )}
      {menubar && <MenuBar features={ALL_FEATURES} km={km} getApi={getApi} run={runFeature} onSearch={() => setSearchOpen(true)} />}
      <div className="vw-grid" dir="ltr">
        <Bin bin={bin} loading={binLoading} onAdd={(it) => addFromBin(it)} onUpload={(f) => void uploadVideo(f)} onProxy={(it) => void buildProxy(it)} proxyBusy={proxyBusy} storeId={storeId} onGoSound={() => setTab("audio")} />
        <Monitor
          ref={monitor}
          project={project} media={media} time={time} playing={playing} rate={rate} selection={selection} looks={looks} compare={compare} engine={engine} duckSpans={duckSpans}
          luts={lutData} matteMeta={matteMeta} pickOverlay={pickOverlay}
          onTime={setTime} onEnded={() => { if (loopRef.current) { setTime(project.inout?.in ?? 0); setPlaying(true); } else { setPlaying(false); setTime(totalRef.current); } }}
          onSeek={seek} onPlay={togglePlay} onStep={step}
          onRate={(r) => { void engine.resume(); setRate(r); setPlaying(true); }}
          onGizmo={onGizmo}
          onReframe={onReframe} cropMode={cropMode} onCropMode={setCropMode} storeId={storeId} safeZones={cat?.safe_zones}
          onFrame={() => { if (scopesOpen) setScopeVer((v) => v + 1); }}
          selectedProxyHint={proxyNeeded ? <span className="vw-proxy-note">این قطعه سنگین است؛ در «رسانه‌ها» پیش‌نمایشِ سبک بسازید</span> : null}
          badge={<Badge tone={exact ? "ok" : "neutral"}>{exact ? "پیش‌نمایشِ دقیق (سرور)" : "پیش‌نمایشِ فوری (تقریبی)"}</Badge>}
          extraTransport={
            <>
              <button type="button" className="ws-btn" onClick={() => { setPlaying(false); setExact(exactRange()); }} data-testid="exact-preview" title="همان رندرِ نهایی برای چند ثانیه با کیفیتِ پایین؛ برای چیزهایی که مرورگر دقیق نشان نمی‌دهد (کلیدِ رنگی، گذارها، ثابت‌کردن، منحنیِ سرعت…)">
                پیش‌نمایشِ دقیقِ این بازه
              </button>
              <button type="button" className={`ws-btn ${scopesOpen ? "is-on" : ""}`} onClick={() => setScopesOpen((v) => !v)} data-testid="toggle-scopes" title="موج، برداری و هیستوگرام روی فریمِ زیرِ سرِ پخش">اسکوپ‌ها</button>
            </>
          }
          overlay={exact ? (
            <div className="vw-exact" data-testid="exact-overlay">
              <ExactPreview storeId={storeId} projectId={projectId} getData={() => toApi(root)} t0={exact.t0} t1={exact.t1} ensureSaved={saveNow} onClose={() => setExact(null)} />
            </div>
          ) : undefined}
          footer={scopesOpen ? <div className="vw-scopes" data-testid="scopes"><Scopes getFrame={() => monitor.current?.getFrame() ?? null} version={scopeVer} /></div> : undefined}
        />
        <Inspector
          storeId={storeId} project={project} selection={selection} selected={selected} playhead={time} tools={tools} media={media} edit={edit} cat={cat} looks={looks}
          tab={tab} onTab={setTab}
          title={title} onTitle={setTitle} check={check} saving={saving} projects={projects} projectId={projectId}
          onOpenProject={(id) => void openProject(id)} onDeleteProject={() => void deleteProject()}
          engine={engine} thumbSource={() => monitor.current?.getCanvas() ?? null} onCompare={(on) => setCompare(on ? primaryId : null)}
          hasClipboard={!!clipboard}
          onCopyAttrs={(groups: AttrGroup[]) => { if (selected?.clip.type === "media") { setClipboard(copyAttrs(selected.clip, groups)); setNotice("ویژگی‌ها کپی شد؛ قطعه‌های دیگر را انتخاب و «چسباندن» بزنید."); } }}
          onPasteAttrs={() => clipboard && apply("چسباندنِ ویژگی‌ها", (pr) => pasteAttrs(pr, selection, clipboard))}
          onExtractAudio={() => selected && apply("جدا کردنِ صدا", (pr) => extractAudio(pr, selected.clip.id))}
          onUnlink={() => apply("قطعِ پیوند", (pr) => unlinkClips(pr, selection))}
          onFreeze={() => selected && apply("فریمِ ثابت", (pr) => freezeFrameAt(pr, selected.clip.id, time))}
          onJLCut={jlCut} linked={linkedSel}
          onRender={doRender} renderBusy={renderStarting}
          onSubtitles={(r) => void importSubtitles(r)} hasSubtitleSource={hasSubtitleSource}
          onInsertCaptions={insertCaptions} onNotice={setNotice} onBeats={() => void addBeatMarkers()} beatsBusy={beatsBusy}
          onEditMask={setEditingMask} editingMask={editingMask} exportWhere={where}
          sound={{ root, applyRoot, nested: path.length > 0, bin, onBinChanged: () => void loadBin(), onNotice: setNotice }}
          onCropMode={setCropMode} cropOn={cropMode}
          pro={{
            project, root, path, selection, selected, playhead: time, media, bin, edit,
            onAddShape: addShape, onAddMedia: (it) => addFromBin(it),
            onNest: nestSelection, onOpenSeq: openSeq, onCloseSeq: closeSeq,
            onUnnest: () => { if (selected) { const r = unnestClip(project, selected.clip.id); if (r.message) setNotice(r.message); else { apply("بازکردنِ توالی", () => r.project); setSelection([]); } } },
            syncBusy, syncRows, syncError: syncErr, onSync: () => void syncAngles(), onCreateMulticam: makeMulticam,
            onAngle: cutToAngle,
            onRemoveCut: (i) => multicamSel && apply("حذفِ برشِ مولتی‌کم", (pr) => removeCutAt(pr, multicamSel.sid, i)),
            onMulticamAudio: (a) => multicamSel && apply("صدای مولتی‌کم", (pr) => setMulticamAudio(pr, multicamSel.sid, a)),
            onBeats: () => void addBeatMarkers(), beatsBusy, onBeatCut: beatCut,
            pickRegion, region, onPickRegion: (on) => { setPickRegion(on); if (on) setRegion(null); },
            trackBusy: trackMsg, trackError: trackErr, onTrack: (o) => void startTrack(o),
            onAttach: attachSelected,
            onDetach: (mask) => selected && apply("جدا کردن از ردیاب", (pr) => detach(pr, selected.clip.id, mask)),
            onDeleteTracker: (id) => applyRoot("حذفِ ردیاب", (r) => ({ ...r, trackers: (r.trackers ?? []).filter((t) => t.id !== id) })),
            luts, lutBusy, onImportLut: (f) => void importLut(f), onDeleteLut: (k) => void deleteLut(k),
            matteStatus, mattes, matteBusy: matteMsg, matteError: matteErr, onMakeMatte: (fps) => void makeMatte(fps),
            onDeleteMatte: (k) => { void videoApi.deleteMatte(storeId, k).then(loadMattes).catch((err) => setNotice(errorMessage(err))); },
          }}
        />
        <div className="vw-timeline" dir="rtl">
          {ready && !hasClips && (
            <QuickStart
              formatKey={project.format.preset}
              onFormat={(key) => { const f = FORMATS.find((x) => x.key === key); if (f) apply("قابِ پروژه", (pr) => ({ ...pr, format: { ...pr.format, width: f.width, height: f.height, preset: f.key } })); }}
              onDirector={onGoDirector}
              onAdd={() => setNotice("ویدیو یا عکس را از «رسانه‌ها» (ستونِ سمتِ چپ) بکشید روی تایم‌لاین، یا روی آن دوبار کلیک کنید. فیلمِ تازه را هم با «+ آپلودِ ویدیوی تازه» همان‌جا بیاورید.")}
            />
          )}
          <div className="tl-toolbar" data-testid="tl-toolbar">
            {tlButton("↶", "برگشت (Ctrl+Z)", hist.undo, { disabled: !hist.canUndo, test: "tl-undo" })}
            {tlButton("↷", "جلو (Ctrl+Y)", hist.redo, { disabled: !hist.canRedo, test: "tl-redo" })}
            <span className="ws-sep" />
            {TOOLS.map((tt) => tlButton(tt.label, tt.title, () => setTool(tt.key), { on: tool === tt.key, cls: "tool", test: `tool-${tt.key}` }))}
            <span className="ws-sep" />
            {tlButton("⇥ بعدی‌ها جلو بروند", "جابه‌جایی خودکارِ بعدی‌ها: وقتی قطعه‌ای را کند می‌کنید (یا سرعت/منحنی/فریمِ ثابت) و دراز می‌شود، قطعه‌های بعدیِ همان ترک و صدای پیوندی‌شان خودکار جلو می‌روند (مثلِ ریپل). کوتاه‌کردن چیزی را عقب نمی‌کشد.", () => applyRoot("جابه‌جایی خودکارِ بعدی‌ها", (r) => ({ ...r, auto_ripple: r.auto_ripple === false ? undefined : false })), { on: rippleOn, test: "tl-auto-ripple" })}
            {tlButton("✂ تقسیم (S)", "تقسیم در سرِ پخش (S)؛ روی همهٔ ترک‌ها: Ctrl+Shift+K", () => splitHere(), { disabled: !hasClips, test: "tl-split" })}
            {tlButton("حذف", "حذف (Delete)", () => removeSelected(false), { disabled: !selection.length, test: "tl-delete" })}
            {tlButton("حذفِ بی‌فاصله", "حذف و بستنِ جا (Shift+Delete)", () => removeSelected(true), { disabled: !selection.length, test: "tl-ripple" })}
            {tlButton("تکرار", "کپی پشتِ قطعه (Ctrl+D؛ Alt+کشیدن هم نسخه می‌سازد)", () => selection.length && apply("تکرار", (pr) => duplicateClips(pr, selection)), { disabled: !selection.length })}
            {tlButton("کوتاه تا سرِ پخش", "ریپلِ لبهٔ چپ تا سرِ پخش (Q) — لبهٔ راست (W)", () => trimToPlayhead("l"), { disabled: !hasClips })}
            {tlButton("❄ فریمِ ثابت", "فریمِ سرِ پخش را نگه دار", () => selected && apply("فریمِ ثابت", (pr) => freezeFrameAt(pr, selected.clip.id, time)), { disabled: !selected || selected.clip.type !== "media" || selected.clip.kind !== "video" })}
            <span className="ws-sep" />
            {tlButton("🧲", "چسبیدن به لبه‌ها، نشانگرها و سرِ پخش", () => setSnapOn((v) => !v), { on: snapOn, test: "tl-snap" })}
            {tlButton("خط بلندی", "خطِ زردِ بلندیِ صدا روی قطعه‌ها: بالا/پایین بکشید تا بلندی عوض شود؛ دو بار زدن روی خط = کلیدفریم، دو بار زدن روی نقطه = حذف. برای قطعهٔ انتخاب‌شده همیشه دیده می‌شود؛ برای بقیه روی ترکِ صدا همیشه و روی تصویر فقط اگر بلندی‌اش تغییر کرده", () => setVolLine((v) => !v), { on: volLine, test: "tl-vol-toggle" })}
            {tlButton("−", "کوچک‌نمایی (-)", () => setPx((v) => Math.max(8, v / 1.25)), { test: "tl-zoom-out" })}
            {tlButton("+", "بزرگ‌نمایی (+)", () => setPx((v) => Math.min(400, v * 1.25)), { test: "tl-zoom-in" })}
            {tlButton("جا شدن", "کلِ پروژه در قاب (\\)", () => setPx(Math.max(8, Math.min(200, 700 / Math.max(5, totalRef.current)))))}
            <span className="ws-sep" />
            {tlButton("◆ نشانگر (M)", "نشانگر در سرِ پخش", () => apply("نشانگر", (pr) => addMarker(pr, time, "")), { test: "tl-marker" })}
            {tlButton("[ I", "ورودیِ بازه (I)", () => apply("ورودی", (pr) => ({ ...pr, inout: { in: time, out: Math.max(pr.inout?.out ?? time + 5, time + 0.1) } })), { test: "tl-in" })}
            {tlButton("O ]", "خروجیِ بازه (O)", () => apply("خروجی", (pr) => ({ ...pr, inout: { in: Math.min(pr.inout?.in ?? 0, Math.max(0, time - 0.1)), out: time } })), { test: "tl-out" })}
            {project.inout && tlButton("برداشتنِ بازه", "بازهٔ ورودی–خروجی از همهٔ ترک‌ها برداشته و جا بسته شود", () => apply("برداشتنِ بازه", (pr) => liftRange(pr, pr.inout!.in, pr.inout!.out, true)), { test: "tl-lift" })}
            <span className="ws-sep" />
            {tlButton("+ تصویر", "ترکِ تصویر", () => apply("ترکِ تصویر", (pr) => addTrack(pr, "video")), { test: "tl-add-video" })}
            {tlButton("+ صدا", "ترکِ صدا", () => apply("ترکِ صدا", (pr) => addTrack(pr, "audio")), { test: "tl-add-audio" })}
            {tlButton("+ ترکِ متن", "ترکِ متن", () => apply("ترکِ متن", (pr) => addTrack(pr, "text")), { test: "tl-add-text-track" })}
            {tlButton("T+ متن", "متنِ تازه در سرِ پخش (T)", () => newText(), { test: "tl-add-text" })}
            {tlButton("جدا کردنِ صدا از تصویر", "صدای قطعهٔ ویدیوی انتخاب‌شده روی ترکِ صدا می‌رود و به تصویر «پیوند» می‌ماند؛ بعد می‌توانید صدا را زودتر یا دیرتر از تصویر شروع کنید (J-cut / L-cut)", () => selected && apply("جدا کردنِ صدا", (pr) => extractAudio(pr, selected.clip.id)), { disabled: !selected || selected.clip.type !== "media" || selected.clip.kind !== "video" || !selected.clip.has_audio || !selected.clip.audio_on, test: "tl-extract-audio" })}
            {tlButton("قطعِ پیوند", "پیوندِ صدا و تصویرِ انتخاب‌شده برداشته شود تا هر کدام مستقل جابه‌جا شوند", () => apply("قطعِ پیوند", (pr) => unlinkClips(pr, selection)), { disabled: !linkedSel, test: "tl-unlink" })}
            {selection.length > 1 && tlButton("پیوند", "قطعه‌های انتخاب‌شده با هم پیوند شوند و با هم جابه‌جا شوند", () => apply("پیوند", (pr) => linkClips(pr, selection)), { test: "tl-link" })}
          </div>
          <TrimBar
            project={project} selection={selection} fps={project.format.fps}
            onApply={apply} onSeek={seek} onSplit={() => splitHere()} onRemove={() => removeSelected(true)}
          />
          <TimelineView
            project={project} selection={selection} playhead={time} px={px} snapOn={snapOn} tool={tool} storeId={storeId} media={media} fps={project.format.fps} volLine={volLine}
            onProject={(p, liveDrag, base) => (liveDrag ? hist.live((r) => through(r, () => p, base)) : hist.apply("ویرایش", (r) => through(r, () => p, base)))}
            onCommit={(l) => hist.end(l)}
            onSelect={(ids) => { setSelection(ids); if (ids.length === 1) { const f = findClip(project, ids[0]); if (f?.clip.type === "text") setTab("text"); else if (tab === "text") setTab("clip"); } }}
            onSeek={seek}
            onDropRef={(trackId, ref, at) => { const it = media[ref]; if (it) addFromBin(it, trackId, at); }}
            onTrack={(id, patch) => apply("ترک", (pr) => updateTrack(pr, id, patch))}
            onRemoveTrack={(id) => apply("حذفِ ترک", (pr) => removeTrack(pr, id))}
            onRazor={(id, t) => apply("برش با تیغه", (pr) => splitMany(pr, withLinked(pr, [id]), t))}
            onTrackForward={(t) => setSelection(project.tracks.flatMap((tr) => (tr.locked ? [] : tr.clips.filter((c) => clipEnd(c) > t).map((c) => c.id))))}
            onMarkerClick={(id, alt) => { const m = (project.markers ?? []).find((x) => x.id === id); if (alt) apply("حذفِ نشانگر", (pr) => removeMarker(pr, id)); else if (m) seek(m.t); }}
            onInOut={(a, b) => apply("بازهٔ ورودی/خروجی", (pr) => ({ ...pr, inout: { in: a, out: b } }))}
            onKeyPick={(id, ch: KfChannel, t) => { setSelection([id]); const f = findClip(project, id); if (f) seek(f.clip.at + t); setTab("clip"); void ch; }}
          />
        </div>
      </div>
      {help && <ShortcutSheet onClose={() => setHelp(false)} />}
      {searchOpen && <CommandPalette features={ALL_FEATURES} km={km} getApi={getApi} run={runFeature} onClose={() => setSearchOpen(false)} />}
      <PanelHost panels={ALL_PANELS} active={panel} api={wsApi} onClose={() => setPanel(null)} />
    </Workspace>
  );
}

// برای تایپ‌اسکریپت: AnyClip/clipEnd در جاهای دیگر استفاده می‌شوند
export type { AnyClip };
export { clipEnd };
