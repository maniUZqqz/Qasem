import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Alert, Button, Card, ErrorBox, Field, Input, SectionTitle, Select, Spinner } from "../../components/ui";
import { Canned, Settings, del, get, patch, post } from "./api";
import { faNum, toInt } from "./format";
import { useInbox } from "./InboxLayout";

const CONFIDENCE: { value: number; label: string; hint: string }[] = [
  { value: 0.0, label: "همیشه جواب بدهد", hint: "هر پاسخی که ربات ساخت فرستاده می‌شود (پیشنهاد نمی‌شود)." },
  { value: 0.55, label: "فقط وقتی «متوسط» یا بالاتر مطمئن است (پیشنهادی)", hint: "اگر ربات خودش «کم‌اطمینان» گفت، پاسخ نمی‌رود و گفتگو به تیم می‌رسد." },
  { value: 0.8, label: "فقط وقتی «زیاد» مطمئن است", hint: "محتاط‌ترین حالت؛ بیشتر گفتگوها به تیم می‌رسد." },
];

function WidgetLook({ cfg, save, canEdit }: { cfg: Settings; save: (c: Partial<Settings>) => Promise<void>; canEdit: boolean }) {
  const w = cfg.widget as Record<string, string | boolean>;
  const [draft, setDraft] = useState<Record<string, string | boolean>>(w);
  useEffect(() => setDraft(w), [cfg.widget]); // eslint-disable-line react-hooks/exhaustive-deps
  const color = String(draft.color || "#2563eb");
  const title = String(draft.title || "گفتگو با ما");
  const welcome = String(draft.welcome || "سلام! چطور می‌توانیم کمک کنیم؟");
  const side = draft.position === "right" ? "right" : "left";
  return (
    <Card>
      <SectionTitle>ظاهر ویجت چت سایت</SectionTitle>
      <div className="grid gap-4 md:grid-cols-2 *:min-w-0">
        <div className="grid gap-3 *:min-w-0">
          <Field label="عنوان">
            <Input value={String(draft.title ?? "")} placeholder="گفتگو با ما" disabled={!canEdit} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          </Field>
          <Field label="زیرعنوان (در ساعت کاری)">
            <Input value={String(draft.subtitle ?? "")} placeholder="معمولاً در چند دقیقه پاسخ می‌دهیم" disabled={!canEdit} onChange={(e) => setDraft({ ...draft, subtitle: e.target.value })} />
          </Field>
          <Field label="پیام خوش‌آمد">
            <Input value={String(draft.welcome ?? "")} placeholder="سلام! چطور می‌توانیم کمک کنیم؟" disabled={!canEdit} onChange={(e) => setDraft({ ...draft, welcome: e.target.value })} />
          </Field>
          <div className="flex flex-wrap items-center gap-4">
            <Field label="رنگ">
              <input type="color" value={color} disabled={!canEdit} onChange={(e) => setDraft({ ...draft, color: e.target.value })} aria-label="رنگ ویجت" style={{ width: 56, height: 36 }} />
            </Field>
            <Field label="جای دکمه">
              <Select value={side} disabled={!canEdit} onChange={(e) => setDraft({ ...draft, position: e.target.value })} style={{ width: 140 }}>
                <option value="left">پایین چپ</option>
                <option value="right">پایین راست</option>
              </Select>
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={Boolean(draft.auto_open)} disabled={!canEdit} onChange={(e) => setDraft({ ...draft, auto_open: e.target.checked })} />
            ویجت بعد از چند ثانیه خودش باز شود
          </label>
          {canEdit && <div><Button size="sm" onClick={() => void save({ widget: draft })}>ذخیرهٔ ظاهر</Button></div>}
        </div>
        <div className="ib-live" style={{ minHeight: 230, background: "var(--surface-2)", borderRadius: 14, border: "1px solid var(--line)" }} aria-label="پیش‌نمایش ویجت">
          <div style={{ position: "absolute", left: side === "left" ? 14 : "auto", right: side === "right" ? 14 : "auto", bottom: 14, width: "78%", maxWidth: 260, background: "#fff", color: "#1a1a1a", borderRadius: 14, boxShadow: "0 8px 24px rgba(0,0,0,.25)", overflow: "hidden" }}>
            <div style={{ background: color, color: "#fff", padding: "10px 12px", fontWeight: 800, fontSize: 13 }}>{title}</div>
            <div style={{ padding: 12, fontSize: 12, lineHeight: 1.9, background: "#f6f7f9" }}>{welcome}</div>
            <div style={{ padding: 8, borderTop: "1px solid #e3e6ea", fontSize: 12, color: "#8a94a8" }}>پیامتان را بنویسید…</div>
          </div>
        </div>
      </div>
    </Card>
  );
}

