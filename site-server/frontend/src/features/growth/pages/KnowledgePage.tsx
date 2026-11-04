import { FormEvent, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, PageHeader, Select, fa } from "../../../components/ui";
import { g, useGet } from "../api";
import { LoadState } from "../components/bits";
import Modal, { ConfirmDialog } from "../components/Modal";
import { Flash } from "../components/outreach/shared";
import { fieldErrorsOf, useAction } from "../outreach/api";
import type { KnowledgeItem, KnowledgeList, KnowledgeSection } from "../outreach/types";

type WriterStatus = { known: boolean; first?: string; order?: string[]; model?: string; local?: { ready: boolean; reason: string }; reason?: string };

const SECTION_HELP: Record<KnowledgeSection, string> = {
  feature: "چیزهایی که NM واقعاً دارد و می‌تواند.",
  benefit: "فایده‌ای که مشتری می‌برد (فقط چیزی که راست است).",
  audience: "برای چه کسب‌وکارهایی مناسب است.",
  offer: "پیشنهادِ فعلی (مثلاً دورهٔ رایگان). هیچ تخفیفی که واقعاً نیست ننویسید.",
  limitation: "محدودیت‌ها را صادقانه بنویسید؛ نویسنده ادعایی که با این‌ها نخواند نمی‌کند.",
  demo: "نشانیِ نمونه یا دمو که می‌شود به مشتری نشان داد.",
  price: "قیمتِ واقعی. تا چیزی ننویسید هیچ قیمتی در پیام‌ها گفته نمی‌شود.",
  note: "هر نکتهٔ دیگری که باید بدانند.",
};

type Draft = { section: KnowledgeSection; title: string; body: string; url: string; note: string; is_active: boolean };
const EMPTY: Draft = { section: "feature", title: "", body: "", url: "", note: "", is_active: true };

function ItemDialog({ open, item, section, onClose, onSaved }: { open: boolean; item: KnowledgeItem | null; section: KnowledgeSection; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [sections, setSections] = useState<{ key: KnowledgeSection; label: string }[]>([]);
  const save = useAction();
  const errors = fieldErrorsOf(save.error);
  const list = useGet<KnowledgeList>(open ? "/knowledge/" : null);

  useEffect(() => {
    if (!open) return;
    setDraft(item ? { section: item.section, title: item.title, body: item.body, url: item.url, note: item.note, is_active: item.is_active } : { ...EMPTY, section });
    save.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item, section]);
  useEffect(() => {
    if (list.data) setSections(list.data.sections);
  }, [list.data]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = { ...draft, title: draft.title.trim(), body: draft.body.trim(), url: draft.url.trim(), note: draft.note.trim() };
    const done = await save.run(() => (item ? g.patch<KnowledgeItem>(`/knowledge/${item.id}/`, body) : g.post<KnowledgeItem>("/knowledge/", body)));
    if (done) onSaved();
  };

  const price = draft.section === "price";
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={item ? `ویرایش: ${item.title}` : "موردِ تازه"}
      size="lg"
      busy={save.busy}
      testId="knowledge-dialog"
      footer={
        <>
          <Button variant="secondary" type="button" onClick={onClose} disabled={save.busy}>
            انصراف
          </Button>
          <Button type="submit" form="knowledge-form" disabled={save.busy || !draft.title.trim() || (!price && !draft.body.trim())} data-testid="knowledge-save">
            {save.busy ? "در حال ذخیره…" : "ذخیره"}
          </Button>
        </>
      }
    >
      <form id="knowledge-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="بخش" hint={SECTION_HELP[draft.section]}>
            <Select value={draft.section} onChange={(e) => set("section", e.target.value as KnowledgeSection)} disabled={!!item?.is_default} data-testid="knowledge-section">
              {sections.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </Select>
          </Field>
          <label className="flex items-center gap-2 self-end pb-2.5 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={draft.is_active} onChange={(e) => set("is_active", e.target.checked)} />
            فعال (نویسنده می‌تواند به آن تکیه کند)
          </label>
        </div>
        <Field label="عنوان">
          <Input value={draft.title} onChange={(e) => set("title", e.target.value)} maxLength={200} data-autofocus data-testid="knowledge-title" />
          {errors.title && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.title}</span>}
        </Field>
        <div>
          <label htmlFor="knowledge-body" className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
            متن {price && <span style={{ color: "var(--warn)" }}>— قیمتِ واقعی را وارد کنید</span>}
          </label>
          <textarea id="knowledge-body" className="u-input" rows={7} value={draft.body} onChange={(e) => set("body", e.target.value)} dir="auto" data-testid="knowledge-body" />
          {errors.body && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.body}</span>}
          {price && !draft.body.trim() && <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>خالی بماند، در پیام‌ها هیچ قیمتی گفته نمی‌شود.</span>}
        </div>
        <Field label="نشانی (اختیاری؛ برای نمونه یا پیشنهاد)">
          <Input dir="ltr" value={draft.url} onChange={(e) => set("url", e.target.value)} placeholder="https://" data-testid="knowledge-url" />
          {errors.url && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.url}</span>}
        </Field>
        <Field label="یادداشتِ داخلی (در پیام‌ها نمی‌آید)">
          <Input value={draft.note} onChange={(e) => set("note", e.target.value)} maxLength={400} />
        </Field>
        {save.error && !errors.title && !errors.body && !errors.url && <Flash tone="bad">{save.error.message}</Flash>}
      </form>
    </Modal>
  );
}

