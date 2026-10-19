import { MutableRefObject, useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, ErrorBox, Spinner } from "../../../components/ui";
import { actionFor, clone, errMsg, fa, label, up3d } from "./api";
import { type AiOut, AiPanel, CodePanel, IssueCount, IssuesPanel, VersionsTable } from "./editor/BottomPanels";
import Inspector from "./editor/Inspector";
import { type Sel, OVT, TRACKS, byId, docDuration, newItem, selFromPath, sortTrack } from "./editor/model";
import QualityPanel, { hasQuality } from "./editor/QualityPanel";
import { ActorsEditor, AudioSettings, EnvironmentLighting, ProductsEditor, SceneBasics } from "./editor/SceneSettings";
import { ExportActions, PreviewPanel, ProjectJobs } from "./editor/SidePanels";
import Summary from "./editor/Summary";
import Timeline from "./editor/Timeline";
import { Advanced, ButtonTabs, JobSteps, Muted, Section, useCatalog, usePoll, useStatus, useToast } from "./shared";
import type { Estimate, Issue, Item, JobKind, Project, QualityOverride, SceneDoc, Track, UploadResult } from "./types";

/**
 * ویرایشگرِ پروژه — یک جریانِ راهنمای پنج‌گامه به‌جای سه ستونِ هم‌زمان:
 *   ۱ محصول، مجری و صحنه   ۲ حرکت و دوربین (خطِ زمان + بازرس + ایرادها/ویرایش با AI)
 *   ۳ متن، صدا و موسیقی      ۴ کیفیت و رندر      ۵ خروجی‌ها      + ابزارهای پیشرفته (کد، نسخه‌ها)
 * و یک کارتِ چسبانِ «خلاصه و وضعیت» که می‌گوید چه چیزی، با چه کیفیتی، روی کدام کارگر و چقدر.
 *
 * منطق همان قبلی است: یک «سند» در حافظه (doc) که همهٔ بخش‌ها روی آن کار می‌کنند؛ هر تغییر یک پلهٔ undo،
 * نیم ثانیه بعدش وارسیِ زنده، «ذخیره» یک نسخهٔ تازه روی سرور. پروژه هر ۴ ثانیه از سرور تازه می‌شود (کارها، نسخه‌ها)؛
 * سند فقط وقتی عوض می‌شود که تغییرِ ذخیره‌نشده نباشد.
 */

