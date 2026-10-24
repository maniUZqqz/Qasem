import { NavLink } from "react-router-dom";

import Icon from "../../components/Icon";
import { useFlags } from "../panel/FlagsContext";

/**
 * زبانه‌های درونِ «صدا و گوینده»: گوینده (پروفایل و تلفظ) و کلونِ صدا.
 * کلیدها همان کلیدهای صفحه در `features/panel/registry.ts` اند؛ زبانه‌ی خاموش کشیده نمی‌شود.
 */
export default function VoiceTabs({ storeId }: { storeId: string }) {
  const { pageEnabled } = useFlags();
  if (!pageEnabled("voice_clone")) return null;
  const tabs = [
    { key: "voice", to: `/stores/${storeId}/voice`, label: "گوینده", end: true },
    { key: "voice_clone", to: `/stores/${storeId}/voice/clone`, label: "کلونِ صدا", end: false },
  ];
  return (
    <nav className="u-tabs" aria-label="صدا">
      {tabs.map((tab) => (
        <NavLink
          key={tab.key}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}
        >
          <span className="flex items-center gap-1.5">
            <Icon name={tab.key === "voice" ? "mic" : "sparkle"} size={14} />
            {tab.label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}
