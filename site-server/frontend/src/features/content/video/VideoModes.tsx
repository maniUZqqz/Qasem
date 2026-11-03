import { useEffect, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import BeforeAfter, { Measurements } from "../../../components/BeforeAfter";
import { Alert, Badge, Button, Spinner, TextArea, fa } from "../../../components/ui";
import type { ToolInfo } from "../ToolPicker";
import ToolPicker from "../ToolPicker";
import type { AiInfo, EditableOp, Plan } from "./api";
import { OpList } from "./ToolForm";
import type { Video } from "./types";

type Common = {
  storeId: string;
  video: Video;
  tools: ToolInfo[];
  busy: boolean;
  /** تدوین را شروع کن (کارِ پس‌زمینه). mode: AUTO | MANUAL | DIRECTED */
  start: (video: Video, mode: string, operations: EditableOp[] | null) => Promise<void>;
  /** نتیجهٔ کار را (ویدیوی تدوین‌شده) تازه کن */
  setError: (m: string | null) => void;
};

const toEditable = (ops: Plan["operations"]): EditableOp[] => ops.map((o) => ({ ...o, on: true }));

/** نتیجهٔ آخرِ تدوین: قبل/بعد، داوری، کارهایی که انجام شد (هرکدام خاموش‌شدنی) و ساختنِ دوباره از اصل. */
export function EditResult({ video, tools, busy, start }: Pick<Common, "video" | "tools" | "busy" | "start">) {
  const outcome = video.edit_outcome;
  const [ops, setOps] = useState<EditableOp[]>([]);
  const [dirty, setDirty] = useState(false);
  const key = `${video.id}-${video.edited_url ?? ""}-${outcome?.summary ?? ""}`;
  useEffect(() => {
    setOps(toEditable(outcome?.operations ?? []));
    setDirty(false);
  }, [key]);

  if (!outcome || !outcome.mode) return null;
  const kept = outcome.kept !== false && !!video.edited_url && !!video.video_url;
  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }} data-testid="edit-result">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>نتیجهٔ آخرین تدوین</span>
        {outcome.improved === true && kept && <Badge tone="ok">داوریِ دوم: بهتر شد</Badge>}
        {outcome.improved === false && <Badge tone="warn">داوریِ دوم: بهتر نشد</Badge>}
        {outcome.rounds ? <Badge tone="neutral">{fa(outcome.rounds)} دور</Badge> : null}
      </div>
      {outcome.note && <p className="mb-2 text-sm" style={{ color: outcome.kept === false ? "var(--warn)" : "var(--text-2)" }}>{outcome.note}</p>}
      {kept && (
        <BeforeAfter
          beforeUrl={video.video_url!} afterUrl={video.edited_url!}
          before={outcome.before ?? (video.facts as Measurements)} after={outcome.after}
          effects={outcome.effects ?? []} note={undefined} improved={outcome.improved ?? null} summary={outcome.summary}
        />
      )}
      {outcome.denoise && (
        <p className="mt-2 text-xs" style={{ color: "var(--text-2)" }}>
          🎧 حذف نویز با {outcome.denoise.engine}
          {typeof outcome.denoise.before?.snr_db === "number" && typeof outcome.denoise.after?.snr_db === "number" && (
            <> — فاصله‌ی صدا از نویز {fa(Math.round(outcome.denoise.before.snr_db))} ← {fa(Math.round(outcome.denoise.after.snr_db))} دسی‌بل</>
          )}
        </p>
      )}
      {(outcome.refusals ?? []).length > 0 && (
        <div className="mt-2"><Alert tone="warn" title="این‌ها انجام نشد">{(outcome.refusals ?? []).join(" · ")}</Alert></div>
      )}
      {ops.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
            کارهایی که انجام شد — هرکدام را خاموش یا اصلاح کنید و دوباره از اصلِ ویدیو بسازید
          </div>
          <OpList ops={ops} onChange={(o) => { setOps(o); setDirty(true); }} tools={tools} testId="result-ops" />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void start(video, "MANUAL", ops)} disabled={busy || ops.filter((o) => o.on).length === 0} data-testid="rebuild">
              {dirty ? "ساختنِ دوباره با این تغییرها" : "ساختنِ دوباره"}
            </Button>
            {video.edited_url && <a href={video.edited_url} target="_blank" rel="noreferrer"><Button variant="secondary">دانلودِ نسخهٔ تدوین‌شده</Button></a>}
          </div>
        </div>
      )}
    </div>
  );
}

