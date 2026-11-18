import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Spinner, fa } from "../../../components/ui";
import { Code, DraftResult, Item, Mode, ReviewLine, Score, Target, downloadFile, i2cApi } from "./api";

type Tab = "compare" | "scores" | "code";
type CodeTab = "html" | "css" | "tree";

const VERDICT_TONE = { good: "ok", ok: "warn", weak: "bad" } as const;
const NO_FLAGS: ReviewLine[] = [];

/** تصویری که با ورودِ کاربر (توکن) گرفته می‌شود؛ <img src> ساده توکن نمی‌فرستد. ``name`` پیش‌نمایشِ سبک (WebP) است؛ اگر نشد PNGِ کامل می‌آید. */
function useBlobUrl(storeId: string, id: number, name: string, fallback: string, enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!enabled) {
      setUrl(null);
      return;
    }
    let dead = false;
    let made: string | null = null;
    setFailed(false);
    setUrl(null);
    i2cApi
      .blob(storeId, id, name)
      .catch(() => i2cApi.blob(storeId, id, fallback))
      .then((b) => {
        if (dead) return;
        made = URL.createObjectURL(b);
        setUrl(made);
      })
      .catch(() => !dead && setFailed(true));
    return () => {
      dead = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [storeId, id, name, fallback, enabled]);
  return { url, failed };
}

function Meter({ score }: { score: Score }) {
  const num = typeof score.value === "number" && score.value <= 1 ? score.value : null;
  return (
    <div className="i2c-score" data-testid="i2c-score" data-key={score.key} data-verdict={score.verdict}>
      <div className="i2c-score-top">
        <span className="i2c-score-label">{score.label}</span>
        <Badge tone={VERDICT_TONE[score.verdict]}>{score.verdict_fa}</Badge>
      </div>
      <div className="i2c-score-value">{score.display}</div>
      {num !== null && (
        <div className="i2c-meter" aria-hidden="true">
          <i style={{ width: `${Math.round(Math.max(0, Math.min(1, num)) * 100)}%` }} className={`is-${score.verdict}`} />
        </div>
      )}
      <p className="i2c-score-hint">{score.hint}</p>
    </div>
  );
}

const WHY_FA: Record<string, string> = {
  conf: "اطمینانِ خواندن کم بود",
  unknown: "واژه‌ای که در واژه‌نامه نیست (شاید یک حرف غلط باشد)",
  mixed: "حرفِ فارسی به عدد/لاتین چسبیده",
  stray: "نویسهٔ تکیِ کنارِ خط (شاید آیکون بوده)",
};

/** کادرِ زردِ خط‌های مشکوک رویِ تصویر؛ مختصات درصدیِ ابعادِ تصویرِ پردازش‌شده است، پس با هر اندازهٔ نمایش درست می‌ماند. */
function Flags({ lines, size, focus }: { lines: ReviewLine[]; size: [number, number]; focus: number | null }) {
  const [w, h] = size;
  if (w <= 0 || h <= 0) return null;
  return (
    <>
      {lines.map((l, i) => (
        <span
          key={i}
          className={`i2c-flag ${focus === i ? "is-focus" : ""}`}
          data-testid="i2c-flag"
          data-idx={i}
          title="این خط را بررسی کن"
          aria-label={`این خط را بررسی کن: ${l.text}`}
          style={{ left: `${(l.box[0] / w) * 100}%`, top: `${(l.box[1] / h) * 100}%`, width: `${(l.box[2] / w) * 100}%`, height: `${(l.box[3] / h) * 100}%` }}
        />
      ))}
    </>
  );
}

