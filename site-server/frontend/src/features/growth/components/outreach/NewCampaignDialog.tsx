import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Alert, Badge, Button, Field, Input, Select, Table, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { fieldErrorsOf, asList, useAction } from "../../outreach/api";
import { CHANNELS, isManualChannel, MODE_LABEL, REASON_TEXT } from "../../outreach/labels";
import type { AddLeadsResult, Campaign, CampaignChannel, CampaignMode, Template } from "../../outreach/types";
import type { LeadRow, Paged } from "../../types";
import Modal from "../Modal";
import LeadPicker from "./LeadPicker";
import { Flash } from "./shared";

type Result = { campaign: Campaign; added?: AddLeadsResult; addError?: string };

const MODE_HELP: Record<CampaignMode, string> = {
  auto: "سیستم (فرم، ایمیل یا پیامک) را خودش می‌فرستد، ولی فقط بعد از تأییدِ شما: پیش‌نمایشِ دقیقِ آنچه می‌رود را می‌بینید و موردها را تأیید می‌کنید. لیدهایی که کانالشان مشکل دارد (کپچا، ایمیلِ نامعتبر، گوشیِ جفت‌نشده و …) به صفِ دستی می‌روند.",
  manual: "هیچ‌چیز خودکار نمی‌رود. برای هر لید متن آماده است و شما خودتان در سایتشان می‌فرستید و نتیجه را با یک کلید ثبت می‌کنید.",
};

/**
 * «کمپین تازه»: name, template, mode and the leads (handed over from the lead table as `?lead_ids=` or
 * picked here). The campaign is created first, then the leads are added so that the answer lists exactly
 * which leads were skipped and why.
 */
