import { useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Spinner } from "../../../components/ui";
import DownloadWhen from "./DownloadWhen";
import {
  autoSummary,
  autoView,
  bulkOk,
  confirmText,
  diskText,
  diskUsedPct,
  featuresText,
  fitText,
  groupAnchor,
  groupSummary,
  licenseView,
  missingIn,
  needsNodeUpdate,
  needsText,
  nodeNote,
  progressView,
  selectable,
  selectionText,
  sizeText,
  stateView,
  toFa,
  vramView,
  type ModelPackage,
  type NodeModels,
} from "./nodeModels";
import { DEFAULT_WHEN, whenBody, whenError, whenValid, type WhenChoice } from "./schedule";

/**
 * «مدل‌های سرورِ پردازش» — بسته‌های دانلودیِ ComfyUI / Hugging Face و بقیه (تصویر، ویدیو، بزرگ‌کردن و ترمیم، کنترل و ثبات،
 * عمق، صدا، حذفِ پس‌زمینه) با مجوز، جای‌گیریِ VRAM، «به چه کاری می‌آید»، «به چه نیاز دارد»، جای دیسک و وضعیتِ دانلودِ خودکار.
 * مدل‌های متنیِ Ollama کنارش در همین صفحه‌اند (OllamaModelsCard).
 *
 * دانلود همان کارِ همیشگیِ «node.models» است (POST /compute/nodes/<id>/models/download/ {packages, when})؛ سرور در پس‌زمینه
 * دانلود می‌کند، ادامه‌پذیر است و «زمانِ دانلود» (الان / ساعتِ … / بازهٔ شبانه) را رعایت می‌کند. داده را والد می‌دهد
 * (useModelsListing) تا یک درخواست برای همهٔ کارت‌های صفحه کافی باشد.
 */