function ReviewList({ lines, count, focus, onFocus }: { lines: ReviewLine[]; count: number; focus: number | null; onFocus: (i: number) => void }) {
  return (
    <section className="i2c-review" data-testid="i2c-review" aria-label="خط‌های نیازمندِ بررسی">
      <h4>{fa(count)} خط از متن‌ها را با اطمینانِ کم خواندیم</h4>
      <p className="i2c-note">
        خواندنِ نوشته‌های ریزِ فارسی از روی عکس همیشه کامل نیست. این خط‌ها روی تصویر با کادرِ زرد نشان داده شده‌اند؛ متنشان را یک بار بخوانید و در صورتِ لزوم در سایت‌ساز یا کد درست کنید.
        برای متنِ دقیق، تبدیل را با «نشانیِ صفحه» انجام دهید.
      </p>
      <ul className="i2c-review-list">
        {lines.map((l, i) => (
          <li key={i}>
            <button type="button" className={`i2c-review-row ${focus === i ? "is-focus" : ""}`} onClick={() => onFocus(i)} data-testid="i2c-review-row" data-idx={i}>
              <Badge tone="warn">این خط را بررسی کن</Badge>
              <span className="i2c-review-text" dir="auto">{l.text || "(خالی)"}</span>
              <small>{l.why.map((k) => WHY_FA[k] ?? k).join(" · ")}{l.why.length ? " · " : ""}اطمینان {fa(Math.round(l.conf * 100))}٪</small>
            </button>
          </li>
        ))}
      </ul>
      {count > lines.length && <p className="i2c-note">{fa(count - lines.length)} خطِ دیگر هم مشکوک بود؛ فقط کم‌اطمینان‌ترین‌ها این‌جا آمده‌اند.</p>}
    </section>
  );
}

function SideBySide({ a, b, ratioA, ratioB, flags, size, focus }: { a: string; b: string | null; ratioA: number; ratioB: number; flags: ReviewLine[]; size: [number, number]; focus: number | null }) {
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  const lock = useRef(false);
  useEffect(() => {
    if (focus == null || !flags[focus] || size[1] <= 0) return;
    const pane = left.current;
    const img = pane?.querySelector("img");
    if (!pane || !img) return;
    pane.scrollTo({ top: Math.max(0, (flags[focus].box[1] / size[1]) * img.clientHeight - 80), behavior: "smooth" });
  }, [focus, flags, size]);
  function sync(from: HTMLDivElement | null, to: HTMLDivElement | null) {
    if (!from || !to || lock.current) return;
    lock.current = true;
    const span = from.scrollHeight - from.clientHeight;
    const frac = span > 0 ? from.scrollTop / span : 0;
    to.scrollTop = frac * Math.max(0, to.scrollHeight - to.clientHeight);
    to.scrollLeft = from.scrollLeft;
    window.requestAnimationFrame(() => {
      lock.current = false;
    });
  }
  return (
    <div className="i2c-side-by-side" data-testid="i2c-compare-side">
      <figure>
        <figcaption>تصویرِ اصلی</figcaption>
        <div className="i2c-pane" ref={left} onScroll={() => sync(left.current, right.current)} tabIndex={0} aria-label="تصویرِ اصلی (اسکرول‌پذیر)">
          <div className="i2c-imgwrap">
            <img src={a} alt="تصویرِ اصلی" style={{ aspectRatio: String(ratioA) }} />
            <Flags lines={flags} size={size} focus={focus} />
          </div>
        </div>
      </figure>
      <figure>
        <figcaption>نتیجهٔ ساخته‌شده</figcaption>
        <div className="i2c-pane" ref={right} onScroll={() => sync(right.current, left.current)} tabIndex={0} aria-label="نتیجهٔ ساخته‌شده (اسکرول‌پذیر)">
          {b ? (
            <div className="i2c-imgwrap">
              <img src={b} alt="نتیجهٔ ساخته‌شده" style={{ aspectRatio: String(ratioB) }} />
              <Flags lines={flags} size={size} focus={focus} />
            </div>
          ) : (
            <Spinner />
          )}
        </div>
      </figure>
    </div>
  );
}

