import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import Workspace from "../../../../components/Workspace";
import { Badge, Spinner } from "../../../../components/ui";
import { useHistory } from "../../../../hooks/useHistory";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { ToolInfo } from "../../ToolPicker";
import type { Bin as BinData, Catalogue, Check, MediaItem, ProjectRow } from "../api";
import { videoApi } from "../api";
import { AudioEngine } from "./AudioEngine";
import Bin from "./Bin";
import type { LookDef } from "./color";
import ExactPreview from "./ExactPreview";
import Inspector, { InspectorTab } from "./Inspector";
import { KfChannel } from "./keyframes";
import { fetchBeats, srcToTimeline, useDuckSpans } from "./mediaAnalysis";
import Monitor, { MonitorHandle } from "./Monitor";
import {
  AnyClip, AttrClip, AttrGroup, MediaClip, Project, TextClip, addMarker, addMedia, addText, addTextClips, addTrack, clearMarkers, clipEnd, clipLength, copyAttrs,
  deleteClips, duplicateClips, emptyProject, extractAudio, findClip, freeSpot, freezeFrameAt, fromApi, isMedia, linkClips, liftRange, moveClips, pasteAttrs, projectLength,
  removeMarker, removeTrack, rippleTrim, splitAt, toApi, trimEnd, trimStart, uid, unlinkClips, updateClip, updateTrack, withLinked,
} from "./model";
import Scopes from "./Scopes";
import TimelineView, { Tool } from "./TimelineView";
import "./workspace.css";

type Props = {
  storeId: string;
  tools: ToolInfo[];
  /** ویدیویی که با «ویرایشِ دستی» از فهرست آمده: پروژهٔ تازه با همین قطعه شروع می‌شود */
  startRef?: string | null;
  onStartConsumed?: () => void;
};

const TOOLS: { key: Tool; label: string; title: string }[] = [
  { key: "select", label: "V", title: "انتخاب (V)" },
  { key: "razor", label: "✂ C", title: "تیغه: روی قطعه کلیک کنید تا همان‌جا بریده شود (C)" },
  { key: "trackfwd", label: "A", title: "انتخابِ همهٔ قطعه‌ها از این نقطه به جلو (A)" },
  { key: "ripple", label: "B", title: "ریپل: لبه را ببرید، بقیه جلو/عقب می‌آیند (B)" },
  { key: "roll", label: "N", title: "رول: برشِ بینِ دو قطعه را جابه‌جا کنید (N)" },
  { key: "slip", label: "Y", title: "اسلیپ: همان طول، بازهٔ منبع عوض می‌شود (Y)" },
  { key: "slide", label: "U", title: "اسلاید: قطعه می‌لغزد و همسایه‌ها جبران می‌کنند (U)" },
  { key: "rate", label: "R", title: "تغییرِ سرعت با کشیدنِ لبه (R)" },
];