/** The editor agent's own choice of strength (services/editing/agent.py `suggest`), from how noisy the recording measured. */
function denoiseAmount(video: Video): number {
  const snr = Number(video.facts.snr_db);
  if (!Number.isFinite(snr) || snr >= 15) return 12;
  return snr >= 8 ? 16 : 20;
}

/** میان‌برهای صدا (از ادیتورِ قبلی): حذفِ نویز و یکسان‌کردنِ بلندی، با همان راهنمای «فاصلهٔ صدا از نویز». */
function AudioQuick({ video, ops, setOps, tools }: { video: Video; ops: EditableOp[]; setOps: (o: EditableOp[]) => void; tools: ToolInfo[] }) {
  if (!video.has_audio) return null;
  const add = (tool: string, params: Record<string, number>) =>
    setOps([...ops, { tool, title: tools.find((t) => t.key === tool)?.title ?? tool, params, reason: "افزودهٔ شما", notes: [], on: true }]);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {!ops.some((o) => o.tool === "denoise_audio") && (
        <Button size="sm" variant="secondary" onClick={() => add("denoise_audio", { amount: denoiseAmount(video) })}>🎧 حذف نویز صدا</Button>
      )}
      {!ops.some((o) => o.tool === "normalize_audio") && (
        <Button size="sm" variant="secondary" onClick={() => add("normalize_audio", { target: -16 })}>🔊 یکسان‌کردن بلندی صدا</Button>
      )}
      {typeof video.facts.snr_db === "number" && (
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          صدای شما {fa(Math.round(video.facts.snr_db as number))} دسی‌بل از نویز پشتش بلندتر است
          {(video.facts.snr_db as number) >= 30 ? " — تمیز است." : "."}
        </span>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════ خودکار

export function VideoAutoBlock(p: Common) {
  const [reviewFirst, setReviewFirst] = useState<boolean>(() => {
    try { return localStorage.getItem("nm.video.review") === "1"; } catch { return false; }
  });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [ops, setOps] = useState<EditableOp[]>([]);
  const [loading, setLoading] = useState(false);

  const remember = (v: boolean) => {
    setReviewFirst(v);
    try { localStorage.setItem("nm.video.review", v ? "1" : "0"); } catch { /* ignore */ }
  };

  async function go() {
    p.setError(null);
    if (!reviewFirst) {
      await p.start(p.video, "AUTO", null);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post<Plan>(`/stores/${p.storeId}/videos/${p.video.id}/plan/`, { mode: "SUGGEST" });
      setPlan(data);
      setOps(toEditable(data.operations));
    } catch (err) {
      p.setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function apply() {
    const dropped = ops.filter((o) => !o.on);
    if (dropped.length) {
      // رد کردنِ یک پیشنهاد آموزنده‌ترین چیزی است که ادیتور می‌شنود؛ پیش از تدوین جدا ثبت می‌شود
      await api.post(`/stores/${p.storeId}/videos/${p.video.id}/reject/`, { tools: dropped.map((o) => ({ tool: o.tool, params: o.params })) }).catch(() => undefined);
    }
    await p.start(p.video, "MANUAL", ops.filter((o) => o.on));
    setPlan(null);
  }

  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }} data-testid="video-auto">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void go()} disabled={p.busy || loading || !p.video.facts || p.video.state === "FAILED"} data-testid="video-auto-run">
          {loading ? <Spinner size={16} /> : "✨ تدوینِ خودکار"}
        </Button>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={reviewFirst} onChange={(e) => remember(e.target.checked)} data-testid="video-review-first" />
          اول نشانم بده، من تأیید کنم
        </label>
      </div>
      <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
        می‌سنجد (سکوت، نور، رنگ‌زدگی، لرزش، نویز) ← تصمیم می‌گیرد ← اعمال می‌کند ← دوباره می‌سنجد و داوری می‌کند؛ اگر نتیجه بدتر شود نسخهٔ اصلی نگه داشته می‌شود.
      </p>

      {plan && (
        <div className="mt-3" data-testid="video-review">
          {ops.length === 0 ? (
            <Alert tone="ok">چیزی برای اصلاح پیدا نشد — این ویدیو همین‌طوری خوب است.</Alert>
          ) : (
            <>
              <p className="mb-2 text-sm" style={{ color: "var(--text-2)" }}>این کارها انجام می‌شود. هرکدام را نمی‌خواهید بردارید:</p>
              <OpList ops={ops} onChange={setOps} tools={p.tools} testId="review-ops" />
              <AudioQuick video={p.video} ops={ops} setOps={setOps} tools={p.tools} />
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => void apply()} disabled={p.busy || ops.filter((o) => o.on).length === 0} data-testid="video-review-apply">اعمال کن</Button>
                <Button variant="ghost" onClick={() => setPlan(null)}>بی‌خیال</Button>
              </div>
            </>
          )}
          {plan.refusals.length > 0 && <div className="mt-3"><Alert tone="warn" title="این‌ها انجام نمی‌شود">{plan.refusals.join(" · ")}</Alert></div>}
          <ToolPicker
            tools={p.tools} hasAudio={p.video.has_audio} busy={p.busy}
            onAdd={(o) => setOps((cur) => [...cur, { tool: o.tool, title: p.tools.find((t) => t.key === o.tool)?.title ?? o.tool, params: o.params, reason: "افزودهٔ شما", notes: [], on: true }])}
          />
        </div>
      )}
      <EditResult video={p.video} tools={p.tools} busy={p.busy} start={p.start} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════ نیمه‌خودکار

const EXAMPLES = [
  "مثل یک یوتیوبر حرفه‌ای، ساده و بدون افکت زیاد",
  "برای ریلز: سریع، سکوت‌ها حذف، صدا واضح",
  "تمیز و طبیعی؛ فقط صدا و نور را درست کن",
  "گرم‌تر و روشن‌تر برای محصول",
  "ساده و آرام، بدون زوم و گذار",
];

function AiBanner({ ai }: { ai: AiInfo }) {
  if (ai.ok) {
    return (
      <Alert tone={ai.via === "node" ? "ok" : "info"} title={ai.via === "node" ? "Qwen روی سرورِ پردازش جواب داد" : "سرویسِ هوش مصنوعی (پشتیبان) جواب داد"}>
        {ai.via === "node" ? "اعتبارِ بیرونی خرج نشد." : ai.fallback_reason ? `سرورِ پردازش در دسترس نبود: ${ai.fallback_reason}` : null}
        {ai.model ? ` (مدل: ${ai.model})` : ""}
      </Alert>
    );
  }
  return (
    <div data-testid="ai-error">
      <Alert tone="warn" title="هوشِ مصنوعی جواب نداد">
        <span data-testid="ai-error-text">{ai.error}</span>
        {ai.used_fallback_plan ? " — به‌جایش پیشنهادِ خودکارِ مبتنی بر اندازه‌گیری آمده است." : ""}
        {ai.kept_previous ? " — طرحِ قبلی همان‌طور ماند." : ""}
      </Alert>
    </div>
  );
}

export function VideoPromptBlock(p: Common) {
  const [instruction, setInstruction] = useState("");
  const [follow, setFollow] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [ops, setOps] = useState<EditableOp[]>([]);
  const [asking, setAsking] = useState(false);

  async function ask(text: string, previous?: EditableOp[]) {
    p.setError(null);
    setAsking(true);
    try {
      const body: Record<string, unknown> = { mode: "DIRECTED", instruction: text };
      if (previous && previous.length) body.previous = previous.filter((o) => o.on).map((o) => ({ tool: o.tool, params: o.params, reason: o.reason }));
      const { data } = await api.post<Plan>(`/stores/${p.storeId}/videos/${p.video.id}/plan/`, body);
      setPlan(data);
      setOps(toEditable(data.operations));
      setFollow("");
    } catch (err) {
      p.setError(errorMessage(err));
    } finally {
      setAsking(false);
    }
  }

  async function apply() {
    const dropped = ops.filter((o) => !o.on);
    if (dropped.length) {
      await api.post(`/stores/${p.storeId}/videos/${p.video.id}/reject/`, { tools: dropped.map((o) => ({ tool: o.tool, params: o.params })) }).catch(() => undefined);
    }
    await p.start(p.video, "MANUAL", ops.filter((o) => o.on));
    setPlan(null);
  }

  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }} data-testid="video-prompt">
      <p className="mb-2 text-sm" style={{ color: "var(--text-2)" }}>
        بنویسید چطور ادیت شود. اول از Qwen روی سرورِ پردازشِ خودتان می‌پرسیم و فقط اگر نبود از سرویسِ بیرونی؛ جواب به‌صورتِ مرحله‌های قابل‌ویرایش می‌آید.
      </p>
      <TextArea rows={2} value={instruction} maxLength={300} onChange={(e) => setInstruction(e.target.value)} data-testid="video-instruction"
        placeholder="مثلاً: مثل یک یوتیوبر حرفه‌ای، ساده و بدون افکت زیاد" />
      <div className="mt-2 flex flex-wrap gap-2">
        {EXAMPLES.map((x) => <button key={x} type="button" className="example-chip" onClick={() => setInstruction(x)}>{x}</button>)}
      </div>
      <div className="mt-3">
        <Button onClick={() => void ask(instruction)} disabled={p.busy || asking || !instruction.trim() || !p.video.facts} data-testid="video-ask">
          {asking ? <Spinner size={16} /> : "بپرس"}
        </Button>
      </div>

      {plan && (
        <div className="mt-4" data-testid="video-prompt-plan">
          {plan.ai && <div className="mb-3"><AiBanner ai={plan.ai} /></div>}
          {ops.length === 0 ? (
            <Alert tone="ok">چیزی برای اصلاح پیدا نشد — این ویدیو همین‌طوری خوب است.</Alert>
          ) : (
            <>
              <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
                این مراحل را انتخاب کرد — خاموش یا اصلاح کنید، بعد اعمال کنید
              </div>
              <OpList ops={ops} onChange={setOps} tools={p.tools} testId="prompt-ops" />
              <AudioQuick video={p.video} ops={ops} setOps={setOps} tools={p.tools} />
            </>
          )}
          {plan.refusals.length > 0 && <div className="mt-3"><Alert tone="warn" title="این‌ها انجام نمی‌شود">{plan.refusals.join(" · ")}</Alert></div>}
          <ToolPicker
            tools={p.tools} hasAudio={p.video.has_audio} busy={p.busy}
            onAdd={(o) => setOps((cur) => [...cur, { tool: o.tool, title: p.tools.find((t) => t.key === o.tool)?.title ?? o.tool, params: o.params, reason: "افزودهٔ شما", notes: [], on: true }])}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void apply()} disabled={p.busy || ops.filter((o) => o.on).length === 0} data-testid="video-prompt-apply">اعمال کن</Button>
            <Button variant="ghost" onClick={() => setPlan(null)}>بی‌خیال</Button>
          </div>
          <div className="mt-4" data-testid="video-follow-up">
            <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>هنوز نشد؟ دستورِ بعدی را بنویسید</div>
            <div className="flex flex-wrap gap-2">
              <input className="u-input min-w-[14rem] flex-1" value={follow} onChange={(e) => setFollow(e.target.value)} placeholder="مثلاً: گرم‌ترش کن" data-testid="video-follow-input"
                onKeyDown={(e) => e.key === "Enter" && follow.trim() && void ask(follow, ops)} />
              <Button onClick={() => void ask(follow, ops)} disabled={p.busy || asking || !follow.trim()} data-testid="video-follow-run">اصلاح کن</Button>
            </div>
          </div>
        </div>
      )}
      <EditResult video={p.video} tools={p.tools} busy={p.busy} start={p.start} />
    </div>
  );
}