export default function NodeModelsCard({
  node,
  onChanged,
}: {
  node: NodeModels;
  /** بعد از ثبتِ دانلود: والد دوباره بخواند */
  onChanged: () => Promise<void> | void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [when, setWhen] = useState<WhenChoice>(DEFAULT_WHEN);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const toggle = (key: string) => {
    setNotice(null);
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
  };

  const download = async (keys: string[]) => {
    if (keys.length === 0) return;
    if (!whenValid(when)) {
      setError(whenError(when));
      return;
    }
    if (!window.confirm(confirmText(node.groups, keys, node.node.name, node.node.online))) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const chosen = whenBody(when);
      await api.post(`/compute/nodes/${node.node.id}/models/download/`, chosen ? { packages: keys, when: chosen } : { packages: keys });
      setPicked([]);
      setNotice(
        node.node.online
          ? `${toFa(keys.length)} بسته برای دانلود به «${node.node.name}» فرستاده شد. پیشرفت همین‌جا و در «صفِ پردازش» دیده می‌شود.`
          : `${toFa(keys.length)} بسته در صف رفت؛ همین که «${node.node.name}» روشن شد دانلود شروع می‌شود.`,
      );
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const progress = progressView(node);
  const note = nodeNote(node);
  const disk = diskText(node.node);
  const used = diskUsedPct(node.node);
  const auto = autoSummary(node);

  const row = (p: ModelPackage) => {
    const v = stateView(p);
    const can = selectable(p);
    const lic = licenseView(p);
    const vr = vramView(p);
    const au = autoView(p);
    const fit = p.state === "missing" || p.state === "unknown" ? fitText(p) : null;
    const size = sizeText(p.state === "missing" && p.missing_mb ? p.missing_mb : p.total_mb);
    const needs = needsText(p);
    const feats = featuresText(p);
    const blocked = p.fits === false;
    const isOpenRow = open === p.key;
    return (
      <li
        key={p.key}
        className="rounded-xl px-3 py-2"
        style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
        data-testid={`model-row-${p.key}`}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <label className={`flex min-w-0 flex-1 items-start gap-2 ${can && !blocked ? "cursor-pointer" : ""}`}>
            <input
              type="checkbox"
              className="mt-1.5"
              disabled={!can || busy || blocked}
              checked={picked.includes(p.key)}
              onChange={() => toggle(p.key)}
              data-testid={`model-pick-${p.key}`}
            />
            <span className="min-w-0">
              <span className="block font-bold" style={{ color: "var(--text)" }}>
                {p.title}
                {p.optional && (
                  <span className="mr-2 text-xs font-normal" style={{ color: "var(--text-3)" }}>
                    (اختیاری)
                  </span>
                )}
              </span>
              {p.note && (
                <span className="block text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {p.note}
                </span>
              )}
            </span>
          </label>
          {size && (
            <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
              {size}
            </span>
          )}
          <Badge tone={v.tone}>{v.label}</Badge>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pr-6">
          {lic && (
            <span title={lic.name ? `مجوز: ${lic.name}` : undefined}>
              <Badge tone={lic.tone}>{lic.label}</Badge>
            </span>
          )}
          {vr && (
            <span title={p.vram_note || p.vram_text || undefined}>
              <Badge tone={vr.tone}>{vr.label}</Badge>
            </span>
          )}
          {fit && <Badge tone={fit.tone}>{fit.label}</Badge>}
          {au && <Badge tone={au.tone}>{au.label}</Badge>}
          {p.kind === "node" && <Badge tone="neutral">نودِ ComfyUI</Badge>}
          {p.needs_restart && <Badge tone="info">نیاز به راه‌اندازیِ دوبارهٔ ComfyUI</Badge>}
          {p.in_comfyui > 0 && p.state === "installed" && <Badge tone="neutral">از ComfyUI موجود است</Badge>}
          <button
            type="button"
            className="text-xs underline"
            style={{ color: "var(--text-3)" }}
            onClick={() => setOpen(isOpenRow ? null : p.key)}
            aria-expanded={isOpenRow}
          >
            {isOpenRow ? "بستنِ جزئیات" : "جزئیات"}
          </button>
        </div>
        {(feats || needs) && (
          <div className="mt-1 pr-6 text-xs leading-6" style={{ color: "var(--text-3)" }}>
            {feats && (
              <div>
                <b style={{ color: "var(--text-2)" }}>به کارِ این‌ها می‌آید:</b> {feats}
              </div>
            )}
            {needs && (
              <div>
                <b style={{ color: "var(--text-2)" }}>همراهش دانلود می‌شود:</b> {needs}
              </div>
            )}
          </div>
        )}
        {isOpenRow && (
          <div className="mt-1.5 pr-6 text-xs leading-6" style={{ color: "var(--text-3)" }}>
            {p.vram_text && <div>{p.vram_text}{p.vram_note ? ` — ${p.vram_note}` : ""}</div>}
            {p.auto?.text && <div>{p.auto.text}</div>}
            {p.license && <div dir="ltr" style={{ textAlign: "right" }}>مجوز: {p.license === "unverified" ? "unverified (نامشخص)" : p.license}</div>}
            {p.provenance && <div dir="ltr" style={{ textAlign: "right" }}>{p.provenance}</div>}
            {p.sources && p.sources.length > 0 && (
              <div dir="ltr" style={{ textAlign: "right" }}>
                {p.sources.join(" · ")}
              </div>
            )}
            {p.title_en && (
              <div dir="ltr" style={{ textAlign: "right" }}>
                {p.title_en}
              </div>
            )}
            {node.auto?.why?.[p.key] && <div style={{ color: "var(--warn)" }}>آخرین خطا: {node.auto.why[p.key]}</div>}
          </div>
        )}
      </li>
    );
  };

  return (
    <Card>
      <SectionTitle
        action={
          <Button variant="ghost" size="sm" onClick={() => void onChanged()} aria-label="تازه‌سازی" title="تازه‌سازی" style={{ padding: 7 }}>
            <Icon name="refresh" size={16} />
          </Button>
        }
      >
        <span className="flex items-center gap-2" data-testid="node-models">
          <Icon name="download" size={16} /> مدل‌های تصویر، ویدیو، ترمیم، کنترل، عمق، صدا و حذفِ پس‌زمینه
        </span>
      </SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        بسته‌هایی که روی سرورِ پردازش کار می‌کنند (ComfyUI و Hugging Face). هر کدام را که نصب نیست انتخاب کنید و «دانلود» بزنید؛
        مدل‌هایی که قابلیتِ روشن لازم دارد خودشان می‌آیند. مدل‌های «فقط غیرتجاری» و «با شرط» هرگز خودکار دانلود نمی‌شوند.
      </p>

      <ErrorBox message={error} />

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <b style={{ color: "var(--text)" }}>{node.node.name}</b>
          <Badge tone={node.node.online ? "ok" : "neutral"}>{node.node.online ? "روشن" : "خاموش"}</Badge>
          {disk && <span data-testid="node-disk">دیسک: {disk}</span>}
        </div>
        {used !== null && (
          <div className="u-meter" role="progressbar" aria-label="پُر بودنِ دیسک" aria-valuemin={0} aria-valuemax={100} aria-valuenow={used}>
            <span style={{ width: `${used}%`, background: used >= 90 ? "var(--bad)" : used >= 70 ? "var(--warn)" : "var(--ok)" }} />
          </div>
        )}

        {note && <Alert tone="info">{note}</Alert>}
        {needsNodeUpdate(node) && (
          <Alert tone="warn" title="سرور بسته‌های تازهٔ فهرست را هنوز نمی‌شناسد">
            نرم‌افزارِ سرور قدیمی‌تر از فهرست است. از «سرورهای پردازش ▸ دستورها» دکمهٔ «به‌روزرسانی» را بزنید (یا Update.bat)؛ بعدش
            وضعیتِ همهٔ بسته‌ها و دانلودِ خودکار شروع می‌شود.
          </Alert>
        )}
        {auto && <Alert tone={node.auto?.enabled ? "ok" : "neutral"}>{auto}</Alert>}
        {node.error && (
          <Alert tone="warn" title="آخرین خطای دانلود روی سرور">
            {node.error}
          </Alert>
        )}
        {progress && (
          <div>
            <p className="mb-1 text-sm" style={{ color: "var(--text-2)" }}>
              {progress.text}
            </p>
            <div className="u-meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.pct ?? undefined}>
              <span style={{ width: `${progress.pct ?? 8}%`, background: "var(--brand)" }} />
            </div>
          </div>
        )}

        {node.groups.map((g) => {
          const missing = missingIn(g);
          const heavy = g.packages.filter((p) => !bulkOk(p) && selectable(p)).length;
          return (
            <section key={g.key} id={groupAnchor(g.key)} aria-label={g.title} style={{ scrollMarginTop: 72 }}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                  {g.title}{" "}
                  <span className="text-xs font-normal" style={{ color: "var(--text-3)" }}>
                    ({groupSummary(g)})
                  </span>
                </h3>
                {missing.length > 0 && (
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => void download(missing)} data-testid={`models-all-${g.key}`}>
                    <Icon name="download" size={13} /> دانلودِ همهٔ نصب‌نشده‌ها ({toFa(missing.length)})
                  </Button>
                )}
              </div>
              {g.note && (
                <p className="mb-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {g.note}
                </p>
              )}
              {heavy > 0 && missing.length > 0 && (
                <p className="mb-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  دکمهٔ «همهٔ نصب‌نشده‌ها» فقط مدل‌های «تجاری مجاز» با جای دیسکِ کافی را می‌گیرد؛ بقیه را تک‌به‌تک انتخاب کنید.
                </p>
              )}
              <ul className="flex flex-col gap-1.5">{g.packages.map(row)}</ul>
            </section>
          );
        })}

        <DownloadWhen value={when} onChange={setWhen} disabled={busy} />
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void download(picked)} disabled={busy || picked.length === 0} data-testid="models-download">
            {busy ? <Spinner size={13} /> : <Icon name="download" size={13} />} دانلودِ انتخاب‌شده‌ها
          </Button>
          <span className="text-sm" style={{ color: "var(--text-3)" }}>
            {selectionText(node.groups, picked)}
          </span>
        </div>
        {notice && <Alert tone="ok">{notice}</Alert>}
      </div>
    </Card>
  );
}
