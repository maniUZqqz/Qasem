import { MutableRefObject, useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Badge, Button, Card, ErrorBox, Spinner } from "../../../components/ui";
import { actionFor, clone, errMsg, fa, up3d } from "./api";
import { type AiOut, AiPanel, CodePanel, IssueCount, IssuesPanel, VersionsTable } from "./editor/BottomPanels";
import Inspector from "./editor/Inspector";
import { type Sel, docDuration, newItem, selFromPath, sortTrack } from "./editor/model";
import SceneSettings from "./editor/SceneSettings";
import { PreviewPanel, ProjectJobs, RenderPanel } from "./editor/SidePanels";
import Timeline from "./editor/Timeline";
import { ButtonTabs, JobSteps, Muted, useCatalog, usePoll, useStatus, useToast } from "./shared";
import type { Issue, Item, JobKind, Project, SceneDoc, Track, UploadResult } from "./types";

/**
 * ویرایشگرِ پروژه — همان editor.js ِ قدیمی روی React.
 *
 * یک «سند» در حافظه (doc) که خطِ زمان، بازرس و تبِ کد همه روی آن کار می‌کنند؛ هر تغییر یک پلهٔ undo است،
 * نیم ثانیه بعدش وارسیِ زنده (validate) می‌رود، و «ذخیره» یک نسخهٔ تازه روی سرور می‌سازد.
 * پروژه هر ۴ ثانیه از سرور تازه می‌شود (کارها، نسخه‌ها)؛ سند فقط وقتی عوض می‌شود که تغییرِ ذخیره‌نشده نباشد.
 */

type BTab = "issues" | "ai" | "code" | "versions";

