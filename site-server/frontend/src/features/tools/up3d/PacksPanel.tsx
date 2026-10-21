import { useCallback, useEffect, useRef, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Spinner } from "../../../components/ui";
import { errMsg, fa, up3d } from "./api";
import PackGuide from "./PackGuide";
import { Muted, useToast } from "./shared";
import type { AssetPack, PackReport } from "./types";

/**
 * «بسته‌های دارایی»: بارگذاریِ zip (محیط/صحنه، شخص، حرکت، محصول، نور، دوربین) ⇐ وارسیِ هر manifest با همان قواعدِ
 * دفترِ موتور ⇐ نصب زیرِ data/up3d/asset-packs/<بسته>/ ⇐ کتابخانه بی‌ری‌استارت تازه می‌شود. روشن/خاموش/حذف.
 */

const KIND_FA: Record<string, string> = {
  environment: "محیط / صحنه",
  character: "شخص",
  motion: "حرکت",
  product: "محصول",
  lighting: "نور",
  shot: "دوربین",
};

function size(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes > 1024 * 1024) return `${fa(Math.round(bytes / 1024 / 1024))} مگابایت`;
  return `${fa(Math.max(1, Math.round(bytes / 1024)))} کیلوبایت`;
}

function Report({ rep }: { rep: PackReport }) {
  return (
    <div className="space-y-2">
      <Alert
        tone={rep.errors.length ? "bad" : rep.dry_run ? "info" : "ok"}
        title={
          rep.errors.length
            ? `بسته نصب نشد — ${fa(rep.errors.length)} ایراد`
            : rep.message || (rep.dry_run ? "وارسی بی‌خطا بود" : "نصب شد")
        }
      >
        {rep.errors.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 ps-5 text-xs">
            {rep.errors.slice(0, 12).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </Alert>
      {rep.assets.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {rep.assets.map((a) => (
            <div key={a.folder} className="rounded-lg p-2 text-xs" style={{ background: "var(--surface-2)" }}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={a.errors.length ? "bad" : "ok"}>{KIND_FA[a.kind] || a.kind}</Badge>
                <b style={{ color: "var(--text)" }}>{a.label || a.id}</b>
                <span className="u3d-mono" style={{ color: "var(--text-3)" }}>
                  {a.id}
                </span>
              </div>
              {a.warnings.map((w) => (
                <div key={w} style={{ color: "var(--warn)" }}>
                  ⚠ {w}
                </div>
              ))}
              {a.errors.map((e) => (
                <div key={e} style={{ color: "var(--bad)" }}>
                  ✕ {e}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PacksPanel({ onChanged }: { onChanged?: () => void }) {
  const toast = useToast();
  const [packs, setPacks] = useState<AssetPack[] | null>(null);
  const [problems, setProblems] = useState<{ file: string; error: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<PackReport | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const r = await up3d.packs();
      setPacks(r.packs);
      setProblems(r.problems || []);
      setError(null);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const send = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setReport(null);
    try {
      const r = await up3d.uploadPack(file, { replace, dryRun });
      setReport(r);
      toast(r.message || "انجام شد");
      if (!dryRun) {
        setFile(null);
        if (input.current) input.current.value = "";
        await load();
        onChanged?.();
      }
    } catch (e) {
      const data = (e as { response?: { data?: { report?: PackReport } } }).response?.data;
      if (data?.report) setReport({ ...data.report, errors: data.report.errors || [] });
      toast(errMsg(e), true);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (p: AssetPack) => {
    try {
      const r = await up3d.togglePack(p.id, !p.enabled);
      toast(r.message);
      await load();
      onChanged?.();
    } catch (e) {
      toast(errMsg(e), true);
    }
  };

  const remove = async (p: AssetPack) => {
    if (!window.confirm(`بستهٔ «${p.name}» و ${fa(p.assets.length)} دارایی‌اش پاک شود؟ صحنه‌هایی که از آن‌ها استفاده می‌کنند دیگر رندر نمی‌شوند.`)) return;
    try {
      const r = await up3d.deletePack(p.id);
      toast(r.message);
      await load();
      onChanged?.();
    } catch (e) {
      toast(errMsg(e), true);
    }
  };

  const example = async () => {
    try {
      await up3d.downloadExamplePack();
    } catch (e) {
      toast(errMsg(e), true);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
              افزودنِ بستهٔ دارایی
            </h2>
            <Muted>
              یک فایلِ zip با یک یا چند پوشه؛ هر پوشه یک <code className="u3d-mono">manifest.json</code> و فایل‌هایش: محیط/صحنه
              (glb، fbx، obj، blend)، شخص (glb/fbx با اسکلت، یا دستورِ ساختِ MPFB)، حرکت (BVH یا FBX ِ Mixamo)، محصول (glb/obj)، نور
              (با HDRI) و نمای دوربین. پیش از نصب همه چیز وارسی می‌شود و بعد بی‌ری‌استارت در کتابخانه و ویرایشگر می‌آید.
            </Muted>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowGuide((v) => !v)}>
              <Icon name="info" size={14} />
              {showGuide ? "بستنِ راهنما" : "راهنمای ساختِ بسته"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => void example()}>
              <Icon name="download" size={14} />
              بستهٔ نمونه (zip)
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            ref={input}
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setReport(null);
            }}
            className="text-sm"
          />
          <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            اگر بسته‌ای با همین شناسه هست، جایگزین کن
          </label>
          <Button variant="secondary" disabled={!file || busy} onClick={() => void send(true)}>
            فقط وارسی
          </Button>
          <Button disabled={!file || busy} onClick={() => void send(false)}>
            <Icon name="upload" size={15} />
            {busy ? "در حالِ بارگذاری…" : "بارگذاری و نصب"}
          </Button>
        </div>
        {file && (
          <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            {file.name} · {size(file.size)} {file.size > 190 * 1024 * 1024 ? "— بیش از ۲۰۰ مگابایت از راهِ پنل نمی‌رود؛ بسته را کوچک‌تر کنید" : ""}
          </div>
        )}
        {report && (
          <div className="mt-3">
            <Report rep={report} />
          </div>
        )}
      </Card>

      {showGuide && <PackGuide />}

      <ErrorBox message={error} />
      {problems.length > 0 && (
        <Alert tone="warn" title={`${fa(problems.length)} manifest در کتابخانه خوانده نشد`}>
          <ul className="list-disc ps-5 text-xs">
            {problems.slice(0, 8).map((p) => (
              <li key={p.file}>
                <span className="u3d-mono">{p.file}</span>: {p.error}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {packs === null ? (
        <div className="py-6 text-center">
          <Spinner />
        </div>
      ) : packs.length === 0 ? (
        <Card>
          <EmptyState icon="box" title="هنوز بسته‌ای نصب نشده" description="با فرمِ بالا یک zip بارگذاری کنید (یا بستهٔ نمونه را بگیرید، عوض کنید و بفرستید)." />
        </Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {packs.map((p) => (
            <Card key={p.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <b style={{ color: "var(--text)" }}>{p.name}</b>{" "}
                  <span className="u3d-mono text-xs" style={{ color: "var(--text-3)" }}>
                    {p.id}
                  </span>{" "}
                  <Badge tone={p.enabled ? "ok" : "neutral"}>{p.enabled ? "روشن" : "خاموش"}</Badge>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {p.installed ? `نصب: ${p.installed} · ` : ""}
                    {size(p.size)}
                    {p.source ? ` · ${p.source}` : ""}
                  </div>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="secondary" onClick={() => void toggle(p)}>
                    {p.enabled ? "خاموش کن" : "روشن کن"}
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => void remove(p)}>
                    <Icon name="trash" size={13} />
                    حذف
                  </Button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {p.assets.map((a) => (
                  <span
                    key={`${a.kind}/${a.id}`}
                    className="rounded-md px-2 py-0.5 text-xs"
                    title={a.active === false ? "شناسهٔ تکراری: نسخهٔ دیگری (بستهٔ بعدی) برنده است" : undefined}
                    style={{ background: "var(--surface-2)", color: a.active === false ? "var(--text-3)" : "var(--text-2)" }}
                  >
                    {KIND_FA[a.kind] || a.kind}: {a.name?.fa || a.name?.en || a.id}
                    {a.active === false ? " (غیرفعال)" : ""}
                  </span>
                ))}
              </div>
              {(p.problems || []).length > 0 && (
                <div className="mt-2 text-xs" style={{ color: "var(--bad)" }}>
                  {(p.problems || []).map((x) => x.error).join(" · ")}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
