import { useEffect, useMemo, useState } from "react";

import { errorMessage } from "../../../api/client";
import { Alert, Button, Card, SectionTitle, Spinner, TextArea, fa } from "../../../components/ui";
import type { Asset, Edit, OfflineChoice, Operation, Overview, SmartDecision, Tool } from "./api";
import { NEEDS_CHOICE, photoApi } from "./api";
import OfflineChoiceDialog from "./OfflineChoiceDialog";
import ResultCard from "./ResultCard";
import StepList from "./StepList";

type Common = {
  storeId: string;
  data: Overview;
  tools: Record<string, Tool>;
  selected: number[];
  nodeOn: boolean;
  busy: boolean;
  /** ساختِ نسخه برای عکس‌های انتخاب‌شده؛ ops = null یعنی سرور برای هر عکس خودش می‌چیند. ⇐ جملهٔ خطا یا null */
  run: (recipe: string, ops: Operation[] | null, assetIds?: number[], extra?: OfflineChoice) => Promise<string | null>;
  latest: (assetId: number) => Edit | null;
  asset: Asset | null;
  /** باز کردنِ مراحلِ یک نسخه در حالتِ دستی */
  openManual?: (steps: Operation[]) => void;
};

/** یک دستور آماده (بی نیاز به متن) را مستقیم بساز؛ دستوری که متن می‌خواهد (بنر، ویرایش با دستور) اول فرمش را می‌خواهد. */
function needsInput(ops: Operation[]): boolean {
  return ops.some(
    (o) => o.on !== false && ((o.tool === "kit_smart" && !o.params.goal) || (o.tool === "text" && !o.params.text && !o.params.subtext)),
  );
}

// ═══════════════════════════════════════════════════════════════════ خودکار

