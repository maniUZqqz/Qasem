import { F } from "./core-edit";
import type { FeatureDef } from "./types";

/** تنظیماتِ ویرایشگر: پیش‌فرضِ کمکِ هوش مصنوعی، مدتِ نگهداریِ پیش‌نویس‌های کارگردان */
export const SETTINGS_FEATURES: FeatureDef[] = [
  F("file.editor-settings", "file", "تنظیمات", "تنظیماتِ ویرایشگر (کمکِ هوش مصنوعی، نگهداریِ پیش‌نویس)", "Editor settings",
    "پیش‌فرضِ کمکِ هوش مصنوعی و مدتِ نگهداریِ پیش‌نویس‌های کارگردان را برای این فروشگاه می‌گذارید.",
    (a) => a.openPanel("editor-settings"), { words: ["settings", "preferences", "options", "تنظیمات", "ai", "draft", "پیش نویس", "نگهداری", "هزینه", "اعتبار"] }),
  F("file.ai-default", "file", "تنظیمات", "پیش‌فرضِ کمکِ هوش مصنوعی: روشن/خاموش", "AI assist default: on / off",
    "تیکِ «هوش مصنوعی کمک کند» در کارگردان با همین حالت شروع می‌شود. روشن = هر «بساز» چند درخواستِ کوچک به مدل می‌فرستد و از اعتبار کم می‌شود؛ خاموش = فقط قالب‌های آماده، بدونِ هزینه.",
    (a) => a.op.toggleAiDefault(), {
      on: (a) => !!a.editorSettings?.ai_default,
      words: ["ai", "assist", "copilot", "ai assist", "default", "off", "on", "هوش مصنوعی", "خاموش", "روشن", "پیش فرض", "کمک", "هزینه", "اعتبار", "خاموش کردن هوش مصنوعی"],
    }),
  F("file.director-drafts", "file", "تنظیمات", "پیش‌نویس‌های قبلیِ کارگردان (بازنشده)", "Director drafts",
    "نتیجه‌های «بساز»ِ قبلی که هنوز بازشان نکرده‌اید؛ هر کدام چند روز مانده تا پاک شود و با باز کردن پروژهٔ واقعی می‌شود.",
    (a) => a.goDirector?.(), { when: (a) => (a.goDirector ? null : "از این صفحه در دسترس نیست"), words: ["drafts", "director", "پیش نویس", "کارگردان", "قبلی", "بازنشده"] }),
];
