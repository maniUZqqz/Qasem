import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import {
  Alert, Badge, Button, Card, EmptyState, Field, Input, SectionTitle, Select, Spinner, Table, TextArea, fa,
} from "../../../components/ui";
import { useAuthAudio } from "../useAuthAudio";
import { useAudio } from "../AudioLayout";
import {
  Convert, Depth, Entry, EngineInfo, EngineKey, EvalRun, Overview, Preview, Problem, Shared, WordRow,
  addProblem, convert, deleteEntry, deleteProblem, listen, listenResult, loadLexicon, loadOverview, loadProblems, loadRun,
  loadShared, patchProblem, preview, saveEntry, saveSettings, startRun,
} from "./api";

/**
 * «تلفظ» — لایهٔ تلفظِ فارسی پیش از هر موتورِ صدا.
 *
 * چهار بخش: آزمونِ پیش/پس (تایپ کن، بشنو، ببین چه عوض شد)، واژه‌نامه (مشترک + مالِ فروشگاه که مالک ویرایش می‌کند)،
 * مشکل‌دارها (از بررسی‌ها جمع می‌شود) و سنجشِ صدا ← تشخیصِ گفتار (نرخِ خطای واژه پیش و پس، برای هر موتور).
 * منطقِ اصلی در backend/services/audio/fa_pron است؛ این صفحه فقط آن را نشان می‌دهد و ویرایش می‌کند.
 */

const SAMPLE = "سلام. با چغر، چغرتر شو. معنی عادت خوب در عمل دیده می‌شود؛ ساعت ۱۴:۳۰ و ۳ ست ۱۲ تکرار.";

const SOURCE_FA: Record<string, string> = {
  store: "واژه‌نامهٔ فروشگاه", global: "واژه‌نامهٔ سکو", shared: "واژه‌نامهٔ مشترک", homograph: "هم‌نویسه (بر پایهٔ جمله)",
  phrase: "عبارت", morph: "ساخته‌شده از ریشه", rule: "قاعدهٔ حرف‌به‌حرف", conj: "حرفِ ربطِ «و»",
  letters: "نامِ حرف‌ها (سرواژه)",
};

const TAB_LABELS = [
  { key: "test", label: "آزمونِ تلفظ" },
  { key: "lexicon", label: "واژه‌نامه" },
  { key: "problems", label: "مشکل‌دار" },
  { key: "eval", label: "سنجشِ صدا" },
] as const;
type Tab = (typeof TAB_LABELS)[number]["key"];

const pct = (x: number | null | undefined) => (x == null ? "—" : `${fa((x * 100).toFixed(1))}٪`);

type Ctx = { storeId: string; ov: Overview; reload: () => Promise<void>; setError: (m: string | null) => void };

export default function PronunciationPage() {
  const { storeId, setError } = useAudio();
  const [ov, setOv] = useState<Overview | null>(null);
  const [tab, setTab] = useState<Tab>("test");
  // آزمونِ تلفظ متن و نتیجه‌اش را نگه می‌دارد، حتی وقتی به زبانهٔ دیگر می‌روید و برمی‌گردید
  const [testText, setTestText] = useState(SAMPLE);
  const [testRes, setTestRes] = useState<Preview | null>(null);
  const [testDepth, setTestDepth] = useState<Depth | "">("");

  const reload = useCallback(async () => {
    try {
      setOv(await loadOverview(storeId));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, setError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // سنجشِ در جریان: هر ۲۰ ثانیه نتیجه را تازه می‌کنیم
  const busy = ov?.runs.some((r) => r.state === "waiting" || r.state === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => void reload(), 20000);
    return () => clearInterval(t);
  }, [busy, reload]);

  if (!ov) {
    return (
      <div className="py-10 text-center">
        <Spinner />
      </div>
    );
  }
  const ctx: Ctx = { storeId, ov, reload, setError };
  return (
    <div className="space-y-4">
      <Header {...ctx} />
      <nav className="u-tabs">
        {TAB_LABELS.map((t) => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)} className={`u-tab ${tab === t.key ? "active" : ""}`}>
            {t.label}
            {t.key === "problems" && ov.counts.problems > 0 && <> ({fa(ov.counts.problems)})</>}
          </button>
        ))}
      </nav>
      {tab === "test" && <TestTab {...ctx} text={testText} setText={setTestText} res={testRes} setRes={setTestRes} depth={testDepth} setDepth={setTestDepth} />}
      {tab === "lexicon" && <LexiconTab {...ctx} />}
      {tab === "problems" && <ProblemsTab {...ctx} />}
      {tab === "eval" && <EvalTab {...ctx} />}
    </div>
  );
}

// ───────────────────────────────────────────────────────────── بالای صفحه: روشن/خاموش و عمقِ هر موتور

