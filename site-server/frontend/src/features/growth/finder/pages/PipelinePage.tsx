import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Select, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { faAgo, faDateTime } from "../../format";
import LeadPanel from "../components/LeadPanel";
import { Section } from "../components/bits";
import type { Board, BoardCard, Mission, Paged, Reminders } from "../types";

const WHEN: [string, string][] = [
  ["overdue", "عقب‌افتاده"],
  ["today", "تا امروز"],
  ["week", "این هفته"],
  ["open", "همهٔ بازها"],
  ["done", "انجام‌شده"],
];

/** «پایپ‌لاینِ فروش»: six columns (تازه ← مشتری / رد); drag a card or use its menu to move it. Follow-up reminders are on the right. */
export default function PipelinePage() {
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.get(k) ?? "";
  const params = { ...(get("mission") ? { mission: get("mission") } : {}), ...(get("q") ? { q: get("q") } : {}), ...(get("min_score") ? { min_score: get("min_score") } : {}), scope: get("scope") || "finder" };
  const board = useGet<Board>("/finder/pipeline/", params, { poll: 30000 });
  const [when, setWhen] = useState("overdue");
  const rem = useGet<Reminders>("/finder/reminders/", { when });
  const missions = useGet<Paged<Mission>>("/finder/missions/", { page_size: 100 });
  const [dragId, setDragId] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const patch = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  };

  const move = async (leadId: number, stage: string) => {
    setNotice(null);
    try {
      await g.post(`/finder/leads/${leadId}/stage/`, { stage });
      board.reload();
      rem.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    }
  };

  const reminder = async (id: number, body: Record<string, unknown>) => {
    try {
      await g.patch(`/finder/reminders/${id}/`, body);
      rem.reload();
      board.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    }
  };

  const stages = board.data?.stages ?? [];
  const Card1 = ({ c, stage }: { c: BoardCard; stage: string }) => (
    <div
      draggable
      onDragStart={(e) => {
        setDragId(c.id);
        e.dataTransfer.setData("text/plain", String(c.id));
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragEnd={() => {
        setDragId(null);
        setOver(null);
      }}
      className="rounded-xl p-2.5 text-sm"
      style={{ background: "var(--surface)", border: `1px solid ${c.overdue ? "var(--bad)" : "var(--line)"}`, opacity: dragId === c.id ? 0.5 : 1, cursor: "grab" }}
      data-testid="board-card"
    >
      <div className="flex items-start justify-between gap-2">
        <button type="button" className="text-start font-bold" style={{ color: "var(--text)" }} onClick={() => setOpen(c.id)}>
          {c.name}
        </button>
        {c.score != null && <span className="u-num text-xs font-bold" style={{ color: c.score >= 70 ? "var(--ok)" : "var(--text-3)" }}>{fa(c.score)}</span>}
      </div>
      <div className="text-xs" style={{ color: "var(--text-3)" }}>
        {[c.city, c.category].filter(Boolean).join(" · ")}
      </div>
      {c.phone && (
        <div className="u-num text-xs" dir="ltr" style={{ textAlign: "start", color: "var(--text-2)" }}>
          {c.phone}
        </div>
      )}
      {c.next_due && (
        <div className="mt-1">
          <Badge tone={c.overdue ? "bad" : "info"}>
            <Icon name="bell" size={11} /> {faDateTime(c.next_due)}
          </Badge>
        </div>
      )}
      <Select value={stage} onChange={(e) => move(c.id, e.target.value)} className="mt-2" style={{ fontSize: 12, padding: "4px 8px" }} aria-label="انتقال به مرحله" data-testid="card-stage">
        {stages.map((s) => (
          <option key={s.key} value={s.key}>
            {s.label}
          </option>
        ))}
      </Select>
    </div>
  );

  return (
    <div className="space-y-4" data-testid="finder-pipeline">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={get("mission")} onChange={(e) => patch({ mission: e.target.value })} style={{ width: 220 }} aria-label="مأموریت" data-testid="pipeline-mission">
            <option value="">همهٔ مأموریت‌ها</option>
            {missions.data?.results.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
          <Input value={get("q")} onChange={(e) => patch({ q: e.target.value })} placeholder="جست‌وجو…" style={{ width: 180 }} aria-label="جست‌وجو" />
          <Select value={get("min_score")} onChange={(e) => patch({ min_score: e.target.value })} style={{ width: 150 }} aria-label="حداقل امتیاز">
            <option value="">هر امتیاز</option>
            <option value="45">۴۵ به بالا</option>
            <option value="70">۷۰ به بالا</option>
          </Select>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={get("scope") === "all"} onChange={(e) => patch({ scope: e.target.checked ? "all" : null })} />
            همهٔ لیدهای جذب مشتری (نه فقط یافته‌های مشتری‌یاب)
          </label>
          <span className="ms-auto text-xs" style={{ color: "var(--text-3)" }}>
            {board.data ? `${fa(board.data.total)} لید` : ""}
          </span>
        </div>
      </Card>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}

      <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
        <div className="overflow-x-auto pb-2">
          {board.error ? (
            <Alert tone="bad">{board.error}</Alert>
          ) : (
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(6, minmax(13rem, 1fr))", minWidth: 6 * 208 }} data-testid="board">
              {stages.map((s) => (
                <div
                  key={s.key}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOver(s.key);
                  }}
                  onDragLeave={() => setOver((o) => (o === s.key ? null : o))}
                  onDrop={(e) => {
                    e.preventDefault();
                    const id = Number(e.dataTransfer.getData("text/plain")) || dragId;
                    setOver(null);
                    if (id) move(id, s.key);
                  }}
                  className="space-y-2 rounded-2xl p-2"
                  style={{ background: "var(--surface-2)", border: `1px dashed ${over === s.key ? "var(--brand)" : "var(--line)"}`, minHeight: 160 }}
                  data-testid={`col-${s.key}`}
                >
                  <div className="flex items-center justify-between px-1">
                    <Badge tone={s.tone}>{s.label}</Badge>
                    <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
                      {fa(s.count)}
                    </span>
                  </div>
                  {s.cards.map((c) => (
                    <Card1 key={c.id} c={c} stage={s.key} />
                  ))}
                  {s.count > s.cards.length && (
                    <div className="px-1 text-xs" style={{ color: "var(--text-3)" }}>
                      و {fa(s.count - s.cards.length)} مورد دیگر (فیلتر کنید)
                    </div>
                  )}
                  {!s.cards.length && (
                    <div className="px-1 py-6 text-center text-xs" style={{ color: "var(--text-3)" }}>
                      خالی
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <Section title="یادآوری‌های پیگیری" hint="کارهایی که باید دوباره سراغشان رفت.">
          <Card className="space-y-3" >
            <div data-testid="reminders">
              <div className="flex flex-wrap gap-1.5">
                {WHEN.map(([k, l]) => (
                  <button key={k} type="button" className={`u-btn u-btn-sm ${when === k ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setWhen(k)} data-testid={`rem-${k}`}>
                    {l}
                    {k !== "done" && rem.data ? ` (${fa(rem.data.counts[k as keyof Reminders["counts"]] ?? 0)})` : ""}
                  </button>
                ))}
              </div>
              <ul className="mt-3 space-y-2">
                {rem.data?.items.map((r) => (
                  <li key={r.id} className="rounded-xl p-2.5 text-sm" style={{ background: "var(--surface-2)", border: `1px solid ${r.overdue ? "var(--bad)" : "var(--line)"}` }}>
                    <button type="button" className="font-bold" style={{ color: "var(--text)" }} onClick={() => setOpen(r.lead_id)}>
                      {r.lead_name}
                    </button>
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {r.note || "—"} · {r.done_at ? `انجام شد ${faAgo(r.done_at)}` : faDateTime(r.due_at)}
                    </div>
                    {!r.done_at && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        <Button size="sm" onClick={() => reminder(r.id, { done: true })} data-testid="rem-done">
                          <Icon name="check" size={12} />
                          انجام شد
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => reminder(r.id, { in_days: 1 })}>
                          فردا
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => reminder(r.id, { in_days: 7 })}>
                          هفتهٔ بعد
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
                {rem.data && !rem.data.items.length && (
                  <li>
                    <EmptyState icon="bell" title="یادآوری‌ای نیست">
                      از پنجرهٔ هر لید «یادآوریِ پیگیری» بگذارید.
                    </EmptyState>
                  </li>
                )}
              </ul>
            </div>
          </Card>
        </Section>
      </div>

      {open && <LeadPanel leadId={open} onClose={() => setOpen(null)} onChanged={() => { board.reload(); rem.reload(); }} />}
    </div>
  );
}
