import { createContext, ReactNode, useContext, useMemo } from "react";

import { useGet } from "./api";
import type { Meta } from "./types";

/** `GET /growth/meta/` once per visit: statuses, kinds, countries, CSV limits. */

type MetaValue = {
  meta: Meta | null;
  error: string | null;
  statusLabel: (value: string) => string;
  originLabel: (value: string) => string;
  kindLabel: (value: string) => string;
  countryName: (code: string) => string;
};

const MetaContext = createContext<MetaValue | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const { data, error } = useGet<Meta>("/meta/");
  const value = useMemo<MetaValue>(() => {
    const label = (list: { value: string; label: string }[] | undefined, v: string) => list?.find((c) => c.value === v)?.label ?? v;
    return {
      meta: data,
      error,
      statusLabel: (v) => label(data?.statuses, v),
      originLabel: (v) => label(data?.origins, v),
      kindLabel: (v) => label(data?.contact_kinds, v),
      countryName: (code) => data?.countries.find((c) => c.code === code)?.name ?? code,
    };
  }, [data, error]);
  return <MetaContext.Provider value={value}>{children}</MetaContext.Provider>;
}

export function useMeta(): MetaValue {
  const ctx = useContext(MetaContext);
  if (!ctx) throw new Error("useMeta must be used inside MetaProvider");
  return ctx;
}
