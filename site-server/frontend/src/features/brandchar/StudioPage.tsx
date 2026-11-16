import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import { Alert, Badge, Button, ErrorBox, Input, Select, Spinner, TextArea, fa } from "../../components/ui";
import LookPicker from "../looks/LookPicker";
import { AiJob, Character, Concept, NodeStatus, RenderItem, bcApi } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import CharacterEditor from "./CharacterEditor";
import { CharPicker, Chips, Section, fmtDate, useNotice } from "./common";

type Tab = "editor" | "ai" | "versions";

const AI_MODES = [
  { key: "illustrated", fa: "تصویرسازیِ دیجیتال" },
  { key: "3d", fa: "سه‌بعدی‌نما (خمیری/پیکسارگونه)" },
  { key: "look", fa: "یکی از ۱۱۶ سبکِ کتابخانه" },
];

export default function StudioPage() {
  const { id, ov, sel, select, reload } = useBrandChar();
  const [tab, setTab] = useState<Tab>("editor");
  const [creating, setCreating] = useState(ov.characters.length === 0);
  const [role, setRole] = useState("coach");
  const [style, setStyle] = useState("flat");
  const [name, setName] = useState("");
  const [logo, setLogo] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [mascots, setMascots] = useState<{ id: number; name: string; role_fa: string }[]>([]);
  const n = useNotice();

  useEffect(() => {
    api.get<{ mascots: { id: number; name: string; role_fa: string }[] }>(`/stores/${id}/mascot/`).then((r) => setMascots(r.data.mascots ?? [])).catch(() => setMascots([]));
  }, [id]);

  const create = async (body: Record<string, unknown>) => {
    setBusy("create");
    try {
      const c = await bcApi.create(id, body);
      await reload(c.id);
      setCreating(false);
      setTab("editor");
      n.ok("شخصیت ساخته شد؛ رنگ‌ها و لوگو از «سبکِ برند» فروشگاه آمد.");
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (c: Character) => {
    if (!window.confirm(`«${c.name}» پاک شود؟ عکس‌های ساخته‌شده در کتابخانهٔ ادیتورِ عکس می‌مانند.`)) return;
    try {
      await bcApi.remove(id, c.id);
      await reload();
      n.ok("پاک شد.");
    } catch (e) {
      n.fail(e);
    }
  };

  return (
    <div className="bc-root" data-testid="studio-page">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}

      <Section
        title="شخصیت‌های دیداری"
        hint={`تا ${fa(ov.limits.max_characters)} شخصیت برای هر فروشگاه. شخصیتِ «اصلی» همه‌جا به کار می‌رود.`}
        action={sel ? <div className="bc-row">{!sel.is_primary ? <Button type="button" variant="secondary" size="sm" onClick={() => void bcApi.primary(id, sel.id).then(() => reload(sel.id)).catch(n.fail)}>اصلی کن</Button> : <Badge tone="ok">شخصیتِ اصلی</Badge>}<Button type="button" variant="ghost" size="sm" onClick={() => void remove(sel)}>پاک‌کردن</Button></div> : undefined}
      >
        <CharPicker chars={ov.characters} value={sel?.id ?? null} onChange={(cid) => { select(cid); setCreating(false); }} onAdd={() => setCreating((v) => !v)} disabled={ov.characters.length >= ov.limits.max_characters} />
        {creating ? (
          <div className="bc-card" data-testid="create-form">
            <h2 style={{ margin: 0, fontSize: 14 }}>شخصیتِ تازه</h2>
            <span className="bc-sub">نقش (ظاهرِ اولیه از روی رنگ‌ها و لوگوی برند ساخته می‌شود)</span>
            <div className="bc-chips">
              {ov.roles.map((r) => <button key={r.key} type="button" className="bc-chip" aria-pressed={role === r.key} title={r.hint} onClick={() => setRole(r.key)}>{r.fa}</button>)}
            </div>
            <span className="bc-sub">سبکِ کشیدن</span>
            <div className="bc-chips">
              {ov.options.styles.map((s) => <button key={s.key} type="button" className="bc-chip" aria-pressed={style === s.key} title={s.hint} onClick={() => setStyle(s.key)}>{s.fa}</button>)}
            </div>
            <div className="bc-fields">
              <label className="bc-label">نام<Input value={name} maxLength={80} placeholder={`${ov.roles.find((r) => r.key === role)?.fa ?? ""} ${ov.store.name}`} onChange={(e) => setName(e.target.value)} /></label>
              <label className="bc-row" style={{ gap: 6, alignSelf: "end" }}><input type="checkbox" checked={logo} disabled={!ov.store.has_logo} onChange={(e) => setLogo(e.target.checked)} /> لوگوی فروشگاه روی سینه {!ov.store.has_logo ? <span className="bc-muted">(لوگویی ثبت نشده)</span> : null}</label>
            </div>
            <div className="bc-row">
              <Button type="button" onClick={() => void create({ role, style, name, use_logo: logo })} disabled={busy !== null}>{busy === "create" ? <Spinner size={14} /> : null} بساز</Button>
              <Button type="button" variant="ghost" onClick={() => { setTab("ai"); setCreating(false); }}>یا با توصیفِ فارسی بساز</Button>
            </div>
            {mascots.length ? (
              <>
                <span className="bc-sub">یا یکی از ماسکوت‌های قبلی را بیاور (ماسکوت دست نمی‌خورد)</span>
                <div className="bc-chips">
                  {mascots.map((m) => <button key={m.id} type="button" className="bc-chip" disabled={busy !== null} onClick={() => void create({ from_mascot: m.id })}>{m.name} · {m.role_fa}</button>)}
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </Section>

      <div className="bce-tabs" role="tablist" aria-label="بخش‌های استودیو">
        {([["editor", "ویرایشگر"], ["ai", "ساخت با هوش مصنوعی"], ["versions", "نسخه‌ها و قفل"]] as const).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className="bc-chip" aria-pressed={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "editor" ? (
        sel ? <CharacterEditor id={id} ch={sel} ov={ov} onSaved={() => void reload(sel.id)} onReload={() => reload(sel.id)} /> : <Alert tone="info">اول یک شخصیت بسازید (دکمهٔ «شخصیتِ تازه») یا در سربرگِ «ساخت با هوش مصنوعی» توصیفش کنید.</Alert>
      ) : null}
      {tab === "ai" ? <AiTab onChosen={(c) => { void reload(c).then(() => setTab("editor")); }} /> : null}
      {tab === "versions" && sel ? <VersionsTab ch={sel} /> : null}
      {tab === "versions" && !sel ? <Alert tone="info">شخصیتی نیست.</Alert> : null}
    </div>
  );
}

// ───────────────────────────── نسخه‌ها

function VersionsTab({ ch }: { ch: Character }) {
  const { id, reload } = useBrandChar();
  const [items, setItems] = useState<{ version: number; note: string; created_at: string; style: string }[]>([]);
  const n = useNotice();
  const load = useCallback(() => { bcApi.versions(id, ch.id).then(setItems).catch(() => setItems([])); }, [id, ch.id]);
  useEffect(load, [load, ch.version]);
  return (
    <Section title="نسخه‌ها و قفل" hint="«تأییدِ ظاهر» در ویرایشگر یک نسخهٔ تازه می‌سازد. قفل‌بودن یعنی هیچ‌کس ظاهر را عوض نمی‌کند و همهٔ خروجی‌ها از همین نسخه‌اند.">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}
      <div className="bc-row">
        <Badge tone={ch.locked ? "ok" : "warn"}>{ch.locked ? `قفل · نسخهٔ ${fa(ch.version)}` : "قفل نیست"}</Badge>
        {ch.mascot ? <Badge tone="info">هم‌نام با ماسکوتِ #{fa(ch.mascot)}</Badge> : null}
        <Button type="button" variant="ghost" size="sm" onClick={() => void bcApi.publishMascot(id, ch.id).then(() => { n.ok("به‌عنوانِ ماسکوت (آدمک‌چوبی) هم ثبت شد؛ صفحهٔ «ماسکوتِ برند» و تامنیل‌ساز آن را می‌بینند."); return reload(ch.id); }).catch(n.fail)}>ثبت به‌عنوانِ ماسکوتِ قدیمی</Button>
      </div>
      {items.map((v) => (
        <div className="bc-row" key={v.version}>
          <Badge tone="info">v{fa(v.version)}</Badge>
          <span>{v.note || "تأییدِ ظاهر"}</span>
          <span className="bc-muted">{fmtDate(v.created_at)}</span>
          <Button type="button" variant="ghost" size="sm" disabled={ch.locked} onClick={() => void bcApi.restore(id, ch.id, v.version).then(() => { n.ok("ظاهرِ این نسخه بازگردانده شد (ذخیره شد)."); return reload(ch.id); }).catch(n.fail)}>بازگرداندن</Button>
        </div>
      ))}
      {!items.length ? <span className="bc-muted">هنوز نسخه‌ای تأیید نشده.</span> : null}
    </Section>
  );
}

// ───────────────────────────── خلقِ هوشمند

function AiTab({ onChosen }: { onChosen: (characterId: number) => void }) {
  const { id, ov, sel } = useBrandChar();
  const [desc, setDesc] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [concept, setConcept] = useState<Concept | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sheet, setSheet] = useState<RenderItem | null>(null);
  const n = useNotice();

  const make = async () => {
    setBusy("make");
    setSheet(null);
    try {
      setConcept(await bcApi.concepts(id, desc, useAi));
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };
  const choose = async (idx: number, title: string) => {
    if (!concept) return;
    setBusy(`choose${idx}`);
    try {
      const r = await bcApi.choose(id, concept.id, idx, title);
      setSheet(r.sheet ?? null);
      n.ok("شخصیت ساخته شد و برگهٔ مدلش آماده است.");
      onChosen(r.character.id);
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="bc-root" data-testid="ai-tab">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}
      <Section title="شخصیت را توصیف کنید" hint="فارسی بنویسید؛ مثلاً «مربیِ خندانِ موبلند با هدبندِ فیروزه‌ای و دمبل، لباسِ قرمز». چهار ایدهٔ دیداری با سبک‌های مختلف می‌سازیم؛ یکی را انتخاب کنید تا شخصیت و برگهٔ مدلش ساخته شود.">
        <TextArea rows={3} value={desc} maxLength={600} placeholder="شخصیتِ برندتان چه شکلی است؟" onChange={(e) => setDesc(e.target.value)} aria-label="توصیفِ شخصیت" />
        <div className="bc-row">
          <label className="bc-row" style={{ gap: 6 }}><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> با هوش مصنوعی هم کمک بگیر</label>
          <Button type="button" onClick={() => void make()} disabled={busy !== null || desc.trim().length < 3}>{busy === "make" ? <Spinner size={14} /> : null} چهار ایده بساز</Button>
          <span className="bc-muted">بدونِ هوش مصنوعی هم کار می‌کند (قاعده‌های فارسی)؛ رنگ‌ها از برندِ شما.</span>
        </div>
        {concept ? <p className="bc-note">{concept.source === "ai" ? "ایده‌ها با کمکِ هوش مصنوعی ساخته شد." : concept.note || "ایده‌ها با قاعده‌های فارسی ساخته شد."}</p> : null}
        {concept ? (
          <div className="bc-concepts" data-testid="concepts">
            {concept.options.map((o) => (
              <div key={o.index} className="bc-concept">
                {o.preview ? <img src={o.preview} alt={o.title} /> : null}
                <b>{o.title}</b>
                <p>{o.why}</p>
                <Badge tone={o.source === "ai" ? "info" : "neutral"}>{ov.options.styles.find((s) => s.key === o.doc.style)?.fa}</Badge>
                <Button type="button" variant="secondary" size="sm" onClick={() => void choose(o.index, o.title)} disabled={busy !== null}>{busy === `choose${o.index}` ? <Spinner size={14} /> : null} این را بساز + برگهٔ مدل</Button>
              </div>
            ))}
          </div>
        ) : null}
        {sheet?.asset?.url ? <div className="bc-previewbox"><img src={sheet.asset.url} alt="برگهٔ مدل" /></div> : null}
      </Section>
      {sel ? <AiRenderPanel /> : <Alert tone="info">برای ساختِ تصویرِ هوش مصنوعی اول یک شخصیت بسازید.</Alert>}
    </div>
  );
}

function AiRenderPanel() {
  const { id, ov, sel } = useBrandChar();
  const [mode, setMode] = useState("illustrated");
  const [look, setLook] = useState("");
  const [pose, setPose] = useState("stand");
  const [extra, setExtra] = useState("");
  const [jobs, setJobs] = useState<AiJob[]>([]);
  const [node, setNode] = useState<NodeStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const n = useNotice();
  const timer = useRef<number | null>(null);
  const cid = sel?.id ?? 0;

  const load = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await bcApi.aiJobs(id, cid);
      setJobs(r.items);
      setNode(r.node);
    } catch {
      /* خطا را کاربر با «تازه‌سازی» می‌بیند */
    }
  }, [id, cid]);

  useEffect(() => {
    void load();
  }, [load]);
  // تا وقتی کاری در صف یا در حالِ ساخت است هر ۷ ثانیه
  const active = jobs.some((j) => j.state === "queued" || j.state === "running");
  useEffect(() => {
    if (!active) return undefined;
    timer.current = window.setInterval(() => void load(), 7000);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [active, load]);

  if (!sel) return null;
  const start = async () => {
    setBusy(true);
    try {
      await bcApi.aiRender(id, sel.id, { mode, look: mode === "look" ? look : "", extra, pose, expression: "happy" });
      n.ok("کار در صفِ سرورِ پردازش گذاشته شد.");
      await load();
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="تصویرِ هوش مصنوعی از همین شخصیت" hint="شخصیتِ کدکشیده مرجع است و FLUX روی کارتِ گرافیکِ سرورِ پردازش آن را به سبکِ خواسته می‌برد؛ رنگ‌ها و ساختار حفظ می‌شود و نتیجه با برگهٔ قفل‌شده سنجیده می‌شود. شخصیتِ کدکشیده به این وابسته نیست.">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}
      {node ? (
        <div className="bc-note" data-testid="node-status">
          <b>{node.online ? "سرورِ پردازش روشن است" : node.known ? "سرورِ پردازش الان خاموش است" : "سرورِ پردازشی ثبت نشده"}</b> — {node.note}
          {node.profiles.length ? <> پروفایل‌های FLUX: {node.profiles.join("، ")}.</> : null}
          {node.identity_tools.length ? <> ابزارِ قفلِ هویت روی گره: {node.identity_tools.join("، ")}.</> : null}
          {!sel.locked ? <> <Badge tone="warn">پیشنهاد: اول ظاهر را «تأیید و قفل» کنید تا مرجعِ سنجش ثابت بماند.</Badge></> : null}
        </div>
      ) : null}
      <div className="bc-fields">
        <label className="bc-label">حالت<Select value={mode} onChange={(e) => setMode(e.target.value)}>{AI_MODES.map((m) => <option key={m.key} value={m.key}>{m.fa}</option>)}</Select></label>
        <label className="bc-label">ژستِ مرجع<Select value={pose} onChange={(e) => setPose(e.target.value)}>{ov.options.poses.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}</Select></label>
        <label className="bc-label wide">توضیحِ اضافه (اختیاری، انگلیسی یا فارسی)<Input value={extra} maxLength={200} placeholder="مثلاً: soft studio light" onChange={(e) => setExtra(e.target.value)} /></label>
      </div>
      {mode === "look" ? <LookPicker value={look} onChange={(l) => setLook(l)} kind="NEW_IMAGE" storeId={id} title="سبکِ تصویر" hint="یکی از ۱۱۶ سبک؛ شخصیت به همان سبک بازطراحی می‌شود." /> : null}
      <div className="bc-row">
        <Button type="button" onClick={() => void start()} disabled={busy || (mode === "look" && !look)}>{busy ? <Spinner size={14} /> : null} بسازِ تصویر</Button>
        <Button type="button" variant="ghost" onClick={() => void load()}>تازه‌سازی</Button>
        <Link className="bc-muted" to={`/stores/${id}/brand-character/gallery`}>همهٔ تصویرها در «گالری»</Link>
      </div>
      <div className="bc-list">
        {jobs.map((j) => (
          <div className="bc-job" key={j.id} data-testid="ai-job">
            {j.asset?.thumb ? <img src={j.sticker?.thumb ?? j.asset.thumb} alt="نتیجه" /> : <div className="bc-ph">{j.state === "failed" ? "ناموفق" : j.state === "running" ? "در حالِ ساخت" : "در صف"}</div>}
            <div className="bc-list">
              <div className="bc-row">
                <Badge tone={j.state === "done" ? "ok" : j.state === "failed" ? "bad" : j.state === "running" ? "info" : "warn"}>{j.state_fa}</Badge>
                <b>{j.mode_fa}{j.look_fa ? ` · ${j.look_fa}` : ""}</b>
                <span className="bc-muted">{fmtDate(j.created_at)}</span>
              </div>
              <span className="bc-muted">{j.error || j.message}</span>
              {j.state === "running" ? <div className="bc-bar"><i style={{ width: `${Math.round((j.progress || 0.05) * 100)}%` }} /></div> : null}
              {j.state === "done" && j.check ? (
                <div className="bc-row">
                  <Badge tone={j.check.ok ? "ok" : "warn"}>{j.check.ok ? "با شخصیتِ قفل‌شده می‌خواند" : "با شخصیتِ قفل‌شده کاملاً یکی نیست"}</Badge>
                  <span className="bc-muted">رنگ‌ها {j.check.palette_score != null ? fa(Math.round(j.check.palette_score * 100)) : "؟"}٪ · سیلوئت {j.check.silhouette != null ? fa(Math.round(j.check.silhouette * 100)) : "؟"}٪</span>
                </div>
              ) : null}
              {(j.check?.notes ?? []).map((t) => <span key={t} className="bc-muted">{t}</span>)}
              {j.asset?.url ? <a href={j.asset.url} target="_blank" rel="noreferrer" className="bc-muted">باز کردنِ تصویر</a> : null}
            </div>
          </div>
        ))}
        {!jobs.length ? <span className="bc-muted">هنوز تصویری ساخته نشده.</span> : null}
      </div>
    </Section>
  );
}
