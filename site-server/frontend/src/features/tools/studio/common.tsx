import { ReactNode, useState } from "react";

import Icon from "../../../components/Icon";
import { Button, ErrorBox, Spinner } from "../../../components/ui";
import type { ProjectStatus, ProposalStatus, Shared } from "./types";

/**
 * تکه‌های مشترکِ صفحه‌های سایت‌ساز — همان چیزهایی که base.html ِ قدیمی با
 * چند خط جاوااسکریپت می‌ساخت (کپی، Diff رنگی، ناحیهٔ دستی، پیش‌نمایشِ iframe)،
 * این‌جا به‌شکلِ کامپوننت و با توکن‌های پنل.
 */

export type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

export function statusTone(status: ProjectStatus): Tone {
  return status === "generated" ? "ok" : status === "error" ? "bad" : "warn";
}

export function proposalTone(status: ProposalStatus): Tone {
  if (status === "applied") return "ok";
  if (status === "failed") return "bad";
  if (status === "pending") return "warn";
  if (status === "running") return "brand";
  return "neutral";
}

/** بارگذاری یا خطا، وسطِ صفحه */
export function Loading({ error }: { error?: string | null }) {
  return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;
}

/** سربرگِ کارت — همان `.card-h` ِ قدیمی: عنوان، راهنمای کوتاه، دکمه */
export function SectionHead({
  title,
  hint,
  action,
  tone,
}: {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  tone?: "bad";
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <h3 className="text-base font-bold" style={{ color: tone === "bad" ? "var(--bad)" : "var(--text)" }}>
        {title}
      </h3>
      {hint && (
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </span>
      )}
      {action && <div className="ms-auto flex flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

/** متنِ راهنمای ریز زیرِ فرم‌ها */
export function Help({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`mt-1 text-xs leading-6 ${className}`} style={{ color: "var(--text-3)" }}>
      {children}
    </p>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <code dir="ltr" className={`font-mono text-xs ${className}`} style={{ unicodeBidi: "isolate" }}>
      {children}
    </code>
  );
}

export function Muted({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`text-sm ${className}`} style={{ color: "var(--text-3)" }}>
      {children}
    </span>
  );
}

/** چک‌باکس با برچسب */
export function Check({
  label,
  checked,
  onChange,
  disabled,
  className = "",
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label
      className={`inline-flex cursor-pointer items-center gap-2 text-sm ${className}`}
      style={{ color: "var(--text-2)", opacity: disabled ? 0.6 : 1 }}
    >
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

/** فهرستِ کلید/مقدار (همان `dl.kv`) */
export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm" style={{ gridTemplateColumns: "max-content 1fr" }}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt style={{ color: "var(--text-3)" }}>{k}</dt>
          <dd className="min-w-0 break-words" style={{ color: "var(--text-2)" }}>
            {v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** تب‌های داخلِ صفحه (بدونِ تغییرِ نشانی) */
export function Tabs<K extends string>({
  tabs,
  active,
  onChange,
  mono,
}: {
  tabs: { key: K; label: ReactNode; count?: number }[];
  active: K;
  onChange: (k: K) => void;
  mono?: boolean;
}) {
  return (
    <div className="u-tabs mb-4">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          className={`u-tab ${active === t.key ? "active" : ""} ${mono ? "font-mono" : ""}`}
          onClick={() => onChange(t.key)}
        >
          {t.label}
          {t.count !== undefined && (
            <span
              className="ms-1.5 rounded-full px-1.5 text-xs"
              style={{ background: "var(--surface-2)", color: "var(--text-3)" }}
            >
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/** دکمهٔ کپی با بازخورد «کپی شد ✓» */
export function CopyButton({ text, label = "کپی" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          window.setTimeout(() => setDone(false), 1200);
        } catch {
          /* روی مبدأ ناامن کلیپ‌بورد بسته است؛ متن روی صفحه هست */
        }
      }}
    >
      <Icon name="copy" size={13} />
      {done ? "کپی شد ✓" : label}
    </Button>
  );
}

/** بلوکِ کد. اگر `mark` داده شود، از آن خط به بعد (ناحیهٔ دستی) رنگی می‌شود. */
export function Pre({
  text,
  mark,
  maxHeight = 520,
  className = "",
  rtl,
}: {
  text: string;
  mark?: string;
  maxHeight?: number | string;
  className?: string;
  rtl?: boolean;
}) {
  const i = mark ? text.indexOf(mark) : -1;
  return (
    <pre
      dir={rtl ? "rtl" : "ltr"}
      className={`overflow-auto rounded-xl p-3 font-mono text-xs leading-6 ${className}`}
      style={{
        background: "var(--surface-2)",
        color: "var(--text)",
        border: "1px solid var(--line)",
        maxHeight,
        textAlign: rtl ? "right" : "left",
        whiteSpace: "pre",
        margin: 0,
      }}
    >
      {i < 0 ? (
        text
      ) : (
        <>
          {text.slice(0, i)}
          <span style={{ color: "var(--warn)" }}>{text.slice(i)}</span>
        </>
      )}
    </pre>
  );
}

/** Diff رنگی (+ سبز، − قرمز، @@ آبی) */
export function DiffView({ text, maxHeight = 480 }: { text: string; maxHeight?: number | string }) {
  const lines = (text || "(بی‌تغییر)").split("\n");
  const color = (line: string): string => {
    if (/^(\+\+\+|---)/.test(line)) return "var(--text-3)";
    if (line[0] === "+") return "var(--ok)";
    if (line[0] === "-") return "var(--bad)";
    if (/^@@/.test(line)) return "var(--info)";
    if (/^diff --git|^index |^new file|^deleted file/.test(line)) return "var(--text-3)";
    return "var(--text-2)";
  };
  return (
    <pre
      dir="ltr"
      className="overflow-auto rounded-xl p-3 font-mono text-xs leading-6"
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--line)",
        maxHeight,
        textAlign: "left",
        whiteSpace: "pre",
        margin: 0,
      }}
    >
      {lines.map((line, i) => (
        <span key={i} style={{ color: color(line), display: "block" }}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

/** ویرایشگرِ کدِ ساده: تک‌فاصله، چپ‌به‌راست، Tab = دو فاصله */
export function CodeArea({
  value,
  onChange,
  minHeight = 200,
  readOnly,
  placeholder,
  rtl,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  minHeight?: number | string;
  readOnly?: boolean;
  placeholder?: string;
  rtl?: boolean;
  id?: string;
}) {
  return (
    <textarea
      id={id}
      value={value}
      readOnly={readOnly}
      placeholder={placeholder}
      spellCheck={false}
      dir={rtl ? "rtl" : "ltr"}
      className="u-input font-mono text-xs leading-6"
      style={{ minHeight, resize: "vertical", whiteSpace: "pre", textAlign: rtl ? "right" : "left" }}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Tab" && !readOnly) {
          e.preventDefault();
          const el = e.currentTarget;
          const start = el.selectionStart;
          const end = el.selectionEnd;
          onChange(`${value.slice(0, start)}  ${value.slice(end)}`);
          window.requestAnimationFrame(() => {
            el.selectionStart = start + 2;
            el.selectionEnd = start + 2;
          });
        }
      }}
    />
  );
}

/* ------------------------------------------------------------ پیش‌نمایش */

export const FONT_LINK =
  '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">';

/** تگ‌های قالبِ جنگو را برای پیش‌نمایشِ بی‌داده حذف می‌کند ({% %} حذف، {{ }} ⇒ «…») */
export function stripTemplate(s: string, placeholder = "…"): string {
  const T = new RegExp("{" + "%[^]*?%" + "}", "g");
  const V = new RegExp("{" + "{[^]*?}" + "}", "g");
  const C = new RegExp("{" + "#[^]*?#" + "}", "g");
  return (s || "").replace(C, "").replace(T, "").replace(V, placeholder);
}

/** یک سندِ کاملِ HTML برای iframe: CSSِ مشترک + هدر + بدنه + فوتر */
export function docHtml(shared: Shared, body: string, css = "", placeholder = "…"): string {
  return (
    '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">' +
    FONT_LINK +
    "<style>" +
    shared.base_css +
    "</style><style>" +
    css +
    "</style></head><body>" +
    stripTemplate(shared.header, placeholder) +
    '<main id="page-body">' +
    stripTemplate(body, placeholder) +
    "</main>" +
    stripTemplate(shared.footer, placeholder) +
    "</body></html>"
  );
}

/** قابِ پیش‌نمایش با نوارِ مرورگرگونه */
export function PreviewFrame({
  html,
  src,
  height = 420,
  title = "پیش‌نمایش",
  address,
}: {
  html?: string;
  src?: string;
  height?: number | string;
  title?: string;
  address?: string;
}) {
  return (
    <div className="overflow-hidden rounded-xl" style={{ border: "1px solid var(--line)" }}>
      <div
        className="flex items-center gap-1.5 px-3 py-1.5"
        style={{ background: "var(--surface-2)", borderBottom: "1px solid var(--line)" }}
      >
        {["#fb7185", "#fbbf24", "#34d399"].map((c) => (
          <i key={c} className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />
        ))}
        {address && (
          <span dir="ltr" className="ms-2 font-mono text-xs" style={{ color: "var(--text-3)" }}>
            {address}
          </span>
        )}
      </div>
      <iframe
        title={title}
        srcDoc={html}
        src={html === undefined ? src : undefined}
        className="block w-full"
        style={{ height, background: "#fff", border: 0 }}
      />
    </div>
  );
}

/** تأییدِ پیش از کارهای خطرناک — همان `data-confirm` ِ قدیمی */
export function confirmDo(message: string): boolean {
  return window.confirm(message);
}

/** نوارِ عملیاتِ چسبان در پایینِ فرم‌های بلند */
export function StickyBar({ children }: { children: ReactNode }) {
  return (
    <div
      className="u-card sticky bottom-3 z-10 flex flex-wrap items-center gap-2 p-3"
      style={{ background: "var(--glass-2)", backdropFilter: "blur(12px)" }}
    >
      {children}
    </div>
  );
}
