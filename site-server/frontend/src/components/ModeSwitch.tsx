import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

import Icon, { type IconName } from "./Icon";
import "./editors.css";

/**
 * سه حالتِ هر دو ادیتور (عکس و ویدیو):
 *   خودکار     — یک کلیک؛ ورودی را نگاه می‌کند و خودش ادیت می‌زند
 *   نیمه‌خودکار — دستور می‌دهید؛ هوش مصنوعی درستش می‌کند (مراحلش قابل‌ویرایش است)
 *   دستی       — فضای کامل مثل فتوشاپ / پریمیر
 *
 * حالتِ انتخاب‌شده در نشانی (?mode=…) و در حافظهٔ مرورگر می‌ماند تا با بازکردنِ دوباره همان‌جا برگردید.
 */
export type EditorMode = "auto" | "prompt" | "manual";

const MODES: EditorMode[] = ["auto", "prompt", "manual"];

function remembered(key: string): EditorMode {
  try {
    const v = localStorage.getItem(key);
    if (v && (MODES as string[]).includes(v)) return v as EditorMode;
  } catch {
    /* حافظهٔ مرورگر بسته است */
  }
  return "auto";
}

export function useEditorMode(storageKey: string): [EditorMode, (m: EditorMode) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("mode");
  const mode: EditorMode = raw && (MODES as string[]).includes(raw) ? (raw as EditorMode) : remembered(storageKey);
  const set = useCallback(
    (next: EditorMode) => {
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        /* ignore */
      }
      const p = new URLSearchParams(params);
      p.set("mode", next);
      setParams(p, { replace: true });
    },
    [params, setParams, storageKey],
  );
  return [mode, set];
}

const META: Record<EditorMode, { icon: IconName; title: string }> = {
  auto: { icon: "sparkle", title: "خودکار" },
  prompt: { icon: "bulb", title: "نیمه‌خودکار (با دستور)" },
  manual: { icon: "settings", title: "دستی" },
};

export default function ModeSwitch({
  mode,
  onChange,
  hints,
}: {
  mode: EditorMode;
  onChange: (m: EditorMode) => void;
  hints: Record<EditorMode, string>;
}) {
  return (
    <div className="mode-switch" role="tablist" aria-label="حالتِ ویرایش" data-testid="mode-switch">
      {MODES.map((m) => (
        <button
          key={m}
          type="button"
          role="tab"
          aria-selected={mode === m}
          data-mode={m}
          className={`mode-tab ${mode === m ? "is-on" : ""}`}
          onClick={() => onChange(m)}
        >
          <span className="mode-ico">
            <Icon name={META[m].icon} size={20} />
          </span>
          <span className="mode-text">
            <span className="mode-title">{META[m].title}</span>
            <span className="mode-hint">{hints[m]}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
