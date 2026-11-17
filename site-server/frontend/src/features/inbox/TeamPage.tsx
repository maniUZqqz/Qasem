import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../api/client";
import { Badge, Button, Card, ErrorBox, Field, Input, SectionTitle, Select, Spinner } from "../../components/ui";
import {
  ASSIGN_TITLE, CHANNEL_TITLE, PRESENCE_TITLE, ROLE_TITLE, Settings, Stats, TeamRow, WEEKDAYS, get, patch,
} from "./api";
import { ago, duration, faNum, toInt } from "./format";
import { useInbox } from "./InboxLayout";

const CHANNEL_KEYS = ["TELEGRAM", "BALE", "EITAA", "RUBIKA", "WEBCHAT", "SMS", "INSTAGRAM", "WHATSAPP"];

function Stat({ value, label, tone }: { value: string; label: string; tone?: "bad" | "ok" }) {
  return (
    <Card>
      <div className="ib-stat">
        <b style={{ color: tone === "bad" ? "var(--bad)" : tone === "ok" ? "var(--ok)" : undefined }}>{value}</b>
        <span>{label}</span>
      </div>
    </Card>
  );
}

function MemberEditor({ row, storeId, canEdit, onSaved }: { row: TeamRow; storeId: string; canEdit: boolean; onSaved: () => void }) {
  const [channels, setChannels] = useState<string[]>(row.channels);
  const [skills, setSkills] = useState(row.skills.join("، "));
  const [maxOpen, setMaxOpen] = useState(String(row.max_open));
  const [accepts, setAccepts] = useState(row.accepts_chats);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await patch(storeId, `team/${row.username}/`, {
        channels,
        skills: skills.split(/[،,\n]/).map((s) => s.trim()).filter(Boolean),
        max_open: toInt(maxOpen, 12),
        accepts_chats: accepts,
      });
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-3 p-3 *:min-w-0" style={{ background: "var(--surface-2)", borderRadius: 12 }}>
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <input type="checkbox" checked={accepts} disabled={!canEdit} onChange={(e) => setAccepts(e.target.checked)} />
        گفتگوی تازه به این نفر داده شود
      </label>
      <Field label="کانال‌هایی که می‌پوشاند" hint="هیچ‌کدام = همه‌ی کانال‌ها (در حالت «بر اساس کانال» کسی که کانالی را نام ببرد اولویت دارد).">
        <div className="flex flex-wrap gap-2">
          {CHANNEL_KEYS.map((k) => (
            <label key={k} className="ib-pill" style={{ cursor: canEdit ? "pointer" : "default" }}>
              <input
                type="checkbox"
                checked={channels.includes(k)}
                disabled={!canEdit}
                onChange={(e) => setChannels(e.target.checked ? [...channels, k] : channels.filter((x) => x !== k))}
              />
              {CHANNEL_TITLE[k]}
            </label>
          ))}
        </div>
      </Field>
      <Field label="مهارت‌ها" hint="با ویرگول جدا کنید. در حالت «بر اساس مهارت»، گفتگو به کسی می‌رسد که مهارتش با برچسبِ گفتگو یا مشتری، یا با یک کلمهٔ پیام‌های اخیرِ مشتری (مثلاً «مشکل پرداخت دارم» ⇐ «پرداخت») جور باشد. مثل: پرداخت، ثبت‌نام">
        <Input value={skills} disabled={!canEdit} onChange={(e) => setSkills(e.target.value)} />
      </Field>
      <Field label="سقف گفتگوی هم‌زمان">
        <Input value={maxOpen} inputMode="numeric" disabled={!canEdit} onChange={(e) => setMaxOpen(e.target.value)} style={{ width: 120 }} />
      </Field>
      <ErrorBox message={error} />
      {canEdit && (
        <div>
          <Button size="sm" disabled={busy} onClick={() => void save()}>ذخیرهٔ این عضو</Button>
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const { storeId, me } = useInbox();
  const [days, setDays] = useState(30);
  const [team, setTeam] = useState<{ members: TeamRow[]; unassigned_open: number } | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openMember, setOpenMember] = useState<string | null>(null);
  const canEdit = Boolean(me?.can_settings);

  const load = useCallback(async () => {
    try {
      const [t, s, c] = await Promise.all([
        get<{ members: TeamRow[]; unassigned_open: number }>(storeId, "team/", { days }),
        get<Stats>(storeId, "stats/", { days }),
        get<Settings>(storeId, "settings/"),
      ]);
      setTeam(t);
      setStats(s);
      setCfg(c);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, days]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveCfg = async (changes: Partial<Settings>) => {
    try {
      const res = await patch<Settings>(storeId, "settings/", changes);
      setCfg(res);
      setNotice("ذخیره شد.");
      setError(null);
      window.setTimeout(() => setNotice(null), 2500);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!team || !stats || !cfg) return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  const hours = cfg.working_hours.days?.length ? cfg.working_hours : null;

  return (
    <div className="grid gap-6 *:min-w-0">
      <ErrorBox message={error} />
      {notice && <div className="text-sm" style={{ color: "var(--ok)" }}>{notice}</div>}

      <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        بازهٔ گزارش
        <Select value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 130 }} aria-label="بازهٔ گزارش">
          <option value={7}>۷ روز</option>
          <option value={30}>۳۰ روز</option>
          <option value={90}>۹۰ روز</option>
        </Select>
      </div>

      <div className="ib-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 170px), 1fr))" }}>
        <Stat value={faNum(stats.open)} label="گفتگوی باز" />
        <Stat value={faNum(stats.waiting_for_person)} label="منتظر پاسخ" tone={stats.waiting_for_person ? "bad" : undefined} />
        <Stat value={faNum(team.unassigned_open)} label="بدون مسئول" tone={team.unassigned_open ? "bad" : undefined} />
        <Stat value={duration(stats.avg_first_response_seconds)} label="میانگین اولین پاسخ" />
        <Stat value={faNum(stats.sla_breaches)} label="رد شدن SLA" tone={stats.sla_breaches ? "bad" : "ok"} />
        <Stat value={faNum(stats.bot_handoffs)} label="واگذاری ربات به تیم" />
        <Stat value={stats.survey.average === null ? "—" : faNum(stats.survey.average)} label={`رضایت (از ۵) · ${faNum(stats.survey.answered)} پاسخ`} />
      </div>

      <div>
        <SectionTitle>اعضای تیم</SectionTitle>
        <Card padded={false}>
          <div className="ib-table-wrap">
            <table className="u-table">
              <thead>
                <tr>
                  <th>عضو</th>
                  <th>وضعیت</th>
                  <th>گفتگوی باز</th>
                  <th>پاسخ‌ها</th>
                  <th>میانگین پاسخ</th>
                  <th>اولین پاسخ</th>
                  <th>رد SLA</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {team.members.map((m) => (
                  <>
                    <tr key={m.username}>
                      <td>
                        <b>{m.name}</b>
                        <div className="text-xs" style={{ color: "var(--text-3)" }}>{m.role_title || (m.role ? ROLE_TITLE[m.role] ?? m.role : "")}</div>
                      </td>
                      <td>
                        <Badge tone={m.status === "ONLINE" ? "ok" : m.status === "BUSY" ? "warn" : "neutral"}>{PRESENCE_TITLE[m.status]}</Badge>
                        {m.status_note && <div className="text-xs" style={{ color: "var(--text-3)" }}>{m.status_note}</div>}
                        {m.status === "OFFLINE" && m.last_seen_at && <div className="text-xs" style={{ color: "var(--text-3)" }}>{ago(m.last_seen_at)}</div>}
                      </td>
                      <td className="u-num">{faNum(m.open)} / {faNum(m.max_open)}</td>
                      <td className="u-num">{faNum(m.replies)}</td>
                      <td className="u-num">{duration(m.avg_response_seconds)}</td>
                      <td className="u-num">{duration(m.avg_first_response_seconds)}</td>
                      <td className="u-num" style={{ color: m.sla_breaches ? "var(--bad)" : undefined }}>{faNum(m.sla_breaches)}</td>
                      <td>
                        <Button size="sm" variant="ghost" onClick={() => setOpenMember(openMember === m.username ? null : m.username)}>
                          {canEdit ? "تنظیم" : "جزئیات"}
                        </Button>
                      </td>
                    </tr>
                    {openMember === m.username && (
                      <tr key={`${m.username}-edit`}>
                        <td colSpan={8}>
                          <MemberEditor row={m} storeId={storeId} canEdit={canEdit} onSaved={() => { setOpenMember(null); void load(); }} />
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          اعضا را از صفحهٔ «اعضا و دسترسی» اضافه کنید (نقش «پشتیبانی» یا بالاتر). زمان پاسخ از لحظه‌ای حساب می‌شود که گفتگو به آدم رسید، نه از اولین پیام مشتری؛ گفتگوهای آزمایشی در هیچ عددی نیستند.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 *:min-w-0">
        <Card>
          <SectionTitle>تقسیم خودکار گفتگو</SectionTitle>
          <div className="grid gap-3 *:min-w-0">
            <Field label="روش تقسیم">
              <Select value={cfg.assignment_mode} disabled={!canEdit} onChange={(e) => void saveCfg({ assignment_mode: e.target.value as Settings["assignment_mode"] })}>
                {Object.entries(ASSIGN_TITLE).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </Select>
            </Field>
            <Field label="چه وقت تقسیم شود؟">
              <Select value={cfg.assign_when} disabled={!canEdit} onChange={(e) => void saveCfg({ assign_when: e.target.value as Settings["assign_when"] })}>
                <option value="HANDOFF">وقتی ربات گفتگو را به تیم داد</option>
                <option value="ALWAYS">از اولین پیام (حتی وقتی ربات جواب می‌دهد)</option>
              </Select>
            </Field>
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={cfg.assign_only_online} disabled={!canEdit} onChange={(e) => void saveCfg({ assign_only_online: e.target.checked })} />
              فقط به کسانی که «آنلاین» هستند (مشغول و آفلاین گفتگو نمی‌گیرند)
            </label>
          </div>
        </Card>

        <Card>
          <SectionTitle>SLA — مهلتِ اولین پاسخ</SectionTitle>
          <div className="grid gap-3 *:min-w-0">
            <Field label="مهلت (دقیقه)" hint="از لحظه‌ای که گفتگو به آدم رسید.">
              <Input value={String(cfg.sla_first_response_min)} inputMode="numeric" disabled={!canEdit} style={{ width: 140 }}
                onChange={(e) => setCfg({ ...cfg, sla_first_response_min: toInt(e.target.value, 15) })}
                onBlur={() => void saveCfg({ sla_first_response_min: cfg.sla_first_response_min })} />
            </Field>
            <Field label="هشدار از چند درصدِ مهلت" hint="مثلاً ۸۰٪ یعنی وقتی ۸۰٪ مهلت گذشت هشدار می‌دهد، و وقتی تمام شد «رد شد».">
              <Input value={String(cfg.sla_warn_percent)} inputMode="numeric" disabled={!canEdit} style={{ width: 140 }}
                onChange={(e) => setCfg({ ...cfg, sla_warn_percent: toInt(e.target.value, 80) })}
                onBlur={() => void saveCfg({ sla_warn_percent: cfg.sla_warn_percent })} />
            </Field>
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={cfg.sla_pause_off_hours} disabled={!canEdit} onChange={(e) => void saveCfg({ sla_pause_off_hours: e.target.checked })} />
              بیرون از ساعت کاری ساعتِ SLA متوقف باشد (از اولین ساعت کاری شروع شود)
            </label>
          </div>
        </Card>
      </div>

      <Card>
        <SectionTitle>ساعت کاری</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          ربات، پیام «خارج از ساعت کاری» و SLA از این ساعت‌ها می‌دانند الان باز هستید یا نه (به وقت تهران). خالی = همیشه باز.
          الان: <b>{cfg.open_now ? "باز" : "بسته"}</b>
        </p>
        <div className="flex flex-wrap gap-2">
          {WEEKDAYS.map((d) => {
            const on = hours?.days?.includes(d.n) ?? false;
            return (
              <label key={d.n} className={`ib-pill ${on ? "on" : ""}`} style={{ cursor: canEdit ? "pointer" : "default" }}>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={on}
                  disabled={!canEdit}
                  onChange={(e) => {
                    const base = hours ?? cfg.default_working_hours;
                    const set = new Set(base.days ?? []);
                    if (e.target.checked) set.add(d.n);
                    else set.delete(d.n);
                    void saveCfg({ working_hours: set.size ? { days: [...set], start: base.start, end: base.end } : {} });
                  }}
                />
                {d.label}
              </label>
            );
          })}
        </div>
        {hours && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm" style={{ color: "var(--text-2)" }}>
            از
            <input type="time" className="u-input" style={{ width: 130 }} value={hours.start} disabled={!canEdit}
              onChange={(e) => void saveCfg({ working_hours: { ...hours, start: e.target.value } })} aria-label="ساعت شروع" />
            تا
            <input type="time" className="u-input" style={{ width: 130 }} value={hours.end} disabled={!canEdit}
              onChange={(e) => void saveCfg({ working_hours: { ...hours, end: e.target.value } })} aria-label="ساعت پایان" />
          </div>
        )}
        {!hours && canEdit && (
          <div className="mt-3">
            <Button size="sm" variant="secondary" onClick={() => void saveCfg({ working_hours: cfg.default_working_hours })}>
              شنبه تا چهارشنبه، ۹ تا ۱۸
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
