import { Badge, Select } from "./ui";

/**
 * The three-state subtitle switch. §8
 *
 * Three states, not two, and that is what makes a per-video setting usable: a
 * shop sets the default once and only touches the ones that differ. A two-state
 * toggle forces a decision on every single video, and people answer those by
 * accepting whatever is in front of them.
 *
 * The effective answer is always shown next to the control, because "as the
 * shop decided" is useless if you cannot see what the shop decided.
 */
export default function SubtitleSwitch({
  label,
  value,
  effective,
  onChange,
  disabled,
  hint,
}: {
  label: string;
  /** null = follow the shop default */
  value: boolean | null;
  effective: boolean;
  onChange: (next: boolean | null) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const current = value === null ? "default" : value ? "on" : "off";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm" style={{ color: "var(--text-2)" }}>
        {label}
      </span>
      <Select
        value={current}
        disabled={disabled}
        onChange={(e) => {
          const next = e.target.value;
          onChange(next === "default" ? null : next === "on");
        }}
      >
        <option value="default">پیش‌فرض فروشگاه</option>
        <option value="on">روشن</option>
        <option value="off">خاموش</option>
      </Select>
      {value === null && (
        <Badge tone={effective ? "ok" : "neutral"}>
          {effective ? "الان روشن است" : "الان خاموش است"}
        </Badge>
      )}
      {hint && (
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}