export default function NewCampaignDialog({ open, onClose, initialLeadIds }: { open: boolean; onClose: () => void; initialLeadIds: number[] }) {
  const navigate = useNavigate();
  const templatesData = useGet<Paged<Template> | Template[]>("/outreach/templates/");
  const allTemplates = useMemo(() => asList(templatesData.data).filter((t) => t.is_active), [templatesData.data]);
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [channel, setChannel] = useState<CampaignChannel>("contact_form");
  const [mode, setMode] = useState<CampaignMode>("auto");
  // a template written for another channel is not offered; "auto" campaigns take any (the channel's own default is used per lead)
  const templates = useMemo(
    () => allTemplates.filter((t) => channel === "auto" || !t.channel || t.channel === "any" || t.channel === channel),
    [allTemplates, channel],
  );
  const manualOnly = isManualChannel(channel);
  const [picked, setPicked] = useState<LeadRow[]>([]);
  const [force, setForce] = useState(false);
  const [handoffNames, setHandoffNames] = useState<string[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const action = useAction();
  const errors = fieldErrorsOf(action.error);

  useEffect(() => {
    if (!open) return;
    setName("");
    setMode("auto");
    setChannel("contact_form");
    setPicked([]);
    setForce(false);
    setResult(null);
    action.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!templateId && templates.length === 1) setTemplateId(String(templates[0].id));
    if (templateId && !templates.some((t) => String(t.id) === templateId)) setTemplateId(templates.length === 1 ? String(templates[0].id) : "");
  }, [templates, templateId]);
  useEffect(() => {
    if (manualOnly) setMode("manual");
  }, [manualOnly]);

  // a few names for the leads handed over from the lead table (the rest is only counted)
  useEffect(() => {
    setHandoffNames([]);
    if (!open || initialLeadIds.length === 0) return;
    let cancelled = false;
    Promise.all(initialLeadIds.slice(0, 5).map((id) => g.get<LeadRow>(`/leads/${id}/`).then((l) => l.display_name).catch(() => `لید ${id}`))).then((names) => {
      if (!cancelled) setHandoffNames(names);
    });
    return () => {
      cancelled = true;
    };
  }, [open, initialLeadIds]);

  const allIds = useMemo(() => Array.from(new Set([...initialLeadIds, ...picked.map((l) => l.id)])), [initialLeadIds, picked]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const campaign = await action.run(() => g.post<Campaign>("/outreach/campaigns/", { name: name.trim(), template_id: Number(templateId), mode, channel }));
    if (!campaign) return;
    if (allIds.length === 0) {
      setResult({ campaign });
      return;
    }
    try {
      const added = await g.post<AddLeadsResult>(`/outreach/campaigns/${campaign.id}/add-leads/`, { lead_ids: allIds, force: mode === "manual" && force });
      setResult({ campaign, added });
    } catch (err) {
      setResult({ campaign, addError: problem(err).message });
    }
  };

  const close = () => {
    onClose();
  };

  // ------------------------------------------------------------------ the answer
  if (result) {
    const { campaign, added, addError } = result;
    return (
      <Modal
        open={open}
        onClose={close}
        title="کمپین ساخته شد"
        size="lg"
        testId="campaign-created"
        footer={
          <>
            <Button variant="secondary" onClick={close}>
              بستن
            </Button>
            <Button onClick={() => navigate(`/growth/outreach/${campaign.id}`)} data-testid="go-to-campaign">
              رفتن به کمپین
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm" style={{ color: "var(--text-2)" }}>
            کمپینِ «{campaign.name}» ({MODE_LABEL[campaign.mode]}{campaign.channel_label ? ` · ${campaign.channel_label}` : ""}) ساخته شد.
          </p>
          {added && (
            <Alert tone={added.added > 0 ? "ok" : "warn"} title={`${fa(added.added)} لید به کمپین اضافه شد`}>
              {added.skipped.length > 0 ? `${fa(added.skipped.length)} لید اضافه نشد؛ دلیلش در جدولِ زیر است.` : "هیچ لیدی کنار گذاشته نشد."}
            </Alert>
          )}
          {addError && <Flash tone="bad">{`لیدها اضافه نشدند: ${addError}. می‌توانید از صفحهٔ کمپین دوباره اضافه کنید.`}</Flash>}
          {added && added.skipped.length > 0 && (
            <div data-testid="skipped-list">
              <Table>
                <thead>
                  <tr>
                    <th className="text-start">لید</th>
                    <th className="text-start">چرا اضافه نشد</th>
                  </tr>
                </thead>
                <tbody>
                  {added.skipped.map((s) => (
                    <tr key={`${s.lead_id}-${s.reason}`}>
                      <td>
                        <Link to={`/growth/leads/${s.lead_id}`} className="no-underline" style={{ color: "var(--brand-strong)" }}>
                          {s.lead_name || `لید ${s.lead_id}`}
                        </Link>
                      </td>
                      <td>{s.reason_text || REASON_TEXT[s.reason] || s.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </div>
      </Modal>
    );
  }

  // ------------------------------------------------------------------ the form
  const noTemplates = !templatesData.loading && templates.length === 0;
  return (
    <Modal
      open={open}
      onClose={close}
      title="کمپینِ تازه"
      size="lg"
      busy={action.busy}
      testId="campaign-wizard"
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={action.busy} type="button">
            انصراف
          </Button>
          <Button type="submit" form="campaign-form" disabled={action.busy || !name.trim() || !templateId} data-testid="campaign-create">
            {action.busy ? "در حال ساخت…" : "ساختنِ کمپین"}
          </Button>
        </>
      }
    >
      <form id="campaign-form" onSubmit={submit} className="space-y-5">
        <Field label="نامِ کمپین">
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="مثلاً: فروشگاه‌های پوشاکِ تهران — آبان" data-autofocus data-testid="campaign-name" />
          {errors.name && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.name}</span>}
        </Field>

        <Field label="کانال (از چه راهی پیام برود؟)" hint={channel === "auto" ? "برای هر لید اولین کانالِ روشن (به ترتیبِ صفحهٔ «کانال‌ها») که بتواند به او برسد." : manualOnly ? "این کانال را خودتان می‌فرستید؛ لینک و متن آماده می‌شود و نتیجه را ثبت می‌کنید." : undefined}>
          <Select value={channel} onChange={(e) => setChannel(e.target.value as CampaignChannel)} data-testid="campaign-channel">
            <option value="auto">خودکار (بر اساسِ اولویتِ کانال‌ها)</option>
            {CHANNELS.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}{c.kind === "manual" ? " — دستی" : ""}
              </option>
            ))}
          </Select>
          {errors.channel && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.channel}</span>}
        </Field>

        <Field label="قالبِ پیام">
          {noTemplates ? (
            <Alert tone="warn" title="قالبِ فعالی نیست" action={<Link to="/growth/templates" className="u-btn u-btn-secondary u-btn-sm no-underline">ساختنِ قالب</Link>}>
              اول یک قالبِ پیام بسازید.
            </Alert>
          ) : (
            <Select value={templateId} onChange={(e) => setTemplateId(e.target.value)} data-testid="campaign-template">
              <option value="">— انتخاب کنید —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          )}
          {errors.template_id && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.template_id}</span>}
        </Field>

        <div>
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
            روشِ ارسال
          </div>
          <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="روشِ ارسال">
            {(["auto", "manual"] as CampaignMode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => !(manualOnly && m === "auto") && setMode(m)}
                disabled={manualOnly && m === "auto"}
                className="rounded-xl p-3 text-start"
                style={{ border: `1px solid ${mode === m ? "var(--brand)" : "var(--line)"}`, background: mode === m ? "var(--brand-soft)" : "var(--surface-2)", opacity: manualOnly && m === "auto" ? 0.5 : 1 }}
                data-testid={`mode-${m}`}
              >
                <div className="mb-1 flex items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  {MODE_LABEL[m]}
                  {mode === m && <Badge tone="brand">انتخاب‌شده</Badge>}
                </div>
                <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {MODE_HELP[m]}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
            لیدها
          </div>
          {initialLeadIds.length > 0 && (
            <div className="mb-3 rounded-xl p-3 text-sm" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="handoff-leads">
              <b>{fa(initialLeadIds.length)}</b> لید از دیتابیسِ لیدها انتخاب شده است
              {handoffNames.length > 0 && (
                <span style={{ color: "var(--text-3)" }}>
                  : {handoffNames.join("، ")}
                  {initialLeadIds.length > handoffNames.length ? ` و ${fa(initialLeadIds.length - handoffNames.length)} موردِ دیگر` : ""}
                </span>
              )}
              .
            </div>
          )}
          <LeadPicker selected={picked} onChange={setPicked} multi placeholder="لیدِ دیگری هم اضافه کنید (جست‌وجو)…" />
          <p className="mt-1.5 text-xs" style={{ color: "var(--text-3)" }}>
            لیدهایی که «تماس نگیر» هستند، قبلاً با همین قالب پیام گرفته‌اند یا از یک سایت دو بار آمده‌اند خودکار کنار گذاشته می‌شوند و دلیلش را می‌بینید. بعداً هم می‌توانید لید اضافه کنید.
          </p>
          {mode === "manual" && (
            <label className="mt-2 flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" className="mt-1" checked={force} onChange={(e) => setForce(e.target.checked)} />
              <span>لیدهایی را هم اضافه کن که قبلاً با همین قالب پیام گرفته‌اند (فقط وقتی عمداً می‌خواهید دوباره پیام بدهید)</span>
            </label>
          )}
        </div>

        {action.error && !errors.name && !errors.template_id && <Flash tone="bad">{action.error.message}</Flash>}
      </form>
    </Modal>
  );
}
