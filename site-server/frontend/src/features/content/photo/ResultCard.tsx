import { useEffect, useState } from "react";

import { Alert, Badge, Button, Spinner, fa } from "../../../components/ui";
import type { Asset, Edit, Kit, Operation, Tool } from "./api";
import CompareSlider from "./CompareSlider";
import StepList from "./StepList";

/** کارهای یک نسخه برای ویرایش‌شدن: «بهبودِ خودکار» و «ویرایشِ هوشمند» به همان گام‌هایی باز می‌شوند که کیت واقعاً به کار برد. */
export function stepsOf(edit: Edit): Operation[] {
  const out: Operation[] = [];
  const chosen = edit.chosen ?? [];
  for (const o of edit.operations) {
    if ((o.tool === "kit_auto" || o.tool === "kit_smart") && chosen.length) {
      if (!out.some((s) => s.group)) out.push(...chosen.map((c) => ({ ...c, on: true })));
      continue;
    }
    out.push({ tool: o.tool, params: o.params, on: true, title: o.title, where: o.where, reason: o.reason });
  }
  return out;
}

/** نتیجهٔ آخرِ یک عکس: قبل/بعد، «آنچه انجام شد» با دلیل، و ساختنِ دوباره با مراحلِ خاموش/روشن‌شده. */
export default function ResultCard({
  asset,
  edit,
  tools,
  kit,
  nodeOn,
  busy,
  onRerender,
  onOpenManual,
  aiNotes = false,
  children,
}: {
  asset: Asset;
  edit: Edit;
  tools: Record<string, Tool>;
  kit: Kit;
  nodeOn: boolean;
  busy: boolean;
  onRerender: (steps: Operation[], recipe: string) => void;
  /** ادامه در حالتِ دستی: همین مراحل به‌صورتِ لغزنده و لایه باز می‌شوند */
  onOpenManual?: (steps: Operation[]) => void;
  aiNotes?: boolean;
  children?: React.ReactNode;
}) {
  const [steps, setSteps] = useState<Operation[]>(() => stepsOf(edit));
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setSteps(stepsOf(edit));
    setDirty(false);
  }, [edit.id, edit.state, (edit.chosen ?? []).length]);

  const notes = edit.kit?.notes;
  const noteText = Array.isArray(notes) ? notes.join(" ") : notes;
  const goal = edit.operations.find((o) => o.tool === "kit_smart")?.params.goal as string | undefined;

  return (
    <div className="mt-4" data-testid="result-card" data-edit={edit.id}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>نسخهٔ {fa(edit.number)} — {edit.recipe_title}</span>
        <Badge tone={edit.state === "READY" ? "ok" : edit.state === "FAILED" ? "bad" : "info"}>{edit.state_label}</Badge>
        {edit.size && <Badge tone="neutral">{fa(edit.size[0])}×{fa(edit.size[1])}</Badge>}
        {edit.node && <Badge tone="neutral">روی {edit.node}</Badge>}
      </div>
      {goal && <p className="mb-2 text-sm" style={{ color: "var(--text-2)" }}>دستور: «{goal}»</p>}

      {edit.active && (
        <div className="flex items-center gap-2 text-sm" style={{ color: "var(--warn)" }}>
          <Spinner size={16} /> {edit.message}
        </div>
      )}
      {edit.state === "FAILED" && <Alert tone="bad">{edit.error}</Alert>}

      {edit.state === "READY" && edit.urls.preview && (
        <>
          <CompareSlider before={asset.preview} after={edit.urls.preview} beforeSize={[asset.width, asset.height]} afterSize={edit.size} />
          {aiNotes && (
            <div className="mt-3 ai-note" data-testid="ai-note">
              {edit.kit?.usedAi === true
                ? "هوش مصنوعیِ بینا عکس را دید و این مراحل را انتخاب کرد."
                : edit.kit?.usedAi === false
                  ? "مدلِ بینا روی سرورِ پردازش در دسترس نبود؛ همان بهبودِ خودکارِ کیت اعمال شد."
                  : null}
              {noteText ? <div>{noteText}</div> : null}
              {edit.kit?.error ? <div style={{ color: "var(--warn)" }}>{String(edit.kit.error)}</div> : null}
            </div>
          )}
          {edit.server_notes.length > 0 && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>{edit.server_notes.join(" · ")}</p>
          )}
          <div className="mt-4">
            <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>
              آنچه انجام شد — هر مرحله را خاموش یا اصلاح کنید و دوباره بسازید
            </div>
            <StepList
              steps={steps} onChange={(s) => { setSteps(s); setDirty(true); }} tools={tools} kit={kit} nodeOn={nodeOn}
              testId="result-steps"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                onClick={() => onRerender(steps, edit.recipe || "manual")}
                disabled={busy || steps.filter((s) => s.on !== false).length === 0}
                data-testid="rerender"
              >
                {dirty ? "ساختنِ دوباره با این تغییرها" : "ساختنِ دوباره"}
              </Button>
              {edit.urls.result && <a href={edit.urls.result} download><Button variant="secondary">دانلود</Button></a>}
              {onOpenManual && (
                <Button variant="ghost" onClick={() => onOpenManual(steps.filter((s) => s.on !== false))} data-testid="open-manual">
                  ادامه در حالتِ دستی (لایه‌ها و لغزنده‌ها)
                </Button>
              )}
            </div>
            {!nodeOn && steps.some((s) => s.on !== false && (s.where ?? tools[s.tool]?.where) === "node") && (
              <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                چند مرحله به سرورِ پردازش نیاز دارد و الان خاموش است؛ نسخه در صف می‌ماند. برای نتیجهٔ همین حالا تیکِ آن‌ها را بردارید.
              </p>
            )}
          </div>
        </>
      )}
      {children}
    </div>
  );
}