function ItemCard({ item, onEdit, onDelete, onToggle, onReset }: { item: KnowledgeItem; onEdit: () => void; onDelete: () => void; onToggle: () => void; onReset: () => void }) {
  return (
    <div
      className="space-y-2 rounded-xl p-4"
      style={{ border: `1px solid ${item.needs_value ? "var(--warn)" : "var(--line)"}`, background: item.is_active ? "var(--surface)" : "var(--surface-2)", opacity: item.is_active ? 1 : 0.75 }}
      data-testid="knowledge-item"
      data-section={item.section}
      data-active={item.is_active ? "1" : "0"}
    >
      <div className="flex flex-wrap items-center gap-2">
        <b style={{ color: "var(--text)" }}>{item.title}</b>
        {!item.is_active && <Badge tone="neutral">غیرفعال</Badge>}
        {item.is_default && <Badge tone="info">پیش‌فرض</Badge>}
        {item.needs_value && <Badge tone="warn">{item.needs_value_hint || "قیمت را وارد کنید"}</Badge>}
        <span className="mr-auto flex flex-wrap gap-1">
          <Button variant="ghost" size="sm" onClick={onToggle} aria-label={item.is_active ? "غیرفعال کن" : "فعال کن"} title={item.is_active ? "غیرفعال کن" : "فعال کن"}>
            <Icon name={item.is_active ? "pause" : "play"} size={14} />
          </Button>
          <Button variant="ghost" size="sm" onClick={onEdit} aria-label="ویرایش" data-testid="knowledge-edit">
            <Icon name="edit" size={14} />
          </Button>
          {item.is_default && (
            <Button variant="ghost" size="sm" onClick={onReset} aria-label="بازگشت به متنِ پیش‌فرض" title="بازگشت به متنِ پیش‌فرض">
              <Icon name="refresh" size={14} />
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onDelete} aria-label="حذف" data-testid="knowledge-delete">
            <Icon name="trash" size={14} />
          </Button>
        </span>
      </div>
      {item.body ? (
        <p className="whitespace-pre-wrap text-sm leading-7" style={{ color: "var(--text-2)" }} dir="auto">
          {item.body}
        </p>
      ) : (
        <p className="text-sm" style={{ color: "var(--warn)" }}>
          هنوز چیزی نوشته نشده؛ تا نوشته نشود در پیام‌ها هیچ قیمتی گفته نمی‌شود.
        </p>
      )}
      {item.url && (
        <a href={item.url} target="_blank" rel="noopener noreferrer" dir="ltr" className="block text-xs" style={{ color: "var(--brand-strong)" }}>
          {item.url}
        </a>
      )}
      {item.note && (
        <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
          یادداشتِ داخلی: {item.note}
        </p>
      )}
    </div>
  );
}

/**
 * «دانشِ محصول»: what NM really offers, in the team's words. The default texts were taken from the product and its public site; the
 * internal tools are seeded OFF and the price is empty until a person types it. The AI writer may only talk about what is here.
 */
export default function KnowledgePage() {
  const list = useGet<KnowledgeList>("/knowledge/");
  const writer = useGet<WriterStatus>("/knowledge/writer-status/");
  const [editing, setEditing] = useState<KnowledgeItem | null>(null);
  const [adding, setAdding] = useState<KnowledgeSection | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeItem | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const act = useAction();

  const data = list.data;
  const grouped = (data?.sections ?? []).map((s) => ({ ...s, items: (data?.items ?? []).filter((i) => i.section === s.key) }));

  const toggle = async (item: KnowledgeItem) => {
    const done = await act.run(() => g.patch<KnowledgeItem>(`/knowledge/${item.id}/`, { is_active: !item.is_active }));
    if (done) list.reload();
  };
  const reset = async (item: KnowledgeItem) => {
    const done = await act.run(() => g.post<KnowledgeItem>(`/knowledge/${item.id}/reset/`));
    if (done) {
      setNotice({ tone: "ok", text: `«${item.title}» به متنِ پیش‌فرض برگشت.` });
      list.reload();
    }
  };
  const remove = async () => {
    if (!deleting) return;
    const done = await act.run(() => g.del(`/knowledge/${deleting.id}/`));
    if (done !== undefined) {
      setNotice({ tone: "ok", text: `«${deleting.title}» حذف شد.` });
      setDeleting(null);
      list.reload();
    }
  };
  const restore = async () => {
    const done = await act.run(() => g.post<{ knowledge: number; templates: number }>("/knowledge/restore-defaults/"));
    if (done) {
      setNotice({ tone: done.knowledge + done.templates > 0 ? "ok" : "warn", text: done.knowledge + done.templates > 0 ? `${fa(done.knowledge)} مورد و ${fa(done.templates)} قالبِ پیش‌فرض برگردانده شد.` : "چیزی کم نبود؛ همهٔ پیش‌فرض‌ها سرِ جایشان هستند." });
      list.reload();
    }
  };

  const w = writer.data;
  return (
    <div className="space-y-5" data-testid="knowledge-page">
      <PageHeader
        title="دانشِ محصول"
        subtitle="آنچه آپ‌مارکت واقعاً دارد و می‌تواند، با زبانِ خودتان. نویسندهٔ هوشمند فقط به همین‌ها (و اطلاعاتِ خودِ لید) تکیه می‌کند و چیزی از خودش نمی‌سازد."
        actions={
          <Button variant="secondary" onClick={restore} disabled={act.busy} data-testid="knowledge-restore">
            <Icon name="refresh" size={15} /> بازگرداندنِ پیش‌فرض‌های حذف‌شده
          </Button>
        }
      />

      <Alert tone="info" title="این متن‌ها از کجا آمده‌اند؟">
        از خودِ محصول و سایتِ عمومیِ آن (صفحهٔ قیمت‌ها، صفحهٔ اصلی، فهرستِ قابلیت‌های پنل). هیچ قیمت، عدد، نظرِ مشتری یا نتیجهٔ فروشی از خودمان ننوشته‌ایم. چیزهایی که فقط ابزارِ داخلی‌اند (مثل سایت‌ساز) غیرفعال گذاشته شده‌اند تا شما تصمیم بگیرید به مشتری وعده‌اش را بدهید یا نه.
      </Alert>

      {data && data.summary.prices_missing > 0 && (
        <Alert tone="warn" title="قیمت وارد نشده است">
          تا قیمتِ واقعی را ننویسید، پیام‌ها (و نویسندهٔ هوشمند) هیچ قیمتی نمی‌گویند. این اشکالی ندارد؛ فقط بدانید.
        </Alert>
      )}

      <Card>
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="writer-status">
          <Icon name="cpu" size={16} />
          <b style={{ color: "var(--text)" }}>نویسندهٔ هوشمند چه کسی را صدا می‌زند؟</b>
          {!w ? (
            <span style={{ color: "var(--text-3)" }}>…</span>
          ) : w.known ? (
            <>
              <span style={{ color: "var(--text-2)" }}>
                اول: {w.first === "metis" ? "متیس (API)" : `سرورِ پردازشِ خودمان${w.model ? ` (${w.model})` : ""}`}، بعد: {w.first === "metis" ? "سرورِ پردازش" : "متیس"} — طبقِ «اولویتِ هوش مصنوعی».
              </span>
              {w.local && <Badge tone={w.local.ready ? "ok" : "warn"}>{w.local.ready ? "سرورِ پردازش آماده است" : "سرورِ پردازش الان آماده نیست"}</Badge>}
              {w.local && !w.local.ready && w.local.reason && <span className="text-xs" style={{ color: "var(--text-3)" }}>{w.local.reason}</span>}
            </>
          ) : (
            <span style={{ color: "var(--text-3)" }}>وضعیت خوانده نشد؛ در هر صورت قالب‌ها بدونِ هوش مصنوعی کار می‌کنند.</span>
          )}
        </div>
      </Card>

      {notice && (
        <Flash tone={notice.tone} onClose={() => setNotice(null)}>
          {notice.text}
        </Flash>
      )}
      {act.error && <Flash tone="bad">{act.error.message}</Flash>}

      <LoadState loading={list.loading && !data} error={list.error} onRetry={list.reload}>
        <div className="space-y-6">
          {grouped.map((section) => (
            <section key={section.key} className="space-y-3" data-testid={`section-${section.key}`}>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-extrabold" style={{ color: "var(--text)" }}>
                  {section.label}
                </h2>
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  {SECTION_HELP[section.key]}
                </span>
                <Button variant="secondary" size="sm" className="mr-auto" onClick={() => setAdding(section.key)} data-testid={`add-${section.key}`}>
                  <Icon name="plus" size={14} /> مورد
                </Button>
              </div>
              {section.items.length === 0 ? (
                <Card>
                  <EmptyState icon="empty" title="مواردی نیست">برای این بخش چیزی ننوشته‌اید.</EmptyState>
                </Card>
              ) : (
                <div className="grid gap-3 lg:grid-cols-2 [&>*]:min-w-0">
                  {section.items.map((item) => (
                    <ItemCard key={item.id} item={item} onEdit={() => setEditing(item)} onDelete={() => setDeleting(item)} onToggle={() => void toggle(item)} onReset={() => void reset(item)} />
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      </LoadState>

      <ItemDialog
        open={editing !== null || adding !== null}
        item={editing}
        section={adding ?? "feature"}
        onClose={() => {
          setEditing(null);
          setAdding(null);
        }}
        onSaved={() => {
          setEditing(null);
          setAdding(null);
          setNotice({ tone: "ok", text: "ذخیره شد." });
          list.reload();
        }}
      />
      <ConfirmDialog
        open={!!deleting}
        title="این مورد حذف شود؟"
        danger
        confirmLabel="بله، حذف شود"
        busy={act.busy}
        onConfirm={remove}
        onClose={() => setDeleting(null)}
        message={deleting?.is_default ? `«${deleting.title}» یکی از موردهای پیش‌فرض است؛ هر وقت خواستید با «بازگرداندنِ پیش‌فرض‌ها» برمی‌گردد.` : `«${deleting?.title}» برای همیشه پاک می‌شود.`}
      />
    </div>
  );
}