function Slider({ a, b, ratio, flags, size, focus }: { a: string; b: string; ratio: number; flags: ReviewLine[]; size: [number, number]; focus: number | null }) {
  const [pos, setPos] = useState(50);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef(false);
  const move = useCallback((clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || r.width <= 0) return;
    setPos(Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100)));
  }, []);
  return (
    <div data-testid="i2c-compare-slider">
      <div
        className="i2c-slider"
        ref={box}
        style={{ aspectRatio: String(ratio) }}
        onPointerDown={(e) => {
          drag.current = true;
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          move(e.clientX);
        }}
        onPointerMove={(e) => drag.current && move(e.clientX)}
        onPointerUp={() => (drag.current = false)}
        onPointerCancel={() => (drag.current = false)}
      >
        <img src={a} alt="تصویرِ اصلی" draggable={false} className="i2c-slider-base" />
        <img src={b} alt="نتیجهٔ ساخته‌شده" draggable={false} className="i2c-slider-top" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} />
        <Flags lines={flags} size={size} focus={focus} />
        <span className="i2c-slider-handle" style={{ left: `${pos}%` }} aria-hidden="true" />
        <span className="i2c-slider-tag i2c-tag-l">نتیجه</span>
        <span className="i2c-slider-tag i2c-tag-r">اصلی</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(pos)}
        onChange={(e) => setPos(Number(e.target.value))}
        aria-label="لغزندهٔ مقایسه؛ چپ نتیجه، راست تصویرِ اصلی"
        data-testid="i2c-slider-range"
        className="i2c-range"
        dir="ltr"
      />
    </div>
  );
}

