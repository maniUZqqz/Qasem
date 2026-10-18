import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { fa } from "./ui";

type Metric = {
  metric: string;
  label: string;
  allowed: number;
  used: number;
  remaining: number;
  percent: number;
};

type Snapshot = {
  subscription: { plan: string; days_left: number; status_label: string } | null;
  metrics: Metric[];
  blocked: boolean;
  billing?: boolean;
};

/**
 * The quota, always visible in the sidebar.
 *
 * A customer who only discovers their limit when a job is refused has already
 * had a bad day; showing the meters next to the nav means the ceiling is never
 * a surprise.
 */
export default function UsageWidget({ storeId }: { storeId: string }) {
  const [data, setData] = useState<Snapshot | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get(`/stores/${storeId}/usage/`)
      .then(({ data }) => alive && setData(data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [storeId]);

  // billing switched off (no plans configured) or not loaded — show nothing
  if (!data || data.billing === false || !data.subscription) return null;

  return (
    <Link
      to={`/stores/${storeId}/plan`}
      className="block rounded-xl p-3 no-underline"
      style={{ background: "rgb(255 255 255 / .05)" }}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-bold" style={{ color: "#e2e8f0" }}>
          {data.subscription.plan}
        </span>
        <span className="text-[11px]" style={{ color: "rgb(148 163 184 / .8)" }}>
          {fa(data.subscription.days_left)} روز مانده
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {data.metrics.map((m) => {
          const color =
            m.percent >= 90 ? "#f87171" : m.percent >= 70 ? "#fbbf24" : "#34d399";
          return (
            <div key={m.metric}>
              <div
                className="mb-1 flex justify-between text-[11px]"
                style={{ color: "rgb(148 163 184 / .9)" }}
              >
                <span>{m.label}</span>
                <span className="u-num">
                  {fa(m.used)}/{fa(m.allowed)}
                </span>
              </div>
              <div
                style={{
                  height: 5,
                  borderRadius: 999,
                  background: "rgb(255 255 255 / .1)",
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    display: "block",
                    height: "100%",
                    width: `${Math.min(100, m.percent)}%`,
                    background: color,
                    borderRadius: 999,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Link>
  );
}
