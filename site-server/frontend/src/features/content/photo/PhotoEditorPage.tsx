import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
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
import OperationForm from "./OperationForm";
import SourcePicker from "./SourcePicker";
import {
  ACTIVE_STATES,
  Asset,
  Edit,
  NodeStatus,
  Operation,
  Overview,
  Sources,
  Tool,
  photoApi,
  stateTone,
} from "./api";

/**
 * ادیتورِ عکس — همتای «ادیتور ویدیو».
 *
 * دو جا کار می‌کند و صفحه این را پنهان نمی‌کند: کارهای سبک (برش برای شبکه‌ها، اندازه، متن، لوگو، واترمارک،
 * نور و رنگِ ساده) همین حالا روی سرورِ سایت انجام می‌شود؛ کارهای کیتِ PersianAiKit.Photo (بهبودِ حرفه‌ای،
 * حذفِ پس‌زمینه، بزرگ‌نمایی، ترمیم، ویرایش با دستور) به سرورِ پردازش می‌رود و اگر خاموش است «منتظر» می‌ماند.
 * هر کار برچسبِ جایش را دارد تا کسی منتظرِ چیزی نماند که نمی‌داند منتظرش است.
 */
export default function PhotoEditorPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [recipe, setRecipe] = useState("suggest");
  const [ops, setOps] = useState<Operation[] | null>(null);
  const [opsEdited, setOpsEdited] = useState(false);
  const [openOp, setOpenOp] = useState<number | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [picker, setPicker] = useState<null | "products" | "generated">(null);
  const [tracking, setTracking] = useState<Edit[]>([]);
  const [lastBatch, setLastBatch] = useState<string | null>(null);
  const [node, setNode] = useState<NodeStatus | null>(null);
  const [detail, setDetail] = useState<Asset | null>(null);
  const [compareId, setCompareId] = useState<number | null>(null);
  const [sources, setSources] = useState<Sources | null>(null);
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

  // دستور ⇐ کارها (برای اولین عکسِ انتخاب‌شده؛ «پیشنهادی» برای هر عکس جدا حساب می‌شود)
  useEffect(() => {
    if (selected.length === 0) {
      setOps(null);
      return;
    }
    let stop = false;
    setPlanBusy(true);
    photoApi
      .plan(id, selected[0], recipe)
      .then((p) => {
        if (stop) return;
        setOps(p.operations);
        setOpsEdited(false);
        // کاری که بی متن معنی ندارد (ویرایش با دستور، متن روی عکس) ⇐ فرمش از اول باز
        const need = p.operations.findIndex(
          (o) => (o.tool === "kit_smart" && !o.params.goal) || (o.tool === "text" && !o.params.text),
        );
        setOpenOp(need >= 0 ? need : null);
        setNode(p.node);
      })
      .catch((err) => !stop && setError(errorMessage(err)))
      .finally(() => !stop && setPlanBusy(false));
    return () => {
      stop = true;
    };
  }, [id, recipe, selected.join(",")]);

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

  function updateOp(index: number, next: Operation) {
    setOps((cur) => (cur ? cur.map((o, i) => (i === index ? next : o)) : cur));
    setOpsEdited(true);
  }

  function addTool(key: string) {
    const t = tools[key];
    if (!t) return;
    const params: Record<string, unknown> = {};
    t.params.forEach((p) => (params[p.key] = p.default));
    const op: Operation = { tool: key, params, on: true, title: t.title, where: t.where, reason: t.help };
    setOps((cur) => {
      const list = [...(cur ?? [])];
      const exportAt = list.findIndex((o) => o.tool === "export");
      if (exportAt >= 0 && key !== "export") list.splice(exportAt, 0, op);
      else list.push(op);
      setOpenOp(exportAt >= 0 && key !== "export" ? exportAt : list.length - 1);
      return list;
    });
    setOpsEdited(true);
  }

  async function apply() {
    if (!ops || selected.length === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const sendOps = recipe === "suggest" && !opsEdited && selected.length > 1 ? null : ops;
      const res = sendOps
        ? await photoApi.apply(id, selected, recipe, sendOps)
        : await photoApi.applyRecipe(id, selected, recipe);
      setNode(res.node);
      setTracking((cur) => [...res.edits, ...cur.filter((e) => !res.edits.some((x) => x.id === e.id))]);
      setLastBatch(res.batch);
      // تازه ثبت‌شده‌ها هنوز «در صف» اند؛ این‌که کجا می‌روند از کارهایشان پیداست
      const waiting = res.edits.filter((e) => e.state === "NODE" || (e.state === "QUEUED" && e.needs_node)).length;
      const ready = res.edits.filter((e) => e.state === "READY").length;
      const working = res.edits.filter(
        (e) => e.state === "SERVER" || (e.state === "QUEUED" && !e.needs_node),
      ).length;
      setNotice(
        [
          ready ? `${fa(ready)} عکس آماده شد.` : "",
          working ? `${fa(working)} عکس روی سرورِ سایت در کار است (چند ثانیه).` : "",
          waiting
            ? res.node.online
              ? `${fa(waiting)} عکس به سرورِ پردازش رفت.`
              : `${fa(waiting)} عکس منتظرِ سرورِ پردازش می‌ماند (الان خاموش است).`
            : "",
        ]
          .filter(Boolean)
          .join(" "),
      );
      await load();
      if (selected.length === 1) await openDetail(selected[0], true, res.edits[0]?.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

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
  const selectedNodeOps = (ops ?? []).filter((o) => o.on !== false && tools[o.tool]?.where === "node");
  const singleImage =
    selected.length === 1 ? assets.find((a) => a.id === selected[0])?.preview ?? null : null;
  const batchEdits = lastBatch ? tracking.filter((e) => e.batch === lastBatch) : [];

  return (
    <>
      <PageHeader
        title="ادیتور عکس"
        subtitle="عکس بدهید — برای اینستاگرام، استوری و فروشگاه آماده‌اش می‌کنیم: نور و رنگ، پس‌زمینه، قاب، متن و لوگو"
        actions={
          <>
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
            کارهای هوشمند (بهبودِ حرفه‌ای، حذفِ پس‌زمینه، بزرگ‌نمایی، ویرایش با دستور) همین حالا روی{" "}
            {(node ?? data.node).nodes.join("، ")} انجام می‌شود.
          </Alert>
        ) : (
          <Alert tone="warn" title="سرورِ پردازش خاموش است">
            کارهای سبک — برش برای شبکه‌ها، اندازه، چرخش، متن، لوگو، واترمارک و نور و رنگِ ساده — همین‌جا روی
            سرورِ سایت انجام می‌شود. کارهای هوشمندِ کیت (برچسبِ «سرورِ پردازش») در صف می‌مانند تا سرورِ پردازش
            روشن شود؛ صفحه را می‌توانید ببندید.
          </Alert>
        )}
      </div>

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

      {selected.length > 0 && (
        <Card className="mt-6">
          <div data-testid="recipe-card">
            <SectionTitle>
              دستورِ ویرایش — {fa(selected.length)} عکس
            </SectionTitle>
            <div className="mb-2 flex flex-wrap gap-2">
              {data.recipes.map((r) => (
                <Button
                  key={r.key}
                  size="sm"
                  variant={recipe === r.key ? "primary" : "secondary"}
                  onClick={() => setRecipe(r.key)}
                  title={r.help}
                >
                  {r.title}
                </Button>
              ))}
            </div>
            <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
              {data.recipes.find((r) => r.key === recipe)?.help}
              {recipe === "suggest" && selected.length > 1 && !opsEdited &&
                " (برای هر عکس از روی اندازه‌گیریِ خودش؛ این‌جا کارهای عکسِ اول دیده می‌شود.)"}
            </p>

            {planBusy && <Spinner size={18} />}
            {ops && !planBusy && (
              <>
                {ops.length === 0 ? (
                  <Alert tone="info">هنوز کاری انتخاب نکرده‌اید — از پایین ابزار اضافه کنید.</Alert>
                ) : (
                  <div className="flex flex-col gap-2" data-testid="operations">
                    {ops.map((op, index) => {
                      const t = tools[op.tool];
                      if (!t) return null;
                      const off = op.on === false;
                      return (
                        <div
                          key={`${op.tool}-${index}`}
                          className="rounded-xl p-3"
                          style={{ border: "1px solid var(--line)", opacity: off ? 0.55 : 1 }}
                        >
                          <div className="flex flex-wrap items-start gap-3">
                            <input
                              type="checkbox"
                              className="mt-1"
                              checked={!off}
                              aria-label={t.title}
                              onChange={() => updateOp(index, { ...op, on: off })}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-bold" style={{ color: "var(--text)" }}>{t.title}</span>
                                <Badge tone={t.where === "server" ? "ok" : nodeOn ? "info" : "warn"}>
                                  {t.where === "server" ? "سرورِ سایت" : nodeOn ? "سرورِ پردازش" : "سرورِ پردازش — منتظر"}
                                </Badge>
                                {op.optional && <Badge tone="neutral">اختیاری</Badge>}
                              </div>
                              <p className="text-sm" style={{ color: "var(--text-2)" }}>{op.reason || t.help}</p>
                            </div>
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" onClick={() => setOpenOp(openOp === index ? null : index)}>
                                {openOp === index ? "بستنِ تنظیمات" : "تنظیمات"}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                title="برداشتنِ این کار"
                                onClick={() => {
                                  setOps((cur) => (cur ? cur.filter((_o, i) => i !== index) : cur));
                                  setOpsEdited(true);
                                  setOpenOp(null);
                                }}
                              >
                                ×
                              </Button>
                            </div>
                          </div>
                          {openOp === index && (
                            <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
                              <OperationForm
                                tool={t}
                                params={op.params}
                                kit={data.kit}
                                spotImage={singleImage}
                                onChange={(params) => updateOp(index, { ...op, params })}
                              />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) addTool(e.target.value);
                    }}
                    aria-label="افزودنِ ابزار"
                    className="!w-auto"
                  >
                    <option value="">+ افزودنِ ابزار…</option>
                    <optgroup label="سرورِ سایت (همین حالا)">
                      {data.tools.filter((t) => t.where === "server").map((t) => (
                        <option key={t.key} value={t.key}>{t.title}</option>
                      ))}
                    </optgroup>
                    <optgroup label="سرورِ پردازش (کیتِ PersianAiKit.Photo)">
                      {data.tools.filter((t) => t.where === "node").map((t) => (
                        <option key={t.key} value={t.key}>{t.title}</option>
                      ))}
                    </optgroup>
                  </Select>
                </div>

                {selectedNodeOps.length > 0 && !nodeOn && (
                  <div className="mt-3">
                    <Alert tone="warn">
                      {fa(selectedNodeOps.length)} کار به سرورِ پردازش نیاز دارد ({selectedNodeOps
                        .map((o) => tools[o.tool]?.title)
                        .join("، ")}). این نسخه‌ها «منتظرِ سرورِ پردازش» می‌مانند تا روشن شود؛ برای نتیجهٔ همین حالا
                      تیکِ آن‌ها را بردارید.
                    </Alert>
                  </div>
                )}

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    onClick={() => void apply()}
                    disabled={busy || ops.filter((o) => o.on !== false).length === 0}
                    data-testid="apply"
                  >
                    اعمال روی {fa(selected.length)} عکس
                  </Button>
                  <Button variant="ghost" onClick={() => setSelected([])}>
                    بی‌خیال
                  </Button>
                </div>
              </>
            )}
          </div>
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
