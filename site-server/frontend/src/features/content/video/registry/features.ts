import { CORE_EDIT } from "./core-edit";
import { CORE_UI } from "./core-ui";
import { NEW_FEATURES } from "./new-features";
import type { FeatureDef } from "./types";

/**
 * فهرستِ واحدِ همهٔ ویژگی‌های ادیتور. منوی کامل، جستجوی ابزار (Ctrl+K) و ویرایشگرِ میان‌برها همه از همین ساخته می‌شوند.
 * ترتیب: همان که در منو دیده می‌شود (ورودی‌های هر منو به ترتیبِ ثبت می‌آیند).
 */
export const ALL_FEATURES: FeatureDef[] = [...CORE_EDIT, ...CORE_UI, ...NEW_FEATURES];

export const FEATURE_BY_ID: Map<string, FeatureDef> = new Map(ALL_FEATURES.map((f) => [f.id, f]));
