import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import ModeSwitch, { useEditorMode } from "../../../components/ModeSwitch";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  fa,
} from "../../../components/ui";
import CompareSlider from "./CompareSlider";
import BatchPanel from "./designer/BatchPanel";
import DesignerPanel from "./designer/DesignerPanel";
import EditorSettings from "./designer/EditorSettings";
import { PhotoAutoPanel, PhotoPromptPanel } from "./ModePanels";
import { smartChipText } from "./ResultCard";
import PhotoWorkspace from "./manual/PhotoWorkspace";
import ProWorkspace from "./pro/ProWorkspace";
import SourcePicker from "./SourcePicker";
import {
  ACTIVE_STATES,
  Asset,
  Edit,
  NodeStatus,
  Operation,
  Overview,
  Params,
  Sources,
  Tool,
  photoApi,
  stateTone,
} from "./api";

/**
 * ادیتورِ عکس — سه حالت: «خودکار» (یک کلیک)، «نیمه‌خودکار» (دستور به هوشِ مصنوعی) و «دستی» (فضای کاملِ فتوشاپ‌مانند).
 *
 * دو جا کار می‌کند و صفحه این را پنهان نمی‌کند: کارهای سبک (برش برای شبکه‌ها، اندازه، متن، لوگو، واترمارک،
 * نور و رنگِ ساده) همین حالا روی سرورِ سایت انجام می‌شود؛ کارهای کیتِ PersianAiKit.Photo (بهبودِ حرفه‌ای،
 * حذفِ پس‌زمینه، بزرگ‌نمایی، ترمیم، ویرایش با دستور) به سرورِ پردازش می‌رود و اگر خاموش است «منتظر» می‌ماند.
 * هر کار برچسبِ جایش را دارد تا کسی منتظرِ چیزی نماند که نمی‌داند منتظرش است.
 */
let webgl2: boolean | null = null;
/** ادیتورِ حرفه‌ای به WebGL2 نیاز دارد؛ مرورگرِ بی‌آن همان فضای کارِ قبلی را می‌گیرد */
function hasWebGL2(): boolean {
  if (webgl2 === null) {
    try {
      webgl2 = !!document.createElement("canvas").getContext("webgl2");
    } catch {
      webgl2 = false;
    }
  }
  return webgl2;
}

