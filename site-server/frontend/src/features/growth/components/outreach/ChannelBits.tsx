import Icon from "../../../../components/Icon";
import { Alert, Badge, fa } from "../../../../components/ui";
import { shortUrl } from "../../format";
import { CHANNELS, channelLabel } from "../../outreach/labels";
import type { OutreachItem, SmsSize } from "../../outreach/types";
import { CopyButton } from "../bits";
import { Ltr } from "./shared";

/** A small chip with the channel of an item / campaign / template. */
export function ChannelBadge({ channel, label }: { channel?: string | null; label?: string }) {
  const known = CHANNELS.find((c) => c.key === channel);
  const tone = !channel || channel === "any" ? "neutral" : channel === "auto" ? "brand" : known?.kind === "manual" ? "warn" : "info";
  return (
    <span data-testid="channel-badge" data-channel={channel ?? "contact_form"}>
      <Badge tone={tone}>{label || channelLabel(channel)}</Badge>
    </span>
  );
}

/** What an SMS costs: parts of the phone's SMS, in plain words. */
export function SmsMeter({ size }: { size: SmsSize | { parts: number; length: number; max_parts?: number; fits?: boolean } | null | undefined }) {
  if (!size) return null;
  const max = "max_parts" in size && size.max_parts ? size.max_parts : 2;
  const fits = "fits" in size && size.fits !== undefined ? size.fits : size.parts <= max;
  return (
    <span className="inline-flex items-center gap-2 text-xs" data-testid="sms-meter" data-fits={fits ? "1" : "0"}>
      <Badge tone={fits ? "ok" : "bad"}>
        {fa(size.parts)} از {fa(max)} بخش
      </Badge>
      <span style={{ color: "var(--text-3)" }}>{fa(size.length)} نویسه (بخشِ اول ۷۰، بعد هر بخش ۶۷)</span>
      {!fits && <span style={{ color: "var(--bad)" }}>بیش از حدِ مجاز؛ متن را کوتاه کنید.</span>}
    </span>
  );
}

/** The recipient of an item as one short cell: the page for a form, the address / number for the other channels. */
export function RecipientText({ item }: { item: OutreachItem }) {
  const channel = item.channel ?? "contact_form";
  if (channel === "contact_form") return item.target_url ? <Ltr className="text-xs">{shortUrl(item.target_url)}</Ltr> : <span style={{ color: "var(--text-3)" }}>—</span>;
  const value = item.recipient || item.manual?.recipient || "";
  return value ? <Ltr className="text-xs">{shortUrl(value)}</Ltr> : <span style={{ color: "var(--text-3)" }}>—</span>;
}

/**
 * The right-hand block of the review dialog for a channel that is not a form: who gets it, from where, how big it is,
 * what is wrong (if anything) - or, for a channel a person works by hand, the ready link and the steps.
 */
export function ChannelPlanBox({ item }: { item: OutreachItem }) {
  const plan = item.plan;
  const channel = item.channel ?? "contact_form";
  const problems = plan?.problems ?? [];
  const row = (label: string, value: React.ReactNode) => (
    <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
      <span style={{ color: "var(--text-3)" }}>{label}:</span>
      <span style={{ color: "var(--text)" }}>{value}</span>
    </div>
  );
  return (
    <div className="space-y-3" data-testid="channel-plan">
      <div className="flex flex-wrap items-center gap-2">
        <ChannelBadge channel={channel} label={item.channel_label} />
        {item.template && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            قالب: {item.template.name}
          </span>
        )}
      </div>
      {row("گیرنده", item.recipient ? <Ltr>{item.recipient}</Ltr> : <span style={{ color: "var(--text-3)" }}>معلوم نیست</span>)}
      {channel === "email" && plan?.from && row("فرستنده (From)", <Ltr>{plan.from}</Ltr>)}
      {channel === "email" && plan?.reply_to && row("پاسخ‌ها به", <Ltr>{plan.reply_to}</Ltr>)}
      {channel === "email" && row("موضوع", item.subject || <span style={{ color: "var(--bad)" }}>خالی</span>)}
      {channel === "sms" && item.sms && <SmsMeter size={item.sms} />}
      {plan?.note && <Alert tone="warn">{plan.note}</Alert>}
      {problems.length > 0 && (
        <Alert tone="warn" title="چرا آماده نیست">
          <ul className="list-disc ps-5">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      )}
      {item.manual && <ManualActions item={item} />}
      {!item.manual && plan?.ok && (
        <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
          پیش از ارسال دوباره بررسی می‌شود (حسابِ ایمیل، گوشی، متن و فهرستِ «تماس نگیر»)؛ اگر چیزی عوض شده باشد تأیید باطل می‌شود و چیزی نمی‌رود.
          {channel === "sms" && " «ارسال شد» فقط وقتی نوشته می‌شود که گوشی گزارش بدهد."}
        </p>
      )}
    </div>
  );
}

/** The ready link + the text to paste for a channel a person works by hand. Nothing here talks to any messenger account. */
export function ManualActions({ item }: { item: OutreachItem }) {
  const manual = item.manual;
  if (!manual) return null;
  return (
    <div className="space-y-2 rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="manual-actions">
      <div className="text-xs leading-6" style={{ color: "var(--text-2)" }}>
        {manual.steps}
      </div>
      <div className="flex flex-wrap gap-2">
        {manual.link && (
          <a href={manual.link} target={manual.link_kind === "https" ? "_blank" : undefined} rel="noopener noreferrer" className="u-btn u-btn-secondary u-btn-sm no-underline" data-testid="manual-link">
            <Icon name="link" size={14} /> {manual.label}
          </a>
        )}
        <CopyButton text={item.rendered_text} label="کپیِ متن" />
      </div>
      {manual.note && (
        <div className="text-xs" style={{ color: "var(--warn)" }}>
          {manual.note}
        </div>
      )}
    </div>
  );
}
