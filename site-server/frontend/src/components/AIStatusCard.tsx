import { useEffect, useState } from "react";

import { api } from "../api/client";
import { Badge, Card, SectionTitle, Skeleton } from "./ui";

type Capability = {
  capability: string;
  label: string;
  provider: string | null;
  kind: string | null;
  model: string | null;
  local: boolean | null;
  fallbacks: number;
};

/**
 * Which engine is answering right now.
 *
 * Worth showing to the store owner, not just to us: "your content is produced
 * on our own hardware" is a privacy claim, and it should be visible rather
 * than only asserted on the marketing site.
 */
export default function AIStatusCard() {
  const [rows, setRows] = useState<Capability[] | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get("/ai/status/")
      .then(({ data }) => alive && setRows(data.capabilities ?? []))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, []);

  if (rows === null) return <Skeleton className="h-40" />;
  if (rows.length === 0) return null;

  return (
    <Card>
      <SectionTitle>موتور هوش مصنوعی</SectionTitle>
      <div className="flex flex-col gap-3">
        {rows.map((row) => (
          <div key={row.capability} className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                {row.label}
              </div>
              <div className="truncate text-xs" style={{ color: "var(--text-3)" }}>
                {row.model ?? "تنظیم نشده"}
                {row.fallbacks > 0 && ` · ${row.fallbacks} پشتیبان`}
              </div>
            </div>
            <Badge tone={row.local ? "ok" : "info"}>
              {row.local ? "🖥️ سرور ما" : "☁️ سرویس بیرونی"}
            </Badge>
          </div>
        ))}
      </div>
    </Card>
  );
}
