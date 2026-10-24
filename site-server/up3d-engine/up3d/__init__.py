"""UpMarket 3D — هستهٔ مستقل از موتور.

لایه‌ها:
  assets     دفترِ دارایی‌ها (هر دارایی = پوشه + manifest.json)
  scene      سندِ صحنه (قراردادِ مشترکِ AI، کد، ویرایشگرِ گرافیکی)
  validate   وارسی + گرافِ حرکت + ترمیمِ خودکار
  compiler   سندِ صحنه ⇐ برنامهٔ اجرایی با فریمِ مطلق (ورودیِ هر موتور: Blender، وب، بازی)
  sdk        ساختِ صحنه با کد
  director   کارگردانِ هوشِ مصنوعی (کتابخانهٔ openai)
  templates  قالب‌های قاعده‌محور (بی‌نیاز به AI)
  tts/lipsync/overlays/labels/assemble/qc  صدا، لب، نوشتهٔ فارسی، برچسبِ محصول، مونتاژ، کنترلِ کیفیت
  pipeline   خطِ تولید با وضعیت‌ها
  worker     کارگرِ رندرِ HTTP (سرور یا PC با GPU)

هیچ وابستگیِ بیرونی برای scene/validate/compiler/sdk لازم نیست؛
همین بسته داخلِ پایتونِ Blender هم بار می‌شود.
"""

__version__ = '1.2.0'   # 1.2: ویرایشگرِ آزاد (جای آزاد، کلید، اشیا، نور، دوربینِ آزاد، preview_glb)؛ 1.1: تپشِ قلب، واگذاری، بسته‌ها، کلیپ
SCENE_FORMAT = 'up3d.scene/1'
COMPILED_FORMAT = 'up3d.compiled/1'
