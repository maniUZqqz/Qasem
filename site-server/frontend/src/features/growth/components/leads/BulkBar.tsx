import { useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Button, Input, Select, fa } from "../../../../components/ui";
import { download, g, problem } from "../../api";
import { useMeta } from "../../MetaContext";
import { ConfirmDialog } from "../Modal";

type BulkResult = { affected: number; skipped: number; missing: number };

/**
 * Actions on the selected leads. Every action reports what it really did («۳ لید تغییر کرد، ۱ لید از قبل
 * همین‌طور بود»), and delete asks first.
 */
export default function BulkBar({
  ids,
  onClear,
  onChanged,
  onExtract,
  onCampaign,
}: {
  ids: number[];
  onClear: () => void;
  /** after a change: `clear` = the selection no longer makes sense (archived / deleted) */
  onChanged: (clear: boolean) => void;
  onExtract: (ids: number[]) => void;
  onCampaign: (ids: number[]) => void;
}) {
  const { meta } = useMeta();
  const [status, setStatus] = useState("");
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const limit = meta?.limits.bulk_max_ids ?? 500;
  const tooMany = ids.length > limit;

  const run = async (action: string, extra: Record<string, unknown>, label: string, clear = false) => {
    setBusy(true);
    setMessage(null);
    try {
      const r = await g.post<BulkResult>("/leads/bulk/", { ids, action, ...extra });
      const same = r.skipped - r.missing;
      setMessage({
        tone: "ok",
        text: `${label}: ${fa(r.affected)} لید تغییر کرد${same > 0 ? `، ${fa(same)} لید از قبل همین‌طور بود` : ""}${r.missing ? `، ${fa(r.missing)} لید پیدا نشد` : ""}.`,
      });
      setConfirmDelete(false);
      onChanged(clear);
    } catch (err) {
      setMessage({ tone: "bad", text: problem(err).message });
      setConfirmDelete(false);
    } finally {
      setBusy(false);
    }
  };

  const exportSelected = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await download("/leads/export/", { ids: ids.join(",") }, "growth-leads.csv");
    } catch (err) {
      setMessage({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="u-card space-y-3 p-3"
      style={{ borderColor: "color-mix(in srgb, var(--brand) 45%, var(--line))", background: "var(--brand-soft)" }}
      data-testid="bulk-bar"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }} data-testid="bulk-count">
          {fa(ids.length)} لید انتخاب شد
        </span>
        <Button variant="ghost" size="sm" onClick={onClear} data-testid="bulk-clear">
          لغوِ انتخاب
        </Button>
        {tooMany && (
          <span className="text-xs" style={{ color: "var(--bad)" }}>
            در هر عملیات حداکثر {fa(limit)} لید ممکن است؛ انتخاب را کم کنید.
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex items-center gap-1.5">
          <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="وضعیتِ تازه" style={{ width: 150 }} data-testid="bulk-status">
            <option value="">تغییرِ وضعیت…</option>
            {(meta?.statuses ?? []).map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
          <Button size="sm" disabled={busy || tooMany || !status} onClick={() => run("set_status", { status }, "تغییرِ وضعیت")} data-testid="bulk-status-go">
            اعمال
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <Input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="نامِ برچسب" aria-label="نامِ برچسب" style={{ width: 140 }} data-testid="bulk-tag" />
          <Button size="sm" disabled={busy || tooMany || !tag.trim()} onClick={() => run("add_tag", { tag: tag.trim() }, `افزودنِ برچسبِ «${tag.trim()}»`)} data-testid="bulk-tag-add">
            افزودن
          </Button>
          <Button variant="secondary" size="sm" disabled={busy || tooMany || !tag.trim()} onClick={() => run("remove_tag", { tag: tag.trim() }, `برداشتنِ برچسبِ «${tag.trim()}»`)} data-testid="bulk-tag-remove">
            برداشتن
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => run("archive", {}, "بایگانی", true)} data-testid="bulk-archive">
          بایگانی
        </Button>
        <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => run("unarchive", {}, "خارج کردن از بایگانی", true)} data-testid="bulk-unarchive">
          خارج از بایگانی
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={exportSelected} data-testid="bulk-export">
          <Icon name="download" size={14} />
          خروجیِ CSV
        </Button>
        <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => onExtract(ids)} data-testid="bulk-extract">
          <Icon name="search" size={14} />
          استخراجِ اطلاعاتِ تماس
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => onCampaign(ids)} data-testid="bulk-campaign">
          <Icon name="send" size={14} />
          ایجادِ کمپینِ پیام
        </Button>
        <Button variant="danger" size="sm" disabled={busy || tooMany} onClick={() => setConfirmDelete(true)} data-testid="bulk-delete">
          <Icon name="trash" size={14} />
          حذف
        </Button>
      </div>

      {message && (
        <Alert tone={message.tone}>
          <span data-testid="bulk-message">{message.text}</span>
        </Alert>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="حذفِ لیدها"
        message={`${fa(ids.length)} لید همراهِ یادداشت‌ها، راه‌های تماس و تاریخچه‌شان برای همیشه پاک می‌شود. این کار برگشت ندارد. اگر فقط نمی‌خواهیدشان ببینید، «بایگانی» بهتر است.`}
        confirmLabel="بله، حذف شود"
        danger
        busy={busy}
        onConfirm={() => run("delete", { confirm: true }, "حذف", true)}
        onClose={() => !busy && setConfirmDelete(false)}
      />
    </div>
  );
}
