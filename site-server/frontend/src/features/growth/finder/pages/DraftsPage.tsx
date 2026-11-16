import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Select, TextArea, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import Pagination from "../../components/Pagination";
import { faAgo } from "../../format";
import { useFinder } from "../FinderLayout";
import type { Draft, Mission, Paged } from "../types";

type DraftList = Paged<Draft> & { counts: Record<string, number> };
const STATUS_TONE: Record<string, "neutral" | "ok" | "info" | "warn" | "bad" | "brand"> = { draft: "neutral", approved: "ok", queued: "brand", sent_manual: "info", rejected: "bad", blocked: "bad" };
const STATUS_LABEL: Record<string, string> = { draft: "پیش‌نویس", approved: "متن تأیید شد", queued: "در کمپین گذاشته شد", sent_manual: "دستی فرستاده شد", rejected: "ردشد", blocked: "مسدود (تماس نگیر)" };

function openLink(d: Draft): string {
  if (d.channel === "instagram_dm") return d.recipient;
  if (d.channel === "whatsapp") return `https://wa.me/${d.recipient.replace(/^\+/, "").replace(/^0/, "98")}`;
  if (d.channel === "telegram") return d.recipient;
  return "";
}

/**
 * «پیش‌نویسِ پیام‌ها»: the messages written in the brand's voice, one per business and channel. Nothing here sends anything:
 * approving says «this text is fine»; for SMS / e-mail / the site's form a second step puts it into the mission's campaign (which has its
 * own approval, caps, quiet hours and the do-not-contact list); for Instagram / WhatsApp / Telegram you copy the text and send it yourself.
 */
