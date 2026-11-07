import { EDIT_FEATURES } from "./r4-edit";
import { R5_FEATURES } from "./r5-features";
import { SETTINGS_FEATURES } from "./r4-settings";
import type { FeatureDef } from "./types";

/**
 * ویژگی‌هایی که در دورِ چهارم افزوده شدند. هر ناحیه فایلِ خودش را دارد و این‌جا یک‌جا جمع می‌شود
 * تا ثبتِ ویژگیِ تازه فقط یک خط تغییر در این فایل باشد.
 */
export const NEW_FEATURES: FeatureDef[] = [...SETTINGS_FEATURES, ...EDIT_FEATURES, ...R5_FEATURES];
