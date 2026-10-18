import { useEffect, useRef, useState } from "react";
import axios from "axios";

import Icon from "./Icon";
import { Field, Input } from "./ui";

/**
 * «کد معرفی یا تخفیف دارید؟»
 *
 * کد را همان‌جا که تایپ می‌شود اعتبارسنجی می‌کند، با
 * `POST /api/v1/codes/check/` — اندپوینتی که از قبل ساخته شده بود و هیچ
 * فرمی صدایش نمی‌زد.
 *
 * چند تصمیم که از خود بک‌اند می‌آید و اینجا شکسته نمی‌شود:
 *
 * **کد نامعتبر، ثبت‌نام را متوقف نمی‌کند.** پیام نشان داده می‌شود و فرم
 * کار خودش را می‌کند. کسی که کدش منقضی شده، باید بتواند حساب بسازد.
 *
 * **جواب سرور هرگز نمی‌گوید کد مال کیست.** فرم ثبت‌نام جای فهمیدن این
 * نیست که مشتری‌های ما چه کسانی‌اند — پس اینجا هم فقط همان پیام سرور
 * نمایش داده می‌شود، نه چیزی بیشتر.
 *
 * `axios` خام و نه `api`: این فرم قبل از وجود حساب پر می‌شود، پس
 * رهگیرِ ۴۰۱ که به `/login` می‌فرستد اینجا مزاحم است.
 */

type Check = { valid: boolean; message: string; kind?: string; discount_percent?: number };

export default function CodeField({
  value,
  onChange,
  label = "کد معرفی یا تخفیف (اختیاری)",
}: {
  value: string;
  onChange: (code: string) => void;
  label?: string;
}) {
  const [check, setCheck] = useState<Check | null>(null);
  const [checking, setChecking] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const code = value.trim();
    if (timer.current) window.clearTimeout(timer.current);
    if (code.length < 2) {
      setCheck(null);
      return;
    }
    // نیم ثانیه مکث: یک درخواست به‌ازای هر حرفِ تایپ‌شده، هم سرور را
    // می‌زند هم محدودکننده‌ی نرخِ خود این اندپوینت را فعال می‌کند.
    timer.current = window.setTimeout(() => {
      setChecking(true);
      axios
        .post<Check>("/api/v1/codes/check/", { code })
        .then((r) => setCheck(r.data))
        .catch(() => setCheck(null)) // شبکه قطع بود؛ کد شاید درست باشد
        .finally(() => setChecking(false));
    }, 500);

    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [value]);

  return (
    <Field label={label}>
      <div className="relative">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          placeholder="مثلاً ALI-4821"
          dir="ltr"
          maxLength={40}
          autoComplete="off"
          aria-describedby="code-check"
        />
        {checking && (
          <span
            className="absolute inset-y-0 flex items-center"
            style={{ insetInlineEnd: 11, color: "var(--text-3)" }}
          >
            …
          </span>
        )}
      </div>
      {/* حالت با آیکون *و* متن، نه فقط رنگ */}
      {check && !checking && (
        <span
          id="code-check"
          className="mt-1 flex items-center gap-1 text-xs"
          style={{ color: check.valid ? "var(--ok)" : "var(--text-3)" }}
        >
          <Icon name={check.valid ? "ok" : "info"} size={13} />
          {check.message}
        </span>
      )}
    </Field>
  );
}
