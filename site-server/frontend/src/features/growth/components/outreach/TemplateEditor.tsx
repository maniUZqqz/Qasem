import { FormEvent, useEffect, useRef, useState } from "react";

import { Alert, Badge, Button, Field, Input, Select, Spinner } from "../../../../components/ui";
import { g, useGet } from "../../api";
import { fieldErrorsOf, useAction, useDebounced, useSettings, problem, type ApiProblem } from "../../outreach/api";
import { closingBlock, DEFAULT_PLACEHOLDERS, LANGUAGES } from "../../outreach/labels";
import type { Placeholder, PreviewResult, Template, TemplateInput } from "../../outreach/types";
import type { LeadRow } from "../../types";
import Modal from "../Modal";
import { Flash } from "./shared";
import LeadPicker from "./LeadPicker";

const EMPTY: TemplateInput = { name: "", subject: "", body: "", language: "fa", is_active: true };

function ErrorText({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }} role="alert">
      {text}
    </span>
  );
}

/**
 * Create / edit a message template with placeholder buttons and a live preview
 * (`POST /growth/outreach/templates/preview/`, debounced).
 */
export default function TemplateEditor({
  open,
  template,
  onClose,
  onSaved,
}: {
  open: boolean;
  template: Template | null;
  onClose: () => void;
  onSaved: (t: Template) => void;
}) {
  const [form, setForm] = useState<TemplateInput>(EMPTY);
  const [lead, setLead] = useState<LeadRow[]>([]);
  const [pick, setPick] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<ApiProblem | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const save = useAction();
  const settings = useSettings();
  const placeholders = useGet<Placeholder[]>("/outreach/placeholders/");
  const keys = placeholders.data && placeholders.data.length ? placeholders.data : DEFAULT_PLACEHOLDERS;

  useEffect(() => {
    if (!open) return;
    setForm(template ? { name: template.name, subject: template.subject, body: template.body, language: template.language, is_active: template.is_active } : EMPTY);
    setLead([]);
    setPick(false);
    setPreview(null);
    setPreviewError(null);
    save.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, template]);

  // live preview, 500 ms after the last keystroke
  const body = useDebounced(form.body, 500);
  const subject = useDebounced(form.subject, 500);
  const leadId = lead[0]?.id;
  useEffect(() => {
    if (!open) return;
    if (!body.trim()) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    g.post<PreviewResult>("/outreach/templates/preview/", { body, subject, lead_id: leadId })
      .then((r) => {
        if (!cancelled) {
          setPreview(r);
          setPreviewError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(problem(err));
      })
      .finally(() => {
        if (!cancelled) setPreviewing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, body, subject, leadId]);

  const errors = fieldErrorsOf(save.error);
  const set = <K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  const insert = (token: string) => {
    const el = bodyRef.current;
    const start = el?.selectionStart ?? form.body.length;
    const end = el?.selectionEnd ?? form.body.length;
    const next = form.body.slice(0, start) + token + form.body.slice(end);
    set("body", next);
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const payload: TemplateInput = { ...form, name: form.name.trim(), subject: form.subject.trim(), body: form.body.trim() };
    const result = await save.run(() =>
      template ? g.patch<Template>(`/outreach/templates/${template.id}/`, payload) : g.post<Template>("/outreach/templates/", payload),
    );
    if (result) onSaved(result);
  };

  const s = settings.data;
  const closing = s ? closingBlock(s) : "";
  const previewHasClosing = !!(preview && s && s.opt_out_line.trim() && preview.text.includes(s.opt_out_line.trim()));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={template ? `ویرایشِ قالب «${template.name}»` : "قالبِ تازه"}
      size="xl"
      busy={save.busy}
      testId="template-editor"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.busy} type="button">
            انصراف
          </Button>
          <Button type="submit" form="template-form" disabled={save.busy || !form.name.trim() || !form.body.trim()} data-testid="template-save">
            {save.busy ? "در حال ذخیره…" : "ذخیره"}
          </Button>
        </>
      }
    >
      <form id="template-form" onSubmit={submit} className="grid gap-5 lg:grid-cols-2">
        {/* ----------------------------------------------------------- the form */}
        <div className="space-y-4">
          <Field label="نامِ قالب (فقط برای خودتان)">
            <Input value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={120} data-autofocus data-testid="template-name" />
            <ErrorText text={errors.name} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="زبان">
              <Select value={form.language} onChange={(e) => set("language", e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </Field>
            <label className="flex items-center gap-2 self-end pb-2.5 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
              فعال (در کمپین‌ها قابل انتخاب)
            </label>
          </div>
          <Field label="موضوع (اختیاری)" hint="بعضی فرم‌ها «موضوع» می‌خواهند. اگر خالی بماند و فرم آن را اجباری بداند، آن لید به صفِ دستی می‌رود.">
            <Input value={form.subject} onChange={(e) => set("subject", e.target.value)} maxLength={200} data-testid="template-subject" />
            <ErrorText text={errors.subject} />
          </Field>
          <div>
            <label htmlFor="template-body" className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              متنِ پیام
            </label>
            <div className="mb-2 flex flex-wrap gap-1.5" data-testid="placeholder-buttons">
              {keys.map((p) => (
                <button key={p.key} type="button" className="u-btn u-btn-secondary u-btn-sm" onClick={() => insert(`{${p.key}}`)} title={p.label}>
                  <span dir="ltr">{`{${p.key}}`}</span>
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    {p.label}
                  </span>
                </button>
              ))}
            </div>
            <textarea id="template-body" ref={bodyRef} className="u-input" rows={9} value={form.body} onChange={(e) => set("body", e.target.value)} dir="auto" data-testid="template-body" />
            <ErrorText text={errors.body} />
            <span className="mt-1 block text-xs leading-6" style={{ color: "var(--text-3)" }}>
              برای جایی که ممکن است خالی باشد، جایگزین بگذارید: <span dir="ltr">{"{city|شهر شما}"}</span> یعنی اگر شهر نبود «شهر شما» نوشته شود. هیچ‌چیز از خودش اضافه نمی‌شود.
            </span>
          </div>
          {save.error && !errors.name && !errors.body && !errors.subject && <Flash tone="bad">{save.error.message}</Flash>}
        </div>

        {/* ----------------------------------------------------------- the preview */}
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
              پیش‌نمایش با اطلاعاتِ یک لیدِ واقعی
            </div>
            {lead.length > 0 && !pick ? (
              <div className="flex items-center justify-between gap-2 rounded-xl p-3 text-sm" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                <span style={{ color: "var(--text)" }}>{lead[0].display_name}</span>
                <span className="flex gap-2">
                  <Button type="button" variant="secondary" size="sm" onClick={() => setPick(true)}>
                    عوض کن
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setLead([])}>
                    بدونِ لید
                  </Button>
                </span>
              </div>
            ) : (
              <div className="space-y-2">
                <LeadPicker
                  selected={lead}
                  onChange={(next) => {
                    setLead(next);
                    setPick(false);
                  }}
                />
                {lead.length === 0 && (
                  <p className="text-xs" style={{ color: "var(--text-3)" }}>
                    بدونِ انتخابِ لید، جاگذارها خالی می‌مانند.
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="template-preview">
            <div className="mb-2 flex items-center justify-between text-xs font-bold" style={{ color: "var(--text-3)" }}>
              <span>این پیام این‌طور دیده می‌شود</span>
              {previewing && <Spinner size={14} />}
            </div>
            {previewError ? (
              <Flash tone="bad">{previewError.message}</Flash>
            ) : preview ? (
              <div className="space-y-3">
                {preview.subject && (
                  <div className="text-sm" style={{ color: "var(--text-2)" }}>
                    موضوع: <b style={{ color: "var(--text)" }}>{preview.subject}</b>
                  </div>
                )}
                <pre className="whitespace-pre-wrap text-sm leading-7" dir="auto" style={{ color: "var(--text)", fontFamily: "inherit", margin: 0 }}>
                  {preview.text}
                </pre>
                {preview.unknown_placeholders.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs" style={{ color: "var(--bad)" }}>
                    جاگذارِ ناشناخته:
                    {preview.unknown_placeholders.map((p) => (
                      <Badge key={p} tone="bad">
                        <span dir="ltr">{`{${p}}`}</span>
                      </Badge>
                    ))}
                  </div>
                )}
                {preview.warnings.length > 0 && (
                  <Alert tone="warn" title="هشدار">
                    <ul className="list-disc ps-5">
                      {preview.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </Alert>
                )}
              </div>
            ) : (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                متن را بنویسید تا پیش‌نمایش اینجا بیاید.
              </p>
            )}
          </div>

          {!previewHasClosing && (
            <div className="rounded-xl p-4" style={{ border: "1px dashed var(--line-strong)" }} data-testid="closing-note">
              <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                و این‌ها خودکار به آخرِ هر پیام اضافه می‌شود (از «تنظیمات»)
              </div>
              {closing ? (
                <pre className="whitespace-pre-wrap text-sm leading-7" dir="auto" style={{ color: "var(--text-2)", fontFamily: "inherit", margin: 0 }}>
                  {closing}
                </pre>
              ) : (
                <p className="text-sm" style={{ color: "var(--text-3)" }}>
                  مشخصاتِ فرستنده و جملهٔ لغو را در «تنظیمات» پُر کنید؛ بدونِ آن‌ها ارسالِ خودکار ممکن نیست.
                </p>
              )}
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
}
