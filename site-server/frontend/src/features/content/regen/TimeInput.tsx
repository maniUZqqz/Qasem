import { useEffect, useState } from "react";

import { Input } from "../../../components/ui";
import { mmss, parseSeconds } from "./api";

/**
 * ثانیه با اعشار («۳۰٫۵»، «30.5» یا «1:05.25»). تا Enter یا بیرون رفتن از کادر چیزی عوض نمی‌شود (وسطِ تایپ
 * پرش نمی‌کند)؛ بعد به نزدیک‌ترین فریمِ واقعی می‌چسبد و همان را نشان می‌دهد.
 */
export default function TimeInput({
  seconds,
  onCommit,
  label,
  testid,
  note,
}: {
  seconds: number;
  onCommit: (seconds: number) => void;
  label: string;
  testid: string;
  note?: string;
}) {
  const shown = (Math.round(seconds * 1000) / 1000).toString();
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(shown);
    setBad(false);
  }, [shown]);

  const commit = () => {
    const v = parseSeconds(text);
    if (v === null || v < 0) {
      setBad(true);
      return;
    }
    setBad(false);
    onCommit(v);
  };

  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs" style={{ color: "var(--text-3)" }}>
        {label}
      </span>
      <Input
        value={text}
        dir="ltr"
        inputMode="decimal"
        data-testid={testid}
        className="text-center"
        style={{ width: 110, borderColor: bad ? "var(--bad)" : undefined }}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
          if (e.key === "Escape") setText(shown);
        }}
      />
      <span className="text-xs" dir="ltr" style={{ color: "var(--text-3)" }} data-testid={`${testid}-shown`}>
        {mmss(seconds)}
        {note ? ` · ${note}` : ""}
      </span>
    </label>
  );
}
