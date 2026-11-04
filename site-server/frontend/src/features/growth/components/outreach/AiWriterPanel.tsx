import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Input, Spinner, fa } from "../../../../components/ui";
import { g, useGet } from "../../api";
import { faDateTime } from "../../format";
import { useAction } from "../../outreach/api";
import type { MessageVersion, OutreachItem, VersionCompare, VersionList } from "../../outreach/types";
import { Flash } from "./shared";
import { SmsMeter } from "./ChannelBits";

const TONE: Record<MessageVersion["status"], "neutral" | "brand" | "ok" | "warn" | "bad" | "info"> = {
  generating: "brand",
  proposed: "info",
  approved: "ok",
  superseded: "neutral",
  rejected: "neutral",
  failed: "bad",
};

const VIA: Record<string, string> = { local: "سرورِ پردازشِ خودمان", metis: "متیس (API)" };

function Diff({ data }: { data: VersionCompare }) {
  return (
    <div className="rounded-xl p-3 text-sm leading-8" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="version-diff">
      <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>
        {data.a.label} ← → {data.b.label}: <span style={{ color: "var(--bad)" }}>قرمز = حذف‌شده</span> · <span style={{ color: "var(--ok)" }}>سبز = اضافه‌شده</span>
      </div>
      <div className="whitespace-pre-wrap" dir="auto">
        {data.ops.map((op, i) =>
          op.op === "equal" ? (
            <span key={i}>{op.a}</span>
          ) : op.op === "delete" ? (
            <span key={i} style={{ color: "var(--bad)", textDecoration: "line-through" }}>
              {op.a}
            </span>
          ) : (
            <span key={i} style={{ color: "var(--ok)", background: "var(--ok-soft)" }}>
              {op.b}
            </span>
          ),
        )}
      </div>
    </div>
  );
}

