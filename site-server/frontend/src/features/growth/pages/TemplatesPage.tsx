import { useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Table, fa } from "../../../components/ui";
import { g, useGet } from "../api";
import { LoadState } from "../components/bits";
import { ConfirmDialog } from "../components/Modal";
import { Flash, SendingBanners } from "../components/outreach/shared";
import TemplateEditor from "../components/outreach/TemplateEditor";
import { faDate } from "../format";
import { asList, useAction, useSettings } from "../outreach/api";
import { ChannelBadge } from "../components/outreach/ChannelBits";
import { LANGUAGES } from "../outreach/labels";
import type { Template } from "../outreach/types";
import type { Paged } from "../types";

/** «قالب‌های پیام»: the texts the campaigns send, one or more per channel. They work without any AI; the AI writer is an optional extra on a single message. */
export default function TemplatesPage() {
  const list = useGet<Paged<Template> | Template[]>("/outreach/templates/");
  const settings = useSettings();
  const [editing, setEditing] = useState<Template | null>(null);
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<Template | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const remove = useAction();
  const toggle = useAction();

  const templates = [...asList(list.data)].sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.name.localeCompare(b.name, "fa"));

  const openEditor = (t: Template | null) => {
    setEditing(t);
    setOpen(true);
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const done = await remove.run(() => g.del(`/outreach/templates/${deleting.id}/`));
    if (done !== undefined) {
      setDeleting(null);
      setNotice({ tone: "ok", text: `قالبِ «${deleting.name}» حذف شد.` });
      list.reload();
    }
  };

  const setActive = async (t: Template, active: boolean) => {
    const done = await toggle.run(() => g.patch<Template>(`/outreach/templates/${t.id}/`, { is_active: active }));
    if (done) {
      setNotice({ tone: "ok", text: active ? `قالبِ «${t.name}» دوباره فعال شد.` : `قالبِ «${t.name}» بایگانی شد؛ دیگر در کمپینِ تازه پیشنهاد نمی‌شود.` });
      list.reload();
    }
  };

  return (
    <div className="space-y-5" data-testid="templates-page">
      <SendingBanners settings={settings.data} onChanged={settings.reload} />
      <PageHeader
        title="قالب‌های پیام"
        subtitle="متنِ پیام‌ها را اینجا می‌نویسید (برای هر کانال قالبِ جدا: فرم، ایمیل، پیامک، واتساپ …). سیستم فقط جاگذارها ({business_name} و …) را با اطلاعاتِ هر لید پُر می‌کند و چیزی از خودش اضافه نمی‌کند."
        actions={
          <Button onClick={() => openEditor(null)} data-testid="template-new">
            <Icon name="plus" size={16} />
            قالبِ تازه
          </Button>
        }
      />

      <Alert tone="info" title="متنِ نهایی از چه ساخته می‌شود؟">
        متنِ قالب + مشخصاتِ فرستنده (نام، شرکت، تلفن، ایمیل) + جملهٔ لغو. دو مورد آخر را در «تنظیمات» می‌نویسید و خودکار به آخرِ هر پیام می‌چسبند.
      </Alert>

      {notice && (
        <Flash tone={notice.tone} onClose={() => setNotice(null)}>
          {notice.text}
        </Flash>
      )}
      {(remove.error || toggle.error) && (
        <Flash tone="bad">
          {(remove.error ?? toggle.error)?.message}
          {remove.error && " اگر این قالب در یک کمپین استفاده شده، به‌جای حذف بایگانی‌اش کنید."}
        </Flash>
      )}

      <Card padded={false}>
        <div className="p-2">
          <LoadState loading={list.loading && !list.data} error={list.error} onRetry={list.reload}>
            {templates.length === 0 ? (
              <EmptyState
                icon="file"
                title="هنوز قالبی نساخته‌اید"
                action={
                  <Button onClick={() => openEditor(null)}>
                    <Icon name="plus" size={16} />
                    ساختنِ اولین قالب
                  </Button>
                }
              >
                بدونِ قالب نمی‌شود کمپینِ پیام ساخت.
              </EmptyState>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th className="text-start">نام</th>
                    <th className="text-start">کانال</th>
                    <th className="text-start">زبان</th>
                    <th className="text-start">وضعیت</th>
                    <th className="text-start">کمپین‌ها</th>
                    <th className="text-start">آخرین تغییر</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {templates.map((t) => (
                    <tr key={t.id} data-testid="template-row">
                      <td>
                        <button type="button" className="text-start font-medium" style={{ color: "var(--text)" }} onClick={() => openEditor(t)}>
                          {t.name}
                        </button>
                        <div className="max-w-md truncate text-xs" style={{ color: "var(--text-3)" }}>
                          {t.body.replace(/\s+/g, " ").slice(0, 90)}
                        </div>
                      </td>
                      <td>
                        <ChannelBadge channel={t.channel ?? "any"} label={t.channel_label} />
                      </td>
                      <td>{LANGUAGES.find((l) => l.value === t.language)?.label ?? t.language}</td>
                      <td>
                        <Badge tone={t.is_active ? "ok" : "neutral"}>{t.is_active ? "فعال" : "بایگانی‌شده"}</Badge>
                      </td>
                      <td>{t.campaigns_count !== undefined ? fa(t.campaigns_count) : "—"}</td>
                      <td className="whitespace-nowrap text-xs" style={{ color: "var(--text-3)" }}>
                        {faDate(t.updated_at)}
                      </td>
                      <td className="whitespace-nowrap text-end">
                        <Button variant="ghost" size="sm" onClick={() => openEditor(t)} aria-label="ویرایش">
                          <Icon name="edit" size={15} />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setActive(t, !t.is_active)} disabled={toggle.busy} aria-label={t.is_active ? "بایگانی" : "فعال‌سازی"} title={t.is_active ? "بایگانی" : "فعال‌سازی"}>
                          <Icon name={t.is_active ? "down" : "up"} size={15} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            remove.clear();
                            setDeleting(t);
                          }}
                          aria-label="حذف"
                          data-testid="template-delete"
                        >
                          <Icon name="trash" size={15} />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </LoadState>
        </div>
      </Card>

      <TemplateEditor
        open={open}
        template={editing}
        onClose={() => setOpen(false)}
        onSaved={(t) => {
          setOpen(false);
          setNotice({ tone: "ok", text: `قالبِ «${t.name}» ذخیره شد.` });
          list.reload();
        }}
      />

      <ConfirmDialog
        open={!!deleting}
        title="این قالب حذف شود؟"
        danger
        confirmLabel="بله، حذف شود"
        busy={remove.busy}
        onConfirm={confirmDelete}
        onClose={() => setDeleting(null)}
        message={
          <div className="space-y-2">
            <p>قالبِ «{deleting?.name}» برای همیشه پاک می‌شود. اگر در کمپینی استفاده شده باشد، سرور اجازهٔ حذف نمی‌دهد و باید بایگانی‌اش کنید.</p>
            {remove.error && <p style={{ color: "var(--bad)" }}>{remove.error.message}</p>}
          </div>
        }
      />
    </div>
  );
}