/** state + ref هم‌زمان: callbackهای پولینگ و میان‌برها همیشه آخرین مقدار را می‌بینند. */
function useStateRef<T>(init: T): [T, (v: T) => void, MutableRefObject<T>] {
  const [v, setV] = useState(init);
  const ref = useRef(init);
  const set = useCallback((x: T) => {
    ref.current = x;
    setV(x);
  }, []);
  return [v, set, ref];
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const pid = Number(id);
  const toast = useToast();
  const { cat, error: catError } = useCatalog();
  const status = useStatus();
  const aiReady = status?.ai_ready ?? false;
  const origin = window.location.origin;

  const [proj, setProj, projRef] = useStateRef<Project | null>(null);
  const [doc, setDoc, docRef] = useStateRef<SceneDoc | null>(null);
  const [dirty, setDirty, dirtyRef] = useStateRef(false);
  const [, setLoadedVersion, loadedVersionRef] = useStateRef<number | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [sel, setSel] = useState<Sel>(null);
  const [zoom, setZoom] = useState(70);
  const [playhead, setPlayhead] = useState(0);
  const [btab, setBtab] = useState<BTab>("issues");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiOut, setAiOut] = useState<AiOut>(null);
  const [error, setError] = useState<string | null>(null);
  const historyRef = useRef<string[]>([]);
  const [histLen, setHistLen] = useState(0);
  const vTimer = useRef(0);

  // ───────── وارسیِ زنده
  const scheduleValidate = useCallback((next: SceneDoc) => {
    window.clearTimeout(vTimer.current);
    vTimer.current = window.setTimeout(async () => {
      try {
        const r = await up3d.validate(next);
        setIssues(r.issues);
      } catch {
        /* وارسی دورِ بعد */
      }
    }, 500);
  }, []);
  useEffect(() => () => window.clearTimeout(vTimer.current), []);

  // ───────── بار کردن
  const load = useCallback(
    async (force: boolean) => {
      try {
        const p = await up3d.project(pid);
        setProj(p);
        setError(null);
        if (p.document && (force || !dirtyRef.current) && p.version !== loadedVersionRef.current) {
          setDoc(p.document);
          setLoadedVersion(p.version);
          historyRef.current = [];
          setHistLen(0);
          setDirty(false);
          setSel(null);
          setIssues(p.report?.issues || []);
        }
      } catch (e) {
        setError(errMsg(e));
      }
    },
    [pid, setProj, setDoc, setLoadedVersion, setDirty, dirtyRef, loadedVersionRef],
  );

  usePoll(() => load(false), 4000, [pid]);

  // ───────── تغییرِ سند (با تاریخچه)
  const pushHistory = (cur: SceneDoc) => {
    historyRef.current.push(JSON.stringify(cur));
    if (historyRef.current.length > 60) historyRef.current.shift();
    setHistLen(historyRef.current.length);
  };
  const replaceDoc = (next: SceneDoc) => {
    setDoc(next);
    setDirty(true);
    scheduleValidate(next);
  };
  const change = (fn: (d: SceneDoc) => void) => {
    const cur = docRef.current;
    if (!cur) return;
    pushHistory(cur);
    const next = clone(cur);
    fn(next);
    replaceDoc(next);
  };
  const changeItem = (track: Track, idx: number, fn: (it: Item, d: SceneDoc) => void) =>
    change((d) => {
      const it = d[track][idx];
      if (!it) return;
      fn(it, d);
      sortTrack(d[track]);
      setSel({ track, idx: d[track].indexOf(it) });
    });
  const undo = () => {
    const h = historyRef.current;
    if (!h.length) return;
    const prev = JSON.parse(h.pop()!) as SceneDoc;
    setHistLen(h.length);
    replaceDoc(prev);
  };
  const addItem = (track: Track) => {
    if (!cat || !docRef.current) return;
    const t = Math.round(playhead * 20) / 20;
    change((d) => {
      const it = newItem(cat, d, track, t);
      d[track].push(it);
      sortTrack(d[track]);
      setSel({ track, idx: d[track].indexOf(it) });
    });
  };
  const deleteSel = () => {
    if (!sel) return;
    change((d) => void d[sel.track].splice(sel.idx, 1));
    setSel(null);
  };

  // ───────── ذخیره / ترمیم
  const save = async (repair: boolean): Promise<boolean> => {
    const cur = docRef.current;
    if (!cur) return false;
    try {
      const r = await up3d.saveScene(pid, { document: cur, repair, source: "editor", note: repair ? "ترمیمِ خودکار" : "ویرایشگر" });
      setDoc(r.document);
      setLoadedVersion(r.version);
      setIssues(r.report.issues || []);
      setDirty(false);
      const ch = r.report.changes || [];
      toast(`نسخهٔ ${fa(r.version)} ذخیره شد${ch.length ? ` · ${fa(ch.length)} ترمیم` : ""}${r.valid ? "" : " · هنوز ایراد دارد"}`, !r.valid);
      await load(true);
      return r.valid;
    } catch (e) {
      toast(errMsg(e), true);
      return false;
    }
  };
  const saveRef = useRef(save);
  saveRef.current = save;
  const undoRef = useRef(undo);
  undoRef.current = undo;
  const deleteRef = useRef(deleteSel);
  deleteRef.current = deleteSel;

  // ───────── کارها
  const startJob = async (kind: JobKind, body: Record<string, unknown>) => {
    if (dirtyRef.current && !(await save(false))) return;
    if (!projRef.current?.valid) {
      toast("صحنه ایراد دارد؛ اول «ترمیمِ خودکار»", true);
      return;
    }
    try {
      const j = await up3d.startJob(pid, actionFor(kind, body.profile as string | undefined), body);
      toast(`کار #${fa(j.id)} در صف گذاشته شد`);
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

  // ───────── هوشِ مصنوعی
  const aiEdit = async (ins: string) => {
    if (dirtyRef.current && !(await save(false))) return;
    setAiBusy(true);
    setAiOut(null);
    try {
      const r = await up3d.aiEdit(pid, ins);
      setAiOut({ version: r.version, diff: r.diff, repairs: r.repairs });
      await load(true);
    } catch (e) {
      setAiOut({ error: errMsg(e) });
    } finally {
      setAiBusy(false);
    }
  };
  const replan = async () => {
    if (!window.confirm("برنامه از اول با هوشِ مصنوعی نوشته شود؟ (نسخهٔ فعلی در «نسخه‌ها» می‌ماند)")) return;
    try {
      await up3d.plan(pid, { mode: "ai" });
      toast("برنامه‌ریزی شروع شد");
      await load(false);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };

  // ───────── نسخه‌ها و JSON
  const restore = async (n: number) => {
    try {
      const r = await up3d.scene(pid, n);
      if (!r.document || !docRef.current) return;
      pushHistory(docRef.current);
      replaceDoc(r.document);
      toast(`نسخهٔ ${fa(n)} بار شد؛ برای نگه‌داشتن ذخیره کنید`);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const applyJson = (text: string) => {
    try {
      const d = JSON.parse(text) as SceneDoc;
      if (!d || typeof d !== "object") throw new Error("سند نیست");
      change((cur) => Object.assign(cur, d));
      toast("اعمال شد");
    } catch (e) {
      toast(`JSON نامعتبر: ${e instanceof Error ? e.message : String(e)}`, true);
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

  // ───────── میان‌برها و هشدارِ خروج
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toUpperCase();
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        deleteRef.current();
        e.preventDefault();
      }
      if (e.key === "z" && (e.ctrlKey || e.metaKey)) {
        undoRef.current();
        e.preventDefault();
      }
      if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
        void saveRef.current(false);
        e.preventDefault();
      }
    };
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    document.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [dirtyRef]);

  // ───────── نمایش
  if (!cat || !proj) {
    return (
      <div className="py-10 text-center">
        {catError || error ? <ErrorBox message={catError || error} /> : <Spinner />}
      </div>
    );
  }

  const plan = proj.jobs.find((j) => j.kind === "plan" && !j.final);
  const failedPlan = proj.jobs.find((j) => j.kind === "plan" && j.state === "FAILED");
  const canUndo = histLen > 0;

  return (
    <div className="space-y-3">
      <ErrorBox message={error} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-extrabold" style={{ color: "var(--text)" }}>
            {proj.title}
          </h1>
          <Badge tone={proj.valid ? "ok" : "bad"}>
            {proj.version ? `نسخهٔ ${fa(proj.version)} · ${proj.valid ? "معتبر" : "ایراد"}` : "بی‌نسخه"}
          </Badge>
          {dirty && <Badge tone="warn">تغییرِ ذخیره‌نشده</Badge>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={undo} disabled={!canUndo} title="Ctrl+Z">
            ↶ برگرد
          </Button>
          <Button variant="secondary" onClick={() => void save(true)} disabled={!doc}>
            ترمیمِ خودکار
          </Button>
          <Button onClick={() => void save(false)} disabled={!doc} title="Ctrl+S">
            ذخیره (نسخهٔ تازه)
          </Button>
        </div>
      </div>

      {(plan || !proj.document) && (
        <Card>
          {plan ? (
            <>
              <b style={{ color: "var(--text)" }}>کارگردان در حالِ نوشتنِ برنامه…</b>
              <JobSteps job={plan} />
              <Muted>{plan.message || ""}</Muted>
            </>
          ) : failedPlan ? (
            <>
              <b style={{ color: "var(--bad)" }}>برنامه‌ریزی ناموفق بود:</b> <span style={{ color: "var(--text-2)" }}>{failedPlan.message}</span>
            </>
          ) : (
            <Muted>در انتظارِ برنامه…</Muted>
          )}
        </Card>
      )}

      {doc && (
        <div className="u3d-studio">
          <div className="u3d-col u3d-left">
            <PreviewPanel proj={proj} />
            <RenderPanel
              cat={cat}
              pid={pid}
              version={proj.version}
              onRender={(profile, allowCpu) => void startJob("render", allowCpu ? { profile, allow_cpu: true } : { profile })}
              onExport={(format) => void startJob("export", { format })}
              onContact={() => void startJob("contact", { count: 6 })}
            />
            <ProjectJobs jobs={proj.jobs} onCancel={(jid) => void cancelJob(jid)} />
          </div>

          <div className="u3d-col">
            <Timeline
              cat={cat}
              doc={doc}
              issues={issues}
              sel={sel}
              zoom={zoom}
              playhead={playhead}
              onSelect={setSel}
              onPlayhead={setPlayhead}
              onAdd={addItem}
              onMove={(track, idx, start, duration) =>
                changeItem(track, idx, (it) => {
                  it.start = start;
                  it.duration = duration;
                })
              }
              onZoom={(f) => setZoom((z) => Math.max(20, Math.min(260, z * f)))}
            />
            <Card>
              <ButtonTabs<BTab>
                tabs={[
                  {
                    id: "issues",
                    label: (
                      <span className="flex items-center gap-1.5">
                        ایرادها <IssueCount issues={issues} />
                      </span>
                    ),
                  },
                  { id: "ai", label: "ویرایش با هوشِ مصنوعی" },
                  { id: "code", label: "کد (JSON / Python / API)" },
                  { id: "versions", label: "نسخه‌ها" },
                ]}
                value={btab}
                onChange={setBtab}
              />
              {btab === "issues" && (
                <IssuesPanel
                  issues={issues}
                  onPick={(path) => {
                    const s = selFromPath(path);
                    if (s && docRef.current && docRef.current[s.track][s.idx]) setSel(s);
                  }}
                />
              )}
              {btab === "ai" && <AiPanel aiReady={aiReady} busy={aiBusy} out={aiOut} onEdit={(ins) => void aiEdit(ins)} onReplan={() => void replan()} />}
              {btab === "code" && <CodePanel doc={doc} pid={pid} origin={origin} onApplyJson={applyJson} />}
              {btab === "versions" && <VersionsTable versions={proj.versions} current={proj.version} onRestore={(n) => void restore(n)} />}
            </Card>
          </div>

          <div className="u3d-col">
            <Card>
              {sel && doc[sel.track][sel.idx] ? (
                <Inspector key={`${sel.track}:${sel.idx}`} ed={{ cat, doc, issues, sel, setSel, change, changeItem }} />
              ) : (
                <SceneSettings cat={cat} doc={doc} change={change} upload={upload} />
              )}
            </Card>
          </div>
        </div>
      )}

      {doc && (
        <Muted className="text-xs">
          مدتِ صحنه {fa(docDuration(doc).toFixed(1))} ثانیه · زمانِ افزودن {fa(playhead.toFixed(2))} ثانیه
        </Muted>
      )}
    </div>
  );
}