function VersionCard({ campaignId, item, version, onChanged }: { campaignId: number; item: OutreachItem; version: MessageVersion; onChanged: () => void }) {
  const base = `/outreach/campaigns/${campaignId}/items/${item.id}/versions`;
  const [ack, setAck] = useState(false);
  const [diff, setDiff] = useState<VersionCompare | null>(null);
  const act = useAction();
  const blocking = version.warnings.filter((w) => w.blocking);
  const soft = version.warnings.filter((w) => !w.blocking);
  const open = version.status === "proposed";

  const compare = async () => {
    if (diff) {
      setDiff(null);
      return;
    }
    const data = await act.run(() => g.get<VersionCompare>(`${base}/compare/`, { a: "current", b: version.id }));
    if (data) setDiff(data);
  };
  const approve = async () => {
    const done = await act.run(() => g.post(`${base}/${version.id}/approve/`, { acknowledge_warnings: ack }));
    if (done !== undefined) onChanged();
  };
  const reject = async () => {
    const done = await act.run(() => g.post(`${base}/${version.id}/reject/`));
    if (done !== undefined) onChanged();
  };

  return (
    <div className="space-y-3 rounded-xl p-4" style={{ border: "1px solid var(--line)", background: open ? "var(--surface)" : "var(--surface-2)" }} data-testid="ai-version" data-status={version.status}>
      <div className="flex flex-wrap items-center gap-2">
        <b style={{ color: "var(--text)" }}>نسخهٔ {fa(version.version)}</b>
        <Badge tone={TONE[version.status]}>{version.status_label}</Badge>
        {version.route?.via && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            نوشته‌شده با {VIA[version.route.via] ?? version.route.via}
            {version.route.model ? ` (${version.route.model})` : ""}
          </span>
        )}
        <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
          {faDateTime(version.created_at)}
          {version.created_by_name ? ` · ${version.created_by_name}` : ""}
        </span>
      </div>
      {version.instructions && (
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          راهنمای شما: {version.instructions}
        </div>
      )}

      {version.status === "generating" && (
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <Spinner size={16} /> در حال نوشتن… (ممکن است چند دقیقه طول بکشد؛ می‌توانید صفحه را باز نگه دارید)
        </div>
      )}

      {version.status === "failed" && (
        <Alert tone="bad" title="نوشته نشد">
          {version.error}
        </Alert>
      )}

      {version.text && version.status !== "failed" && version.status !== "generating" && (
        <>
          {version.subject && (
            <div className="text-sm" style={{ color: "var(--text-2)" }}>
              موضوع: <b style={{ color: "var(--text)" }}>{version.subject}</b>
            </div>
          )}
          <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl p-3 text-sm leading-7" dir="auto" style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text)", fontFamily: "inherit", margin: 0 }} data-testid="version-text">
            {version.text}
          </pre>
          {version.sms && <SmsMeter size={version.sms} />}
          {version.personalization_reason && (
            <p className="text-xs leading-6" style={{ color: "var(--text-2)" }}>
              <b>چرا این‌طور شخصی شد:</b> {version.personalization_reason}
            </p>
          )}
          {version.evidence.length > 0 && (
            <details className="text-xs" style={{ color: "var(--text-2)" }}>
              <summary style={{ cursor: "pointer" }}>مدارکِ این نسخه ({fa(version.evidence.length)})</summary>
              <ul className="mt-1 list-disc ps-5 leading-6">
                {version.evidence.map((e) => (
                  <li key={e.ref}>
                    <b>{e.label}</b>: {e.text}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {blocking.length > 0 && (
            <Alert tone="bad" title="هشدارِ جدی">
              <ul className="list-disc ps-5">
                {blocking.map((w) => (
                  <li key={w.code + w.text}>{w.text}</li>
                ))}
              </ul>
            </Alert>
          )}
          {soft.length > 0 && (
            <Alert tone="warn" title="نکته‌ها">
              <ul className="list-disc ps-5">
                {soft.map((w) => (
                  <li key={w.code + w.text}>{w.text}</li>
                ))}
              </ul>
            </Alert>
          )}
          {diff && <Diff data={diff} />}
          {act.error && <Flash tone="bad">{act.error.message}</Flash>}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={compare} disabled={act.busy} data-testid="version-compare">
              <Icon name="search" size={14} /> {diff ? "بستنِ مقایسه" : "مقایسه با متنِ فعلی"}
            </Button>
            {open && (
              <>
                {blocking.length > 0 && (
                  <label className="flex items-center gap-1.5 text-xs" style={{ color: "var(--bad)" }}>
                    <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="version-ack" />
                    با این هشدار می‌پذیرم
                  </label>
                )}
                <Button size="sm" onClick={approve} disabled={act.busy || (blocking.length > 0 && !ack)} data-testid="version-approve">
                  <Icon name="check" size={14} /> پذیرفتنِ این نسخه (جایگزینِ متنِ پیام)
                </Button>
                <Button size="sm" variant="ghost" onClick={reject} disabled={act.busy} data-testid="version-reject">
                  رد
                </Button>
              </>
            )}
            {version.same_as_current && version.status === "approved" && <Badge tone="ok">همین متن در پیام است</Badge>}
          </div>
        </>
      )}
      {version.status === "failed" && (
        <div>
          <Button size="sm" variant="ghost" onClick={reject} disabled={act.busy}>
            کنار بگذار
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * The AI writer for one item: ask for a version, read it with its evidence and warnings, compare it with the current text, approve
 * (replaces the item's text; the send approval must be given again) or reject. The templates keep working without it.
 */
export default function AiWriterPanel({ campaignId, item, editable, onChanged }: { campaignId: number; item: OutreachItem; editable: boolean; onChanged: () => void }) {
  const base = `/outreach/campaigns/${campaignId}/items/${item.id}`;
  const [poll, setPoll] = useState<number | undefined>(undefined);
  const list = useGet<VersionList>(`${base}/versions/`, undefined, { poll });
  const [instructions, setInstructions] = useState("");
  const ask = useAction();
  const versions = list.data?.versions ?? [];
  const generating = versions.some((v) => v.status === "generating");

  useEffect(() => {
    setPoll(generating ? 2500 : undefined);
  }, [generating]);
  useEffect(() => {
    setInstructions("");
  }, [item.id]);

  const start = async () => {
    const done = await ask.run(() => g.post(`${base}/ai/`, { instructions: instructions.trim() }));
    if (done !== undefined) {
      list.reload();
      setPoll(2500);
    }
  };

  const refresh = () => {
    list.reload();
    onChanged();
  };

  return (
    <div className="space-y-3 rounded-xl p-4" style={{ border: "1px dashed var(--line-strong)" }} data-testid="ai-writer">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="cpu" size={16} />
        <h3 className="text-sm font-extrabold" style={{ color: "var(--text)" }}>
          نویسندهٔ هوشمند (اختیاری)
        </h3>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          فقط از «دانشِ محصول» و اطلاعاتِ همین لید می‌نویسد؛ قیمت و عددِ ساختگی نمی‌گذارد (اگر بگذارد، هشدار می‌دهیم).
        </span>
        <Link to="/growth/knowledge" className="mr-auto text-xs no-underline" style={{ color: "var(--brand-strong)" }}>
          ویرایشِ دانشِ محصول
        </Link>
      </div>

      {editable ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[14rem] flex-1">
            <Input value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={500} placeholder="راهنمای اضافه (اختیاری)؛ مثلاً: کوتاه‌تر و گرم‌تر بنویس" aria-label="راهنمای نویسنده" data-testid="ai-instructions" />
          </div>
          <Button size="sm" onClick={start} disabled={ask.busy || generating} data-testid="ai-write">
            <Icon name="sparkle" size={14} /> {versions.length ? "نوشتنِ نسخهٔ تازه" : "نوشتنِ پیام با هوش مصنوعی"}
          </Button>
        </div>
      ) : (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          این مورد دیگر قابل ویرایش نیست.
        </p>
      )}
      {ask.error && <Flash tone="bad">{ask.error.message}</Flash>}
      {list.error && <Flash tone="bad">{list.error}</Flash>}

      {versions.length === 0 && !list.loading ? (
        <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
          هنوز نسخه‌ای نوشته نشده. قالب‌ها بدونِ هوش مصنوعی هم کامل کار می‌کنند؛ این بخش فقط برای شخصی‌ترکردنِ یک پیام است. اگر سرورِ پردازش خاموش یا اعتبارِ متیس تمام شده باشد، دلیلش همین‌جا نوشته می‌شود و پیامِ فعلی دست‌نخورده می‌ماند.
        </p>
      ) : (
        <div className="space-y-3">
          {versions.map((v) => (
            <VersionCard key={v.id} campaignId={campaignId} item={item} version={v} onChanged={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}
