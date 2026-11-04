import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Button, Card, EmptyState, PageHeader, Table, fa } from "../../../components/ui";
import { useGet } from "../api";
import { LoadState } from "../components/bits";
import NewCampaignDialog from "../components/outreach/NewCampaignDialog";
import { CampaignStateBadge, ModeBadge, SendingBanners } from "../components/outreach/shared";
import { faDate } from "../format";
import { asList, useSettings } from "../outreach/api";
import { templateName } from "../outreach/labels";
import type { Campaign } from "../outreach/types";
import type { Paged } from "../types";

function Counters({ campaign }: { campaign: Campaign }) {
  const c = campaign.counts;
  if (!c) return <span style={{ color: "var(--text-3)" }}>—</span>;
  const total = campaign.items_total ?? Object.values(c).reduce((a, b) => a + b, 0);
  const sent = (c.sent ?? 0) + (c.manual_sent ?? 0);
  return (
    <span className="text-xs leading-6" style={{ color: "var(--text-2)" }}>
      {fa(total)} مورد · {fa(sent)} ارسال‌شده
      {c.ready ? ` · ${fa(c.ready)} منتظرِ تأیید` : ""}
      {c.needs_manual ? ` · ${fa(c.needs_manual)} دستی` : ""}
    </span>
  );
}

/**
 * «پیام‌رسانی»: the campaigns. The lead table hands leads over with `?new=1&lead_ids=1,2,3`, which opens the
 * «کمپین تازه» dialog with those leads already chosen.
 */
export default function OutreachPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const list = useGet<Paged<Campaign> | Campaign[]>("/outreach/campaigns/");
  const settings = useSettings();
  const [open, setOpen] = useState(false);

  const handoffIds = useMemo(
    () =>
      (params.get("lead_ids") ?? "")
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isInteger(n) && n > 0),
    [params],
  );

  useEffect(() => {
    if (params.get("new") === "1") setOpen(true);
  }, [params]);

  const closeDialog = () => {
    setOpen(false);
    if (params.has("new") || params.has("lead_ids")) setParams({}, { replace: true });
    list.reload();
  };

  const campaigns = asList(list.data);

  return (
    <div className="space-y-5" data-testid="outreach-page">
      <SendingBanners settings={settings.data} onChanged={settings.reload} />
      <PageHeader
        title="پیام‌رسانی"
        subtitle="هر کمپین یک قالبِ پیام و یک گروه از لیدهاست. ارسالِ خودکار فقط بعد از تأییدِ شما و در حدِ سقفِ روزانه انجام می‌شود؛ صفِ دستی برای وقتی است که خودتان می‌فرستید."
        actions={
          <Button onClick={() => setOpen(true)} data-testid="campaign-new">
            <Icon name="plus" size={16} />
            کمپینِ تازه
          </Button>
        }
      />

      <Card padded={false}>
        <div className="p-2">
          <LoadState loading={list.loading && !list.data} error={list.error} onRetry={list.reload}>
            {campaigns.length === 0 ? (
              <EmptyState
                icon="send"
                title="هنوز کمپینی نساخته‌اید"
                action={
                  <Button onClick={() => setOpen(true)}>
                    <Icon name="plus" size={16} />
                    ساختنِ اولین کمپین
                  </Button>
                }
              >
                کمپین یعنی: یک قالبِ پیام + چند لید. می‌توانید از «دیتابیس لیدها» چند لید را انتخاب کنید و مستقیم کمپین بسازید.
              </EmptyState>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th className="text-start">کمپین</th>
                    <th className="text-start">قالب</th>
                    <th className="text-start">روش</th>
                    <th className="text-start">وضعیت</th>
                    <th className="text-start">شمارنده‌ها</th>
                    <th className="text-start">ساخته‌شده</th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((c) => (
                    <tr
                      key={c.id}
                      data-testid="campaign-row"
                      onClick={() => navigate(`/growth/outreach/${c.id}`)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>
                        <Link to={`/growth/outreach/${c.id}`} className="font-medium no-underline" style={{ color: "var(--text)" }} onClick={(e) => e.stopPropagation()}>
                          {c.name}
                        </Link>
                      </td>
                      <td>{templateName(c)}</td>
                      <td>
                        <ModeBadge mode={c.mode} />
                      </td>
                      <td>
                        <CampaignStateBadge status={c.status} label={c.status_label} />
                      </td>
                      <td>
                        <Counters campaign={c} />
                      </td>
                      <td className="whitespace-nowrap text-xs" style={{ color: "var(--text-3)" }}>
                        {faDate(c.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </LoadState>
        </div>
      </Card>

      <NewCampaignDialog open={open} onClose={closeDialog} initialLeadIds={handoffIds} />
    </div>
  );
}