function Header({ storeId, ov, reload, setError }: Ctx) {
  const s = ov.settings;
  const patch = async (body: Parameters<typeof saveSettings>[1]) => {
    try {
      await saveSettings(storeId, body);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <Card>
      <SectionTitle>تلفظِ درستِ فارسی، پیش از هر صدا</SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        پیش از این‌که متن به موتورِ صدا برود، این لایه عدد و تاریخ و ساعت و قیمت و شماره‌تلفن را به واژه تبدیل می‌کند، حرف‌های عربی را فارسی می‌کند،
        واژه‌های لاتین را همان‌طور که ایرانی‌ها می‌گویند می‌نویسد و واژه‌هایی را که صدا اشتباه می‌خواند (ع، ه، و/او، ی، اضافه، هم‌نویسه‌ها) با آوای
        درست می‌دهد. هر موتور همان چیزی را می‌گیرد که خودش بهتر می‌فهمد: Piper آوا، Edge و MOSS متنِ بازنویسی‌شده.
      </p>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={s.enabled} onChange={(e) => void patch({ enabled: e.target.checked })} />
          لایهٔ تلفظ برای این فروشگاه روشن باشد
        </label>
        <label className="flex items-center gap-2 text-sm" title="کتابِ من ← کتابِ‌ من (-ِ یا -یِ بین اسم و صفت یا مضاف‌الیه)">
          <input type="checkbox" checked={s.ezafe} disabled={!s.enabled} onChange={(e) => void patch({ ezafe: e.target.checked })} />
          اضافه (کسرهٔ ربط) را هم بگذار
        </label>
        {ov.local_only && <Badge tone="warn">سیاستِ داده «فقط لوکال»: Edge در دسترس نیست</Badge>}
        <Badge tone={ov.node.online ? "ok" : "neutral"}>
          {ov.node.online ? `سرورِ پردازش روشن است (${ov.node.names.join("، ")})` : "سرورِ پردازش خاموش است؛ بخش‌های وابسته در صف می‌مانند"}
        </Badge>
      </div>
      {s.enabled && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {ov.engines.map((e) => (
            <Field key={e.key} label={e.label} hint={e.native}>
              <Select
                value={e.depth}
                onChange={(ev) => void patch({ depth: { ...s.depth, [e.key]: ev.target.value as Depth } })}
              >
                {(Object.keys(ov.depths) as Depth[]).map((d) => (
                  <option key={d} value={d}>
                    {ov.depths[d]}
                    {d === e.default_depth ? " (پیش‌فرض)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          ))}
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── آزمون

type Playing = { state: "idle" | "loading" | "queued" | "error"; msg?: string };

function ListenButton({ storeId, text, engine, variant, disabled, depth }: {
  storeId: string; text: string; engine: EngineKey; variant: "before" | "after"; disabled?: boolean; depth?: Depth | "";
}) {
  const audio = useAuthAudio();
  const [st, setSt] = useState<Playing>({ state: "idle" });
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const poll = useCallback(async (token: string) => {
    try {
      const r = await listenResult(storeId, token);
      if (r.state === "ready") {
        setSt({ state: "idle" });
        await audio.play(r.url);
      } else if (r.state === "failed") {
        setSt({ state: "error", msg: r.message });
      } else {
        timer.current = window.setTimeout(() => void poll(token), 4000);
      }
    } catch (err) {
      setSt({ state: "error", msg: errorMessage(err) });
    }
  }, [storeId, audio]);

  const go = async () => {
    setSt({ state: "loading" });
    try {
      const r = await listen(storeId, text, engine, variant, depth);
      if (r.state === "ready") {
        setSt({ state: "idle" });
        await audio.play(r.url);
      } else if (r.state === "failed") {
        setSt({ state: "error", msg: r.message });
      } else {
        setSt({ state: "queued", msg: "در صفِ سرورِ پردازش ..." });
        void poll(r.token);
      }
    } catch (err) {
      setSt({ state: "error", msg: errorMessage(err) });
    }
  };
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button size="sm" variant={variant === "after" ? "primary" : "secondary"} disabled={disabled || st.state === "loading" || st.state === "queued"} onClick={() => void go()}>
        <span className="inline-flex items-center gap-1">
          {st.state === "loading" || st.state === "queued" ? <Spinner size={14} /> : <Icon name="play" size={14} />}
          {variant === "before" ? "پیش از لایه" : "پس از لایه"}
        </span>
      </Button>
      {st.msg && <span className="text-xs" style={{ color: st.state === "error" ? "var(--bad)" : "var(--text-3)" }}>{st.msg}</span>}
    </span>
  );
}

function WordFix({ storeId, row, onSaved, setError }: { storeId: string; row: WordRow; onSaved: () => void; setError: (m: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(row.heard_as || row.text);
  const save = async () => {
    try {
      await saveEntry(storeId, { word: row.text, respelling: text });
      setOpen(false);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  if (!open) {
    return <Button size="sm" variant="ghost" onClick={() => setOpen(true)}><Icon name="edit" size={13} /> تصحیح</Button>;
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Input value={text} onChange={(e) => setText(e.target.value)} style={{ width: 140 }} dir="rtl" />
      <Button size="sm" onClick={() => void save()}>ذخیره</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>بستن</Button>
    </span>
  );
}

type TestState = {
  text: string; setText: (v: string) => void; res: Preview | null; setRes: (v: Preview | null) => void;
  depth: Depth | ""; setDepth: (v: Depth | "") => void;
};

function TestTab({ storeId, ov, reload, setError, text, setText, res, setRes, depth, setDepth }: Ctx & TestState) {
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (d: Depth | "" = depth) => {
    setBusy(true);
    setError(null);
    try {
      setRes(await preview(storeId, text, d));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [storeId, text, depth, setError, setRes]);

  useEffect(() => { if (!res) void run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const known = res?.words.filter((w) => w.pn && w.applied) ?? [];
  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>متن را بنویسید</SectionTitle>
        <TextArea value={text} onChange={(e) => setText(e.target.value)} rows={3} dir="rtl" maxLength={1500} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button onClick={() => void run()} disabled={busy || !text.trim()}>
            {busy ? "در حالِ بررسی ..." : "بررسی کن"}
          </Button>
          <label className="flex items-center gap-2 text-sm" title="فقط برای همین آزمون؛ تنظیمِ فروشگاه عوض نمی‌شود">
            <span style={{ color: "var(--text-2)" }}>عمقِ لایه در این آزمون</span>
            <Select value={depth} onChange={(ev) => { const d = ev.target.value as Depth | ""; setDepth(d); void run(d); }}>
              <option value="">طبقِ تنظیمِ فروشگاه</option>
              {(Object.keys(ov.depths) as Depth[]).map((d) => (<option key={d} value={d}>{ov.depths[d]}</option>))}
            </Select>
          </label>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            زیرِ هر موتور دو دکمه هست: همان متن بدونِ لایه، و پس از لایه؛ پشتِ‌سرِ‌هم بشنوید.
          </span>
        </div>
      </Card>

      {res && (
        <>
          <Card>
            <SectionTitle>متنی که موتور می‌گیرد</SectionTitle>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>پیش</div>
                <div className="rounded-lg p-3 text-sm leading-8" style={{ background: "var(--surface-2)" }}>{res.text}</div>
              </div>
              <div>
                <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>پس از نرمال‌سازی (عدد، تاریخ، ساعت، قیمت، لاتین، نشانه‌ها)</div>
                <div className="rounded-lg p-3 text-sm leading-8" style={{ background: "var(--surface-2)" }}>{res.normalized}</div>
              </div>
            </div>
            {res.latin_guesses.length > 0 && (
              <div className="mt-3">
                <Alert tone="warn" title="این واژه‌های لاتین را حدس زدم">
                  {res.latin_guesses.join("، ")} — اگر درست نیست، در «واژه‌نامه» بازنویسیِ درست را بنویسید.
                </Alert>
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle>موتورها: پیش و پس</SectionTitle>
            <div className="grid gap-4 lg:grid-cols-3">
              {ov.engines.map((e) => (
                <EngineCard key={e.key} engine={e} storeId={storeId} text={text} res={res} depth={depth} />
              ))}
            </div>
          </Card>

          <Card>
            <SectionTitle>چه واژه‌هایی عوض شد و چرا</SectionTitle>
            <p className="mb-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              این جدول همهٔ واژه‌هایی است که لایه می‌شناسد (عمقِ «واژه‌های شناخته‌شده»). هر موتور فقط در عمقِ خودش از آن‌ها استفاده می‌کند: در عمقِ پیش‌فرض
              (فقط نرمال‌سازی) تنها سرواژه‌ها و واژه‌های واژه‌نامهٔ خودِ فروشگاه عوض می‌شوند؛ برای شنیدنِ بقیه «عمقِ لایه در این آزمون» را روی
              «واژه‌های شناخته‌شده» بگذارید.
            </p>
            {known.length === 0 ? (
              <EmptyState icon="info" title="در این متن واژه‌ای نبود که لایه باید عوضش کند"
                action={<span className="text-sm" style={{ color: "var(--text-3)" }}>عدد و تاریخ و … هم بالا در «متنی که موتور می‌گیرد» دیده می‌شود.</span>} />
            ) : (
              <Table>
                <thead>
                  <tr><th>واژه</th><th>این‌طور خوانده می‌شود</th><th>از کجا</th><th /></tr>
                </thead>
                <tbody>
                  {known.map((w, i) => (
                    <tr key={`${w.text}-${i}`}>
                      <td><b>{w.text}</b></td>
                      <td style={{ fontSize: 17 }}>{w.heard_as}{w.ezafe && <span style={{ color: "var(--text-3)" }}> (+ اضافه)</span>}</td>
                      <td><Badge tone={w.source === "store" ? "brand" : "neutral"}>{SOURCE_FA[w.source] ?? w.source}</Badge></td>
                      <td><WordFix storeId={storeId} row={w} setError={setError} onSaved={() => { void run(); void reload(); }} /></td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            {res.unknown.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>
                  {fa(res.unknown.length)} واژه در واژه‌نامه نیست (خودِ موتور می‌خواندشان) — اگر یکی را غلط خواند، این‌جا تصحیح کنید
                </summary>
                <div className="mt-2 flex flex-wrap gap-2">
                  {Array.from(new Set(res.unknown)).slice(0, 40).map((w) => (
                    <span key={w} className="inline-flex items-center gap-1 rounded-lg px-2 py-1" style={{ background: "var(--surface-2)" }}>
                      {w}
                      <WordFix storeId={storeId} row={{ text: w, pn: "", source: "", ezafe: false, applied: true, heard_as: w }} setError={setError}
                        onSaved={() => { void run(); void reload(); }} />
                      <Button size="sm" variant="ghost" title="گزارش: درست خوانده نمی‌شود"
                        onClick={async () => { try { await addProblem(storeId, w, text); await reload(); } catch (err) { setError(errorMessage(err)); } }}>
                        <Icon name="warn" size={13} />
                      </Button>
                    </span>
                  ))}
                </div>
              </details>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function EngineCard({ engine, storeId, text, res, depth }: { engine: EngineInfo; storeId: string; text: string; res: Preview; depth: Depth | "" }) {
  const info = res.engines[engine.key];
  const after = info?.ipa || info?.text;
  return (
    <div className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <b className="text-sm">{engine.label}</b>
        <Badge tone={engine.local ? "ok" : "info"}>{engine.local ? "لوکال" : "آنلاین"}</Badge>
        {info && <Badge>{({ normalize: "فقط نرمال‌سازی", lexicon: "واژه‌های شناخته‌شده", full: "همه" } as Record<string, string>)[info.depth]}</Badge>}
      </div>
      <div className="mb-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>{engine.native}</div>
      {engine.blocked ? (
        <Alert tone="warn">سیاستِ دادهٔ این فروشگاه «فقط لوکال» است؛ این موتور متن را بیرون می‌فرستد.</Alert>
      ) : (
        <>
          <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>{info?.ipa ? "آوایی که به Piper می‌دهیم (IPA)" : "متنی که به موتور می‌دهیم"}</div>
          <div className="mb-3 max-h-40 overflow-auto rounded-lg p-2 text-sm leading-7" dir={info?.ipa ? "ltr" : "rtl"}
            style={{ background: "var(--surface-2)", fontFamily: info?.ipa ? "monospace" : undefined }}>
            {after || "—"}
          </div>
          {engine.key === "piper" && (info?.engine_words ?? 0) > 0 && (
            <div className="mb-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              واژه‌های میانِ ‹ › را لایه نمی‌شناسد؛ خودِ صدا (espeak) هنگامِ ساخت می‌خواندشان ({fa(info?.engine_words ?? 0)} واژه).
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <ListenButton storeId={storeId} text={text} engine={engine.key} variant="before" depth={depth} />
            <ListenButton storeId={storeId} text={text} engine={engine.key} variant="after" depth={depth} />
          </div>
        </>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────── واژه‌نامه

function LexiconTab({ storeId, ov, reload, setError }: Ctx) {
  const [rows, setRows] = useState<Entry[] | null>(null);
  const [scope, setScope] = useState<"store" | "global">("store");
  const [word, setWord] = useState("");
  const [resp, setResp] = useState("");
  const [note, setNote] = useState("");
  const [conv, setConv] = useState<Convert | null>(null);
  const [convErr, setConvErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await loadLexicon(storeId, scope));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, scope, setError]);
  useEffect(() => { void load(); }, [load]);

  // تبدیلِ زنده هنگام تایپ
  useEffect(() => {
    if (!resp.trim()) { setConv(null); setConvErr(null); return; }
    const t = window.setTimeout(async () => {
      try { setConv(await convert(storeId, resp)); setConvErr(null); } catch (err) { setConv(null); setConvErr(errorMessage(err)); }
    }, 350);
    return () => window.clearTimeout(t);
  }, [resp, storeId]);

  const reset = () => { setWord(""); setResp(""); setNote(""); setEditing(null); };
  const save = async () => {
    try {
      await saveEntry(storeId, { word, respelling: resp, note, scope }, editing ?? undefined);
      reset();
      await load();
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>{editing ? "ویرایشِ واژه" : "افزودنِ واژه به واژه‌نامهٔ فروشگاه"}</SectionTitle>
        <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
          واژه را همان‌طور که در متن می‌آید بنویسید و زیرش بنویسید چطور خوانده شود، با فارسیِ ساده: کوتاه‌صداها را با
          ـَ (زبر) ـِ (زیر) ـُ (پیش) بگذارید و ع را همان ع بنویسید؛ مثلاً «چغر» ← «چَغَر»، «معنی» ← «مَعنی». حروفِ لاتینِ ساده
          (مثلاً <span dir="ltr">Caqar</span>) هم پذیرفته می‌شود. واژه‌نامهٔ فروشگاه بر واژه‌نامهٔ مشترک مقدم است.
        </p>
        <p className="mb-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          فهرستِ سادهٔ «تلفظ اسم‌ها» در <Link to={`/stores/${storeId}/voice`} style={{ color: "var(--brand)" }}>صدا و گوینده</Link> هم
          کار می‌کند (نامِ برندِ لاتین را «همان‌طور که می‌گویید» جایگزین می‌کند) و پیش از این واژه‌نامه اعمال می‌شود؛ برای واژه‌هایی که
          ع، ه، او، ی یا اضافه دارند همین‌جا بنویسید.
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="واژه (همان‌طور که نوشته می‌شود)"><Input value={word} onChange={(e) => setWord(e.target.value)} dir="rtl" maxLength={80} /></Field>
          <Field label="بازنویسی ساده (چطور خوانده شود)"><Input value={resp} onChange={(e) => setResp(e.target.value)} dir="rtl" maxLength={160} /></Field>
          <Field label="یادداشت (اختیاری)"><Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} /></Field>
        </div>
        <div className="mt-3 min-h-[2.5rem] text-sm">
          {conv && (
            <span>
              خوانده می‌شود: <b style={{ fontSize: 18 }}>{conv.respelling}</b>
              <span className="mx-2" style={{ color: "var(--text-3)" }}>·</span>
              <span dir="ltr" style={{ fontFamily: "monospace" }}>{conv.ipa}</span>
              <span className="mx-2" style={{ color: "var(--text-3)" }}>·</span>
              {fa(conv.syllables)} هجا
            </span>
          )}
          {convErr && <span style={{ color: "var(--bad)" }}>{convErr}</span>}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button onClick={() => void save()} disabled={!word.trim() || !resp.trim() || !!convErr}>{editing ? "ذخیرهٔ تغییر" : "افزودن"}</Button>
          {editing && <Button variant="ghost" onClick={reset}>انصراف</Button>}
          {ov.is_staff && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={scope === "global"} onChange={(e) => setScope(e.target.checked ? "global" : "store")} />
              افزودهٔ سراسری (برای همهٔ فروشگاه‌ها؛ فقط کارمند)
            </label>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle>{scope === "global" ? "افزوده‌های سراسری" : "واژه‌نامهٔ این فروشگاه"} {rows && <>({fa(rows.length)})</>}</SectionTitle>
        {rows === null ? <div className="py-6 text-center"><Spinner /></div> : rows.length === 0 ? (
          <EmptyState icon="mic" title="هنوز واژه‌ای اضافه نکرده‌اید"
            action={<span className="text-sm" style={{ color: "var(--text-3)" }}>اسمِ برند، محصول یا کلمه‌هایی که صدا غلط می‌خواند را این‌جا بنویسید.</span>} />
        ) : (
          <Table>
            <thead><tr><th>واژه</th><th>بازنویسی</th><th>خوانده می‌شود</th><th>یادداشت</th><th /></tr></thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} style={{ opacity: e.enabled ? 1 : 0.5 }}>
                  <td><b>{e.word}</b></td>
                  <td>{e.respelling}</td>
                  <td style={{ fontSize: 17 }}>{e.heard_as}</td>
                  <td className="text-xs" style={{ color: "var(--text-3)" }}>{e.note}</td>
                  <td className="whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => { setEditing(e.id); setWord(e.word); setResp(e.respelling); setNote(e.note); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                      <Icon name="edit" size={13} />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={async () => { try { await deleteEntry(storeId, e.id); await load(); await reload(); } catch (err) { setError(errorMessage(err)); } }}>
                      <Icon name="trash" size={13} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <SharedList storeId={storeId} total={ov.counts.shared} setError={setError} />
    </div>
  );
}

function SharedList({ storeId, total, setError }: { storeId: string; total: number; setError: (m: string | null) => void }) {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [data, setData] = useState<Shared | null>(null);
  useEffect(() => {
    const t = window.setTimeout(async () => {
      try { setData(await loadShared(storeId, q, cat)); } catch (err) { setError(errorMessage(err)); }
    }, 250);
    return () => window.clearTimeout(t);
  }, [storeId, q, cat, setError]);
  return (
    <Card>
      <SectionTitle>واژه‌نامهٔ مشترک ({fa(total)} واژه؛ فقط‌خواندنی)</SectionTitle>
      <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
        واژه‌هایی که صدا در آن‌ها زیاد اشتباه می‌کند: ع و ء، «ه» پایانی، و/او، ی، عددها، ترتیبی‌ها، واژه‌های ورزش و برنامه. اگر واژه‌ای
        را جور دیگر می‌گویید، در واژه‌نامهٔ فروشگاه بنویسید؛ آن مقدم است.
      </p>
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Input placeholder="جست‌وجو (واژه یا بازنویسی)" value={q} onChange={(e) => setQ(e.target.value)} dir="rtl" />
        <Select value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">همهٔ دسته‌ها</option>
          {data?.categories.map((c) => <option key={c.name} value={c.name}>{c.name} ({fa(c.count)})</option>)}
        </Select>
      </div>
      {data === null ? <div className="py-6 text-center"><Spinner /></div> : (
        <>
          <div className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>{fa(data.total)} نتیجه{data.total > data.rows.length ? ` (${fa(data.rows.length)} تای اول)` : ""}</div>
          <Table>
            <thead><tr><th>واژه</th><th>خوانده می‌شود</th><th>IPA</th><th>دسته</th></tr></thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={`${r.word}-${i}`}>
                  <td><b>{r.word}</b></td>
                  <td style={{ fontSize: 17 }}>{r.respelling}</td>
                  <td dir="ltr" style={{ fontFamily: "monospace" }}>{r.ipa}</td>
                  <td className="text-xs" style={{ color: "var(--text-3)" }}>{r.category}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── مشکل‌دار

function ProblemRow({ p, storeId, onChange, setError }: { p: Problem; storeId: string; onChange: () => void; setError: (m: string | null) => void }) {
  const [resp, setResp] = useState("");
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); onChange(); } catch (err) { setError(errorMessage(err)); }
  };
  return (
    <tr style={{ opacity: p.status === "open" ? 1 : 0.55 }}>
      <td><b>{p.word}</b> {p.count > 1 && <Badge>{fa(p.count)} بار</Badge>}</td>
      <td><Badge tone={p.source === "latin" ? "warn" : "neutral"}>{p.source_label}</Badge></td>
      <td className="text-xs leading-6" style={{ color: "var(--text-3)", maxWidth: 320 }}>{p.detail || p.context}</td>
      <td className="whitespace-nowrap">
        {p.status === "open" ? (
          <span className="inline-flex flex-wrap items-center gap-1">
            <Input value={resp} onChange={(e) => setResp(e.target.value)} placeholder="بازنویسی درست" dir="rtl" style={{ width: 150 }} />
            <Button size="sm" disabled={!resp.trim()} onClick={() => void act(() => patchProblem(storeId, p.id, { respelling: resp }))}>افزودن به واژه‌نامه</Button>
            <Button size="sm" variant="ghost" onClick={() => void act(() => patchProblem(storeId, p.id, { status: "ignored" }))}>نادیده</Button>
          </span>
        ) : (
          <Badge tone={p.status === "fixed" ? "ok" : "neutral"}>{p.status === "fixed" ? "حل شد" : "نادیده"}</Badge>
        )}
        <Button size="sm" variant="ghost" onClick={() => void act(() => deleteProblem(storeId, p.id))}><Icon name="trash" size={13} /></Button>
      </td>
    </tr>
  );
}

function ProblemsTab({ storeId, reload, setError }: Ctx) {
  const [rows, setRows] = useState<Problem[] | null>(null);
  const [all, setAll] = useState(false);
  const [word, setWord] = useState("");
  const load = useCallback(async () => {
    try { setRows(await loadProblems(storeId, all ? "all" : "open")); } catch (err) { setError(errorMessage(err)); }
  }, [storeId, all, setError]);
  useEffect(() => { void load(); }, [load]);
  const changed = () => { void load(); void reload(); };
  return (
    <Card>
      <SectionTitle action={
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />حل‌شده‌ها و نادیده‌ها هم</label>
      }>واژه‌های مشکل‌دار</SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        این فهرست خودش پر می‌شود: واژه‌های لاتینی که تلفظشان را حدس زدیم، و واژه‌هایی که تشخیصِ گفتار در سنجشِ صدا چند بار نشنید. هر کدام را با
        بازنویسیِ درست به واژه‌نامه ببرید تا از آن به بعد درست خوانده شود.
      </p>
      <div className="mb-3 flex flex-wrap gap-2">
        <Input placeholder="گزارشِ دستیِ یک واژه" value={word} onChange={(e) => setWord(e.target.value)} dir="rtl" style={{ maxWidth: 260 }} />
        <Button variant="secondary" disabled={!word.trim()} onClick={async () => { try { await addProblem(storeId, word); setWord(""); changed(); } catch (err) { setError(errorMessage(err)); } }}>
          <Icon name="plus" size={14} /> افزودن به فهرست
        </Button>
      </div>
      {rows === null ? <div className="py-6 text-center"><Spinner /></div> : rows.length === 0 ? (
        <EmptyState icon="ok" title="واژهٔ مشکل‌داری نیست" action={<span className="text-sm" style={{ color: "var(--text-3)" }}>با هر متن و هر سنجش، این فهرست پر می‌شود.</span>} />
      ) : (
        <Table>
          <thead><tr><th>واژه</th><th>منبع</th><th>توضیح</th><th /></tr></thead>
          <tbody>{rows.map((p) => <ProblemRow key={p.id} p={p} storeId={storeId} onChange={changed} setError={setError} />)}</tbody>
        </Table>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── سنجش

const STATE_TONE = { waiting: "warn", running: "info", done: "ok", failed: "bad" } as const;

function Delta({ d }: { d?: number }) {
  if (d == null) return <>—</>;
  const better = d < 0;
  return <span style={{ color: better ? "var(--ok)" : d > 0 ? "var(--bad)" : "var(--text-3)" }}>{d > 0 ? "+" : ""}{fa((d * 100).toFixed(1))}٪</span>;
}

function EvalTab({ storeId, ov, reload, setError }: Ctx) {
  const [open, setOpen] = useState<EvalRun | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const tagName = useMemo(() => ov.tags, [ov.tags]);

  const start = async (engine: EngineKey, sample: "quick" | "full") => {
    setStarting(`${engine}-${sample}`);
    setError(null);
    try {
      await startRun(storeId, engine, sample);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(null);
    }
  };
  const show = async (r: EvalRun) => {
    try { setOpen(await loadRun(storeId, r.id)); } catch (err) { setError(errorMessage(err)); }
  };

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>صدا ← تشخیصِ گفتار ← نرخِ خطای واژه</SectionTitle>
        <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
          هر یک از {fa(ov.counts.sentences)} جملهٔ ثابتِ آزمون (پر از ع، ه، و/او، ی، اضافه، عدد، تاریخ، قیمت، تلفن، واژهٔ لاتین و هم‌نویسه) دو بار گفته می‌شود: بدونِ لایه
          و با لایه. تشخیصِ گفتار (Whisper روی کارتِ سرورِ پردازش) هر دو را گوش می‌دهد و می‌شمارد چند واژه را درست شنید. «نرخِ خطای واژه»
          هرچه کمتر، صدا روشن‌تر. این عدد «طبیعی بودن» را نمی‌سنجد، فقط می‌گوید شنونده (ماشین) واژه‌ها را درست می‌فهمد یا نه.
        </p>
        {!ov.node.online && (
          <Alert tone="info" title="سرورِ پردازش خاموش است">
            سنجش در صفِ ماندگار می‌ماند و با روشن شدنِ سرور خودش اجرا می‌شود؛ نصبِ Piper و مدلِ Whisper را هم خودِ سرور انجام می‌دهد.
            تا آن موقع نتیجهٔ اولیه‌ای که همراهِ نسخه آمده (در پایین، «اولیه») دیده می‌شود.
          </Alert>
        )}
      </Card>

      <Card>
        <SectionTitle>آخرین نتیجه برای هر موتور</SectionTitle>
        <Table>
          <thead>
            <tr><th>موتور</th><th>صدا</th><th>عمقِ لایه</th><th>خطا پیش</th><th>خطا پس</th><th>تغییر</th><th>جمله</th><th>تشخیصِ گفتار</th><th>اجرا</th><th /></tr>
          </thead>
          <tbody>
            {ov.engines.map((e) => {
              const r = ov.latest[e.key];
              const o = r?.summary.overall;
              return (
                <tr key={e.key}>
                  <td><b>{e.label}</b>{r?.baseline && <> <Badge>اولیه</Badge></>}</td>
                  <td className="text-xs">
                    <span dir="ltr">{r?.voice || "—"}</span>
                    {r && e.key === "piper" && r.voice && !ov.site_voices.includes(r.voice.replace(/\.onnx$/, "")) && (
                      <> <Badge tone="warn">روی این سایت نصب نیست</Badge></>
                    )}
                  </td>
                  <td className="text-xs">{r?.depth ? ov.depths[r.depth as Depth] ?? r.depth : "—"}</td>
                  <td>{pct(o?.before)}</td>
                  <td><b>{pct(o?.after)}</b></td>
                  <td><Delta d={o?.delta} /></td>
                  <td>{r ? fa(r.n) : "—"}</td>
                  <td className="text-xs" style={{ color: "var(--text-3)" }}>{r?.asr || "—"}</td>
                  <td className="whitespace-nowrap">
                    {r && <Button size="sm" variant="ghost" onClick={() => void show(r)}>جزئیات</Button>}
                    <Button size="sm" variant="secondary" disabled={e.blocked || starting !== null} onClick={() => void start(e.key, "quick")}>
                      {starting === `${e.key}-quick` ? <Spinner size={13} /> : "سنجشِ سریع"}
                    </Button>
                    {ov.is_staff && (
                      <Button size="sm" variant="ghost" disabled={e.blocked || starting !== null} onClick={() => void start(e.key, "full")}>
                        {starting === `${e.key}-full` ? <Spinner size={13} /> : "کامل"}
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          «سریع» ۲ جمله از هر دسته ({fa(ov.counts.quick)} جمله) است؛ «کامل» همهٔ جمله‌ها (فقط کارمند). Edge متن را به مایکروسافت می‌فرستد (جمله‌های
          آزمون عمومی‌اند) و روی فروشگاهِ «فقط لوکال» کار نمی‌کند (دکمه‌اش خاموش است و سرور هم نمی‌پذیرد).
        </p>
        <p className="mt-1 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          هر عدد برای <b>یک صدا و یک عمقِ لایه</b> است؛ عددِ یک صدا را به صدای دیگر نسبت ندهید. صداهای Piperِ نصب‌شده روی این سایت: <span dir="ltr">{ov.site_voices.join("، ") || "—"}</span>.
          نتیجهٔ «اولیه» با تشخیصِ گفتارِ کوچکِ Vosk روی سایت اندازه‌گیری شده؛ جدولِ Whisper روی کارتِ گره، با روشن شدنش، جایش را می‌گیرد.
        </p>
      </Card>

      <Card>
        <SectionTitle>سابقهٔ سنجش‌ها</SectionTitle>
        {ov.runs.length === 0 ? <EmptyState icon="chart" title="هنوز سنجشی نیست" /> : (
          <div className="flex flex-col gap-2">
            {ov.runs.map((r) => (
              <button key={r.id} type="button" onClick={() => void show(r)} className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 text-right"
                style={{ background: "var(--surface-2)" }}>
                <span className="text-sm"><b>{ov.engines.find((e) => e.key === r.engine)?.label ?? r.engine}</b>{r.voice && <> · <span dir="ltr">{r.voice}</span></>} · {r.depth ? (ov.depths[r.depth as Depth] ?? r.depth) : ""} · {r.sample === "full" ? "کامل" : "سریع"} · {fa(r.n)} جمله {r.baseline && <Badge>اولیه</Badge>}</span>
                <span className="flex items-center gap-2">
                  {r.state === "done" ? <span className="text-sm">{pct(r.summary.overall?.before)} ← <b>{pct(r.summary.overall?.after)}</b></span> : <span className="text-xs" style={{ color: "var(--text-3)" }}>{r.message}</span>}
                  <Badge tone={STATE_TONE[r.state]}>{r.state_label}</Badge>
                </span>
              </button>
            ))}
          </div>
        )}
      </Card>

      {open && <RunDetails run={open} tags={tagName} onClose={() => setOpen(null)} />}
    </div>
  );
}

function RunDetails({ run, tags, onClose }: { run: EvalRun; tags: Record<string, string>; onClose: () => void }) {
  const s = run.summary;
  const rows = run.rows ?? [];
  const sample = rows.filter((r) => r.before != null && r.after != null).slice(0, 12);
  return (
    <Card>
      <SectionTitle action={<Button variant="ghost" size="sm" onClick={onClose}>بستن</Button>}>
        جزئیاتِ سنجش — {run.engine === "piper" ? "Piper" : run.engine === "edge" ? "Edge" : "MOSS"} {run.voice && <span dir="ltr">({run.voice})</span>}
      </SectionTitle>
      <div className="mb-3 flex flex-wrap gap-2 text-sm">
        <Badge tone={STATE_TONE[run.state]}>{run.state_label}</Badge>
        {run.asr && <Badge>تشخیصِ گفتار: {run.asr}</Badge>}
        {run.where && <Badge>اجرا: {run.where}</Badge>}
        {run.depth && <Badge>عمقِ لایه: {run.depth}</Badge>}
        {run.baseline && <Badge tone="brand">نتیجهٔ اولیهٔ همراهِ نسخه (Vosk کوچک، روی Piper)</Badge>}
      </div>
      {run.message && <div className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>{run.message}</div>}
      {s.by_tag && ["ayn", "he", "vav", "ezafe", "ezw"].some((k) => s.by_tag?.[k]) && (
        <div className="mb-3 rounded-lg p-3 text-sm leading-7" style={{ background: "var(--surface-2)" }}>
          <b>دسته‌های شکایتِ مالک (ع، ه، او، اضافه)، خطای واژه پیش ← پس:</b>{" "}
          {["ayn", "he", "vav", "ezafe", "ezw"].filter((k) => s.by_tag?.[k]).map((k) => (
            <span key={k} className="ml-3 inline-block">
              {tags[k] ?? k}: {pct(s.by_tag?.[k]?.before)} ← <b>{pct(s.by_tag?.[k]?.after)}</b> (<Delta d={s.by_tag?.[k]?.delta} />)
            </span>
          ))}
        </div>
      )}
      {s.by_tag && (
        <Table>
          <thead><tr><th>دسته</th><th>جمله</th><th>خطا پیش</th><th>خطا پس</th><th>تغییر</th></tr></thead>
          <tbody>
            {Object.entries(s.by_tag).map(([t, v]) => (
              <tr key={t}>
                <td>{tags[t] ?? t}</td><td>{fa(v.n)}</td><td>{pct(v.before)}</td><td>{pct(v.after)}</td><td><Delta d={v.delta} /></td>
              </tr>
            ))}
            <tr style={{ fontWeight: 700 }}>
              <td>همه</td><td>{fa(s.overall?.n ?? 0)}</td><td>{pct(s.overall?.before)}</td><td>{pct(s.overall?.after)}</td><td><Delta d={s.overall?.delta} /></td>
            </tr>
          </tbody>
        </Table>
      )}
      {sample.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>نمونه جمله‌ها: متن، آنچه بدونِ لایه شنیده شد، آنچه با لایه شنیده شد</summary>
          <div className="mt-2 flex flex-col gap-2">
            {sample.map((r) => (
              <div key={r.id} className="rounded-lg p-3 text-sm leading-7" style={{ background: "var(--surface-2)" }}>
                <div><b>متن:</b> {r.ref}</div>
                <div style={{ color: "var(--text-2)" }}><b>پیش:</b> {r.before}</div>
                <div><b>پس:</b> {r.after}</div>
              </div>
            ))}
          </div>
        </details>
      )}
      {s.worse && s.worse.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>{fa(s.worse.length)} جمله با لایه بدتر شنیده شد</summary>
          <ul className="mt-2 list-disc pr-5 text-sm leading-7">
            {s.worse.map((w, i) => <li key={i}>{w.ref} — {fa(w.before)} ← {fa(w.after)} خطا ({tags[w.tag] ?? w.tag})</li>)}
          </ul>
        </details>
      )}
    </Card>
  );
}