export default function DraftsPage() {
  const { meta } = useFinder();
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.get(k) ?? "";
  const page = Number(get("page")) || 1;
  const params = { ...(get("mission") ? { mission: get("mission") } : {}), ...(get("status") ? { status: get("status") } : {}), ...(get("channel") ? { channel: get("channel") } : {}), page, page_size: 20 };
  const drafts = useGet<DraftList>("/finder/drafts/", params);
  const missions = useGet<Paged<Mission>>("/finder/missions/", { page_size: 100 });
  const [selected, setSelected] = useState<number[]>([]);
  const [edits, setEdits] = useState<Record<number, { body?: string; subject?: string }>>({});
  const [busy, setBusy] = useState<number | "bulk" | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const patch = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in changes)) next.delete("page");
    setSp(next);
  };

  const call = async (id: number | "bulk", fn: () => Promise<string>) => {
    setBusy(id);
    setNotice(null);
    try {
      setNotice({ tone: "ok", text: await fn() });
      drafts.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };
  const act = (d: Draft, action: string, ok: string) => call(d.id, async () => {
    await g.post(`/finder/drafts/${d.id}/${action}/`);
    return ok;
  });
  const save = (d: Draft) => call(d.id, async () => {
    await g.patch(`/finder/drafts/${d.id}/`, edits[d.id]);
    setEdits(({ [d.id]: _gone, ...rest }) => (void _gone, rest));
    return "ذخیره شد؛ تأییدِ قبلی (اگر بود) برداشته شد.";
  });
  const bulk = (action: string, label: string) => call("bulk", async () => {
    const r = await g.post<{ done: number; failed: { id: number; text: string }[] }>("/finder/drafts/bulk/", { ids: selected, action });
    setSelected([]);
    return `${label}: ${fa(r.done)} مورد${r.failed.length ? `؛ ${fa(r.failed.length)} مورد نشد (${r.failed[0].text})` : ""}.`;
  });
  const copy = async (d: Draft) => {
    try {
      await navigator.clipboard.writeText((edits[d.id]?.body ?? d.body) || "");
      setNotice({ tone: "ok", text: "متن کپی شد." });
    } catch {
      setNotice({ tone: "bad", text: "کپی نشد؛ متن را دستی انتخاب کنید." });
    }
  };

  const rows = drafts.data?.results ?? [];
  const counts = drafts.data?.counts ?? {};
  const editable = (d: Draft) => ["draft", "approved", "rejected"].includes(d.status);

  return (
    <div className="space-y-4" data-testid="finder-drafts">
      <Alert tone="info" title="هیچ پیامی از اینجا فرستاده نمی‌شود">
        «تأییدِ متن» فقط می‌گوید متن خوب است. پیامک، ایمیل و فرمِ سایت بعد از «بگذار در کمپین» وارد کمپین می‌شوند و آنجا هنوز تأییدِ جداگانه، سقفِ روزانه، فهرستِ «تماس نگیر» و کلیدِ «ارسالِ خودکار» (الان {meta?.outreach.sending_enabled ? "روشن" : "خاموش"}) لازم است. دایرکت/واتساپ/تلگرام را خودتان می‌فرستید. سقفِ روزانهٔ ارسال {meta ? fa(meta.outreach.daily_cap) : "—"} پیام است ({meta ? fa(meta.outreach.cap_remaining) : "—"} مانده؛ فاصله و ساعتِ سکوت را کمپین رعایت می‌کند).
        {meta && meta.outreach.identity_problems.length > 0 && <div className="mt-1">برای ارسال هنوز باید در «تنظیماتِ جذب مشتری» کامل شود: {meta.outreach.identity_problems.join(" ")}</div>}
      </Alert>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={get("mission")} onChange={(e) => patch({ mission: e.target.value })} style={{ width: 220 }} aria-label="مأموریت" data-testid="drafts-mission">
            <option value="">همهٔ مأموریت‌ها</option>
            {missions.data?.results.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
          <Select value={get("channel")} onChange={(e) => patch({ channel: e.target.value })} style={{ width: 180 }} aria-label="کانال">
            <option value="">همهٔ کانال‌ها</option>
            {meta?.channels.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </Select>
          <Select value={get("status")} onChange={(e) => patch({ status: e.target.value })} style={{ width: 180 }} aria-label="وضعیت" data-testid="drafts-status">
            <option value="">همهٔ وضعیت‌ها</option>
            {Object.entries(STATUS_LABEL).map(([k, l]) => (
              <option key={k} value={k}>
                {l} ({fa(counts[k] ?? 0)})
              </option>
            ))}
          </Select>
          {selected.length > 0 && (
            <span className="ms-auto flex flex-wrap items-center gap-2 text-sm">
              <b>{fa(selected.length)} انتخاب</b>
              <Button size="sm" disabled={busy === "bulk"} onClick={() => bulk("approve", "متن تأیید شد")} data-testid="drafts-bulk-approve">
                تأییدِ متن‌ها
              </Button>
              <Button size="sm" variant="secondary" disabled={busy === "bulk"} onClick={() => bulk("queue", "در کمپین گذاشته شد")}>
                بگذار در کمپین
              </Button>
              <Button size="sm" variant="ghost" disabled={busy === "bulk"} onClick={() => bulk("reject", "ردشد")}>
                رد
              </Button>
            </span>
          )}
        </div>
      </Card>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}

      {drafts.error ? (
        <Alert tone="bad">{drafts.error}</Alert>
      ) : rows.length === 0 && !drafts.loading ? (
        <Card>
          <EmptyState icon="send" title="پیش‌نویسی نیست">
            از «نتیجه‌ها و نقشه» چند لید را انتخاب کنید و «پیش‌نویسِ پیامک/دایرکت/ایمیل» را بزنید.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3" data-testid="draft-list">
          {rows.map((d) => {
            const e = edits[d.id] ?? {};
            const body = e.body ?? d.body;
            const dirty = e.body !== undefined || e.subject !== undefined;
            const link = openLink(d);
            return (
              <Card key={d.id} className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <input type="checkbox" checked={selected.includes(d.id)} onChange={() => setSelected((s) => (s.includes(d.id) ? s.filter((x) => x !== d.id) : [...s, d.id]))} aria-label="انتخاب" />
                  <Link to={`/growth/leads/${d.lead_id}`} className="font-bold no-underline" style={{ color: "var(--text)" }}>
                    {d.lead_name}
                  </Link>
                  {d.city && <Badge tone="brand">{d.city}</Badge>}
                  <Badge>{d.channel_label}</Badge>
                  <Badge tone={STATUS_TONE[d.status] ?? "neutral"}>{STATUS_LABEL[d.status] ?? d.status_label}</Badge>
                  <span className="text-xs" dir="ltr" style={{ color: "var(--text-3)" }}>
                    {d.recipient}
                  </span>
                  <span className="ms-auto text-xs" style={{ color: "var(--text-3)" }}>
                    {faAgo(d.updated_at)}
                  </span>
                </div>
                {d.block_reason && <Alert tone="bad">{d.block_reason}</Alert>}
                {d.warnings.length > 0 && (
                  <Alert tone="warn">
                    <ul className="list-disc ps-5">
                      {d.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </Alert>
                )}
                {d.channel === "email" && (
                  <Input value={e.subject ?? d.subject} disabled={!editable(d)} onChange={(ev) => setEdits({ ...edits, [d.id]: { ...e, subject: ev.target.value } })} aria-label="موضوع" />
                )}
                <TextArea rows={Math.min(12, Math.max(4, body.split("\n").length + 1))} value={body} disabled={!editable(d)} onChange={(ev) => setEdits({ ...edits, [d.id]: { ...e, body: ev.target.value } })} aria-label="متنِ پیام" data-testid="draft-body" />
                <div className="flex flex-wrap items-center gap-2">
                  {d.sms && (
                    <span className="text-xs" style={{ color: d.sms.parts > 2 ? "var(--bad)" : "var(--text-3)" }}>
                      {fa(d.sms.length)} نویسه · {fa(d.sms.parts)} بخشِ پیامک
                    </span>
                  )}
                  {dirty && editable(d) && (
                    <Button size="sm" variant="secondary" disabled={busy === d.id} onClick={() => save(d)} data-testid="draft-save">
                      ذخیره
                    </Button>
                  )}
                  {d.status === "draft" && (
                    <Button size="sm" disabled={busy === d.id || dirty} onClick={() => act(d, "approve", "متن تأیید شد (هنوز چیزی فرستاده نشده).")} data-testid="draft-approve">
                      <Icon name="check" size={13} />
                      تأییدِ متن
                    </Button>
                  )}
                  {d.status === "approved" && !d.manual && (
                    <Button size="sm" disabled={busy === d.id} onClick={() => act(d, "queue", "در کمپین گذاشته شد؛ برای ارسال باید در کمپین هم تأیید شود.")} data-testid="draft-queue">
                      بگذار در کمپین
                    </Button>
                  )}
                  {d.manual && (
                    <>
                      <Button size="sm" variant="secondary" onClick={() => copy(d)} data-testid="draft-copy">
                        <Icon name="copy" size={13} />
                        کپیِ متن
                      </Button>
                      {link && (
                        <a href={link} target="_blank" rel="noreferrer noopener" className="u-btn u-btn-secondary u-btn-sm no-underline">
                          <Icon name="link" size={13} />
                          باز کردنِ گفتگو
                        </a>
                      )}
                      {d.status === "approved" && (
                        <Button size="sm" disabled={busy === d.id} onClick={() => act(d, "sent", "ثبت شد: دستی فرستاده شد.")} data-testid="draft-sent">
                          فرستادم
                        </Button>
                      )}
                    </>
                  )}
                  {d.status === "queued" && d.campaign_id && (
                    <Link to={`/growth/outreach/${d.campaign_id}`} className="u-btn u-btn-secondary u-btn-sm no-underline">
                      رفتن به کمپین
                    </Link>
                  )}
                  {editable(d) && d.status !== "rejected" && (
                    <Button size="sm" variant="ghost" disabled={busy === d.id} onClick={() => act(d, "reject", "ردشد.")}>
                      رد
                    </Button>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {drafts.data && drafts.data.count > 20 && <Pagination page={page} pageSize={20} count={drafts.data.count} onPage={(p) => patch({ page: String(p) })} />}
    </div>
  );
}