type Tab2 = "issues" | "ai";
type TabAdv = "code" | "versions";

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
  const status = useStatus(15000);
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
  const [tab2, setTab2] = useState<Tab2>("issues");
  const [tabAdv, setTabAdv] = useState<TabAdv>("code");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiOut, setAiOut] = useState<AiOut>(null);
  const [error, setError] = useState<string | null>(null);
  const historyRef = useRef<string[]>([]);
  const [histLen, setHistLen] = useState(0);
  const vTimer = useRef(0);

  // کیفیتِ انتخاب‌شده، تنظیمِ دستی و تخمین‌ها (بخشِ ۴ و کارتِ خلاصه هر دو می‌خوانند)
  const [profile, setProfile] = useState("");
  const [quality, setQuality] = useState<QualityOverride | null>(null);
  const [est, setEst] = useState<Record<string, Estimate>>({});

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

  // کیفیتِ پیش‌فرض: تا ویدئویی نگرفته‌اید «انیمیک» (سریع)، بعد پیش‌فرضِ دفتر (پیش‌نمایش)
  useEffect(() => {
    if (!cat || !proj || profile) return;
    const hasVideo = proj.jobs.some((j) => j.kind === "render" && j.state === "COMPLETED");
    const pick = hasVideo
      ? cat.render_profile.find((p) => p.default) || cat.render_profile[0]
      : cat.render_profile.find((p) => p.id === "animatic") || cat.render_profile[0];
    if (pick) setProfile(pick.id);
  }, [cat, proj, profile]);

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
  /** انتخابِ یک قطعه از هر جای صفحه و رفتن به بازرس (بخشِ ۲) */
  const pick = (s: Sel) => {
    setSel(s);
    window.setTimeout(() => document.getElementById("u3d-inspector")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };
  const addItem = (track: Track, goTo = false) => {
    if (!cat || !docRef.current) return;
    const t = Math.round(playhead * 20) / 20;
    change((d) => {
      const it = newItem(cat, d, track, t);
      d[track].push(it);
      sortTrack(d[track]);
      const s = { track, idx: d[track].indexOf(it) };
      if (goTo) pick(s);
      else setSel(s);
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

  // ───────── کارها (همان اکشن‌های preview/render/export/contact ِ API)
  const startJob = async (kind: JobKind, body: Record<string, unknown>) => {
    if (dirtyRef.current && !(await save(false))) return;
    if (!projRef.current?.valid) {
      toast("صحنه ایراد دارد؛ اول «ترمیمِ خودکار»", true);
      return;
    }
    try {
      const j = await up3d.startJob(pid, actionFor(kind, body.profile as string | undefined), body);
      toast(
        j.waiting && j.waiting.eligible.length === 0
          ? `کار #${fa(j.id)} ساخته شد ولی کارگرِ مناسبی آنلاین نیست — بخشِ ۵ را ببینید`
          : `کار #${fa(j.id)} در صف گذاشته شد`,
        !!(j.waiting && j.waiting.eligible.length === 0),
      );
      await load(false);
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const render = (prof: string, allowCpu: boolean, q: QualityOverride | null) =>
    void startJob("render", { profile: prof, ...(allowCpu ? { allow_cpu: true } : {}), ...(hasQuality(q) ? { quality: q } : {}) });
  const renderSelected = () => {
    const e = est[profile];
    if (!e) return;
    if (e.available) render(profile, false, quality);
    else if (e.cpu_seconds) {
      if (e.cpu_seconds > 1800 && !window.confirm(`روی CPU ِ سرور حدودِ ${Math.round(e.cpu_seconds / 60)} دقیقه طول می‌کشد. شروع شود؟`)) return;
      render(profile, true, quality);
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
      const j = await up3d.allowCpu(jid);
      toast(j.waiting && j.waiting.eligible.length ? `کارگرِ ${j.waiting.eligible.join("، ")} به‌زودی کار #${fa(jid)} را می‌گیرد` : "اجازهٔ CPU داده شد؛ تا کارگری آنلاین شود");
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
  const selected = sel && doc ? doc[sel.track][sel.idx] : undefined;

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
        <div className="u-card p-5">
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
        </div>
      )}

      {doc && (
        <div className="u3d-flow">
          <div className="u3d-main">
            <Section n={1} title="محصول، مجری و صحنه" help="چه چیزی، کجا و توسطِ چه کسی معرفی می‌شود. مدت و قاب هم همین‌جاست؛ جزئیاتِ رنگ و لباس زیرِ هر مورد تاشو است.">
              <div className="u3d-two">
                <div className="space-y-4">
                  <div>
                    <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                      خروجی
                    </b>
                    <SceneBasics cat={cat} doc={doc} change={change} />
                  </div>
                  <div>
                    <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                      محیط و نور
                    </b>
                    <EnvironmentLighting cat={cat} doc={doc} change={change} />
                  </div>
                </div>
                <div className="space-y-4">
                  <div>
                    <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                      مجری
                    </b>
                    <ActorsEditor cat={cat} doc={doc} change={change} />
                  </div>
                  <div>
                    <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                      محصول
                    </b>
                    <ProductsEditor cat={cat} doc={doc} change={change} upload={upload} />
                  </div>
                </div>
              </div>
            </Section>

            <Section
              n={2}
              title="حرکت و دوربین (خطِ زمان)"
              help="هر شیار یک چیز است: دوربین، حرکتِ بدن، گفتار، چهره، نگاه، نوشته. روی هر قطعه بزنید تا در «بازرس» ویرایش شود؛ بکشید تا جابه‌جا یا کوتاه/بلند شود."
              action={
                <span className="flex flex-wrap gap-1.5">
                  {TRACKS.map((t) => (
                    <Button key={t.id} size="sm" variant="secondary" onClick={() => addItem(t.id, true)} title={`افزودن در زمانِ ${fa(playhead.toFixed(2))} ثانیه`}>
                      + {t.name}
                    </Button>
                  ))}
                </span>
              }
            >
              <Timeline
                cat={cat}
                doc={doc}
                issues={issues}
                sel={sel}
                zoom={zoom}
                playhead={playhead}
                onSelect={setSel}
                onPlayhead={setPlayhead}
                onAdd={(t) => addItem(t)}
                onMove={(track, idx, start, duration) =>
                  changeItem(track, idx, (it) => {
                    it.start = start;
                    it.duration = duration;
                  })
                }
                onZoom={(f) => setZoom((z) => Math.max(20, Math.min(260, z * f)))}
              />
              <div className="u3d-two">
                <div id="u3d-inspector" className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                  {sel && selected ? (
                    <Inspector key={`${sel.track}:${sel.idx}`} ed={{ cat, doc, issues, sel, setSel, change, changeItem }} />
                  ) : (
                    <div className="py-4 text-center">
                      <Icon name="target" size={22} />
                      <Muted className="mt-1">بازرس: روی یکی از قطعه‌های خطِ زمان بزنید تا این‌جا ویرایش شود.</Muted>
                      <Muted className="mt-1 text-xs">
                        مدتِ صحنه {fa(docDuration(doc).toFixed(1))} ثانیه · زمانِ افزودن {fa(playhead.toFixed(2))} ثانیه (روی خط‌کش بزنید)
                      </Muted>
                    </div>
                  )}
                </div>
                <div>
                  <ButtonTabs<Tab2>
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
                    ]}
                    value={tab2}
                    onChange={setTab2}
                  />
                  {tab2 === "issues" && (
                    <IssuesPanel
                      issues={issues}
                      onPick={(path) => {
                        const s = selFromPath(path);
                        if (s && docRef.current && docRef.current[s.track][s.idx]) pick(s);
                      }}
                    />
                  )}
                  {tab2 === "ai" && <AiPanel aiReady={aiReady} busy={aiBusy} out={aiOut} onEdit={(ins) => void aiEdit(ins)} onReplan={() => void replan()} />}
                </div>
              </div>
            </Section>

            <Section n={3} title="متن، صدا و موسیقی" help="جمله‌های گفتار (با صدای فارسی و هماهنگیِ لب)، نوشته‌های روی تصویر، زیرنویسِ خودکار و موسیقیِ پس‌زمینه.">
              <div className="u3d-two">
                <div className="space-y-3">
                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <b className="text-sm" style={{ color: "var(--text)" }}>
                        <Icon name="mic" size={14} /> گفتار ({fa(doc.speech.length)})
                      </b>
                      <Button size="sm" variant="secondary" onClick={() => addItem("speech", true)}>
                        + جملهٔ تازه
                      </Button>
                    </div>
                    {doc.speech.length === 0 ? (
                      <Muted className="text-xs">جمله‌ای نیست؛ ویدئو بی‌صدا می‌شود.</Muted>
                    ) : (
                      <div className="u3d-rows">
                        {doc.speech.map((s, i) => (
                          <div key={s.id || `sp${i}`} className={`u3d-row ${sel?.track === "speech" && sel.idx === i ? "sel" : ""}`}>
                            <span className="t">{s.text}</span>
                            <span className="when">
                              {fa(s.start.toFixed(1))}ث · {label(byId(cat, "voice", s.voice))}
                            </span>
                            <Button size="sm" variant="ghost" onClick={() => pick({ track: "speech", idx: i })}>
                              ویرایش
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <b className="text-sm" style={{ color: "var(--text)" }}>
                        <Icon name="subtitles" size={14} /> نوشته‌های روی تصویر ({fa(doc.overlays.length)})
                      </b>
                      <Button size="sm" variant="secondary" onClick={() => addItem("overlays", true)}>
                        + نوشتهٔ تازه
                      </Button>
                    </div>
                    {doc.overlays.length === 0 ? (
                      <Muted className="text-xs">نوشته‌ای نیست.</Muted>
                    ) : (
                      <div className="u3d-rows">
                        {doc.overlays.map((o, i) => (
                          <div key={o.id || `ov${i}`} className={`u3d-row ${sel?.track === "overlays" && sel.idx === i ? "sel" : ""}`}>
                            <Badge>{OVT[o.type || ""] || o.type}</Badge>
                            <span className="t">{o.text}</span>
                            <span className="when">{fa(o.start.toFixed(1))}ث</span>
                            <Button size="sm" variant="ghost" onClick={() => pick({ track: "overlays", idx: i })}>
                              ویرایش
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                    <Icon name="music" size={14} /> صدا و موسیقی
                  </b>
                  <AudioSettings doc={doc} change={change} upload={upload} />
                </div>
              </div>
            </Section>

            <Section n={4} title="کیفیت و رندر" help="یک کیفیت انتخاب کنید؛ دکمه می‌گوید روی کدام کارگر و حدوداً چقدر. انیمیک برای وارسی، پیش‌نمایش برای نورِ واقعی، بقیه برای انتشار (کارگرِ GPU).">
              {profile && (
                <QualityPanel
                  cat={cat}
                  pid={pid}
                  version={proj.version}
                  aspect={doc.output.aspect}
                  profile={profile}
                  setProfile={setProfile}
                  quality={quality}
                  setQuality={setQuality}
                  est={est}
                  setEst={setEst}
                  onRender={render}
                />
              )}
            </Section>

            <Section n={5} title="خروجی‌ها" help="ویدئوهای آماده، فریم‌های نمونه، خروجیِ سه‌بعدی برای وب/بازی، و کارهای این پروژه با وضعیتِ لحظه‌ای.">
              <PreviewPanel proj={proj} />
              <div>
                <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                  خروجی‌های دیگر
                </b>
                <ExportActions onExport={(format) => void startJob("export", { format })} onContact={() => void startJob("contact", { count: 6 })} />
              </div>
              <div>
                <b className="mb-1.5 block text-sm" style={{ color: "var(--text)" }}>
                  کارهای این پروژه
                </b>
                <ProjectJobs jobs={proj.jobs} onCancel={(jid) => void cancelJob(jid)} onAllowCpu={(jid) => void allowCpu(jid)} />
              </div>
            </Section>

            <Advanced title="ابزارهای پیشرفته" hint="کد (سندِ JSON، Python SDK، API)، نسخه‌های پیشین، میان‌برها">
              <ButtonTabs<TabAdv>
                tabs={[
                  { id: "code", label: "کد (JSON / Python / API)" },
                  { id: "versions", label: `نسخه‌ها (${fa(proj.versions.length)})` },
                ]}
                value={tabAdv}
                onChange={setTabAdv}
              />
              {tabAdv === "code" && <CodePanel doc={doc} pid={pid} origin={origin} onApplyJson={applyJson} />}
              {tabAdv === "versions" && <VersionsTable versions={proj.versions} current={proj.version} onRestore={(n) => void restore(n)} />}
              <Muted className="text-xs">
                میان‌برها: <span className="u3d-kbd">Delete</span> حذفِ قطعه · <span className="u3d-kbd">Ctrl+Z</span> برگشت · <span className="u3d-kbd">Ctrl+S</span> ذخیره
              </Muted>
            </Advanced>
          </div>

          <aside className="u3d-aside">
            <Summary
              proj={proj}
              doc={doc}
              cat={cat}
              issues={issues}
              dirty={dirty}
              profile={profile}
              quality={quality}
              est={est}
              status={status}
              onRender={renderSelected}
              onSave={() => void save(false)}
              onAllowCpu={(jid) => void allowCpu(jid)}
              onCancel={(jid) => void cancelJob(jid)}
            />
          </aside>
        </div>
      )}
    </div>
  );
}
