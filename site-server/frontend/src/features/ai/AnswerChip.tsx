import { Badge } from "../../components/ui";

/** «جواب از: لوکال (qwq:32b)» / «متیس (پشتیبان)» — کدام مسیرِ هوش مصنوعی این نتیجه را ساخت (apps.ai.AIRequest.answer_info). */
export type AiAnswer = {
  via: string;
  model: string;
  fell_back: boolean;
  fallback_reason: string;
  label: string;
};

export default function AnswerChip({ answer }: { answer?: AiAnswer | null }) {
  if (!answer || !answer.label) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" data-testid="ai-answer" title={answer.fell_back ? answer.fallback_reason : undefined}>
      <span style={{ color: "var(--text-3)" }}>جواب از:</span>
      <Badge tone={answer.fell_back ? "warn" : "info"}>
        <span dir="ltr">{answer.label}</span>
      </Badge>
    </span>
  );
}
