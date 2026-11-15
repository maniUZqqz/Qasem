import { useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, SectionTitle, Select, Spinner, fa } from "../../../components/ui";
import { AudioCfg, Critique, CritiqueRound, Finding, HistoryRow, Library, PlanDTO, QaReport, SoundInfo, Spec } from "./api";

// ───────────────────────────────────────────── تاریخچه (برگشت / جلوتر)

const SRC_FA: Record<string, string> = { user: "ویرایش", ai: "هوش مصنوعی", chat: "چت", patch: "تغییر", qa: "کنترلِ کیفیت", critique: "نقدِ تصویری", audio: "صدا", import: "ورود", undo: "برگشت" };

export function HistoryBar({ plan, busy, onUndo, onRedo, onRestore }: { plan: PlanDTO | null; busy: boolean; onUndo: () => void; onRedo: () => void; onRestore: (n: number) => void }) {
  const [open, setOpen] = useState(false);
  const rows: HistoryRow[] = plan?.history ?? [];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" type="button" onClick={onUndo} disabled={busy || !plan?.can_undo} title="برگشت به نسخهٔ قبل">
          <Icon name="next" size={14} /> برگشت
        </Button>
        <Button variant="secondary" size="sm" type="button" onClick={onRedo} disabled={busy || !plan?.can_redo} title="جلوتر">
          <Icon name="back" size={14} /> جلوتر
        </Button>
        <button type="button" className="text-xs underline" style={{ color: "var(--text-3)" }} onClick={() => setOpen((v) => !v)} disabled={!rows.length}>
          {plan ? `نسخهٔ ${fa(plan.rev)} از ${fa(rows.length)}` : "هنوز نسخه‌ای نیست"}
        </button>
      </div>
      {open && rows.length ? (
        <div className="mt-2 max-h-56 space-y-1 overflow-auto rounded-lg p-2" style={{ background: "var(--surface-2)" }}>
          {[...rows].reverse().map((r) => (
            <button key={r.n} type="button" onClick={() => onRestore(r.n)} className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-start text-xs" style={{ background: r.current ? "var(--brand-soft, var(--surface))" : "transparent", color: "var(--text-2)" }}>
              <span className="w-6 shrink-0 font-bold">{fa(r.n)}</span>
              <Badge tone={r.source === "qa" || r.source === "critique" ? "info" : r.source === "chat" || r.source === "ai" ? "brand" : "neutral"}>{SRC_FA[r.source] || r.source}</Badge>
              <span className="min-w-0 flex-1 truncate">{r.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ───────────────────────────────────────────── چتِ ویرایش

const SUGGEST = ["تیتر بزرگ‌تر شود", "رنگِ صحنهٔ دوم گرم‌تر", "صحنهٔ سوم ۱٫۵ ثانیه طولانی‌تر", "زیرنویس اضافه کن", "گوینده اضافه کن", "دوربین نزدیک‌تر شود"];

export type ChatLine = { q: string; say: string; source: "ai" | "rules"; applied: boolean; message: string; changes?: string[] };

export function ChatEdit({ lines, busy, disabled, onSend }: { lines: ChatLine[]; busy: boolean; disabled: boolean; onSend: (t: string) => Promise<void> }) {
  const [text, setText] = useState("");
  const send = async (t: string) => {
    if (!t.trim() || busy) return;
    await onSend(t.trim());
    setText("");
  };
  return (
    <div>
      <div className="flex gap-2">
        <div className="min-w-0 flex-1">
          <Input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send(text)} placeholder="مثلاً: تیتر بزرگ‌تر شود" disabled={disabled} />
        </div>
        <Button type="button" onClick={() => send(text)} disabled={busy || disabled || !text.trim()}>
          <Icon name="send" size={15} /> {busy ? "…" : "اعمال"}
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {SUGGEST.map((s) => (
          <button key={s} type="button" className="rounded-full px-2 py-0.5 text-xs" style={{ background: "var(--surface-2)", color: "var(--text-2)" }} onClick={() => send(s)} disabled={busy || disabled}>
            {s}
          </button>
        ))}
      </div>
      {lines.length ? (
        <div className="mt-3 space-y-2">
          {lines.slice(-4).map((l, i) => (
            <div key={i} className="rounded-lg p-2 text-sm leading-7" style={{ background: "var(--surface-2)" }}>
              <div style={{ color: "var(--text-3)" }}>« {l.q} »</div>
              <div style={{ color: l.applied ? "var(--text)" : "var(--warn)" }}>
                {l.say} <Badge tone={l.source === "ai" ? "brand" : "neutral"}>{l.source === "ai" ? "هوش مصنوعی" : "قاعده‌های ساده"}</Badge>
              </div>
              {l.changes?.length ? <div className="text-xs" style={{ color: "var(--text-3)" }}>{l.changes.join("؛ ")}</div> : null}
              {l.message ? <div className="text-xs" style={{ color: "var(--text-3)" }}>{l.message}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ───────────────────────────────────────────── کنترلِ کیفیت + نقدِ تصویری

const SEV_TONE = { error: "bad", warn: "warn", info: "info" } as const;
const SEV_FA = { error: "خطا", warn: "هشدار", info: "پیشنهاد" } as const;

function Shots({ shots, title }: { shots: { scene: number; frame: number; image_url?: string }[]; title: string }) {
  const got = shots.filter((s) => s.image_url);
  if (!got.length) return null;
  return (
    <div>
      <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>
        {title}
      </div>
      <div className="flex flex-wrap gap-2">
        {got.map((s, i) => (
          <a key={i} href={s.image_url} target="_blank" rel="noreferrer" title={`صحنهٔ ${s.scene + 1}`}>
            <img src={s.image_url} alt={`صحنهٔ ${s.scene + 1}`} loading="lazy" className="rounded-md object-cover" style={{ height: 120, width: 68, border: "1px solid var(--line)" }} />
          </a>
        ))}
      </div>
    </div>
  );
}

function FindingRow({ f }: { f: Finding }) {
  return (
    <div className="flex items-start gap-2 text-xs leading-6">
      <Badge tone={SEV_TONE[f.severity]}>{SEV_FA[f.severity]}</Badge>
      <span style={{ color: "var(--text-2)" }}>
        {f.message}
        {f.why ? <span style={{ color: "var(--bad)" }}> — اصلاح نشد: {f.why}</span> : null}
      </span>
    </div>
  );
}

const PHASE_FRAC: Record<string, number> = { start: 0, lock: 0.02, measure: 0.1, frames: 0.25, fix: 0.8, final: 0.9 };

/** پیشرفتِ زندهٔ کنترلِ کیفیت: دورِ چندم، چه مرحله‌ای، چند فریم (فریمِ دورِ قبل دوباره رندر نمی‌شود) */
function QaProgressBar({ qa }: { qa: QaReport | undefined }) {
  const pr = qa?.progress;
  const total = Math.max(1, pr?.rounds ?? 3);
  const n = Math.max(1, pr?.n ?? 1);
  const pct = Math.min(97, Math.round((((n - 1) + (PHASE_FRAC[pr?.phase ?? "start"] ?? 0)) / total) * 100));
  const done = qa?.rounds?.length ?? 0;
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <Spinner size={16} /> {pr?.message || qa?.summary || "در حالِ کنترل…"}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }} aria-hidden="true">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--brand)", transition: "width .6s ease" }} />
      </div>
      <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        {done ? `${fa(done)} دور تمام شد؛ نتیجهٔ دورها همین پایین دیده می‌شود. ` : ""}
        فقط صحنه‌هایی که بعد از اصلاح عوض شده‌اند دوباره رندر می‌شوند، و دورِ تازه‌ای پس از حدودِ {fa(10)} دقیقه شروع نمی‌شود. می‌توانید از صفحه بروید؛ نتیجه روی طرح می‌ماند.
      </div>
    </div>
  );
}

export function QaPanel({ qa, critique, busy, hasPlan, onQa, onCritique }: { qa: QaReport | undefined; critique: Critique | undefined; busy: boolean; hasPlan: boolean; onQa: () => void; onCritique: () => void }) {
  const running = qa?.state === "running";
  const rounds = qa?.rounds ?? [];
  const c = critique ?? {};
  const crit = c.state === "waiting" || c.state === "running";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="secondary" onClick={onQa} disabled={busy || running || !hasPlan}>
          <Icon name="shield" size={15} /> {running ? "در حالِ کنترل…" : "کنترلِ کیفیت و اصلاحِ خودکار"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCritique} disabled={busy || crit || !hasPlan}>
          <Icon name="bulb" size={15} /> {crit ? "نقدِ تصویری در جریان…" : "نقدِ تصویری با مدلِ بینایی"}
        </Button>
      </div>
      <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        کنترلِ کیفیت بدونِ هوش مصنوعی و روی هر رندر خودکار اجرا می‌شود: بیرون‌زدگیِ متن، هم‌پوشانی، کنتراست، زمانِ خواندن (≈۰٫۳۲ ثانیه برای هر کلمه)، ناحیهٔ امنِ پلتفرم و اندازهٔ فونت را می‌سنجد و خودش درست می‌کند.
      </div>

      {running ? <QaProgressBar qa={qa} /> : null}

      {qa && qa.state !== "running" && qa.summary ? (
        <Alert tone={qa.remaining && qa.remaining.length ? "warn" : "ok"} title={qa.summary}>
          {qa.geometry_error || qa.geometry_skipped ? <div className="text-xs">بررسیِ هندسیِ فریم‌ها انجام نشد: {qa.geometry_error || qa.geometry_skipped}</div> : null}
        </Alert>
      ) : null}

      {rounds.length ? (
        <div className="space-y-3">
          <SectionTitle>دورهای کنترل</SectionTitle>
          {rounds.map((r) => {
            const bad = r.findings.filter((f) => f.severity !== "info");
            return (
              <Card key={r.n}>
                <div className="mb-2 flex items-center gap-2 text-sm font-bold" style={{ color: "var(--text)" }}>
                  دورِ {fa(r.n)} <Badge tone={bad.length ? "warn" : "ok"}>{bad.length ? `${fa(bad.length)} یافته` : "بدونِ مشکل"}</Badge>
                  {r.applied.length ? <Badge tone="info">{fa(r.applied.length)} اصلاحِ خودکار</Badge> : null}
                </div>
                <div className="space-y-1">{r.findings.map((f, i) => <FindingRow key={i} f={f} />)}</div>
                {r.applied.length ? (
                  <div className="mt-2 rounded-lg p-2 text-xs leading-6" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
                    <b>اصلاح‌های انجام‌شده:</b>
                    {r.applied.map((a, i) => (
                      <div key={i}>✓ {a.message}</div>
                    ))}
                  </div>
                ) : null}
                {r.shots?.length ? (
                  <div className="mt-3">
                    <Shots shots={r.shots} title="فریم‌هایی که سنجیده شد (ورودِ نشسته و پایانِ صحنه)" />
                  </div>
                ) : null}
              </Card>
            );
          })}
        </div>
      ) : null}

      {c.state ? (
        <div className="space-y-3">
          <SectionTitle>نقدِ تصویری (مدلِ بینا)</SectionTitle>
          {c.state === "waiting" || c.state === "running" ? (
            <Alert tone="info" title={c.state === "running" ? "در حالِ اجرا" : "منتظرِ مدلِ بینایی"}>
              {c.message}
            </Alert>
          ) : c.state === "done" ? (
            <Alert tone="ok" title="نقد تمام شد">
              {c.message}
            </Alert>
          ) : (
            <Alert tone="warn" title={c.state === "failed" ? "نقد ناموفق بود" : "نقدِ تصویری ممکن نیست"}>
              {c.message}
            </Alert>
          )}
          {(c.rounds ?? []).map((r: CritiqueRound) => (
            <Card key={r.n}>
              <div className="mb-2 flex items-center gap-2 text-sm font-bold" style={{ color: "var(--text)" }}>
                دورِ {fa(r.n)} <Badge tone={r.verdict === "ok" ? "ok" : "warn"}>{r.verdict === "ok" ? "تأیید" : "نیازمندِ اصلاح"}</Badge>
              </div>
              {r.issues.map((x, i) => (
                <div key={i} className="text-xs leading-6" style={{ color: "var(--text-2)" }}>
                  • صحنهٔ {fa(x.scene + 1)}: {x.problem}
                </div>
              ))}
              {r.rejected?.length ? <div className="text-xs" style={{ color: "var(--text-3)" }}>{fa(r.rejected.length)} پیشنهادِ نامعتبر رد شد.</div> : null}
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Shots shots={r.before} title="قبل" />
                <Shots shots={r.after} title="بعد از اصلاح" />
              </div>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ───────────────────────────────────────────── صدا، زیرنویس و پلتفرم

export function SoundPanel({ spec, lib, sound, onChange }: { spec: Spec; lib: Library; sound: SoundInfo | null; onChange: (patch: Partial<Spec>) => void }) {
  const audio: AudioCfg = spec.audio ?? {};
  const voice = audio.voice;
  const music = audio.music;
  const setAudio = (a: Partial<AudioCfg>) => {
    const next = { ...audio, ...a } as AudioCfg;
    if (!next.voice?.on) delete next.voice;
    if (!next.music?.on) delete next.music;
    onChange({ audio: Object.keys(next).length ? next : undefined });
  };
  const usable = (sound?.voices ?? []).filter((v) => v.available);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-3">
        <label className="flex items-center gap-2 text-sm font-semibold" style={{ color: "var(--text)" }}>
          <input type="checkbox" checked={!!voice?.on} onChange={(e) => setAudio({ voice: e.target.checked ? { on: true, voice_id: "auto", speed: 1 } : undefined })} />
          <Icon name="mic" size={15} /> گویندهٔ فارسی
        </label>
        {voice?.on ? (
          <>
            <Field label="صدا" hint={usable.length ? "«خودکار» سریع‌ترین صدای در دسترس را برمی‌دارد (Piper روی سایت، یا MOSS روی سرورِ پردازش)" : "هیچ صدای آماده‌ای دیده نشد؛ رندر منتظرِ سرورِ پردازش می‌ماند."}>
              <Select value={voice.voice_id} onChange={(e) => setAudio({ voice: { ...voice, voice_id: e.target.value } })}>
                <option value="auto">خودکار</option>
                {usable.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} {v.where === "node" ? "(سرورِ پردازش)" : "(سایت)"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={`سرعتِ گفتار (${fa((voice.speed ?? 1).toFixed(2))}×)`}>
              <input type="range" min={0.8} max={1.25} step={0.05} value={voice.speed ?? 1} onChange={(e) => setAudio({ voice: { ...voice, speed: Number(e.target.value) } })} className="w-full" />
            </Field>
            <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
              اگر برای صحنه «گفتار» ننوشته باشید، همان متنِ روی صحنه خوانده می‌شود. زمانِ هر کلمه از ASR ِ سرورِ پردازش (یا برآوردِ نسبتِ حروف) می‌آید و تیترِ کینتیک و زیرنویس با آن هم‌زمان می‌شوند.
            </div>
          </>
        ) : null}
      </div>
      <div className="space-y-3">
        <label className="flex items-center gap-2 text-sm font-semibold" style={{ color: "var(--text)" }}>
          <input type="checkbox" checked={!!music?.on} onChange={(e) => setAudio({ music: e.target.checked ? { on: true, ref: "auto", level_db: -22 } : undefined })} />
          <Icon name="music" size={15} /> موسیقیِ زمینه
        </label>
        {music?.on ? (
          <>
            <Field label="موسیقی" hint={sound?.hint}>
              <Select value={music.ref} onChange={(e) => setAudio({ music: { ...music, ref: e.target.value } })}>
                <option value="auto">خودکار (از کتابخانهٔ فروشگاه)</option>
                {(sound?.music ?? []).map((m) => (
                  <option key={m.ref} value={m.ref}>
                    {m.title} {m.bpm ? `· ${fa(Math.round(m.bpm))} bpm` : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={`بلندیِ موسیقی (${fa(music.level_db ?? -22)} dB نسبت به گوینده)`}>
              <input type="range" min={-30} max={-12} step={1} value={music.level_db ?? -22} onChange={(e) => setAudio({ music: { ...music, level_db: Number(e.target.value) } })} className="w-full" />
            </Field>
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={audio.beat_sync !== false} onChange={(e) => setAudio({ beat_sync: e.target.checked })} /> برشِ صحنه‌ها روی بیتِ موسیقی
            </label>
          </>
        ) : null}
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={!!audio.sfx} onChange={(e) => setAudio({ sfx: e.target.checked })} /> افکتِ «ووش» روی گذارها (ساختهٔ خودِ سامانه)
        </label>
      </div>
      <div className="grid gap-3 sm:col-span-2 sm:grid-cols-3">
        <Field label="پلتفرمِ انتشار" hint="متن‌ها از نوارهای رابطِ برنامه (نام، دکمه‌ها) دور می‌مانند">
          <Select value={spec.platform ?? ""} onChange={(e) => onChange({ platform: e.target.value || undefined })}>
            <option value="">بدونِ ناحیهٔ امن</option>
            {lib.platforms.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="زیرنویسِ کلمه‌به‌کلمه" hint="نیازمندِ گفتار">
          <Select value={spec.captions?.on ? spec.captions.position || "lower" : ""} onChange={(e) => onChange({ captions: e.target.value ? { on: true, position: e.target.value } : undefined })}>
            <option value="">خاموش</option>
            <option value="lower">پایین</option>
            <option value="center">وسط</option>
            <option value="upper">بالا</option>
          </Select>
        </Field>
        <div className="flex items-end text-xs leading-6" style={{ color: "var(--text-3)" }}>
          خروجی با صدا: بلندیِ استانداردِ شبکه‌ها (‎−۱۴ LUFS) و سقفِ قلهٔ ‎−۱٫۵ dB؛ موسیقی زیرِ گوینده خودکار کم می‌شود.
        </div>
      </div>
    </div>
  );
}

export function PlanJson({ spec, onApply }: { spec: Spec; onApply: (s: Spec) => Promise<string | null> }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const shown = text ?? JSON.stringify(spec, null, 2);
  const apply = async () => {
    try {
      const parsed = JSON.parse(shown);
      const msg = await onApply(parsed);
      setErr(msg);
      if (!msg) setText(null);
    } catch (e) {
      setErr("JSON معتبر نیست: " + String((e as Error).message));
    }
  };
  return (
    <div className="space-y-2">
      <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        طرحِ صحنه (نسخهٔ ۲) تنها منبعِ حقیقتِ ویدیوست؛ هر چیزی را که اینجا عوض کنید پیش از اعمال در سرور اعتبارسنجی می‌شود.
      </div>
      <textarea value={shown} onChange={(e) => setText(e.target.value)} spellCheck={false} dir="ltr" rows={14} className="u-input w-full" style={{ fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 12, lineHeight: 1.55, whiteSpace: "pre", overflow: "auto", textAlign: "left" }} />
      {err ? <Alert tone="bad">{err}</Alert> : null}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={apply} disabled={text === null}>
          <Icon name="check" size={14} /> اعمالِ JSON
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => { setText(null); setErr(null); }} disabled={text === null}>
          بازگشت به طرحِ فعلی
        </Button>
      </div>
    </div>
  );
}

export type { PlanDTO };