export function PhotoAutoPanel(p: Common) {
  const [reviewFirst, setReviewFirst] = useState<boolean>(() => {
    try {
      return localStorage.getItem("nm.photo.review") === "1";
    } catch {
      return false;
    }
  });
  const [review, setReview] = useState<{ recipe: string; title: string; ops: Operation[]; reasons: string[] } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recipes = useMemo(() => p.data.recipes.filter((r) => r.mode === "auto" && r.key !== "suggest"), [p.data.recipes]);
  const noSel = p.selected.length === 0;

  useEffect(() => {
    setReview(null);
  }, [p.selected.join(",")]);

  function remember(v: boolean) {
    setReviewFirst(v);
    try {
      localStorage.setItem("nm.photo.review", v ? "1" : "0");
    } catch {
      /* ignore */
    }
  }

  async function go(recipe: string, title: string) {
    if (noSel) return;
    setError(null);
    setLoading(recipe);
    try {
      const plan = await photoApi.plan(p.storeId, p.selected[0], recipe);
      const first = p.selected.length > 1 && recipe === "suggest";
      if (reviewFirst || needsInput(plan.operations)) {
        setReview({ recipe, title, ops: plan.operations, reasons: plan.findings.map((f) => f.note) });
      } else {
        setReview(null);
        const err = await p.run(recipe, first ? null : plan.operations);
        if (err) setError(err);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(null);
    }
  }

  async function applyReview() {
    if (!review) return;
    setError(null);
    const err = await p.run(review.recipe, review.ops);
    if (err) setError(err);
    else setReview(null);
  }

  const last = p.asset ? p.latest(p.asset.id) : null;

  return (
    <Card className="mt-2">
      <div data-testid="auto-panel">
        <SectionTitle>ویرایشِ خودکار</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          عکس را اندازه می‌گیرد (نور، رنگ‌زدگی، تیزی، نویز، اندازه، زمینه) و خودش فقط کارِ لازم را انجام می‌دهد؛ بعد قبل و بعد و دلیلِ هر کار را
          می‌بینید و هر مرحله را می‌توانید خاموش کنید و دوباره بسازید.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void go("suggest", "پیشنهادِ خودکار")} disabled={noSel || p.busy || !!loading} data-testid="auto-run">
            {loading === "suggest" ? <Spinner size={16} /> : "✨ ویرایشِ خودکار"}
            {!noSel && ` — ${fa(p.selected.length)} عکس`}
          </Button>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={reviewFirst} onChange={(e) => remember(e.target.checked)} data-testid="review-first" />
            اول نشانم بده، من تأیید کنم
          </label>
        </div>
        {noSel && <p className="mt-2 text-sm" style={{ color: "var(--warn)" }}>اول از کتابخانه یک یا چند عکس انتخاب کنید.</p>}

        <div className="mt-4">
          <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>حالت‌های آماده — یک کلیک</div>
          <div className="flex flex-wrap gap-2" data-testid="auto-presets">
            {recipes.map((r) => (
              <Button
                key={r.key} size="sm" variant="secondary" title={r.help} disabled={noSel || p.busy || !!loading}
                onClick={() => void go(r.key, r.title)} data-recipe={r.key}
              >
                {loading === r.key ? <Spinner size={14} /> : r.title}
                {r.needs_node && !p.nodeOn ? " (منتظرِ سرورِ پردازش)" : ""}
              </Button>
            ))}
          </div>
        </div>

        {error && <div className="mt-3"><Alert tone="bad">{error}</Alert></div>}

        {review && (
          <div className="mt-4" data-testid="review-panel">
            <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>
              «{review.title}» این کارها را انجام می‌دهد — هر کدام را نمی‌خواهید بردارید
            </div>
            {review.reasons.length > 0 && (
              <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>آنچه در عکس دیدیم: {review.reasons.join(" · ")}</p>
            )}
            <StepList steps={review.ops} onChange={(ops) => setReview({ ...review, ops })} tools={p.tools} kit={p.data.kit} nodeOn={p.nodeOn} spotImage={p.selected.length === 1 ? p.asset?.preview ?? null : null} />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => void applyReview()} disabled={p.busy || review.ops.filter((o) => o.on !== false).length === 0} data-testid="review-apply">
                اعمال روی {fa(p.selected.length)} عکس
              </Button>
              <Button variant="ghost" onClick={() => setReview(null)}>بی‌خیال</Button>
            </div>
          </div>
        )}

        {p.asset && last && p.selected.length === 1 && (
          <ResultCard
            key={last.id} asset={p.asset} edit={last} tools={p.tools} kit={p.data.kit} nodeOn={p.nodeOn} busy={p.busy}
            onRerender={(steps, recipe) => void p.run(recipe, steps).then((e) => e && setError(e))} onOpenManual={p.openManual}
          />
        )}
      </div>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════ نیمه‌خودکار

const EXAMPLES = [
  "گرم و روشن، مناسبِ اینستاگرامِ کافه",
  "حرفه‌ای و تمیز برای عکسِ محصول، رنگ‌ها طبیعی",
  "سینمایی، کمی تیره و خنک",
  "رنگ‌ها زنده‌تر و جزئیات واضح‌تر",
  "نرم و ملایم مثلِ عکسِ پرتره",
  "پس‌زمینهٔ سفیدِ تمیز و کالا وسط",
];

/** «این دستور کجا انجام می‌شود» — راست و درست، از تصمیمِ سرور (smart.decide_path) یا، تا آن نیامده، از وضعِ سرورِ پردازش. */
function SmartRoute({ decision, nodeOn }: { decision: SmartDecision | null; nodeOn: boolean }) {
  if (decision?.path === "node") {
    return (
      <Alert tone="ok" title="روی سرورِ پردازش">
        «اول لوکال» است و سرورِ پردازش آنلاین است؛ مدلِ بینا (روی کامپیوترِ خودتان) همین حالا جواب می‌دهد و هیچ اعتبارِ بیرونی خرج نمی‌شود.
      </Alert>
    );
  }
  if (decision?.path === "site") {
    const first = decision.first === "metis" ? "متیس" : "لوکال";
    const second = decision.first === "metis" ? "لوکال" : "متیس";
    return (
      <Alert tone="info" title="بی سرورِ پردازش هم کار می‌کند">
        هوشِ مصنوعیِ بینا از سرورِ سایت صدا زده می‌شود: ترتیبِ «تنظیماتِ هوش مصنوعی» اول {first} است و اگر جواب نداد {second}. لغزنده‌ها روی سرورِ
        سایت اعمال می‌شود. اگر هیچ‌کدام جواب ندادند فقط نور و رنگِ خودکارِ سبک اعمال می‌شود و همین را بالای نتیجه می‌نویسیم.
      </Alert>
    );
  }
  return nodeOn ? (
    <Alert tone="ok" title="سرورِ پردازش آنلاین است">
      اگر ترتیبِ هوش مصنوعی «اول لوکال» باشد، مدلِ بینا روی سرورِ پردازش جواب می‌دهد؛ اگر «اول متیس» باشد از سرورِ سایت اول متیس صدا زده می‌شود و لوکال
      پشتیبان است. بالای هر نتیجه نوشته می‌شود چه کسی جواب داد.
    </Alert>
  ) : (
    <Alert tone="info" title="بی سرورِ پردازش هم کار می‌کند">
      هوشِ مصنوعیِ بینا از سرورِ سایت صدا زده می‌شود، به ترتیبِ «تنظیماتِ هوش مصنوعی» (اول لوکال یا اول متیس؛ اگر اولی جواب نداد دومی). اگر هیچ‌کدام جواب
      ندادند فقط نور و رنگِ خودکارِ سبک اعمال می‌شود.
    </Alert>
  );
}

export function PhotoPromptPanel(p: Common) {
  const [goal, setGoal] = useState("");
  const [follow, setFollow] = useState("");
  const [error, setError] = useState<string | null>(null);
  const noSel = p.selected.length === 0;
  const last = p.asset ? p.latest(p.asset.id) : null;
  // روی سرورِ سایت، kit_smart به develop بازنویسی می‌شود؛ نسخهٔ هوشمند را از ثبتِ stats.smart هم می‌شناسیم
  const lastSmart = last && (last.smart || last.operations.some((o) => o.tool === "kit_smart")) ? last : null;
  const [decision, setDecision] = useState<SmartDecision | null>(null);
  const firstSelected = p.selected[0];
  useEffect(() => {
    // مسیرِ این دستور (سرورِ پردازش یا هوشِ مصنوعیِ سایت) را از سرور بپرس تا متنِ زیرِ دکمه راست باشد
    let alive = true;
    setDecision(null);
    if (firstSelected) {
      photoApi
        .plan(p.storeId, firstSelected, "smart")
        .then((pl) => alive && setDecision(pl.smart ?? null))
        .catch(() => alive && setDecision(null));
    }
    return () => {
      alive = false;
    };
  }, [p.storeId, firstSelected, p.nodeOn]);

  // سرورِ پردازش خاموش و انتخابی ذخیره نشده ⇒ سرور 409 می‌دهد و این پنجره از کاربر می‌پرسد (هر دو راه ممکن است)
  const [askOps, setAskOps] = useState<{ ops: Operation[]; refine: boolean } | null>(null);
  async function send(ops: Operation[], refine: boolean, extra?: OfflineChoice) {
    const err = await p.run("smart", ops, undefined, extra);
    if (err === NEEDS_CHOICE) {
      setAskOps({ ops, refine });
      return;
    }
    if (err) setError(err);
    else if (refine) setFollow("");
  }

  async function ask() {
    setError(null);
    await send([
      { tool: "kit_smart", params: { goal: goal.trim() }, on: true, reason: "دستورِ شما" },
      { tool: "export", params: { format: "jpeg", quality: 92 }, on: true },
    ], false);
  }

  async function refine() {
    if (!lastSmart || !follow.trim()) return;
    setError(null);
    // کارهای انتخاب‌شدهٔ قبلی + هدفِ تازه ⇐ کیت از نسخهٔ فعلی ادامه می‌دهد و فقط «تغییر» می‌دهد.
    // نسخهٔ سایت: لغزنده‌های فعلی (develop و ابزارهای سبک) همراه می‌روند؛ هوش مصنوعی آن‌ها را در پرسش می‌بیند و اصلاح می‌کند
    const prior: Operation[] =
      lastSmart.smart?.path === "site"
        ? lastSmart.operations.filter((o) => o.tool !== "export").map((o) => ({ tool: o.tool, params: o.params, on: true }))
        : (lastSmart.chosen ?? []).map((c) => ({ ...c, on: true }));
    const ops: Operation[] = [
      ...prior,
      { tool: "kit_smart", params: { goal: follow.trim() }, on: true, reason: "اصلاحِ شما" },
      { tool: "export", params: { format: "jpeg", quality: 92 }, on: true },
    ];
    await send(ops, true);
  }

  return (
    <Card className="mt-2">
      {askOps && (
        <OfflineChoiceDialog
          onCancel={() => setAskOps(null)}
          onChoose={(choice, remember) => {
            const pending = askOps;
            setAskOps(null);
            void send(pending.ops, pending.refine, { smart_offline: choice, remember });
          }}
        />
      )}
      <div data-testid="prompt-panel">
        <SectionTitle>ویرایش با دستور (نیمه‌خودکار)</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          بنویسید چه می‌خواهید. هوشِ مصنوعیِ بینا عکس را می‌بیند و لغزنده‌های ظهورِ عکس (نور، رنگ، منحنی…) را تنظیم می‌کند؛ بعدش همهٔ انتخاب‌هایش را به‌صورتِ مرحله‌های قابل‌ویرایش می‌بینید و بالای نتیجه نوشته می‌شود چه کسی جواب داد (متیس، لوکال یا بدون هوش مصنوعی).
        </p>
        <TextArea
          rows={3} value={goal} maxLength={300} onChange={(e) => setGoal(e.target.value)} data-testid="goal"
          placeholder="مثلاً: گرم و روشن، مناسبِ اینستاگرامِ کافه"
        />
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" className="example-chip" onClick={() => setGoal(x)}>{x}</button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={() => void ask()} disabled={noSel || p.busy || !goal.trim()} data-testid="prompt-run">
            ویرایش کن{!noSel && ` — ${fa(p.selected.length)} عکس`}
          </Button>
          {noSel && <span className="text-sm" style={{ color: "var(--warn)" }}>اول از کتابخانه عکس انتخاب کنید.</span>}
        </div>
        <div className="mt-3" data-testid="smart-route">
          <SmartRoute decision={decision} nodeOn={p.nodeOn} />
        </div>
        {error && <div className="mt-3"><Alert tone="bad">{error}</Alert></div>}

        {p.asset && lastSmart && p.selected.length === 1 && (
          <ResultCard
            key={lastSmart.id} asset={p.asset} edit={lastSmart} tools={p.tools} kit={p.data.kit} nodeOn={p.nodeOn} busy={p.busy} aiNotes
            onRerender={(steps, recipe) => void p.run(recipe === "smart" ? "manual" : recipe, steps).then((e) => e && setError(e))} onOpenManual={p.openManual}
          >
            {lastSmart.state === "READY" && (
              <div className="mt-4" data-testid="follow-up">
                <div className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>هنوز نشد؟ دستورِ بعدی را بنویسید</div>
                <div className="flex flex-wrap gap-2">
                  <input
                    className="u-input min-w-[14rem] flex-1" value={follow} maxLength={300} onChange={(e) => setFollow(e.target.value)}
                    placeholder="مثلاً: گرم‌ترش کن" data-testid="follow-input"
                    onKeyDown={(e) => e.key === "Enter" && void refine()}
                  />
                  <Button onClick={() => void refine()} disabled={p.busy || !follow.trim()} data-testid="follow-run">اصلاح کن</Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {["گرم‌ترش کن", "روشن‌تر", "کنتراستِ کمتر", "رنگ‌ها زنده‌تر", "تیره‌تر و سینمایی‌تر"].map((x) => (
                    <button key={x} type="button" className="example-chip" onClick={() => setFollow(x)}>{x}</button>
                  ))}
                </div>
              </div>
            )}
          </ResultCard>
        )}
      </div>
    </Card>
  );
}
