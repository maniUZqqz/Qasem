import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, PageHeader, Select, Spinner } from "../../../components/ui";
import AutoModelsCard from "./AutoModelsCard";
import NodeModelsCard from "./NodeModelsCard";
import OllamaModelsCard from "./OllamaModelsCard";
import { countInstalled, groupAnchor, toFa, type ModelsListing } from "./nodeModels";
import { useModelsListing } from "./useModelsListing";

/**
 * «دانلودِ مدل‌ها» — یک جا برای همهٔ مدل‌های هوش مصنوعیِ سرورِ پردازش:
 *   ۱. دانلودِ خودکار (قابلیتِ روشن ⇒ مدل‌هایش خودش می‌آید)
 *   ۲. مدل‌های متن و بینایی (Ollama)
 *   ۳. بسته‌های ComfyUI / Hugging Face: تصویر، ویدیو، بزرگ‌کردن و ترمیم، کنترل و ثبات، عمق، صدا، حذفِ پس‌زمینه
 * مالک (۱۴۰۵/۰۸/۲۳): «فقط Ollama گذاشتی؛ قرار بود هاگینگ‌فیس و ComfyUI هم باشد» و «کارت را پیدا نکردم» — برای همین این صفحه
 * در منوی «ابزارها» با نامِ «دانلودِ مدل‌ها» آمده و از «سرورهای پردازش» و «موتورهای AI» هم به آن پیوند هست.
 */
export default function ModelsPage() {
  const { data, error, reload } = useModelsListing();
  const [nodeId, setNodeId] = useState<number | null>(null);

  useEffect(() => {
    if (!data) return;
    setNodeId((cur) => (cur !== null && data.nodes.some((n) => n.node.id === cur) ? cur : data.nodes[0]?.node.id ?? null));
  }, [data]);

  const current = data?.nodes.find((n) => n.node.id === nodeId);
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="space-y-4">
      <PageHeader
        title="دانلودِ مدل‌ها"
        subtitle="همهٔ مدل‌های هوش مصنوعیِ سرورِ پردازش یک‌جا: متن و بینایی (Ollama) و تصویر، ویدیو، ترمیم، کنترل و عمق (ComfyUI / Hugging Face)"
        actions={
          <>
            <Link to="/tools/compute" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="cpu" size={13} /> سرورهای پردازش
            </Link>
            <Link to="/admin/providers" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="sparkle" size={13} /> موتورهای AI
            </Link>
          </>
        }
      />
      <ErrorBox message={error} />
      {!data && !error && <Spinner />}
      {data && data.nodes.length === 0 && (
        <Alert tone="info" title="هنوز سرورِ پردازشی ثبت نشده">
          با «سرورهای پردازش» یک کامپیوترِ گرافیکی ثبت کنید؛ بعدش فهرستِ مدل‌ها و دانلودِ خودکار همین‌جا کار می‌کند.
        </Alert>
      )}

      {data && data.nodes.length > 1 && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <span>کدام سرور؟</span>
            <Select aria-label="کدام سرور" value={String(nodeId ?? "")} onChange={(e) => setNodeId(Number(e.target.value))} className="w-auto">
              {data.nodes.map((n) => (
                <option key={n.node.id} value={n.node.id}>
                  {n.node.name} {n.node.online ? "(روشن)" : "(خاموش)"}
                </option>
              ))}
            </Select>
          </div>
        </Card>
      )}

      {data && (
        <nav className="flex flex-wrap items-center gap-2" aria-label="پرش به بخش" data-testid="models-nav">
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            پرش به:
          </span>
          <Button variant="ghost" size="sm" onClick={() => jump("models-group-ollama")}>
            متن و بینایی (Ollama)
          </Button>
          {(current?.groups ?? []).map((g) => (
            <Button key={g.key} variant="ghost" size="sm" onClick={() => jump(groupAnchor(g.key))}>
              {g.title.split(":")[0]}
            </Button>
          ))}
        </nav>
      )}

      {data?.auto && <AutoModelsCard auto={data.auto} onChanged={reload} />}
      {data && <OllamaModelsCard ollama={data.ollama} onChanged={reload} providersPage={data.ollama_page || "/admin/providers"} />}
      {current && <NodeModelsCard key={current.node.id} node={current} onChanged={reload} />}
    </div>
  );
}

/** خلاصهٔ کوچک برای صفحهٔ «سرورهای پردازش»: چند مدل نصب است و پیوند به صفحهٔ «دانلودِ مدل‌ها». */
export function ModelsEntryCard() {
  const { data, error } = useModelsListing();
  const current: ModelsListing["nodes"][number] | undefined = data?.nodes[0];
  const counts = current ? countInstalled(current.groups) : null;
  const ollama = data?.ollama;
  const ollamaCounts = ollama ? { installed: ollama.models.filter((m) => m.installed === true).length, total: ollama.models.length } : null;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-lg font-bold" style={{ color: "var(--text)" }} data-testid="models-entry">
            <Icon name="download" size={16} /> دانلودِ مدل‌ها
          </h2>
          <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            مدل‌های متن و بینایی (Ollama) و بسته‌های ComfyUI / Hugging Face (تصویر، ویدیو، ترمیم، کنترل، عمق، صدا، حذفِ پس‌زمینه) با دانلودِ
            خودکار — همه در یک صفحه.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            {counts && (
              <Badge tone="brand">
                {toFa(counts.installed)} از {toFa(counts.total)} بسته نصب است
              </Badge>
            )}
            {ollamaCounts && ollamaCounts.total > 0 && (
              <Badge tone="info">
                Ollama: {toFa(ollamaCounts.installed)} از {toFa(ollamaCounts.total)}
              </Badge>
            )}
            {data?.auto && <Badge tone={data.auto.enabled ? "ok" : "neutral"}>{data.auto.enabled ? "دانلودِ خودکار روشن" : "دانلودِ خودکار خاموش"}</Badge>}
          </div>
          <ErrorBox message={error} />
        </div>
        <Link to="/tools/models" className="u-btn u-btn-primary no-underline" data-testid="models-open">
          <Icon name="download" size={14} /> باز کردنِ «دانلودِ مدل‌ها»
        </Link>
      </div>
    </Card>
  );
}
