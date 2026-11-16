import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

import Icon, { type IconName } from "../../../components/Icon";
import { useFlags } from "../../panel/FlagsContext";
import { useGet } from "../api";
import type { FinderMeta } from "./types";

type FinderValue = {
  meta: FinderMeta | null;
  error: string | null;
  reload: () => void;
  typeLabel: (key: string) => string;
  stageLabel: (key: string) => string;
};

const FinderContext = createContext<FinderValue | null>(null);

/** `GET /growth/finder/meta/` once per visit: the business types, presets, sources, stages and the node's state. */
export function FinderProvider({ children }: { children: ReactNode }) {
  const { data, error, reload } = useGet<FinderMeta>("/finder/meta/");
  const value = useMemo<FinderValue>(
    () => ({
      meta: data,
      error,
      reload,
      typeLabel: (key) => data?.types.find((t) => t.key === key)?.label ?? key,
      stageLabel: (key) => data?.stages.find((s) => s.key === key)?.label ?? key,
    }),
    [data, error, reload],
  );
  return <FinderContext.Provider value={value}>{children}</FinderContext.Provider>;
}

export function useFinder(): FinderValue {
  const ctx = useContext(FinderContext);
  if (!ctx) throw new Error("useFinder must be used inside FinderProvider");
  return ctx;
}

const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "growth_finder", to: "/growth/finder", label: "مأموریت‌ها", icon: "target", end: true },
  { key: "growth_finder_results", to: "/growth/finder/results", label: "نتیجه‌ها و نقشه", icon: "search" },
  { key: "growth_finder_pipeline", to: "/growth/finder/pipeline", label: "پایپ‌لاینِ فروش", icon: "trending" },
  { key: "growth_finder_drafts", to: "/growth/finder/drafts", label: "پیش‌نویسِ پیام‌ها", icon: "send" },
];

/** The frame of «مشتری‌یاب»: a second row of tabs under the Growth Engine's own. */
export default function FinderLayout() {
  const { pageEnabled } = useFlags();
  return (
    <FinderProvider>
      <div className="space-y-4" data-testid="finder-root">
        <nav className="flex flex-wrap gap-2" aria-label="بخش‌های مشتری‌یاب">
          {TABS.filter((t) => pageEnabled(t.key)).map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) => `u-btn u-btn-sm ${isActive ? "u-btn-primary" : "u-btn-secondary"}`}
              style={{ textDecoration: "none" }}
              data-testid={`finder-tab-${t.key}`}
            >
              <Icon name={t.icon} size={14} />
              {t.label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </div>
    </FinderProvider>
  );
}
