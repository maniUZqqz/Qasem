import { useState } from "react";

import { Input } from "./ui";
import { cleanNumberInput, formatGrouped, rejectedMessage } from "./numberInput";

/**
 * کادرِ عدد برای قیمت و موجودی — با ارقام فارسی کار می‌کند.
 *
 * `<input type="number">` با «۳۰۰۰۰۰» کادر را خالی می‌گذاشت و کاربر نمی‌فهمید چرا.
 * این کادر متنی است با کیبوردِ عددیِ موبایل (`inputMode`)، هر رقمِ فارسی/عربی را
 * همان لحظه لاتین می‌کند، جداکننده‌ها را برمی‌دارد و زیرش مقدار را خوانا نشان
 * می‌دهد («= ۳۰۰٬۰۰۰ تومان»). چیزی که عدد نیست حذف می‌شود و *گفته می‌شود*.
 *
 * مقدارِ `value`/`onChange` همیشه رشته‌ی لاتین است (یا خالی)، همان چیزی که API
 * می‌پذیرد.
 */
export default function NumberField({
  value,
  onChange,
  unit = "تومان",
  decimals = false,
  placeholder,
  id,
  disabled,
  required,
  testId,
}: {
  value: string;
  onChange: (value: string) => void;
  /** «تومان»، «عدد» … زیرِ کادر کنارِ مقدارِ خوانا. */
  unit?: string;
  decimals?: boolean;
  placeholder?: string;
  id?: string;
  disabled?: boolean;
  required?: boolean;
  testId?: string;
}) {
  const [note, setNote] = useState<string | null>(null);
  const pretty = formatGrouped(value);

  return (
    <span className="block">
      <Input
        id={id}
        type="text"
        inputMode={decimals ? "decimal" : "numeric"}
        autoComplete="off"
        dir="ltr"
        style={{ textAlign: "right" }}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        data-testid={testId}
        aria-invalid={note ? true : undefined}
        onChange={(e) => {
          const cleaned = cleanNumberInput(e.target.value, { decimals });
          setNote(cleaned.rejected || cleaned.negative ? rejectedMessage(cleaned, decimals) : null);
          onChange(cleaned.value);
        }}
        onBlur={() => setNote(null)}
      />
      <span
        className="mt-1 block text-xs"
        aria-live="polite"
        data-testid={testId ? `${testId}-preview` : undefined}
        style={{ color: note ? "var(--bad)" : "var(--text-3)", minHeight: "1.1em" }}
      >
        {note ?? (pretty ? `= ${pretty}${unit ? ` ${unit}` : ""}` : "")}
      </span>
    </span>
  );
}
