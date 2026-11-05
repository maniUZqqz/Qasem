import { useMemo, useSyncExternalStore } from "react";

import { KeyOverrides, Keymap, buildKeymap, loadOverrides, normalizeCombo, saveOverrides } from "./keymap";
import type { FeatureDef } from "./types";

/** حالتِ مشترکِ میان‌برهای کاربر (منو، جستجو، ویرایشگرِ میان‌برها و کنترلِ کیبورد همه از همین می‌خوانند) */
let overrides: KeyOverrides = loadOverrides();
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

/** وقتی ویرایشگرِ میان‌برها منتظرِ فشردنِ یک کلید است، میان‌برهای فضای کار نباید اجرا شوند */
let capturing = false;
export const setKeyCapture = (v: boolean): void => {
  capturing = v;
};
export const isKeyCapture = (): boolean => capturing;

export const getOverrides = (): KeyOverrides => overrides;

/** combo: ترکیبِ تازه؛ "" = بدونِ میان‌بر؛ null = برگرداندن به پیش‌فرض */
export function setOverride(id: string, combo: string | null): void {
  const next = { ...overrides };
  if (combo === null) delete next[id];
  else next[id] = normalizeCombo(combo);
  overrides = next;
  saveOverrides(overrides);
  emit();
}

export function resetOverrides(): void {
  overrides = {};
  saveOverrides(overrides);
  emit();
}

const subscribe = (f: () => void) => {
  subs.add(f);
  return () => {
    subs.delete(f);
  };
};

export function useOverrides(): KeyOverrides {
  return useSyncExternalStore(subscribe, getOverrides, getOverrides);
}

export function useKeymap(features: FeatureDef[]): Keymap {
  const o = useOverrides();
  return useMemo(() => buildKeymap(features, o), [features, o]);
}
