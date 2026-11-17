import { useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Input, Select, TextArea, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { faAgo, faDateTime } from "../../format";
import Modal from "../../components/Modal";
import type { Activity, Note, Paged as GPaged } from "../../types";
import { useFinder } from "../FinderLayout";
import type { Reminders, Result } from "../types";
import DncDialog from "../../components/leads/DncDialog";
import { ReasonList, ScoreBadge, SOURCE_LABEL, mapsLink } from "./bits";

type ResultList = { results: Result[] };

/**
 * Everything about one found business in one window: why it scored what it did, how to reach it, where it is, its stage, the
 * follow-up reminders, notes and history - and the buttons that write a message draft (nothing is sent from here).
 */
export default function LeadPanel({ leadId, missionId, onClose, onChanged }: { leadId: number; missionId?: number | null; onClose: () => void; onChanged?: () => void }) {
  const { meta } = useFinder();
  const found = useGet<ResultList>("/finder/results/", { lead: leadId, page_size: 5, ...(missionId ? { mission: missionId } : {}) });
  const reminders = useGet<Reminders>("/finder/reminders/", { lead: leadId, when: "open" });
  const notes = useGet<Note[]>(`/leads/${leadId}/notes/`);
  const activity = useGet<GPaged<Activity>>(`/leads/${leadId}/activity/`, { page_size: 12 });
  const lead = useGet<{ id: number; business_name: string; display_name: string; status: string; city: string; contacts: { id: number; kind: string; kind_label?: string; value: string; label?: string; source_url?: string; confidence?: number | null }[] }>(`/leads/${leadId}/`);
  const row = found.data?.results[0] ?? null;

  const [note, setNote] = useState("");
  const [remNote, setRemNote] = useState("");
  const [remDays, setRemDays] = useState("3");
  const [channels, setChannels] = useState<string[]>(["sms"]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [dnc, setDnc] = useState(false);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: "ok", text: ok });
      onChanged?.();
    } catch (err) {
      setMsg({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };

  const stage = row?.stage ?? "new";
  return (
    <Modal open title={row?.name ?? lead.data?.display_name ?? "کسب‌وکار"} onClose={onClose} size="lg" testId="lead-panel">
      <div className="space-y-5">
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        {row?.individual && (
          <Alert tone="warn" title="فردِ مستقل">
            <span data-testid="individual-note">{meta?.individuals.note} پیش از هر پیام مطمئن شوید که او خودش این راهِ تماس را برای کار منتشر کرده؛ اگر نخواست، «تماس نگیر» را بزنید.</span>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {row && <ScoreBadge score={row.score} level={row.level} />}
          {row?.city && <Badge tone="brand">{row.city}</Badge>}
          {row?.category && <Badge>{row.category}</Badge>}
          {row && row.missions > 1 && <Badge tone="info">در {fa(row.missions)} مأموریت</Badge>}
          {row?.sources.map((s) => (
            <Badge key={s} tone="info">
              {SOURCE_LABEL[s] ?? s}
            </Badge>
          ))}
          <span className="ms-auto flex items-center gap-2 text-sm">
            مرحله:
            <Select
              value={stage}
              style={{ width: 160 }}
              onChange={(e) => run("stage", () => g.post(`/finder/leads/${leadId}/stage/`, { stage: e.target.value }).then(() => { found.reload(); lead.reload(); }), "مرحله عوض شد.")}
              data-testid="lead-stage"
              aria-label="مرحلهٔ فروش"
            >
              {meta?.stages.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </Select>
            <Link to={`/growth/leads/${leadId}`} className="u-btn u-btn-secondary u-btn-sm no-underline">
              صفحهٔ کاملِ لید
            </Link>
            <Button variant="ghost" size="sm" onClick={() => setDnc(true)} data-testid="lead-dnc">
              <Icon name="stop" size={13} />
              تماس نگیر
            </Button>
          </span>
        </div>

        {row && (
          <div>
            <h4 className="mb-1 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              چرا این امتیاز؟
            </h4>
            <ReasonList reasons={row.reasons} />
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h4 className="mb-1 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              راه‌های تماس
            </h4>
            <ul className="space-y-1 text-sm" data-testid="lead-contacts">
              {lead.data?.contacts.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2">
                  <Badge>{c.kind_label ?? c.kind}</Badge>
                  <span dir="ltr" className="u-num">
                    {c.value}
                  </span>
                  {typeof c.confidence === "number" && (
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      اطمینان {fa(c.confidence)}٪
                    </span>
                  )}
                  {c.source_url && (
                    <a href={c.source_url} target="_blank" rel="noreferrer noopener" className="text-xs underline" style={{ color: "var(--text-3)" }}>
                      منبع
                    </a>
                  )}
                </li>
              ))}
              {lead.data && !lead.data.contacts.length && <li style={{ color: "var(--text-3)" }}>راهِ تماسی ثبت نشده.</li>}
            </ul>
          </div>
          <div className="space-y-1 text-sm" style={{ color: "var(--text-2)" }}>
            <h4 className="mb-1 text-sm font-bold">مکان و ساعت</h4>
            {row?.address && <div>{row.address}</div>}
            {row?.hours && <div>ساعتِ کاری: {row.hours}</div>}
            {row?.rating != null && <div>امتیازِ نقشه/فهرست: {fa(row.rating)} از ۵</div>}
            {row?.lat != null && row?.lon != null ? (
              <a href={mapsLink(row.lat, row.lon)} target="_blank" rel="noreferrer noopener" className="underline" dir="ltr">
                {fa(row.lat.toFixed(5))}, {fa(row.lon.toFixed(5))}
              </a>
            ) : (
              <div style={{ color: "var(--text-3)" }}>مختصاتی ثبت نشده.</div>
            )}
            {row && row.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {row.tags.map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }}>
          <h4 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
            یادآوریِ پیگیری
          </h4>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={remDays} onChange={(e) => setRemDays(e.target.value)} style={{ width: 130 }} aria-label="چند روز دیگر" data-testid="reminder-days">
              {[["0", "امروز"], ["1", "فردا"], ["3", "۳ روز دیگر"], ["7", "یک هفته دیگر"], ["14", "دو هفته دیگر"], ["30", "یک ماه دیگر"]].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
            <Input value={remNote} onChange={(e) => setRemNote(e.target.value)} placeholder="مثلاً: زنگ بزن و نمونه بفرست" style={{ flex: 1, minWidth: 180 }} data-testid="reminder-note" />
            <Button size="sm" disabled={busy === "rem"} onClick={() => run("rem", () => g.post(`/finder/leads/${leadId}/reminders/`, { in_days: Number(remDays), note: remNote }).then(() => { setRemNote(""); reminders.reload(); activity.reload(); }), "یادآوری ثبت شد.")} data-testid="reminder-add">
              <Icon name="bell" size={14} />
              ثبت
            </Button>
          </div>
          <ul className="mt-2 space-y-1 text-sm" data-testid="reminder-list">
            {reminders.data?.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={r.overdue ? "bad" : "info"}>{faDateTime(r.due_at)}</Badge>
                <span>{r.note || "—"}</span>
                <Button variant="ghost" size="sm" onClick={() => run("rem-done", () => g.patch(`/finder/reminders/${r.id}/`, { done: true }).then(() => { reminders.reload(); activity.reload(); }), "پیگیری انجام شد.")}>
                  <Icon name="check" size={13} />
                  انجام شد
                </Button>
              </li>
            ))}
            {reminders.data && !reminders.data.items.length && <li style={{ color: "var(--text-3)" }}>یادآوریِ بازی نیست.</li>}
          </ul>
        </div>

        {meta && row && (
          <div className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }}>
            <h4 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              پیش‌نویسِ پیام
            </h4>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              {meta.channels.map((c) => (
                <label key={c.key} className="flex items-center gap-1.5">
                  <input type="checkbox" checked={channels.includes(c.key)} onChange={(e) => setChannels(e.target.checked ? [...channels, c.key] : channels.filter((x) => x !== c.key))} />
                  {c.label}
                </label>
              ))}
              <Button size="sm" disabled={!channels.length || busy === "draft"} onClick={() => run("draft", async () => {
                const r = await g.post<{ created: number; updated: number; skipped: { text: string }[] }>(`/finder/missions/${row.mission_id}/drafts/`, { lead_ids: [leadId], channels });
                if (!r.created && !r.updated) throw new Error(r.skipped[0]?.text ?? "پیش‌نویسی ساخته نشد.");
              }, "پیش‌نویس نوشته شد؛ در «پیش‌نویسِ پیام‌ها» ببینید و تأیید کنید. چیزی فرستاده نشد.")} data-testid="draft-make">
                <Icon name="edit" size={14} />
                بنویس
              </Button>
              <Link to={`/growth/finder/drafts?mission=${row.mission_id}`} className="text-xs underline" style={{ color: "var(--text-3)" }}>
                رفتن به پیش‌نویس‌ها
              </Link>
            </div>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h4 className="mb-1 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              یادداشت‌ها
            </h4>
            <div className="flex gap-2">
              <TextArea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="یادداشتِ تازه…" data-testid="note-input" />
              <Button size="sm" disabled={!note.trim() || busy === "note"} onClick={() => run("note", () => g.post(`/leads/${leadId}/notes/`, { body: note.trim() }).then(() => { setNote(""); notes.reload(); activity.reload(); }), "یادداشت ثبت شد.")} data-testid="note-add">
                ثبت
              </Button>
            </div>
            <ul className="mt-2 space-y-2 text-sm" data-testid="note-list">
              {notes.data?.map((n) => (
                <li key={n.id} className="rounded-lg p-2" style={{ background: "var(--surface-2)" }}>
                  <div style={{ color: "var(--text)" }}>{n.body}</div>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {n.author_name || "—"} · {faAgo(n.created_at)}
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mb-1 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              تاریخچه
            </h4>
            <ul className="space-y-1 text-xs" style={{ color: "var(--text-2)" }} data-testid="activity-list">
              {activity.data?.results.map((a) => (
                <li key={a.id}>
                  <b>{a.kind_label}</b> · {a.summary} <span style={{ color: "var(--text-3)" }}>({faAgo(a.created_at)})</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
      <DncDialog open={dnc} leadId={leadId} leadName={row?.name ?? lead.data?.display_name ?? "این کسب‌وکار"} onClose={() => setDnc(false)} onDone={() => { setDnc(false); setMsg({ tone: "ok", text: "در فهرستِ «تماس نگیر» ثبت شد؛ هیچ پیامی برایش نوشته یا فرستاده نمی‌شود." }); onChanged?.(); }} />
    </Modal>
  );
}
