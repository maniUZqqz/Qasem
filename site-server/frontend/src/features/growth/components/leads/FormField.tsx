import { ReactNode } from "react";

/** A labelled control with an optional hint and a field-level error (shown in red under the control). */
export default function FormField({
  label,
  hint,
  error,
  required = false,
  children,
  extra,
  testId,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  children: ReactNode;
  /** something small next to the label (a provenance chip, for instance) */
  extra?: ReactNode;
  testId?: string;
}) {
  return (
    <label className="block" data-testid={testId}>
      <span className="mb-1.5 flex flex-wrap items-center gap-2 text-sm font-medium" style={{ color: "var(--text-2)" }}>
        <span>
          {label}
          {required && (
            <span style={{ color: "var(--bad)" }} aria-hidden="true">
              {" "}
              *
            </span>
          )}
        </span>
        {extra}
      </span>
      {children}
      {hint && !error && (
        <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </span>
      )}
      {error && (
        <span className="mt-1 block text-xs font-medium" style={{ color: "var(--bad)" }} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

/** Errors of a request by field name; `__row__` / unknown fields end up in `general`. */
export function groupErrors(errors: { field: string; message: string }[] | undefined, known: string[]): { byField: Record<string, string>; general: string[] } {
  const byField: Record<string, string> = {};
  const general: string[] = [];
  for (const e of errors ?? []) {
    if (known.includes(e.field) && !byField[e.field]) byField[e.field] = e.message;
    else general.push(e.message);
  }
  return { byField, general };
}
