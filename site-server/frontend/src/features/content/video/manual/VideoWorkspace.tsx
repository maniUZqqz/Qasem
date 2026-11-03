import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import Workspace from "../../../../components/Workspace";
import { Badge, Spinner } from "../../../../components/ui";
import { useHistory } from "../../../../hooks/useHistory";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { ToolInfo } from "../../ToolPicker";
import type { Bin as BinData, Check, MediaItem, ProjectRow } from "../api";
import { videoApi } from "../api";
import Bin from "./Bin";
import Inspector from "./Inspector";
import Monitor from "./Monitor";
import TimelineView from "./TimelineView";
import {
  AnyClip, MediaClip, Project, addMedia, addText, addTrack, clipEnd, deleteClip, duplicateClip, emptyProject, findClip, fromApi,
  projectLength, removeTrack, splitAt, toApi, trimEnd, trimStart, updateTrack,
} from "./model";

type Props = {
  storeId: string;
  tools: ToolInfo[];
  /** ویدیویی که با «ویرایشِ دستی» از فهرست آمده: پروژهٔ تازه با همین قطعه شروع می‌شود */
  startRef?: string | null;
  onStartConsumed?: () => void;
};

const FRAME = 1 / 30;

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
  const [selection, setSelection] = useState<string | null>(null);
  const [px, setPx] = useState(60);
  const [snapOn, setSnapOn] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [renderRow, setRenderRow] = useState<ProjectRow | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [proxyBusy, setProxyBusy] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const lastSaved = useRef<string>("");
  const idRef = useRef<number | null>(null);
  idRef.current = projectId;
  const totalRef = useRef(0);
  totalRef.current = projectLength(project);

  // ───────────── بسته‌ی رسانه
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
  const renderRunner = useJobRunner(async () => {
    if (idRef.current) {
      try {
        const { project: row } = await videoApi.project(storeId, idRef.current);
        setRenderRow(row);
        setRenderError(row.state === "FAILED" ? row.error : null);
      } catch (err) {
        setRenderError(errorMessage(err));
      }
    }
  });

  const media = useMemo(() => {
    const m: Record<string, MediaItem> = {};
    for (const list of bin ? [bin.videos, bin.audio, bin.images] : []) for (const it of list) m[it.ref] = it;
    return m;
  }, [bin]);

  // ───────────── آغاز: بسته + پروژه‌ها
  useEffect(() => {
    let stop = false;
    (async () => {
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
          lastSaved.current = JSON.stringify(toApi(p));
          setProjectId(row.id);
          setTitle(row.title || "پروژه");
          setCheck(ck);
          setRenderRow(row);
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
    setSelection(p.tracks.find((t) => t.kind === "video")!.clips[0]?.id ?? null);
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
    if (!ready || !hasClips && !idRef.current) return;
    if (lastSaved.current === dataKey + "|" + title) return;
    const t = window.setTimeout(() => void saveNow(), 1100);
    return () => window.clearTimeout(t);
  }, [dataKey, title, ready, hasClips, saveNow]);

  async function openProject(id: number | null) {
    setPlaying(false);
    setRenderRow(null);
    setRenderError(null);
    setSelection(null);
    setTime(0);
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
      setRenderRow(row);
    } catch (err) {
      setNotice(errorMessage(err));
    }
  }

  async function deleteProject() {
    if (!projectId || !window.confirm("این پروژه حذف شود؟ (فایلِ رندرشده هم می‌رود)")) return;
    await videoApi.deleteProject(storeId, projectId);
    setProjects((cur) => cur.filter((p) => p.id !== projectId));
    await openProject(null);
  }

  // ───────────── پخش
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      acc += dt;
      if (acc >= 1 / 30) {
        const step = acc * rate;
        acc = 0;
        setTime((t) => {
          const nt = t + step;
          if (rate > 0 && nt >= totalRef.current) {
            setPlaying(false);
            return totalRef.current;
          }
          if (rate < 0 && nt <= 0) {
            setPlaying(false);
            return 0;
          }
          return nt;
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, rate]);

  const seek = (t: number) => setTime(Math.max(0, Math.min(Math.max(totalRef.current, 0.0001) + 20, t)));
  const togglePlay = () => {
    if (!playing && rate < 0 && time <= 0) setRate(1);
    if (!playing && time >= totalRef.current - 0.01 && rate > 0) setTime(0);
    setPlaying((p) => !p);
  };
  const step = (frames: number) => {
    setPlaying(false);
    seek(time + frames * (1 / (project.format.fps || 30)));
  };

  // ───────────── ویرایش
  const selected = findClip(project, selection);
  const live = (fn: (p: Project) => Project) => hist.live(fn);
  const apply = (label: string, fn: (p: Project) => Project) => hist.apply(label, fn);
  const edit = { live, end: hist.end, apply };

  function trackFor(kind: "video" | "audio" | "text") {
    return project.tracks.find((t) => t.kind === kind && !t.locked);
  }

  function addFromBin(item: MediaItem, trackId?: string, at?: number) {
    const kind = item.kind === "audio" ? "audio" : "video";
    const tr = project.tracks.find((t) => t.id === trackId && t.kind === kind && !t.locked) ?? trackFor(kind);
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

  function splitHere() {
    const t = time;
    apply("تقسیم", (pr) => {
      if (selection) return splitAt(pr, selection, t);
      let next = pr;
      for (const tr of pr.tracks) if (!tr.locked) for (const c of tr.clips) next = splitAt(next, c.id, t);
      return next;
    });
  }

  function removeSelected(ripple: boolean) {
    if (!selection) return;
    apply(ripple ? "حذفِ بی‌فاصله" : "حذف", (pr) => deleteClip(pr, selection, ripple));
    setSelection(null);
  }

  async function importSubtitles(ref: string) {
    try {
      const lines = await videoApi.subtitles(storeId, ref);
      const src = project.tracks.flatMap((t) => t.clips).find((c): c is MediaClip => c.type === "media" && c.ref === ref && (c.id === selection));
      if (!src) return;
      const picked = lines.filter((l) => l.end > src.start && l.start < src.end);
      if (picked.length === 0) {
        setNotice("زیرنویسی برای بخشِ استفاده‌شدهٔ این قطعه نیست.");
        return;
      }
      apply("زیرنویس", (pr) => {
        let next = pr;
        const tt = pr.tracks.find((t) => t.kind === "text" && !t.locked) ?? pr.tracks.find((t) => t.kind === "text");
        if (!tt) return pr;
        for (const l of picked) {
          const a = Math.max(l.start, src.start);
          const b = Math.min(l.end, src.end);
          next = addText(next, tt.id, l.text, src.at + (a - src.start) / src.speed, Math.max(0.3, (b - a) / src.speed));
        }
        return next;
      });
      setNotice(`${picked.length} خط زیرنویس به ترکِ متن آمد.`);
    } catch (err) {
      setNotice(errorMessage(err));
    }
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
    setRenderError(null);
    setRenderRow(null);
    const id = await saveNow();
    if (!id) {
      setRenderError("ذخیرهٔ پروژه نشد؛ رندر شروع نشد.");
      return;
    }
    try {
      const r = await videoApi.render(storeId, id, q);
      renderRunner.begin();
      renderRunner.track(r.job_id);
    } catch (err) {
      setRenderError(errorMessage(err));
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
      if (ctrl && k.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? hist.redo() : hist.undo(); return; }
      if (ctrl && k.toLowerCase() === "y") { e.preventDefault(); hist.redo(); return; }
      if (ctrl && k.toLowerCase() === "k") { e.preventDefault(); splitHere(); return; }
      if (ctrl && k.toLowerCase() === "d" && selection) { e.preventDefault(); apply("تکرار", (pr) => duplicateClip(pr, selection)); return; }
      if (ctrl) return;
      if (k === " " || k.toLowerCase() === "k") { e.preventDefault(); if (k === " " || playing) togglePlay(); else { setPlaying(false); } return; }
      if (k.toLowerCase() === "l") { setRate((r) => (playing && r >= 1 && r < 4 ? r * 2 : 1)); setPlaying(true); return; }
      if (k.toLowerCase() === "j") { setRate((r) => (playing && r <= -1 && r > -4 ? r * 2 : -1)); setPlaying(true); return; }
      if (k === "ArrowLeft") { e.preventDefault(); e.shiftKey ? seek(time - 1) : step(-1); return; }
      if (k === "ArrowRight") { e.preventDefault(); e.shiftKey ? seek(time + 1) : step(1); return; }
      if (k === "Home") { seek(0); return; }
      if (k === "End") { seek(totalRef.current); return; }
      if (k.toLowerCase() === "s") { splitHere(); return; }
      if (k === "Delete" || k === "Backspace") { e.preventDefault(); removeSelected(e.shiftKey); return; }
      if (k.toLowerCase() === "q" && selection) { apply("کوتاه تا سرِ پخش", (pr) => trimStart(pr, selection, time)); return; }
      if (k.toLowerCase() === "w" && selection) { apply("کوتاه تا سرِ پخش", (pr) => trimEnd(pr, selection, time)); return; }
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

  const tlButton = (label: string, title: string, onClick: () => void, extra: { disabled?: boolean; on?: boolean; test?: string } = {}) => (
    <button type="button" className={`ws-btn ${extra.on ? "is-on" : ""}`} title={title} onClick={onClick} disabled={extra.disabled} data-testid={extra.test}>{label}</button>
  );

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
          project={project} media={media} time={time} playing={playing} rate={rate}
          onSeek={seek} onPlay={togglePlay} onStep={step}
          onRate={(r) => { setRate(r); setPlaying(true); }}
          selectedProxyHint={proxyNeeded ? <span className="vw-proxy-note">این قطعه سنگین است؛ در «رسانه‌ها» پیش‌نمایشِ سبک بسازید</span> : null}
        />
        <Inspector
          project={project} selected={selected} playhead={time} tools={tools} media={media} edit={edit}
          title={title} onTitle={setTitle} check={check} saving={saving} projects={projects} projectId={projectId}
          onOpenProject={(id) => void openProject(id)} onDeleteProject={() => void deleteProject()}
          render={{ busy: renderRunner.running, label: renderRunner.job?.current_step_label ?? "", error: renderError ?? renderRunner.error, row: renderRow }}
          onRender={(q) => void doRender(q)} onSubtitles={(r) => void importSubtitles(r)} hasSubtitleSource={hasSubtitleSource}
        />
        <div className="vw-timeline" dir="rtl">
          <div className="tl-toolbar" data-testid="tl-toolbar">
            {tlButton("↶", "برگشت (Ctrl+Z)", hist.undo, { disabled: !hist.canUndo, test: "tl-undo" })}
            {tlButton("↷", "جلو (Ctrl+Y)", hist.redo, { disabled: !hist.canRedo, test: "tl-redo" })}
            <span className="ws-sep" />
            {tlButton("✂ تقسیم (S)", "تقسیم در سرِ پخش (S یا Ctrl+K)", splitHere, { disabled: !hasClips, test: "tl-split" })}
            {tlButton("حذف", "حذف (Delete)", () => removeSelected(false), { disabled: !selection, test: "tl-delete" })}
            {tlButton("حذفِ بی‌فاصله", "حذف و بستنِ جا (Shift+Delete)", () => removeSelected(true), { disabled: !selection, test: "tl-ripple" })}
            {tlButton("تکرار", "کپی پشتِ قطعه (Ctrl+D)", () => selection && apply("تکرار", (pr) => duplicateClip(pr, selection)), { disabled: !selection })}
            {tlButton("کوتاه تا سر ‌پخش", "ابتدای قطعه را به سرِ پخش ببر (Q) — انتها (W)", () => selection && apply("کوتاه", (pr) => trimStart(pr, selection, time)), { disabled: !selection })}
            <span className="ws-sep" />
            {tlButton("🧲 چسبیدن", "چسبیدن به لبه‌ها و سرِ پخش", () => setSnapOn((v) => !v), { on: snapOn, test: "tl-snap" })}
            {tlButton("−", "کوچک‌نمایی (-)", () => setPx((v) => Math.max(8, v / 1.25)), { test: "tl-zoom-out" })}
            {tlButton("+", "بزرگ‌نمایی (+)", () => setPx((v) => Math.min(400, v * 1.25)), { test: "tl-zoom-in" })}
            {tlButton("جا شدن", "کلِ پروژه در قاب (\\)", () => setPx(Math.max(8, Math.min(200, 700 / Math.max(5, totalRef.current)))))}
            <span className="ws-sep" />
            {tlButton("+ ترکِ تصویر", "ترکِ تصویر", () => apply("ترکِ تصویر", (pr) => addTrack(pr, "video")), { test: "tl-add-video" })}
            {tlButton("+ ترکِ صدا", "ترکِ صدا", () => apply("ترکِ صدا", (pr) => addTrack(pr, "audio")), { test: "tl-add-audio" })}
            {tlButton("+ ترکِ متن", "ترکِ متن", () => apply("ترکِ متن", (pr) => addTrack(pr, "text")), { test: "tl-add-text-track" })}
            {tlButton("T+ متن", "متنِ تازه در سرِ پخش", () => { const tt = trackFor("text"); if (tt) apply("متن", (pr) => addText(pr, tt.id, "متنِ تازه", time)); }, { test: "tl-add-text" })}
          </div>
          <TimelineView
            project={project} selection={selection} playhead={time} px={px} snapOn={snapOn}
            onProject={(p, liveDrag) => (liveDrag ? hist.live(() => p) : hist.apply("ویرایش", () => p))}
            onCommit={(l) => hist.end(l)}
            onSelect={setSelection} onSeek={seek}
            onDropRef={(trackId, ref, at) => { const it = media[ref]; if (it) addFromBin(it, trackId, at); }}
            onTrack={(id, patch) => apply("ترک", (pr) => updateTrack(pr, id, patch))}
            onRemoveTrack={(id) => apply("حذفِ ترک", (pr) => removeTrack(pr, id))}
          />
        </div>
      </div>
    </Workspace>
  );
}

// برای تایپ‌اسکریپت: AnyClip/clipEnd در جاهای دیگر استفاده می‌شوند
export type { AnyClip };
export { clipEnd };
