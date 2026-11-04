import { ReactNode, useState } from "react";

import Icon from "../../../components/Icon";
import { Badge, Button, Spinner } from "../../../components/ui";
import { jobTone, statusTone, tagTone } from "../format";
import type { Tag } from "../types";

/** Small shared pieces of the Growth Engine screens. */

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return <Badge tone={statusTone(status)}>{label}</Badge>;
}

export function JobBadge({ status, label }: { status: string; label: string }) {
  return <Badge tone={jobTone(status)}>{label}</Badge>;
}

export function TagChips({ tags, max = 4 }: { tags: Tag[]; max?: number }) {
  if (!tags.length) return <span style={{ color: "var(--text-3)" }}>—</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.slice(0, max).map((t) => (
        <Badge key={t.id} tone={tagTone(t.color)}>
          {t.name}
        </Badge>
      ))}
      {tags.length > max && <Badge>+{tags.length - max}</Badge>}
    </span>
  );
}

/** A loading line, or an error with a retry button. */
export function LoadState({ loading, error, onRetry, children }: { loading: boolean; error: string | null; onRetry?: () => void; children: ReactNode }) {
  if (error) {
    return (
      <div
        className="flex flex-wrap items-center justify-between gap-3 rounded-xl p-4"
        style={{ background: "var(--bad-soft)", border: "1px solid color-mix(in srgb, var(--bad) 30%, transparent)" }}
        role="alert"
        data-testid="load-error"
      >
        <span className="text-sm" style={{ color: "var(--bad)" }}>
          {error}
        </span>
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            <Icon name="refresh" size={14} />
            تلاش دوباره
          </Button>
        )}
      </div>
    );
  }
  if (loading) {
    return (
      <div className="py-10 text-center" data-testid="loading">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}

/** A keyboard hint: <Kbd>C</Kbd> */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd
      className="u-num inline-grid min-w-[1.4rem] place-items-center rounded-md px-1.5 text-xs font-bold"
      style={{ background: "var(--surface-2)", border: "1px solid var(--line-strong)", color: "var(--text-2)", lineHeight: "1.4rem" }}
    >
      {children}
    </kbd>
  );
}

/** Copies `text` to the clipboard (with a fallback for plain-http pages) and says so for two seconds. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea trick */
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

export function CopyButton({ text, label = "کپی", size = "sm" }: { text: string; label?: string; size?: "sm" }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  const click = async () => {
    setState((await copyText(text)) ? "ok" : "fail");
    setTimeout(() => setState("idle"), 2000);
  };
  return (
    <Button variant="secondary" size={size} onClick={click} type="button">
      <Icon name={state === "ok" ? "check" : "copy"} size={14} />
      {state === "ok" ? "کپی شد" : state === "fail" ? "نشد" : label}
    </Button>
  );
}

/** A labelled value row for detail screens. */
export function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-sm">
      <span className="w-28 shrink-0" style={{ color: "var(--text-3)" }}>
        {label}
      </span>
      <span className="min-w-0 flex-1 break-words" style={{ color: "var(--text)" }}>
        {children}
      </span>
    </div>
  );
}
