import { ReactNode } from "react";

/** A pill that switches on and off (filter chips). */
export default function ToggleChip({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={testId}
      className={`u-badge ${active ? "u-badge-brand" : "u-badge-neutral"}`}
      style={{ cursor: "pointer", fontFamily: "inherit", padding: "5px 12px" }}
    >
      {children}
    </button>
  );
}