function CannedManager({ storeId, canWrite }: { storeId: string; canWrite: boolean }) {
  const [rows, setRows] = useState<Canned[] | null>(null);
  const [title, setTitle] = useState("");
  const [shortcut, setShortcut] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await get<{ replies: Canned[] }>(storeId, "canned/")).replies);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);
  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    try {
      await post(storeId, "canned/", { title, shortcut, text });
      setTitle("");
      setShortcut("");
      setText("");
      setError(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <Card>
      <SectionTitle>پاسخ‌های آماده</SectionTitle>
      <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
        در پنجرهٔ پاسخ «/» بزنید تا همین‌ها پیشنهاد شود. می‌توانید <code>{"{name}"}</code> هم بگذارید.
      </p>
      <ErrorBox message={error} />
      <div className="grid gap-2 *:min-w-0">
        {(rows ?? []).map((r) => (
          <div key={r.id} className="flex items-start justify-between gap-3 rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            <div style={{ minWidth: 0 }}>
              <b className="text-sm">{r.title}</b> {r.shortcut && <code dir="ltr">/{r.shortcut}</code>}
              <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>{r.text}</div>
              {r.use_count > 0 && <span className="text-[11px]" style={{ color: "var(--text-3)" }}>{faNum(r.use_count)} بار استفاده شد</span>}
            </div>
            {canWrite && (
              <Button size="sm" variant="ghost" onClick={async () => { await del(storeId, `canned/${r.id}/`); await load(); }}>حذف</Button>
            )}
          </div>
        ))}
        {rows && rows.length === 0 && <span className="text-sm" style={{ color: "var(--text-3)" }}>هنوز پاسخ آماده‌ای ندارید.</span>}
      </div>
      {canWrite && (
        <div className="mt-3 grid gap-2">
          <div className="grid gap-2 sm:grid-cols-2 *:min-w-0">
            <Input value={title} placeholder="عنوان (مثلاً ساعت کاری)" onChange={(e) => setTitle(e.target.value)} aria-label="عنوان پاسخ آماده" />
            <Input value={shortcut} dir="ltr" placeholder="میان‌بر (hours)" onChange={(e) => setShortcut(e.target.value)} aria-label="میان‌بر" />
          </div>
          <textarea className="u-input" rows={3} value={text} placeholder="متن پاسخ…" onChange={(e) => setText(e.target.value)} aria-label="متن پاسخ آماده" />
          <div><Button size="sm" disabled={!title.trim() || !text.trim()} onClick={() => void add()}>افزودن پاسخ آماده</Button></div>
        </div>
      )}
    </Card>
  );
}