function CodePane({ storeId, item }: { storeId: string; item: Item }) {
  const [code, setCode] = useState<Code | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<CodeTab>("html");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let dead = false;
    i2cApi.code(storeId, item.id).then((c) => !dead && setCode(c)).catch((e) => !dead && setError(errorMessage(e)));
    return () => {
      dead = true;
    };
  }, [storeId, item.id]);
  const text = code ? code[tab] : "";
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("کپی نشد؛ متن را دستی انتخاب کنید.");
    }
  }
  return (
    <div data-testid="i2c-code">
      <ErrorBox message={error} />
      {!code && !error && <Spinner />}
      {code && (
        <>
          <div className="i2c-tabs">
            {(["html", "css", "tree"] as CodeTab[]).map((t) => (
              <button key={t} type="button" className={`u-btn u-btn-sm ${tab === t ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setTab(t)} data-testid={`i2c-code-${t}`}>
                {t === "html" ? "HTML" : t === "css" ? "CSS" : "درختِ اجزا (JSON)"}
              </button>
            ))}
            <Button size="sm" variant="ghost" onClick={() => void copy()} data-testid="i2c-copy">
              <Icon name="copy" size={14} /> {copied ? "کپی شد" : "کپی"}
            </Button>
          </div>
          {code.truncated && <Alert tone="info">متنِ بلند کوتاه نشان داده شد؛ همهٔ کد در فایلِ ZIP است.</Alert>}
          <pre className="i2c-pre" dir="ltr" tabIndex={0} data-testid="i2c-pre">{text || "(خالی)"}</pre>
        </>
      )}
    </div>
  );
}

function DraftDialog({ storeId, item, onClose, onDone }: { storeId: string; item: Item; onClose: () => void; onDone: (r: DraftResult) => void }) {
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [project, setProject] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    i2cApi.targets(storeId, item.id).then(setTargets).catch((e) => setError(errorMessage(e)));
  }, [storeId, item.id]);
  async function go() {
    setBusy(true);
    setError(null);
    try {
      onDone(await i2cApi.siteDraft(storeId, item.id, project));
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <div className="i2c-modal-bg" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="i2c-modal" role="dialog" aria-modal="true" aria-label="ساختِ صفحه در سایت‌ساز" data-testid="i2c-draft-modal">
        <h3>ساختِ صفحه در سایت‌ساز</h3>
        <p className="i2c-note">از درختِ اجزا یک <b>پیش‌نویس</b> ساخته می‌شود (بخش‌ها و بلوک‌هایی با متن‌ها، رنگ‌ها و تصویرهای واقعیِ همین تصویر). چیزی منتشر نمی‌شود.</p>
        {!targets && !error && <Spinner />}
        {targets && (
          <div className="i2c-targets">
            <label className={`i2c-target ${project === "" ? "is-on" : ""}`}>
              <input type="radio" name="i2c-target" checked={project === ""} onChange={() => setProject("")} data-testid="i2c-target-new" />
              <span><b>پروژهٔ تازه برای این فروشگاه</b><small>صفحهٔ اصلی + سربرگ + پابرگ + رنگ‌ها از تصویر</small></span>
            </label>
            {targets.map((t) => (
              <label key={t.slug} className={`i2c-target ${project === t.slug ? "is-on" : ""}`}>
                <input type="radio" name="i2c-target" checked={project === t.slug} onChange={() => setProject(t.slug)} data-testid="i2c-target-existing" />
                <span>
                  <b>صفحهٔ تازه در «{t.name}»</b>
                  <small>
                    {fa(t.pages)} صفحه دارد؛ پوسته‌اش دست نمی‌خورد.{" "}
                    {t.has_header && t.has_footer
                      ? "سربرگ و پابرگِ خودِ پروژه می‌ماند و سربرگ و پابرگِ تصویر در صفحه نمی‌آید (وگرنه دوتا می‌شد)."
                      : `${!t.has_header ? "سربرگ" : ""}${!t.has_header && !t.has_footer ? " و " : ""}${!t.has_footer ? "پابرگ" : ""} نداشت و از روی تصویر ساخته می‌شود.`}
                  </small>
                </span>
              </label>
            ))}
          </div>
        )}
        <ErrorBox message={error} />
        <div className="i2c-actions">
          <Button disabled={busy || !targets} onClick={() => void go()} data-testid="i2c-draft-confirm">{busy ? "در حال ساختن…" : "بساز"}</Button>
          <Button variant="secondary" disabled={busy} onClick={onClose}>بستن</Button>
        </div>
      </div>
    </div>
  );
}

/** نتیجهٔ یک تبدیل: مقایسه (کنارِ هم و لغزنده)، امتیازهای فارسی، کد، ZIP و دکمه‌های اصلی. */
export default function ResultView({
  storeId,
  item,
  canDraft,
  onChange,
  onAgain,
  onDeleted,
}: {
  storeId: string;
  item: Item;
  canDraft: boolean;
  onChange: (item: Item) => void;
  onAgain: (item: Item) => void;
  onDeleted: () => void;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("compare");
  const [view, setView] = useState<"side" | "slider">("side");
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const [done, setDone] = useState<DraftResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showFlags, setShowFlags] = useState(true);
  const [focus, setFocus] = useState<number | null>(null);
  const ready = item.state === "READY";
  const review = item.review && item.review.count > 0 ? item.review : null;
  const flags = showFlags && review ? review.lines : NO_FLAGS;
  const orig = useBlobUrl(storeId, item.id, "original.preview.webp", "original.png", ready && item.files.original);
  const rend = useBlobUrl(storeId, item.id, "rendered.preview.webp", "rendered.png", ready && item.files.rendered);
  const [w, h] = item.size;
  const ratioA = w > 0 && h > 0 ? w / h : 1;
  const ratioB = ratioA;
  const other: Mode = item.mode === "exact" ? "responsive" : "exact";

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const draft = done?.item.draft ?? item.draft;

  return (
    <Card className="i2c-result">
      <div data-testid="i2c-result" data-id={item.id}>
        <div className="i2c-result-head">
          <div className="i2c-result-title">
            <h2>{item.title || `تبدیلِ ${fa(item.id)}`}</h2>
            <div className="i2c-chips">
              <Badge tone={ready ? "ok" : item.state === "FAILED" ? "bad" : "neutral"}>{item.state_label}</Badge>
              <Badge tone="brand">{item.mode_label}</Badge>
              <Badge>زبان: {item.lang_label}</Badge>
              <Badge>{item.source_label}</Badge>
              {item.seconds != null && <Badge>{fa(Math.round(item.seconds * 10) / 10)} ثانیه</Badge>}
              {w > 0 && <Badge>{fa(w)}×{fa(h)}</Badge>}
            </div>
            {item.source_url && <p className="i2c-src" dir="ltr">{item.source_url}</p>}
          </div>
          <div className="i2c-result-actions">
            {ready && (
              <>
                <Button variant="secondary" disabled={busy === "zip"} onClick={() => void run("zip", () => downloadFile(storeId, item.id, "result.zip", `img2code-${item.id}.zip`))} data-testid="i2c-zip">
                  <Icon name="download" size={15} /> دانلود ZIP
                </Button>
                {canDraft ? (
                  <Button onClick={() => setDialog(true)} data-testid="i2c-draft-btn">
                    <Icon name="sparkle" size={15} /> {draft ? "ساختِ دوبارهٔ صفحه در سایت‌ساز" : "ساختِ صفحه در سایت‌ساز"}
                  </Button>
                ) : (
                  <Button disabled title="سایت‌ساز ابزارِ کارکنان است" data-testid="i2c-draft-btn">ساختِ صفحه در سایت‌ساز (فقط کارکنان)</Button>
                )}
                {item.ui_design && (
                  <Button
                    variant="secondary"
                    disabled={busy === "ui"}
                    title="یک سندِ طراحیِ UI/UX در استودیوی طراحی می‌سازد؛ تصویرها در آن جای‌تصویرند"
                    onClick={() =>
                      void run("ui", async () => {
                        if (item.ui_design?.path) {
                          navigate(item.ui_design.path);
                          return;
                        }
                        const r = await i2cApi.uiDesign(storeId, item.id);
                        onChange(r.item);
                        navigate(r.url);
                      })
                    }
                    data-testid="i2c-ui-design"
                  >
                    <Icon name="edit" size={15} /> {busy === "ui" ? "در حال ساختنِ طرح…" : item.ui_design.label}
                  </Button>
                )}
                <Button variant="secondary" disabled={busy === "again"} onClick={() => void run("again", async () => onAgain(await i2cApi.again(storeId, item.id, other)))} data-testid="i2c-again">
                  <Icon name="refresh" size={15} /> همین تصویر با حالتِ «{other === "exact" ? "دقیق" : "واکنش‌گرا"}»
                </Button>
              </>
            )}
            <Button
              variant="danger"
              disabled={busy === "del"}
              onClick={() => {
                if (!window.confirm("این تبدیل و فایل‌هایش پاک شود؟ (پیش‌نویسی که در سایت‌ساز ساخته‌اید می‌ماند.)")) return;
                void run("del", async () => {
                  await i2cApi.remove(storeId, item.id);
                  onDeleted();
                });
              }}
              data-testid="i2c-delete"
            >
              <Icon name="trash" size={15} /> حذف
            </Button>
          </div>
        </div>

        <ErrorBox message={error} />
        {item.state === "FAILED" && <Alert tone="bad" title="تبدیل ناموفق بود">{item.error || "دوباره امتحان کنید."}</Alert>}
        {item.state === "CANCELLED" && <Alert tone="neutral">این تبدیل لغو شد.</Alert>}
        {draft && (
          <Alert tone="ok" title="پیش‌نویسِ صفحه در سایت‌ساز هست (منتشر نشده)" action={<Link to={draft.url} className="u-btn u-btn-secondary u-btn-sm" data-testid="i2c-open-builder">باز کردن در سایت‌ساز</Link>}>
            {done ? (
              <span data-testid="i2c-draft-done">
                {done.created_project ? "یک پروژهٔ تازه با صفحهٔ اصلی، سربرگ و پابرگ ساخته شد. " : "یک صفحهٔ تازه به پروژه اضافه شد. "}
                {fa(done.stats.blocks ?? 0)} بلوک و {fa(done.stats.images ?? 0)} تصویر.
              </span>
            ) : (
              "هر وقت خواستید از همان‌جا ویرایش و (خودتان) منتشر کنید."
            )}
          </Alert>
        )}
        {done && done.warnings.length > 0 && (
          <Alert tone="warn" title="نکته‌ها">
            <ul className="i2c-list">{done.warnings.map((x) => <li key={x}>{x}</li>)}</ul>
          </Alert>
        )}

        {ready && (
          <>
            <div className="i2c-tabs" role="tablist" aria-label="بخش‌های نتیجه">
              {([["compare", "مقایسه"], ["scores", "امتیازها"], ["code", "کد"]] as [Tab, string][]).map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={tab === k} className={`u-btn ${tab === k ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setTab(k)} data-testid={`i2c-tab-${k}`}>
                  {l}
                </button>
              ))}
            </div>

            {tab === "compare" && (
              <div className="i2c-compare">
                {!item.files.rendered ? (
                  <Alert tone="warn" title="تصویرِ نتیجه نیست">{item.warnings.find((x) => x.includes("مرورگر")) ?? "مرورگرِ بی‌سرِ سرور آماده نبود؛ کد ساخته شد ولی تصویرِ مقایسه ندارد."}</Alert>
                ) : (
                  <>
                    <div className="i2c-tabs">
                      <button type="button" className={`u-btn u-btn-sm ${view === "side" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setView("side")} data-testid="i2c-view-side">کنارِ هم</button>
                      <button type="button" className={`u-btn u-btn-sm ${view === "slider" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setView("slider")} data-testid="i2c-view-slider">لغزنده (رویِ هم)</button>
                      {review && (
                        <label className="i2c-toggle">
                          <input type="checkbox" checked={showFlags} onChange={(e) => setShowFlags(e.target.checked)} data-testid="i2c-flags-toggle" />
                          <span>کادرِ زردِ «این خط را بررسی کن» ({fa(review.count)})</span>
                        </label>
                      )}
                    </div>
                    {orig.failed || rend.failed ? (
                      <ErrorBox message="تصویرها بارگذاری نشد؛ صفحه را تازه کنید." />
                    ) : view === "side" && orig.url ? (
                      <SideBySide a={orig.url} b={rend.url} ratioA={ratioA} ratioB={ratioB} flags={flags} size={item.size} focus={focus} />
                    ) : view === "slider" && orig.url && rend.url ? (
                      <Slider a={orig.url} b={rend.url} ratio={ratioA} flags={flags} size={item.size} focus={focus} />
                    ) : (
                      <p className="i2c-note i2c-loading" data-testid="i2c-loading"><Spinner /> در حال بارگذاریِ تصویرها…</p>
                    )}
                  </>
                )}
                {review && <ReviewList lines={review.lines} count={review.count} focus={focus} onFocus={(i) => setFocus(i)} />}
                {item.scores.length > 0 && (
                  <div className="i2c-brief" data-testid="i2c-brief">
                    {item.scores.filter((s) => ["ssim", "editable", "text"].includes(s.key)).map((s) => (
                      <span key={s.key} className={`i2c-brief-chip is-${s.verdict}`}>{s.label}: <b>{s.display}</b></span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === "scores" && (
              <div data-testid="i2c-scores">
                {item.scores.length === 0 && <Alert tone="info">امتیازی نیست (مرورگرِ سرور آماده نبود).</Alert>}
                <div className="i2c-score-grid">{item.scores.map((s) => <Meter key={s.key} score={s} />)}</div>
                {item.warnings.length > 0 && (
                  <Alert tone="warn" title="چند نکته">
                    <ul className="i2c-list">{item.warnings.map((x) => <li key={x}>{x}</li>)}</ul>
                  </Alert>
                )}
              </div>
            )}

            {tab === "code" && <CodePane storeId={storeId} item={item} />}
          </>
        )}

        {dialog && (
          <DraftDialog
            storeId={storeId}
            item={item}
            onClose={() => setDialog(false)}
            onDone={(r) => {
              setDialog(false);
              setDone(r);
              onChange(r.item);
            }}
          />
        )}
      </div>
    </Card>
  );
}
