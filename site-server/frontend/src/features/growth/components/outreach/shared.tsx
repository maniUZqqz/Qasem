import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Meter, fa } from "../../../../components/ui";
import { g } from "../../api";
import { ConfirmDialog } from "../Modal";
import { useAction } from "../../outreach/api";
import { campaignState, itemStatus, MODE_LABEL } from "../../outreach/labels";
import type { CampaignMode, GrowthSettings } from "../../outreach/types";

/** Small pieces shared by the outreach, settings and campaign screens. */

export function ItemStatusBadge({ status, label }: { status: string; label?: string }) {
  const info = itemStatus(status);
  return (
    <span title={info.hint || undefined}>
      <Badge tone={info.tone}>{label || info.label}</Badge>
    </span>
  );
}

export function CampaignStateBadge({ status, label }: { status: string; label?: string }) {
  const info = campaignState(status);
  return <Badge tone={info.tone}>{label || info.label}</Badge>;
}

export function ModeBadge({ mode }: { mode: CampaignMode }) {
  return <Badge tone={mode === "auto" ? "brand" : "info"}>{MODE_LABEL[mode] ?? mode}</Badge>;
}

/** Left-to-right text inside Persian text (URLs, phones, e-mails, payload values). */
export function Ltr({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span dir="ltr" className={`inline-block max-w-full break-all text-start ${className}`} style={{ unicodeBidi: "isolate" }}>
      {children}
    </span>
  );
}

/** An inline result message that stays until the next action. */
export function Flash({ tone, children, onClose }: { tone: "ok" | "bad" | "warn" | "info"; children: ReactNode; onClose?: () => void }) {
  return (
    <Alert
      tone={tone}
      action={
        onClose && (
          <button type="button" className="u-btn u-btn-ghost u-btn-sm" onClick={onClose} aria-label="بستن پیام">
            <Icon name="x" size={14} />
          </button>
        )
      }
    >
      {children}
    </Alert>
  );
}

/** «امروز ۱۲ از ۴۰» with the usage bar. */
export function CapMeter({ sent, cap }: { sent: number; cap: number }) {
  return (
    <div data-testid="cap-meter">
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span style={{ color: "var(--text-2)" }}>ارسالِ امروز</span>
        <span className="u-num font-bold" style={{ color: "var(--text)" }}>
          {fa(sent)} از {fa(cap)}
        </span>
      </div>
      <Meter used={sent} total={cap} />
    </div>
  );
}

/**
 * The red emergency stop (or, when already stopped, the release). One click and a confirmation:
 * while stopped nothing is sent by any campaign and running send jobs end at once.
 */
export function EmergencyStopButton({ stopped, onChanged, compact = false }: { stopped: boolean; onChanged: () => void; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const action = useAction();
  const confirm = async () => {
    const done = await action.run(() => g.post("/settings/emergency-stop/", { stop: !stopped }));
    if (done !== undefined) {
      setOpen(false);
      onChanged();
    }
  };
  return (
    <>
      <Button
        variant={stopped ? "secondary" : "danger"}
        size={compact ? "sm" : undefined}
        onClick={() => {
          action.clear();
          setOpen(true);
        }}
        data-testid="emergency-stop"
        type="button"
      >
        <Icon name={stopped ? "play" : "stop"} size={compact ? 14 : 17} />
        {stopped ? "رفعِ توقفِ اضطراری" : "توقفِ اضطراری"}
      </Button>
      <ConfirmDialog
        open={open}
        title={stopped ? "رفعِ توقفِ اضطراری؟" : "توقفِ اضطراری؟"}
        danger={!stopped}
        confirmLabel={stopped ? "بله، رفع شود" : "بله، همه‌چیز متوقف شود"}
        busy={action.busy}
        onConfirm={confirm}
        onClose={() => setOpen(false)}
        message={
          <div className="space-y-2">
            <p>
              {stopped
                ? "با رفعِ توقف، کمپین‌های فعال دوباره می‌توانند ارسال کنند (فقط موردهای تأییدشده و در حدِ سقفِ روزانه)."
                : "بلافاصله هیچ پیامی از هیچ کمپینی فرستاده نمی‌شود و کارهای ارسالِ در حال اجرا همین‌جا تمام می‌شوند. پیام‌هایی که تا حالا رفته‌اند برنمی‌گردند."}
            </p>
            {action.error && <p style={{ color: "var(--bad)" }}>{action.error.message}</p>}
          </div>
        }
      />
    </>
  );
}

/**
 * What stops automatic sending right now - shown at the top of the screens where it matters:
 * the emergency stop (red, with the release), sending switched off, identity incomplete.
 */
export function SendingBanners({ settings, onChanged, showSettingsLink = true }: { settings: GrowthSettings | null; onChanged: () => void; showSettingsLink?: boolean }) {
  if (!settings) return null;
  const toSettings = showSettingsLink ? (
    <Link to="/growth/settings" className="u-btn u-btn-secondary u-btn-sm no-underline">
      تنظیمات
    </Link>
  ) : undefined;
  return (
    <div className="space-y-3" data-testid="sending-banners">
      {settings.emergency_stop && (
        <Alert
          tone="bad"
          title="توقفِ اضطراری فعال است"
          action={<EmergencyStopButton stopped onChanged={onChanged} compact />}
        >
          هیچ پیامی ارسال نمی‌شود و کارهای ارسال متوقف‌اند، تا وقتی که توقف را رفع کنید.
        </Alert>
      )}
      {!settings.emergency_stop && !settings.sending_enabled && (
        <Alert tone="warn" title="ارسالِ خودکار خاموش است" action={toSettings}>
          تا وقتی در تنظیمات روشنش نکنید، هیچ پیامی خودکار نمی‌رود. صفِ دستی همچنان کار می‌کند.
        </Alert>
      )}
      {!settings.emergency_stop && !settings.ready.ok && (
        <Alert tone="warn" title="تنظیماتِ ارسال کامل نیست" action={toSettings}>
          <ul className="list-disc ps-5">
            {settings.ready.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      )}
    </div>
  );
}