export default function VideoWorkspace({ storeId, tools, startRef, onStartConsumed }: Props) {
  const hist = useHistory<Project>(emptyProject());
  const project = hist.state;
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
    for (const list of bin ? [bin.videos, bin.audio, bin.images] : []) for (const it of list) m[it.ref] = it;
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
  const dataKey = useMemo(() => JSON.stringify(toApi(project)), [project]);
  const hasClips = project.tracks.some((t) => t.clips.length > 0);
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
  const live = (fn: (p: Project) => Project) => hist.live(fn);
  const apply = (label: string, fn: (p: Project) => Project) => hist.apply(label, fn);
  const edit = { live, end: hist.end, apply };
  const linkedSel = !!selected && selected.clip.type === "media" && !!selected.clip.link && project.tracks.flatMap((t) => t.clips).filter((c) => isMedia(c) && c.link === (selected.clip as MediaClip).link).length > 1;

  function trackFor(kind: "video" | "audio" | "text") {
    return project.tracks.find((t) => t.kind === kind && !t.locked);
  }

  function addFromBin(item: MediaItem, trackId?: string, at?: number) {
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
      if (selection.length) {
        let next = pr;
        for (const id of withLinked(pr, selection)) next = splitAt(next, id, t);
        return next;
      }
      let next = pr;
      for (const tr of pr.tracks) if (!tr.locked) for (const c of tr.clips) next = splitAt(next, c.id, t);
      return next;
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
  function pasteClips() {
    if (!clipsBoard.length) return;
    const t0 = Math.min(...clipsBoard.map((x) => x.clip.at));
    apply("چسباندن", (pr) => {
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
    if (!selected || selected.clip.type !== "media" || !selected.clip.link) return;
    const link = selected.clip.link;
    const partner = project.tracks.flatMap((t) => t.clips).find((c): c is MediaClip => isMedia(c) && c.link === link && c.kind === "audio");
    if (!partner) {
      setNotice("برای J/L-cut اول صدا را از تصویر جدا کنید.");
      return;
    }
    const next = kind === "J" ? trimStart(project, partner.id, partner.at - 0.5) : trimEnd(project, partner.id, clipEnd(partner) + 0.5);
    if (JSON.stringify(findClip(next, partner.id)?.clip) === JSON.stringify(partner)) {
      setNotice(kind === "J" ? "صدا پیش از این نقطه چیزی در منبع ندارد؛ برای برش J قطعه باید از وسطِ منبع شروع شده باشد." : "منبع بعد از این نقطه صدایی ندارد؛ برای برش L قطعه باید پیش از پایانِ منبع تمام شده باشد.");
      return;
    }
    apply(kind === "J" ? "برش J" : "برش L", () => next);
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

  async function doRender(q: "draft" | "final") {
    setRenderStarting(true);
    try {
      const id = await saveNow();
      if (!id) {
        setNotice("ذخیرهٔ پروژه نشد؛ رندر شروع نشد.");
        return;
      }
      await videoApi.render(storeId, id, q, { data: JSON.parse(saveRef.current.key) });
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setRenderStarting(false);
    }
  }

  // ───────────── کلیدهای میان‌بر
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return;
      if (t instanceof HTMLInputElement && !["range", "checkbox"].includes(t.type)) return;
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key;
      const lower = k.toLowerCase();
      if (ctrl && lower === "z") { e.preventDefault(); e.shiftKey ? hist.redo() : hist.undo(); return; }
      if (ctrl && lower === "y") { e.preventDefault(); hist.redo(); return; }
      if (ctrl && lower === "k") { e.preventDefault(); splitHere(); return; }
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
    if (final) hist.apply("جابه‌جایی روی تصویر", (pr) => updateClip(pr, id, patch));
    else hist.live((pr) => updateClip(pr, id, patch));
  };

  return (
    <Workspace
      testId="video-workspace"
      title="فضای کارِ دستیِ ویدیو"
      actions={
        <>
          {uploadRunner.running && <span className="ws-muted"><Spinner size={12} /> {uploadRunner.job?.current_step_label || "در حالِ بررسی…"}</span>}
          {proxyRunner.running && <span className="ws-muted"><Spinner size={12} /> پیش‌نمایشِ سبک…</span>}
          <Badge tone={saving === "error" ? "bad" : "neutral"}>{saving === "saving" ? "ذخیره…" : saving === "saved" ? "ذخیره شد" : "پروژه"}</Badge>
        </>
      }
    >
      {notice && (
        <div className="px-3 py-1 text-xs" style={{ color: "var(--warn)", background: "var(--warn-soft)" }} dir="rtl" data-testid="ws-notice">
          {notice} <button type="button" className="ws-link" onClick={() => setNotice(null)}>×</button>
        </div>
      )}
      <div className="vw-grid" dir="ltr">
        <Bin bin={bin} loading={binLoading} onAdd={(it) => addFromBin(it)} onUpload={(f) => void uploadVideo(f)} onProxy={(it) => void buildProxy(it)} proxyBusy={proxyBusy} />
        <Monitor
          ref={monitor}
          project={project} media={media} time={time} playing={playing} rate={rate} selection={selection} looks={looks} compare={compare} engine={engine} duckSpans={duckSpans}
          onTime={setTime} onEnded={() => { setPlaying(false); setTime(totalRef.current); }}
          onSeek={seek} onPlay={togglePlay} onStep={step}
          onRate={(r) => { void engine.resume(); setRate(r); setPlaying(true); }}
          onGizmo={onGizmo}
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
              <ExactPreview storeId={storeId} projectId={projectId} getData={() => toApi(project)} t0={exact.t0} t1={exact.t1} ensureSaved={saveNow} onClose={() => setExact(null)} />
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
        />
        <div className="vw-timeline" dir="rtl">
          <div className="tl-toolbar" data-testid="tl-toolbar">
            {tlButton("↶", "برگشت (Ctrl+Z)", hist.undo, { disabled: !hist.canUndo, test: "tl-undo" })}
            {tlButton("↷", "جلو (Ctrl+Y)", hist.redo, { disabled: !hist.canRedo, test: "tl-redo" })}
            <span className="ws-sep" />
            {TOOLS.map((tt) => tlButton(tt.label, tt.title, () => setTool(tt.key), { on: tool === tt.key, cls: "tool", test: `tool-${tt.key}` }))}
            <span className="ws-sep" />
            {tlButton("✂ تقسیم (S)", "تقسیم در سرِ پخش (S یا Ctrl+K)", () => splitHere(), { disabled: !hasClips, test: "tl-split" })}
            {tlButton("حذف", "حذف (Delete)", () => removeSelected(false), { disabled: !selection.length, test: "tl-delete" })}
            {tlButton("حذفِ بی‌فاصله", "حذف و بستنِ جا (Shift+Delete)", () => removeSelected(true), { disabled: !selection.length, test: "tl-ripple" })}
            {tlButton("تکرار", "کپی پشتِ قطعه (Ctrl+D؛ Alt+کشیدن هم نسخه می‌سازد)", () => selection.length && apply("تکرار", (pr) => duplicateClips(pr, selection)), { disabled: !selection.length })}
            {tlButton("کوتاه تا سرِ پخش", "ریپلِ لبهٔ چپ تا سرِ پخش (Q) — لبهٔ راست (W)", () => trimToPlayhead("l"), { disabled: !hasClips })}
            {tlButton("❄ فریمِ ثابت", "فریمِ سرِ پخش را نگه دار", () => selected && apply("فریمِ ثابت", (pr) => freezeFrameAt(pr, selected.clip.id, time)), { disabled: !selected || selected.clip.type !== "media" || selected.clip.kind !== "video" })}
            <span className="ws-sep" />
            {tlButton("🧲", "چسبیدن به لبه‌ها، نشانگرها و سرِ پخش", () => setSnapOn((v) => !v), { on: snapOn, test: "tl-snap" })}
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
            {selection.length > 1 && tlButton("پیوند", "قطعه‌های انتخاب‌شده با هم جابه‌جا شوند", () => apply("پیوند", (pr) => linkClips(pr, selection)))}
          </div>
          <TimelineView
            project={project} selection={selection} playhead={time} px={px} snapOn={snapOn} tool={tool} storeId={storeId} media={media} fps={project.format.fps}
            onProject={(p, liveDrag) => (liveDrag ? hist.live(() => p) : hist.apply("ویرایش", () => p))}
            onCommit={(l) => hist.end(l)}
            onSelect={(ids) => { setSelection(ids); if (ids.length === 1) { const f = findClip(project, ids[0]); if (f?.clip.type === "text") setTab("text"); else if (tab === "text") setTab("clip"); } }}
            onSeek={seek}
            onDropRef={(trackId, ref, at) => { const it = media[ref]; if (it) addFromBin(it, trackId, at); }}
            onTrack={(id, patch) => apply("ترک", (pr) => updateTrack(pr, id, patch))}
            onRemoveTrack={(id) => apply("حذفِ ترک", (pr) => removeTrack(pr, id))}
            onRazor={(id, t) => apply("برش با تیغه", (pr) => { let next = pr; for (const x of withLinked(pr, [id])) next = splitAt(next, x, t); return next; })}
            onTrackForward={(t) => setSelection(project.tracks.flatMap((tr) => (tr.locked ? [] : tr.clips.filter((c) => clipEnd(c) > t).map((c) => c.id))))}
            onMarkerClick={(id, alt) => { const m = (project.markers ?? []).find((x) => x.id === id); if (alt) apply("حذفِ نشانگر", (pr) => removeMarker(pr, id)); else if (m) seek(m.t); }}
            onInOut={(a, b) => hist.apply("بازهٔ ورودی/خروجی", (pr) => ({ ...pr, inout: { in: a, out: b } }))}
            onKeyPick={(id, ch: KfChannel, t) => { setSelection([id]); const f = findClip(project, id); if (f) seek(f.clip.at + t); setTab("clip"); void ch; }}
          />
        </div>
      </div>
    </Workspace>
  );
}

// برای تایپ‌اسکریپت: AnyClip/clipEnd در جاهای دیگر استفاده می‌شوند
export type { AnyClip };
export { clipEnd };
