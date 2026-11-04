import { useEffect, useState } from "react";

/** The value, but only after it has stopped changing for `ms` (search boxes). */
export function useDebounced<T>(value: T, ms = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/** Split a typed list («a، b, c») into clean items. */
export function splitList(text: string): string[] {
  return text
    .split(/[,،;؛|\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