export default function BotPage() {
  const { storeId, me } = useInbox();
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [keywords, setKeywords] = useState("");
  const canEdit = Boolean(me?.can_settings);

  useEffect(() => {
    get<Settings>(storeId, "settings/")
      .then((c) => {
        setCfg(c);
        setKeywords(c.bot_handoff_keywords.join("، "));
      })
      .catch((err) => setError(errorMessage(err)));
  }, [storeId]);

  const save = async (changes: Partial<Settings>) => {
    try {
      const res = await patch<Settings>(storeId, "settings/", changes);
      setCfg(res);
      setError(null);
      setNotice("ذخیره شد.");
      window.setTimeout(() => setNotice(null), 2500);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!cfg) return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  return (
    <div className="grid gap-6 *:min-w-0">
      <ErrorBox message={error} />
      {notice && <div className="text-sm" style={{ color: "var(--ok)" }}>{notice}</div>}

      <Card>
        <SectionTitle>ربات پاسخ‌گو (هوش مصنوعی)</SectionTitle>
        <p className="mb-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          همان «ایجنت فروش» فروشگاه است: از محصول‌ها، سیاست‌ها و لحن برند خودتان جواب می‌دهد و عدد و قیمت از خودش درنمی‌آورد.
          سیاست داده (فقط محلی یا بیرونی) از صفحهٔ <Link to={`/stores/${storeId}/data`} style={{ color: "var(--brand-strong)" }}>سیاست داده</Link> می‌آید و ربات به آن پایبند است؛
          قوانین و عبارت‌های ممنوع از <Link to={`/stores/${storeId}/agent`} style={{ color: "var(--brand-strong)" }}>ایجنت فروش</Link>. برای امتحان، از «چت آزمایشی» استفاده کنید —
          گفتگوهای آزمایشی در هیچ آماری نمی‌آیند.
        </p>
        <div className="grid gap-4 *:min-w-0">
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={cfg.bot_enabled} disabled={!canEdit} onChange={(e) => void save({ bot_enabled: e.target.checked })} />
            ربات به مشتری‌ها جواب بدهد (خاموش = همه‌چیز مستقیم به تیم برسد)
          </label>
          <Field label="چه وقت به آدم واگذار کند؟" hint={CONFIDENCE.find((c) => c.value === cfg.bot_min_confidence)?.hint ?? ""}>
            <Select value={String(cfg.bot_min_confidence)} disabled={!canEdit} onChange={(e) => void save({ bot_min_confidence: Number(e.target.value) })}>
              {CONFIDENCE.map((c) => (
                <option key={c.value} value={String(c.value)}>{c.label}</option>
              ))}
              {!CONFIDENCE.some((c) => c.value === cfg.bot_min_confidence) && <option value={String(cfg.bot_min_confidence)}>سفارشی ({faNum(cfg.bot_min_confidence)})</option>}
            </Select>
          </Field>
          <Field label="کلمه‌هایی که یعنی «آدم می‌خواهم»" hint={`با ویرگول جدا کنید. خالی = فهرست پیش‌فرض: ${cfg.bot_handoff_keywords_effective.slice(0, 6).join("، ")}…`}>
            <div className="flex gap-2">
              <Input value={keywords} disabled={!canEdit} onChange={(e) => setKeywords(e.target.value)} placeholder="اپراتور، پشتیبان، مربی" />
              <Button size="sm" variant="secondary" disabled={!canEdit} onClick={() => void save({ bot_handoff_keywords: keywords.split(/[،,\n]/).map((k) => k.trim()).filter(Boolean) })}>ذخیره</Button>
            </div>
          </Field>
          <Field label="پیام خوش‌آمد (چت سایت)" hint="اولین چیزی که بازدیدکننده در ویجت می‌بیند.">
            <textarea className="u-input" rows={2} defaultValue={cfg.greeting_message} disabled={!canEdit} onBlur={(e) => e.target.value !== cfg.greeting_message && void save({ greeting_message: e.target.value })} aria-label="پیام خوش‌آمد" />
          </Field>
        </div>
      </Card>

      <Card>
        <SectionTitle>خارج از ساعت کاری</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          ساعت کاری را در «تیم و SLA» تنظیم کنید. {cfg.working_hours.days?.length ? (cfg.open_now ? "الان باز هستید." : "الان بسته هستید.") : "هنوز ساعت کاری نگذاشته‌اید؛ همیشه باز حساب می‌شود."}
        </p>
        <div className="grid gap-3 *:min-w-0">
          <Field label="وقتی بسته‌ایم">
            <Select value={cfg.bot_offhours} disabled={!canEdit} onChange={(e) => void save({ bot_offhours: e.target.value as Settings["bot_offhours"] })}>
              <option value="BOT">ربات هم‌چنان جواب بدهد</option>
              <option value="MESSAGE">پیام «خارج از ساعت» بفرست و برای صبح در صف تیم بگذار</option>
              <option value="QUEUE">بدون پیام خودکار، فقط در صف تیم بگذار</option>
            </Select>
          </Field>
          {cfg.bot_offhours === "MESSAGE" && (
            <Field label="متن پیام خارج از ساعت" hint={`خالی = «${cfg.bot_offhours_default_message}»`}>
              <textarea className="u-input" rows={2} defaultValue={cfg.offhours_message} disabled={!canEdit} onBlur={(e) => e.target.value !== cfg.offhours_message && void save({ offhours_message: e.target.value })} aria-label="متن پیام خارج از ساعت" />
            </Field>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle>نظرسنجی رضایت</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          بعد از بستنِ گفتگویی که یک نفر از تیم در آن جواب داده، مشتری یک پیام می‌گیرد و با یک عدد از ۱ تا ۵ جواب می‌دهد (روی همهٔ کانال‌ها کار می‌کند). گفتگوهای آزمایشی نظرسنجی نمی‌گیرند.
        </p>
        <div className="grid gap-3 *:min-w-0">
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={cfg.survey_enabled} disabled={!canEdit} onChange={(e) => void save({ survey_enabled: e.target.checked })} />
            بعد از بستن گفتگو نظرسنجی بفرست
          </label>
          {cfg.survey_enabled && (
            <>
              <Field label="چند دقیقه بعد از بستن؟">
                <Input value={String(cfg.survey_delay_min)} inputMode="numeric" disabled={!canEdit} style={{ width: 120 }}
                  onChange={(e) => setCfg({ ...cfg, survey_delay_min: toInt(e.target.value, 10) })}
                  onBlur={() => void save({ survey_delay_min: cfg.survey_delay_min })} />
              </Field>
              <Field label="متن نظرسنجی" hint="خالی = متن پیش‌فرض.">
                <textarea className="u-input" rows={2} defaultValue={cfg.survey_text} disabled={!canEdit} onBlur={(e) => e.target.value !== cfg.survey_text && void save({ survey_text: e.target.value })} aria-label="متن نظرسنجی" />
              </Field>
            </>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle>یادآوری پرداخت</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          سفارشی که اطلاعات پرداختش داده شده ولی رسید نیامده، بعد از مدتی یک یادآوری مؤدبانه می‌گیرد. اگر در این فاصله پرداخت تأیید شود، یادآوری خودش لغو می‌شود.
        </p>
        <div className="grid gap-3 *:min-w-0">
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={cfg.payment_reminder_enabled} disabled={!canEdit} onChange={(e) => void save({ payment_reminder_enabled: e.target.checked })} />
            یادآوری پرداخت روشن باشد
          </label>
          {cfg.payment_reminder_enabled && (
            <>
              <div className="flex flex-wrap gap-4">
                <Field label="بعد از چند ساعت">
                  <Input value={String(cfg.payment_reminder_hours)} inputMode="numeric" disabled={!canEdit} style={{ width: 120 }}
                    onChange={(e) => setCfg({ ...cfg, payment_reminder_hours: toInt(e.target.value, 24) })}
                    onBlur={() => void save({ payment_reminder_hours: cfg.payment_reminder_hours })} />
                </Field>
                <Field label="حداکثر چند بار">
                  <Input value={String(cfg.payment_reminder_max)} inputMode="numeric" disabled={!canEdit} style={{ width: 120 }}
                    onChange={(e) => setCfg({ ...cfg, payment_reminder_max: toInt(e.target.value, 2) })}
                    onBlur={() => void save({ payment_reminder_max: cfg.payment_reminder_max })} />
                </Field>
              </div>
              <Field label="متن یادآوری" hint="خالی = متن پیش‌فرض.">
                <textarea className="u-input" rows={2} defaultValue={cfg.payment_reminder_text} disabled={!canEdit} onBlur={(e) => e.target.value !== cfg.payment_reminder_text && void save({ payment_reminder_text: e.target.value })} aria-label="متن یادآوری پرداخت" />
              </Field>
            </>
          )}
        </div>
      </Card>

      <Card>
        <SectionTitle>یکی‌کردنِ مشتری بین کانال‌ها</SectionTitle>
        <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" className="mt-1" checked={cfg.merge_by_username} disabled={!canEdit} onChange={(e) => void save({ merge_by_username: e.target.checked })} />
          <span>
            کسی که در دو کانال یک نام‌کاربریِ یکسان دارد یک نفر حساب شود
            <span className="block text-xs" style={{ color: "var(--text-3)" }}>
              شمارهٔ موبایلِ یکسان همیشه یک نفر حساب می‌شود. نام‌کاربری ضعیف‌تر است (دو نفر ممکن است در دو پیام‌رسان یک نام داشته باشند)؛ هر ادغام اشتباه را می‌شود در پنل مشتری «جدا کن» کرد.
            </span>
          </span>
        </label>
      </Card>

      <WidgetLook cfg={cfg} save={save} canEdit={canEdit} />
      <CannedManager storeId={storeId} canWrite={Boolean(me?.can_write)} />
      {!canEdit && <Alert tone="info">فقط مالک یا مدیر فروشگاه می‌تواند این تنظیم‌ها را عوض کند.</Alert>}
    </div>
  );
}