export default function PhotoEditorPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [mode, setMode] = useEditorMode("nm.photo.mode");
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [manualStart, setManualStart] = useState<{ n: number; ops: { tool: string; params: Params }[] } | null>(null);
  const [picker, setPicker] = useState<null | "products" | "generated">(null);
  const [tracking, setTracking] = useState<Edit[]>([]);
  const [lastBatch, setLastBatch] = useState<string | null>(null);
  const [node, setNode] = useState<NodeStatus | null>(null);
  const [detail, setDetail] = useState<Asset | null>(null);
  const [compareId, setCompareId] = useState<number | null>(null);
  const [sources, setSources] = useState<Sources | null>(null);
  /** بازکردنِ پروژهٔ تازهٔ «طراحِ خودکار» در حالتِ دستی: کلیدِ فضای کار عوض می‌شود تا پروژه از سرور دوباره خوانده شود */
  const [reloadKey, setReloadKey] = useState(0);
  const [settingsTab, setSettingsTab] = useState<"ai" | "brand" | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [promptTab, setPromptTabState] = useState<"design" | "quick">(() => {
    try {
      return localStorage.getItem("nm.photo.prompttab") === "quick" ? "quick" : "design";
    } catch {
      return "design";
    }
  });
  const setPromptTab = (t: "design" | "quick") => {
    setPromptTabState(t);
    try {
      localStorage.setItem("nm.photo.prompttab", t);
    } catch {
      /* حافظهٔ مرورگر بسته است */
    }
  };
  const fileInput = useRef<HTMLInputElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const tools = useMemo(() => {
    const m: Record<string, Tool> = {};
    data?.tools.forEach((t) => (m[t.key] = t));
    return m;
  }, [data]);

  const load = useCallback(async () => {
    try {
      const d = await photoApi.overview(id);
      setData(d);
      setNode(d.node);
      setTracking((cur) => {
        const known = new Set(cur.map((e) => e.id));
        return [...cur, ...d.active.filter((e) => !known.has(e.id))];
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = useCallback(
    async (assetId: number, scroll = true, focusEdit?: number) => {
      try {
        const a = await photoApi.asset(id, assetId);
        setDetail(a);
        const ready = a.edits?.find((e) => e.state === "READY");
        const focus = focusEdit ? a.edits?.find((e) => e.id === focusEdit && e.state === "READY") : undefined;
        setCompareId((cur) =>
          focus ? focus.id : cur && a.edits?.some((e) => e.id === cur) ? cur : ready?.id ?? null,
        );
        if (!sources) photoApi.sources(id).then(setSources).catch(() => undefined);
        if (scroll) window.setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
      } catch (err) {
        setError(errorMessage(err));
      }
    },
    [id, sources],
  );

  // نسخه‌های در حالِ کار: هر ۳ ثانیه (سرورِ سایت چند ثانیه، سرورِ پردازش ممکن است ساعت‌ها)
  const activeIds = tracking.filter((e) => ACTIVE_STATES.includes(e.state)).map((e) => e.id);
  const analysisPending = detail && ["QUEUED", "CLAIMED", "RUNNING"].includes(detail.kit_analysis?.state ?? "");
  useEffect(() => {
    if (activeIds.length === 0 && !analysisPending) return;
    const t = window.setInterval(async () => {
      try {
        if (activeIds.length) {
          const res = await photoApi.edits(id, activeIds);
          setNode(res.node);
          const finished = res.edits.filter((e) => !e.active);
          setTracking((cur) => cur.map((e) => res.edits.find((x) => x.id === e.id) ?? e));
          if (finished.length) {
            await load();
            const mine = detail ? finished.filter((e) => e.asset === detail.id) : [];
            // نسخه‌ای که همین حالا آماده شد ⇐ همان در قبل/بعد
            if (detail && mine.length) await openDetail(detail.id, false, mine[mine.length - 1].id);
          }
        } else if (detail) {
          await openDetail(detail.id, false);
        }
      } catch {
        /* شبکه: دورِ بعد */
      }
    }, 3000);
    return () => window.clearInterval(t);
  }, [id, activeIds.join(","), analysisPending, detail, load, openDetail]);

  async function upload(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await photoApi.upload(id, files);
      setNotice(`${fa(res.assets.length)} عکس به کتابخانه آمد.` + (res.errors.length ? ` ${res.errors.join(" ")}` : ""));
      setSelected(res.assets.map((a) => a.id));
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  /**
   * ساختِ نسخه برای عکس‌های انتخاب‌شده (هر سه حالت از همین‌جا می‌گذرند).
   * ops = null ⇒ سرور برای هر عکس از روی اندازه‌گیریِ خودش می‌چیند («پیشنهادی»). ⇐ جملهٔ خطا، یا null اگر شروع شد.
   */
  const runEdits = useCallback(
    async (recipe: string, ops: Operation[] | null, assetIds?: number[]): Promise<string | null> => {
      const ids = assetIds ?? selected;
      if (ids.length === 0) return "اول یک عکس انتخاب کنید.";
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        const res = ops ? await photoApi.apply(id, ids, recipe, ops) : await photoApi.applyRecipe(id, ids, recipe);
        setNode(res.node);
        setTracking((cur) => [...res.edits, ...cur.filter((e) => !res.edits.some((x) => x.id === e.id))]);
        setLastBatch(res.batch);
        // تازه ثبت‌شده‌ها هنوز «در صف» اند؛ این‌که کجا می‌روند از کارهایشان پیداست
        const waiting = res.edits.filter((e) => e.state === "NODE" || (e.state === "QUEUED" && e.needs_node)).length;
        const ready = res.edits.filter((e) => e.state === "READY").length;
        const working = res.edits.filter((e) => e.state === "SERVER" || (e.state === "QUEUED" && !e.needs_node)).length;
        setNotice(
          [
            ready ? `${fa(ready)} عکس آماده شد.` : "",
            working ? `${fa(working)} عکس روی سرورِ سایت در کار است (چند ثانیه).` : "",
            waiting
              ? res.node.online
                ? `${fa(waiting)} عکس به سرورِ پردازش رفت.`
                : `${fa(waiting)} عکس منتظرِ سرورِ پردازش می‌ماند (الان خاموش است).`
              : "",
          ].filter(Boolean).join(" "),
        );
        await load();
        if (ids.length === 1) await openDetail(ids[0], false, res.edits[0]?.id);
        return null;
      } catch (err) {
        const msg = errorMessage(err);
        setError(msg);
        return msg;
      } finally {
        setBusy(false);
      }
    },
    [id, selected, load, openDetail],
  );

  async function downloadZip(batch: string) {
    try {
      const blob = await photoApi.zip(id, batch);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `photos-${batch.slice(0, 8)}.zip`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (loading) return <Spinner />;
  if (!data) return <ErrorBox message={error ?? "بارگذاری نشد."} />;

  const assets = data.assets;
  const nodeOn = (node ?? data.node).online;
  const batchEdits = lastBatch ? tracking.filter((e) => e.batch === lastBatch) : [];
  const focusAsset = selected.length ? assets.find((a) => a.id === selected[0]) ?? null : null;

  /** تازه‌ترین نسخهٔ یک عکس: از نسخه‌های در حالِ پیگیری یا آخرین نسخهٔ کتابخانه */
  const latest = (assetId: number): Edit | null => {
    const lib = assets.find((a) => a.id === assetId)?.last_edit ?? null;
    const cands = [...tracking.filter((e) => e.asset === assetId), ...(lib ? [lib] : [])];
    let best: Edit | null = null;
    for (const e of cands) if (!best || e.number > best.number) best = e;
    return best;
  };

  /** بعد از «اعمال» ِ یک طراحی (تکی یا از طراحیِ گروهی) */
  const onDesignApplied = (edit: Edit, openManual: boolean) => {
    setTracking((cur) => [edit, ...cur.filter((e) => e.id !== edit.id)]);
    setLastBatch(edit.batch);
    void load();
    if (openManual) {
      setSelected([edit.asset]);
      setReloadKey((k) => k + 1);
      setMode("manual");
      setBatchOpen(false);
      // فضای کار بالای صفحه است؛ کاربر را همان‌جا ببر
      window.setTimeout(() => document.querySelector('[data-testid="photo-workspace"]')?.scrollIntoView({ behavior: "smooth", block: "start" }), 500);
    }
  };

  const panelProps = {
    storeId: id, data, tools, selected, nodeOn, busy, run: runEdits, latest, asset: focusAsset,
    openManual: (steps: Operation[]) => {
      setManualStart({ n: Date.now(), ops: steps.map((o) => ({ tool: o.tool, params: o.params })) });
      setMode("manual");
    },
  };

  return (
    <>
      <PageHeader
        title="ادیتور عکس"
        subtitle="عکس بدهید — برای اینستاگرام، استوری و فروشگاه آماده‌اش می‌کنیم: خودکار، با یک دستور، یا خودتان با ابزارهای کامل"
        actions={
          <>
            <Button variant="secondary" onClick={() => setBatchOpen((v) => !v)} data-testid="open-batch">طراحیِ گروهی</Button>
            <Button variant="secondary" onClick={() => setSettingsTab("ai")} data-testid="open-settings">تنظیمات و سبکِ برند</Button>
            <Link to={`/stores/${id}/editor`}>
              <Button variant="secondary">ادیتور ویدیو</Button>
            </Link>
            <Link to={`/stores/${id}`}>
              <Button variant="secondary">بازگشت</Button>
            </Link>
          </>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <div className="mb-4" data-testid="node-banner">
        {nodeOn ? (
          <Alert tone="ok" title="سرورِ پردازش آنلاین است">
            کارهای هوشمندِ کیت (بهبودِ حرفه‌ای، حذفِ پس‌زمینه، بزرگ‌نمایی) همین حالا روی{" "}
            {(node ?? data.node).nodes.join("، ")} انجام می‌شود. «ویرایش با دستور» طبقِ ترتیبِ تنظیماتِ هوش مصنوعی یا روی سرورِ پردازش
            یا از سرورِ سایت (متیس/لوکال) انجام می‌شود و بالای نتیجه می‌نویسیم چه کسی جواب داد.
          </Alert>
        ) : (
          <Alert tone="warn" title="سرورِ پردازش خاموش است">
            کارهای سبک — برش برای شبکه‌ها، اندازه، چرخش، متن، لوگو، واترمارک و نور و رنگِ ساده — و «ویرایش با دستور» (هوشِ مصنوعیِ بینا از
            سرورِ سایت: لوکال یا متیس طبقِ تنظیماتِ هوش مصنوعی) همین‌جا روی سرورِ سایت انجام می‌شود. بقیهٔ کارهای هوشمندِ کیت (برچسبِ
            «سرورِ پردازش»: بهبودِ حرفه‌ای، حذفِ پس‌زمینه، بزرگ‌نمایی) در صف می‌مانند تا سرورِ پردازش روشن شود؛ صفحه را می‌توانید ببندید.
          </Alert>
        )}
      </div>

      {batchOpen && <BatchPanel storeId={id} assets={assets} onClose={() => setBatchOpen(false)} onApplied={onDesignApplied} onOpenSettings={(t) => setSettingsTab(t)} />}
      {settingsTab && <EditorSettings storeId={id} assets={assets} initialTab={settingsTab} onClose={() => setSettingsTab(null)} />}

      <ModeSwitch
        mode={mode}
        onChange={setMode}
        hints={{
          auto: "عکس را می‌سنجد و خودش ادیت می‌زند — یک کلیک",
          prompt: "بنویسید چه می‌خواهید؛ طراحِ خودکار چند پیشنهادِ آماده با متنِ فارسی می‌سازد",
          manual: "فضای کامل: لایه، ماسک، برش، منحنی، ترمیم، فیلتر و منوی کامل…",
        }}
      />

      {mode === "manual" && focusAsset && (
        <div className="mb-6">
          {hasWebGL2() ? (
          <ProWorkspace
            key={`${focusAsset.id}-${manualStart?.n ?? 0}-${reloadKey}`}
            storeId={id}
            asset={focusAsset}
            assets={assets}
            onPick={(aid) => setSelected([aid])}
            tools={tools}
            kit={data.kit}
            nodeOn={nodeOn}
            nodeNames={(node ?? data.node).nodes}
            lastEdit={latest(focusAsset.id)}
            busy={busy}
            onBuild={async (ops, recipe) => {
              const err = await runEdits(recipe, ops, [focusAsset.id]);
              if (err) throw new Error(err);
            }}
            onOpenVersions={() => void openDetail(focusAsset.id)}
            startFrom={manualStart?.ops ?? null}
            storeLogo={data.store_logo}
            onOpenSettings={(t) => setSettingsTab(t)}
            onOpenBatch={() => setBatchOpen(true)}
            onNewPhoto={(a) => {
              void load().then(() => setSelected([a.id]));
              setNotice(`عکسِ تازه «${a.title}» در کتابخانه ساخته شد و باز است.`);
            }}
          />
          ) : (
          <PhotoWorkspace
            key={focusAsset.id}
            storeId={id}
            asset={focusAsset}
            assets={assets}
            onPick={(aid) => setSelected([aid])}
            tools={tools}
            kit={data.kit}
            nodeOn={nodeOn}
            nodeNames={(node ?? data.node).nodes}
            lastEdit={latest(focusAsset.id)}
            busy={busy}
            onBuild={async (ops, recipe) => {
              const err = await runEdits(recipe, ops, [focusAsset.id]);
              if (err) throw new Error(err);
            }}
            onOpenVersions={() => void openDetail(focusAsset.id)}
            startFrom={manualStart?.ops ?? null}
          />
          )}
        </div>
      )}

      <Card>
        <SectionTitle>عکسِ تازه</SectionTitle>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff,image/gif"
            multiple
            hidden
            disabled={busy}
            data-testid="photo-upload"
            onChange={(e) => void upload(Array.from(e.target.files ?? []))}
          />
          <Button onClick={() => fileInput.current?.click()} disabled={busy}>
            آپلودِ عکس‌ها
          </Button>
          <Button variant="secondary" onClick={() => setPicker(picker === "products" ? null : "products")}>
            از عکس‌های محصول
          </Button>
          <Button variant="secondary" onClick={() => setPicker(picker === "generated" ? null : "generated")}>
            از تصویرهای ساخته‌شده
          </Button>
        </div>
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          JPEG، PNG، WebP — هر عکس تا {fa(data.limits.max_upload_mb)} مگابایت؛ چند عکس با هم هم می‌شود. اصلِ
          عکس هرگز عوض نمی‌شود؛ هر ویرایش یک نسخهٔ تازه است.
        </p>
        {picker && (
          <SourcePicker
            storeId={id}
            mode={picker}
            onClose={() => setPicker(null)}
            onDone={(made, errs) => {
              setPicker(null);
              setNotice(`${fa(made.length)} عکس در کتابخانه است.` + (errs.length ? ` ${errs.join(" ")}` : ""));
              setSelected(made.map((a) => a.id));
              void load();
            }}
          />
        )}
        {busy && (
          <div className="mt-3 flex items-center gap-2">
            <Spinner size={18} />
            <span className="text-sm" style={{ color: "var(--text-2)" }}>در حالِ کار…</span>
          </div>
        )}
      </Card>

      <div className="mt-6">
        <SectionTitle>کتابخانهٔ عکس‌ها</SectionTitle>
        {assets.length > 0 && (
          <div className="-mt-1 mb-3 flex flex-wrap items-center gap-2">
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              {fa(selected.length)} از {fa(assets.length)} انتخاب شده — روی عکس بزنید تا انتخاب شود
              {mode === "manual" ? " (در حالتِ دستی، اولین عکسِ انتخاب‌شده باز می‌شود)" : ""}
            </span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setSelected(assets.slice(0, data.limits.max_batch).map((a) => a.id))}
            >
              انتخابِ همه
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
              هیچ‌کدام
            </Button>
          </div>
        )}
        {assets.length === 0 ? (
          <Card>
            <EmptyState
              icon="image"
              title="هنوز عکسی نیست"
              description="یک عکس از محصولتان آپلود کنید یا از عکس‌های محصول بیاورید."
            />
          </Card>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="photo-library">
            {assets.map((a) => (
              <AssetCard
                key={a.id}
                asset={a}
                live={tracking.find((e) => e.asset === a.id && e.active) ?? null}
                checked={selected.includes(a.id)}
                onToggle={() =>
                  setSelected((cur) => (cur.includes(a.id) ? cur.filter((x) => x !== a.id) : [...cur, a.id]))
                }
                onOpen={() => void openDetail(a.id)}
              />
            ))}
          </div>
        )}
      </div>

      {mode === "auto" && <PhotoAutoPanel {...panelProps} />}
      {mode === "prompt" && (
        <>
          <div className="dz-tabs mt-4" role="tablist" aria-label="نوعِ ویرایش با دستور" data-testid="prompt-tabs">
            <button type="button" role="tab" className="dz-tab" aria-selected={promptTab === "design"} onClick={() => setPromptTab("design")} data-ptab="design">
              طراحِ خودکار — متن، زمینه، برچسب و قاب
            </button>
            <button type="button" role="tab" className="dz-tab" aria-selected={promptTab === "quick"} onClick={() => setPromptTab("quick")} data-ptab="quick">
              اصلاحِ سریعِ نور و رنگ
            </button>
          </div>
          {promptTab === "design" ? (
            <DesignerPanel
              storeId={id}
              asset={focusAsset}
              nodeOn={nodeOn}
              assets={assets}
              onOpenSettings={(t) => setSettingsTab(t)}
              onApplied={onDesignApplied}
            />
          ) : (
            <PhotoPromptPanel {...panelProps} />
          )}
        </>
      )}
      {mode === "manual" && !focusAsset && (
        <Card className="mt-4">
          <EmptyState icon="image" title="یک عکس انتخاب کنید" description="از کتابخانه یک عکس بزنید تا فضای کارِ دستی برایش باز شود." />
        </Card>
      )}

      {tracking.length > 0 && (
        <div className="mt-6" data-testid="jobs">
          <SectionTitle
            action={
              lastBatch &&
              batchEdits.some((e) => e.state === "READY") && (
                <Button size="sm" variant="secondary" onClick={() => void downloadZip(lastBatch)}>
                  دانلودِ همه (zip)
                </Button>
              )
            }
          >
            کارها
          </SectionTitle>
          <div className="flex flex-col gap-2">
            {tracking.slice(0, 12).map((e) => (
              <JobRow
                key={e.id}
                edit={e}
                asset={assets.find((a) => a.id === e.asset)}
                onCancel={async () => {
                  try {
                    const res = await photoApi.action(id, e.id, "cancel");
                    setTracking((cur) => cur.map((x) => (x.id === e.id ? res.edit : x)));
                    void load();
                  } catch (err) {
                    setError(errorMessage(err));
                  }
                }}
                onOpen={() => void openDetail(e.asset, true, e.id)}
              />
            ))}
          </div>
        </div>
      )}

      {detail && (
        <div ref={detailRef} className="mt-6">
          <AssetDetail
            storeId={id}
            asset={detail}
            compareId={compareId}
            setCompareId={setCompareId}
            sources={sources}
            onChanged={async (msg) => {
              if (msg) setNotice(msg);
              await load();
              await openDetail(detail.id, false);
            }}
            onError={setError}
            onTrack={(e) => setTracking((cur) => [e, ...cur])}
            onClose={() => setDetail(null)}
            onRemoved={async () => {
              setDetail(null);
              setSelected((cur) => cur.filter((x) => x !== detail.id));
              await load();
            }}
          />
        </div>
      )}
    </>
  );
}

function AssetCard({
  asset,
  live,
  checked,
  onToggle,
  onOpen,
}: {
  asset: Asset;
  live: Edit | null;
  checked: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const last = live ?? asset.last_edit ?? null;
  const shown = last?.state === "READY" && last.urls.thumb ? last.urls.thumb : asset.thumb;
  return (
    <div
      className="overflow-hidden rounded-xl"
      style={{ border: `2px solid ${checked ? "var(--brand)" : "var(--line)"}`, background: "var(--surface)" }}
      data-asset={asset.id}
    >
      <button type="button" className="relative block w-full" onClick={onToggle} aria-pressed={checked}>
        <img src={shown} alt={asset.title} loading="lazy" className="h-36 w-full object-cover" />
        <span
          className="absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-md text-xs"
          style={{ background: checked ? "var(--brand)" : "rgba(255,255,255,.85)", color: checked ? "white" : "#333" }}
        >
          {checked ? "✓" : ""}
        </span>
        {last && (
          <span className="absolute bottom-2 left-2">
            <Badge tone={stateTone(last.state)}>
              {last.state === "NODE" ? "منتظرِ سرورِ پردازش" : `نسخهٔ ${fa(last.number)}: ${last.state_label}`}
            </Badge>
          </span>
        )}
      </button>
      <div className="p-2">
        <div className="truncate text-sm font-bold" style={{ color: "var(--text)" }} title={asset.title}>
          {asset.title}
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge tone="neutral">{asset.source_label}</Badge>
          <Badge tone="neutral">{fa(asset.width)}×{fa(asset.height)}</Badge>
          {asset.findings.slice(0, 2).map((f) => (
            <Badge key={f.what} tone={f.what === "plain_bg" ? "info" : "warn"}>
              {f.note.split(" (")[0]}
            </Badge>
          ))}
        </div>
        <Button size="sm" variant="ghost" className="mt-1" onClick={onOpen}>
          باز کن{asset.edits_count ? ` (${fa(asset.edits_count)} نسخه)` : ""}
        </Button>
      </div>
    </div>
  );
}

function JobRow({
  edit,
  asset,
  onCancel,
  onOpen,
}: {
  edit: Edit;
  asset?: Asset;
  onCancel: () => void;
  onOpen: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl p-2" style={{ border: "1px solid var(--line)" }} data-edit={edit.id}>
      <img src={edit.urls.thumb ?? asset?.thumb} alt="" className="h-12 w-12 rounded-lg object-cover" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-bold" style={{ color: "var(--text)" }}>
            {asset?.title ?? `عکس ${fa(edit.asset)}`} — نسخهٔ {fa(edit.number)}
          </span>
          <Badge tone={stateTone(edit.state)}>{edit.state_label}</Badge>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>{edit.recipe_title}</span>
        </div>
        <div className="text-xs" style={{ color: edit.state === "FAILED" ? "var(--bad)" : "var(--text-2)" }}>
          {edit.state === "FAILED" ? edit.error : edit.message}
        </div>
        {edit.active && (
          <div className="mt-1 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.round(edit.progress * 100)}%`, background: edit.state === "NODE" ? "var(--warn)" : "var(--brand)" }}
            />
          </div>
        )}
      </div>
      <div className="flex gap-1">
        {edit.state === "READY" && edit.urls.result && (
          <a href={edit.urls.result} download>
            <Button size="sm" variant="secondary">دانلود</Button>
          </a>
        )}
        <Button size="sm" variant="ghost" onClick={onOpen}>باز کن</Button>
        {edit.active && (
          <Button size="sm" variant="ghost" onClick={onCancel}>لغو</Button>
        )}
      </div>
    </div>
  );
}

const MEASURES: { key: string; label: string; fmt: (v: number) => string }[] = [
  { key: "p50", label: "روشناییِ میانه (۰–۲۵۵)", fmt: (v) => fa(Math.round(v)) },
  { key: "contrast", label: "کنتراست (فاصلهٔ تیره تا روشن)", fmt: (v) => fa(Math.round(v)) },
  { key: "clip_hi", label: "سفیدِ سوخته (٪)", fmt: (v) => fa(Math.round(v * 1000) / 10) },
  { key: "cast_rb", label: "رنگ‌زدگیِ زرد/آبی", fmt: (v) => fa(Math.round(v)) },
  { key: "saturation", label: "اشباعِ رنگ", fmt: (v) => fa(Math.round(v)) },
  { key: "sharpness", label: "تیزی", fmt: (v) => fa(Math.round(v)) },
  { key: "noise", label: "نویز", fmt: (v) => fa(Math.round(v * 10) / 10) },
];

function AssetDetail({
  storeId,
  asset,
  compareId,
  setCompareId,
  sources,
  onChanged,
  onError,
  onTrack,
  onClose,
  onRemoved,
}: {
  storeId: string;
  asset: Asset;
  compareId: number | null;
  setCompareId: (id: number | null) => void;
  sources: Sources | null;
  onChanged: (msg?: string) => Promise<void>;
  onError: (msg: string | null) => void;
  onTrack: (e: Edit) => void;
  onClose: () => void;
  onRemoved: () => Promise<void>;
}) {
  const edits = asset.edits ?? [];
  const current = edits.find((e) => e.id === compareId) ?? null;
  const [productId, setProductId] = useState<string>(asset.product ? String(asset.product) : "");
  const [working, setWorking] = useState(false);
  const products = sources?.products ?? [];

  useEffect(() => {
    setProductId(asset.product ? String(asset.product) : products[0] ? String(products[0].id) : "");
  }, [asset.id, asset.product, products.length]);

  async function act(e: Edit, action: string, body: Record<string, unknown> = {}, msg?: string) {
    setWorking(true);
    onError(null);
    try {
      const res = await photoApi.action(storeId, e.id, action, body);
      if (res.new) onTrack(res.new);
      await onChanged(msg);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  const ka = asset.kit_analysis ?? {};
  return (
    <Card>
      <div data-testid="asset-detail">
        <SectionTitle
          action={
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  if (!window.confirm(`«${asset.title}» و همهٔ نسخه‌هایش حذف شود؟`)) return;
                  await photoApi.removeAsset(storeId, asset.id);
                  await onRemoved();
                }}
              >
                حذفِ عکس
              </Button>
              <Button size="sm" variant="secondary" onClick={onClose}>بستن</Button>
            </div>
          }
        >
          {asset.title}
        </SectionTitle>

        {current?.state === "READY" && current.urls.preview ? (
          <CompareSlider
            before={asset.preview}
            after={current.urls.preview}
            beforeSize={[asset.width, asset.height]}
            afterSize={current.size}
          />
        ) : (
          <img
            src={asset.preview}
            alt={asset.title}
            className="mx-auto block max-h-[60vh] max-w-full rounded-xl"
            style={{ background: "var(--surface-2)" }}
          />
        )}

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
              اندازه‌گیری {current?.after ? `— اصل و نسخهٔ ${fa(current.number)}` : "— اصل"}
            </div>
            <table className="u-table w-full text-sm">
              <thead>
                <tr>
                  <th />
                  <th>اصل</th>
                  {current?.after && <th>نسخهٔ {fa(current.number)}</th>}
                </tr>
              </thead>
              <tbody>
                {MEASURES.map((m) => (
                  <tr key={m.key}>
                    <td style={{ color: "var(--text-2)" }}>{m.label}</td>
                    <td>{typeof asset.facts[m.key] === "number" ? m.fmt(asset.facts[m.key] as number) : "—"}</td>
                    {current?.after && (
                      <td style={{ color: "var(--text)" }}>
                        {typeof current.after[m.key] === "number" ? m.fmt(current.after[m.key] as number) : "—"}
                      </td>
                    )}
                  </tr>
                ))}
                <tr>
                  <td style={{ color: "var(--text-2)" }}>اندازه (پیکسل)</td>
                  <td>{fa(asset.width)}×{fa(asset.height)}</td>
                  {current?.size && <td>{fa(current.size[0])}×{fa(current.size[1])}</td>}
                </tr>
              </tbody>
            </table>
            {asset.findings.length > 0 && (
              <ul className="mt-2 list-inside list-disc text-xs" style={{ color: "var(--text-2)" }}>
                {asset.findings.map((f) => (
                  <li key={f.what}>{f.note}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>تحلیلِ دقیقِ کیت</div>
            {ka.state === "READY" ? (
              <div className="text-sm" style={{ color: "var(--text-2)" }} data-testid="kit-analysis">
                <p>{ka.text}</p>
                {ka.notes && ka.notes.length > 0 && (
                  <p className="mt-1 text-xs">پیشنهادِ خودکارِ کیت: {ka.notes.join(" ")}</p>
                )}
              </div>
            ) : ka.state === "FAILED" ? (
              <Alert tone="bad">{ka.error}</Alert>
            ) : ka.state ? (
              <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }} data-testid="kit-analysis">
                <Spinner size={16} /> {ka.message ?? "در صف"}
              </div>
            ) : (
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                کیت روی سرورِ پردازش نوردهی، سوختگی، رنگ‌زدگی، نویز، تیزی و سادگیِ زمینه را دقیق می‌سنجد.
              </p>
            )}
            {ka.state !== "QUEUED" && ka.state !== "RUNNING" && ka.state !== "CLAIMED" && (
              <Button
                size="sm"
                variant="secondary"
                className="mt-2"
                onClick={async () => {
                  try {
                    await photoApi.analyze(storeId, asset.id);
                    await onChanged();
                  } catch (err) {
                    onError(errorMessage(err));
                  }
                }}
              >
                تحلیلِ دقیق (سرورِ پردازش)
              </Button>
            )}
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>نسخه‌ها</div>
          {edits.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-3)" }}>
              هنوز ویرایشی نشده — عکس را در کتابخانه انتخاب کنید و دستوری بزنید.
            </p>
          ) : (
            <div className="flex flex-col gap-2" data-testid="versions">
              {edits.map((e) => (
                <div
                  key={e.id}
                  className="rounded-xl p-3"
                  style={{ border: `1px solid ${e.id === compareId ? "var(--brand)" : "var(--line)"}` }}
                  data-version={e.number}
                >
                  <div className="flex flex-wrap items-start gap-3">
                    {e.urls.thumb && <img src={e.urls.thumb} alt="" className="h-16 w-16 rounded-lg object-cover" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold" style={{ color: "var(--text)" }}>
                          نسخهٔ {fa(e.number)} — {e.recipe_title}
                        </span>
                        <Badge tone={stateTone(e.state)}>{e.state_label}</Badge>
                        {e.size && <Badge tone="neutral">{fa(e.size[0])}×{fa(e.size[1])}</Badge>}
                        {e.format && <Badge tone="neutral">{e.format.toUpperCase()}</Badge>}
                        {e.bytes ? <Badge tone="neutral">{fa(Math.round(e.bytes / 1024))} KB</Badge> : null}
                      </div>
                      <p className="text-xs" style={{ color: "var(--text-2)" }}>
                        {e.operations.map((o) => `${o.title}${o.where === "node" ? " (سرورِ پردازش)" : ""}`).join("، ")}
                      </p>
                      {e.active && <p className="text-xs" style={{ color: "var(--warn)" }}>{e.message}</p>}
                      {e.state === "FAILED" && <p className="text-xs" style={{ color: "var(--bad)" }}>{e.error}</p>}
                      {e.kit?.notes && (
                        <p className="text-xs" style={{ color: "var(--text-3)" }}>
                          کیت{e.node ? ` روی ${e.node}` : ""}
                          {e.kit.usedAi === true ? " (هوشِ مصنوعیِ بینا)" : e.kit.usedAi === false ? " (بی هوشِ مصنوعی)" : ""}:{" "}
                          {Array.isArray(e.kit.notes) ? e.kit.notes.join(" ") : e.kit.notes}
                        </p>
                      )}
                      {e.state === "READY" && e.smart && !e.smart.pending && (
                        <p className="text-xs" style={{ color: e.smart.fallback ? "var(--warn)" : "var(--text-3)" }} data-testid="version-smart">
                          {smartChipText(e.smart)}
                          {e.smart.notes ? ` — «${e.smart.notes}»` : ""}
                        </p>
                      )}
                      {e.server_notes.length > 0 && (
                        <p className="text-xs" style={{ color: "var(--text-3)" }}>{e.server_notes.join(" · ")}</p>
                      )}
                      {Boolean(e.saved.product_images?.length || e.saved.generated_images?.length) && (
                        <p className="text-xs" style={{ color: "var(--ok)" }}>
                          {e.saved.product_images?.length ? `در محصول ذخیره شد. ` : ""}
                          {e.saved.generated_images?.length ? "در «استودیو تصویر» ِ محصول برای محتوا آماده است." : ""}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {e.state === "READY" && (
                      <>
                        <Button size="sm" variant={e.id === compareId ? "primary" : "secondary"} onClick={() => setCompareId(e.id)}>
                          قبل و بعد
                        </Button>
                        {e.urls.result && (
                          <a href={e.urls.result} download>
                            <Button size="sm" variant="secondary">دانلود</Button>
                          </a>
                        )}
                        <Select
                          value={productId}
                          onChange={(ev) => setProductId(ev.target.value)}
                          aria-label="محصول"
                          className="!w-auto"
                        >
                          {!products.length && <option value="">محصولی نیست</option>}
                          {products.map((p) => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </Select>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={working || !productId}
                          onClick={() => void act(e, "product", { product: Number(productId) }, "به عکس‌های محصول اضافه شد.")}
                        >
                          ذخیره در محصول
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={working || !productId}
                          title="به «استودیو تصویر» ِ محصول می‌رود؛ در کپشن و کمپین انتخاب‌شدنی است"
                          onClick={() =>
                            void act(e, "content", { product: Number(productId) }, "برای محتوا آماده شد (استودیو تصویر ِ محصول).")
                          }
                        >
                          استفاده در محتوا
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={working}
                          title="این نسخه یک عکسِ تازه در کتابخانه می‌شود تا رویش ویرایش کنید"
                          onClick={() => void act(e, "library", {}, "در کتابخانه آمد.")}
                        >
                          به کتابخانه
                        </Button>
                        {productId && (
                          <Link to={`/products/${productId}/images`} className="text-xs underline" style={{ color: "var(--text-3)" }}>
                            استودیو تصویر
                          </Link>
                        )}
                      </>
                    )}
                    {(e.state === "FAILED" || e.state === "CANCELLED" || e.state === "READY") && (
                      <Button size="sm" variant="ghost" disabled={working} onClick={() => void act(e, "retry", {}, "دوباره در کار است.")}>
                        دوباره
                      </Button>
                    )}
                    {e.active && (
                      <Button size="sm" variant="ghost" disabled={working} onClick={() => void act(e, "cancel")}>
                        لغو
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={working}
                      onClick={async () => {
                        if (!window.confirm(`نسخهٔ ${e.number} حذف شود؟`)) return;
                        await photoApi.removeEdit(storeId, e.id);
                        if (compareId === e.id) setCompareId(null);
                        await onChanged();
                      }}
                    >
                      حذف
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
          {asset.source_label}
          {asset.product_name ? ` — ${asset.product_name}` : ""} ·{" "}
          <a href={asset.url} target="_blank" rel="noreferrer" className="underline">
            اصلِ عکس
          </a>
        </p>
      </div>
    </Card>
  );
}
