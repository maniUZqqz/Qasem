# فهرستِ مدل‌ها: ComfyUI و Hugging Face (دانلودِ مدل‌ها)

> این فایل را `backend/tools/gen_model_catalog_doc.py` از `processing/downloads/*.json` می‌سازد؛ دستی ویرایش نشود.

مالک (۱۴۰۵/۰۸/۲۳): «دوباره فقط Ollama گذاشتی؛ قرار بود هاگینگ‌فیس، ComfyUI و منبع‌های دیگرِ مفید هم باشد» و «کارت را پیدا نکردم».

## کجاست؟

پنل ⇐ **ابزارها ⇐ دانلودِ مدل‌ها** (`/panel/tools/models`). همین‌جا مدل‌های Ollama، بسته‌های ComfyUI / Hugging Face (گروه‌بندی‌شده)، دانلودِ خودکار، فضای دیسک و پیشرفتِ دانلود یک‌جاست. از «سرورهای پردازش» (کارتِ «دانلودِ مدل‌ها») و «موتورهای AI» هم پیوند دارد.

## بسته‌ها

هر بسته چند فایل دارد؛ اندازه و sha256 از API ِ Hugging Face گرفته شده (commit ِ سنجاق‌شده)، و گره پس از دانلود دوباره می‌سنجد. ستونِ «۱۲GB» یعنی روی RTX 3060 با ۱۲ گیگابایت چقدر راحت اجرا می‌شود. «خودکار» یعنی با روشن‌بودنِ قابلیت‌ش خودش می‌آید (فقط مجوزِ «تجاری مجاز»).

### تصویر

| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |
|---|---|---|---|---|---|---|---|
| `flux-common` | FLUX — رمزگذارهای متن و VAE (مشترکِ همهٔ مدل‌های FLUX) | ۵٫۱ گیگابایت | تجاری مجاز (Apache-2.0 / MIT) | جا می‌شود | — | نه (یک کلیک) | ساختِ تصویر، ویرایشِ تصویر با دستور |
| `flux-schnell` | FLUX.1 schnell (fp8) — تصویرِ سریع در ۴ گام | ۱۱ گیگابایت | تجاری مجاز (Apache-2.0) | با کمی کندی | `flux-common` | بله (قابلیتِ روشن) | ساختِ تصویر، بندانگشتی و پست |
| `sdxl-base` | SDXL 1.0 پایه + VAEِ fp16 | ۶٫۸ گیگابایت | تجاری مجاز (CreativeML OpenRAIL++-M) | جا می‌شود | — | بله (قابلیتِ روشن) | سبک‌های طراحی، بندانگشتی و پست |
| `sdxl-realvis` | RealVisXL V5.0 — SDXLِ واقع‌گرا | ۶٫۵ گیگابایت | تجاری مجاز (CreativeML OpenRAIL++-M) | جا می‌شود | — | بله (قابلیتِ روشن) | سبک‌های طراحی، بندانگشتی و پست |
| `zimage-turbo` | Z-Image Turbo — تصویرِ سریع و باکیفیت | ۱۷ گیگابایت | تجاری مجاز (Apache-2.0) | با کمی کندی | — | نه (یک کلیک) | ساختِ تصویر، بندانگشتی و پست |
| `flux-dev` | FLUX.1 dev (fp8) — بهترین کیفیتِ FLUX | ۱۱ گیگابایت | فقط غیرتجاری (FLUX.1 [dev] Non-Commercial) | با کمی کندی | `flux-common` | هرگز | ساختِ تصویر |
| `flux-fill` | FLUX.1 Fill dev (fp8) — پرکردنِ بخشی از تصویر (inpaint / outpaint) | ۱۱ گیگابایت | فقط غیرتجاری (FLUX.1 [dev] Non-Commercial) | با کمی کندی | `flux-common` | هرگز | ویرایشِ تصویر با دستور |
| `flux-kontext` | FLUX.1 Kontext dev (fp8) — ویرایشِ تصویر با دستور | ۱۱ گیگابایت | فقط غیرتجاری (FLUX.1 [dev] Non-Commercial) | با کمی کندی | `flux-common` | هرگز | ویرایشِ تصویر با دستور، ثباتِ چهره و سبک |

**`flux-common`** — T5-XXL (fp8)، CLIP-L و ae؛ بدونِ این‌ها هیچ مدلِ FLUX اجرا نمی‌شود. یک بار گرفته می‌شود و همهٔ مدل‌های FLUX از آن استفاده می‌کنند.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `t5xxl_fp8` | ۴٫۶ گیگابایت | `7d330da48161…` | `models\text_encoders\t5xxl_fp8_e4m3fn.safetensors` | `comfyanonymous/flux_text_encoders@6af2a98e/t5xxl_fp8_e4m3fn.safetensors` |
| `clip_l` | ۲۳۵ مگابایت | `660c6f5b1aba…` | `models\text_encoders\clip_l.safetensors` | `comfyanonymous/flux_text_encoders@6af2a98e/clip_l.safetensors` |
| `ae_vae` | ۳۲۰ مگابایت | `afc8e28272cd…` | `models\vae\ae.safetensors` | `Comfy-Org/Z-Image-Turbo@6fc90a3b/split_files/vae/ae.safetensors` |

**`flux-schnell`** — استفادهٔ تجاری آزاد (Apache-2.0). در ۴ گام تصویر می‌سازد؛ برای پیش‌نمایش، بندانگشتی، پستِ شبکه‌های اجتماعی و کارهای پرتعداد مناسب است.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `schnell_fp8` | ۱۱ گیگابایت | `bbdfba27fed8…` | `models\diffusion_models\flux1-schnell-fp8-e4m3fn.safetensors` | `Kijai/flux-fp8@2ef6f85f/flux1-schnell-fp8-e4m3fn.safetensors` |

**`sdxl-base`** — مدلِ پایهٔ سبک‌های طراحی؛ با ControlNet و IP-Adapter کار می‌کند. استفادهٔ تجاری مجاز (با محدودیتِ استفادهٔ مضر).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `sdxl_base` | ۶٫۵ گیگابایت | `31e35c80fc48…` | `models\checkpoints\sd_xl_base_1.0.safetensors` | `stabilityai/stable-diffusion-xl-base-1.0@46216598/sd_xl_base_1.0.safetensors` |
| `sdxl_vae_fp16` | ۳۱۹ مگابایت | `235745af8d86…` | `models\vae\sdxl_vae.safetensors` | `madebyollin/sdxl-vae-fp16-fix@207b116d/sdxl_vae.safetensors` |

**`sdxl-realvis`** — عکسِ واقع‌گرا از آدم و محصول؛ مجوزِ OpenRAIL++ (تجاری مجاز).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `realvisxl_v5` | ۶٫۵ گیگابایت | `6a35a7855770…` | `models\checkpoints\RealVisXL_V5.0_fp16.safetensors` | `SG161222/RealVisXL_V5.0@ac93e0dd/RealVisXL_V5.0_fp16.safetensors` |

**`zimage-turbo`** — مدلِ ۶ میلیاردیِ Apache-2.0 با ۸ گام؛ جایگزینِ آزادِ FLUX. متنِ انگلیسی و چینی را خوب می‌نویسد.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `zimage_bf16` | ۱۱ گیگابایت | `2407613050b8…` | `models\diffusion_models\z_image_turbo_bf16.safetensors` | `Comfy-Org/Z-Image-Turbo@6fc90a3b/split_files/diffusion_models/z_image_turbo_bf16.safetensors` |
| `qwen3_4b_fp8` | ۵٫۲ گیگابایت | `72450b197581…` | `models\text_encoders\qwen_3_4b_fp8_mixed.safetensors` | `Comfy-Org/Z-Image-Turbo@6fc90a3b/split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors` |
| `ae_vae` | ۳۲۰ مگابایت | `afc8e28272cd…` | `models\vae\ae.safetensors` | `Comfy-Org/Z-Image-Turbo@6fc90a3b/split_files/vae/ae.safetensors` |

**`flux-dev`** — مجوزِ غیرتجاری: خودِ مدل را نمی‌شود برای کارِ تجاری سرویس داد (خروجی‌ها طبقِ مجوزِ سازنده). اگر «FLUX.1 [dev] FP8» از قبل روی ComfyUI باشد، نصب‌شده حساب می‌شود.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `dev_fp8` | ۱۱ گیگابایت | `47d8dbdc6da6…` | `models\diffusion_models\flux1-dev-fp8-e4m3fn.safetensors` | `Kijai/flux-fp8@2ef6f85f/flux1-dev-fp8-e4m3fn.safetensors` |

**`flux-fill`** — پاک‌کردن و جایگزینیِ بخشی از عکس و گسترشِ بومِ تصویر. مجوزِ غیرتجاری. فایل بازنشرِ غیررسمیِ fp8 از مدلِ اصلی است؛ در Hugging Face خودِ سازنده نسخهٔ fp8 ندارد.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `fill_dev_fp8` | ۱۱ گیگابایت | `0320d505ca42…` | `models\diffusion_models\flux1-fill-dev-fp8.safetensors` | `wjndd/flux1-fill-dev-fp8@cda97224/flux1-fill-dev-fp8.safetensors` |

**`flux-kontext`** — با یک جمله عکس را ویرایش می‌کند و چهره/محصول را نگه می‌دارد (ثباتِ شخصیت). مجوزِ غیرتجاری.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `kontext_fp8` | ۱۱ گیگابایت | `630ba795ec64…` | `models\diffusion_models\flux1-dev-kontext_fp8_scaled.safetensors` | `Comfy-Org/Flux-1-Kontext-Dev@795e390e/split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors` |

### ویدیو

| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |
|---|---|---|---|---|---|---|---|
| `frame-interp` | RIFE و FILM — نرم‌کردنِ حرکتِ ویدیو (فریمِ میانی) | ۱۰۹ مگابایت | تجاری مجاز (MIT / Apache-2.0) | جا می‌شود | — | بله (قابلیتِ روشن) | نرم‌کردنِ حرکت، ویدیوی AI سبک |
| `wan22-ti2v-5b` | Wan 2.2 TI2V ۵B — ویدیو از متن یا عکس (سبک) | ۱۷ گیگابایت | تجاری مجاز (Apache-2.0) | جا می‌شود | — | بله (قابلیتِ روشن) | ویدیوی AI سبک |
| `ltx-video-distilled` | LTX-Video ۲B (distilled، fp8) — ویدیوی بسیار سریع | ۴٫۶ گیگابایت | با شرط (LTXV Open Weights License 0.X) | جا می‌شود | `flux-common` | هرگز | ویدیوی AI سبک |

**`frame-interp`** — از ۲۴ به ۴۸ یا ۶۰ فریم؛ برای ویدیوهای هوش مصنوعی و اسلوموشن. ComfyUI نودِ داخلی‌اش را دارد؛ بسیار کوچک (حدود ۱۱۵ مگابایت).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `rife_v425` | ۲۲ مگابایت | `1505884b9bda…` | `models\frame_interpolation\rife_v4.25.safetensors` | `Comfy-Org/Frame-Interpolation@aa7009be/frame_interpolation/rife_v4.25.safetensors` |
| `rife_v425_lite` | ۲۱ مگابایت | `e5e5fe0286d3…` | `models\frame_interpolation\rife_v4.25_lite.safetensors` | `Comfy-Org/Frame-Interpolation@aa7009be/frame_interpolation/rife_v4.25_lite.safetensors` |
| `film_net_fp16` | ۶۶ مگابایت | `f226e51375dc…` | `models\frame_interpolation\film_net_fp16.safetensors` | `Comfy-Org/Frame-Interpolation@aa7009be/frame_interpolation/film_net_fp16.safetensors` |

**`wan22-ti2v-5b`** — مدلِ ۵ میلیاردیِ ویدیو با خروجیِ ۷۲۰p و ۲۴ فریم؛ از Wan 2.2 A14B خیلی سبک‌تر است و در کارتِ ۱۲ گیگابایتی راحت اجرا می‌شود. Apache-2.0.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `ti2v_5b_fp16` | ۹٫۳ گیگابایت | `456f901338bd…` | `models\diffusion_models\wan2.2_ti2v_5B_fp16.safetensors` | `Comfy-Org/Wan-2.2@ee6f4a40/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` |
| `wan22_vae` | ۱٫۳ گیگابایت | `e40321bd36b9…` | `models\vae\wan2.2_vae.safetensors` | `Comfy-Org/Wan-2.2@ee6f4a40/split_files/vae/wan2.2_vae.safetensors` |
| `umt5_xxl_fp8` | ۶٫۳ گیگابایت | `c3355d30191f…` | `models\text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `Comfy-Org/Wan-2.2@ee6f4a40/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` |

**`ltx-video-distilled`** — چند ثانیه ویدیو در چند ده ثانیه. مجوز: برای هر کاری آزاد است مگر شرکت‌های با درآمدِ سالانهٔ بالای ۱۰ میلیون دلار که قراردادِ جدا می‌خواهند.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `ltxv_2b_distilled_fp8` | ۴٫۲ گیگابایت | `d6d8fa8ed3a9…` | `models\checkpoints\ltxv-2b-0.9.8-distilled-fp8.safetensors` | `Lightricks/LTX-Video@8984fa25/ltxv-2b-0.9.8-distilled-fp8.safetensors` |
| `ltxv_spatial_upscaler` | ۴۸۲ مگابایت | `5b076031c6f8…` | `models\latent_upscale_models\ltxv-spatial-upscaler-0.9.8.safetensors` | `Lightricks/LTX-Video@8984fa25/ltxv-spatial-upscaler-0.9.8.safetensors` |

### بزرگ‌کردن و ترمیم

| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |
|---|---|---|---|---|---|---|---|
| `esrgan-x4plus` | Real-ESRGAN x4plus — بزرگ‌کردنِ ۴ برابریِ عکس | ۶۴ مگابایت | تجاری مجاز (BSD-3-Clause) | جا می‌شود | — | بله (قابلیتِ روشن) | بزرگ‌کردنِ عکس، بندانگشتی و پست |
| `face-restore` | ترمیمِ چهره — GFPGAN v1.4 (+ تشخیصِ چهره) | ۵۱۸ مگابایت | تجاری مجاز (Apache-2.0) | جا می‌شود | — | بله (قابلیتِ روشن) | ترمیمِ چهره |
| `ultrasharp-4x` | 4x-UltraSharp — بزرگ‌کردنِ تیز | ۶۴ مگابایت | فقط غیرتجاری (CC BY-NC-SA 4.0) | جا می‌شود | — | هرگز | بزرگ‌کردنِ عکس |
| `nmkd-siax-4x` | 4x NMKD-Siax — بزرگ‌کردنِ طبیعی | ۶۴ مگابایت | فقط غیرتجاری (unverified) | جا می‌شود | — | هرگز | بزرگ‌کردنِ عکس |
| `codeformer` | ترمیمِ چهره — CodeFormer | ۳۵۹ مگابایت | فقط غیرتجاری (S-Lab License 1.0) | جا می‌شود | — | هرگز | ترمیمِ چهره |

**`esrgan-x4plus`** — کوچک (۶۴ مگابایت) و سریع؛ بهترین انتخابِ عمومی برای بزرگ‌کردنِ عکسِ محصول و آدم. مجوزِ BSD-3 (تجاری مجاز).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `realesrgan_x4plus` | ۶۴ مگابایت | `37f9a931c215…` | `models\upscale_models\RealESRGAN_x4plus.safetensors` | `Comfy-Org/Real-ESRGAN@5fd49b7b/RealESRGAN_x4plus.safetensors` |

**`face-restore`** — چهرهٔ تارِ عکس را واضح می‌کند. برای استفاده در ComfyUI به یک نودِ ترمیمِ چهره نیاز است (خودکار نصب نمی‌شود)؛ فایل‌ها در پوشه‌ای که این نودها می‌خوانند گذاشته می‌شود.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `gfpgan_v14` | ۳۳۲ مگابایت | `e2cd4703ab14…` | `models\facerestore_models\GFPGANv1.4.pth` | `leonelhs/gfpgan@454bfc5a/GFPGANv1.4.pth` |
| `facexlib_detection` | ۱۰۴ مگابایت | `6d1de9c2944f…` | `models\facedetection\detection_Resnet50_Final.pth` | `leonelhs/facexlib@d3ad6bbf/detection_Resnet50_Final.pth` |
| `facexlib_parsing` | ۸۱ مگابایت | `3d558d8d0e42…` | `models\facedetection\parsing_parsenet.pth` | `leonelhs/facexlib@d3ad6bbf/parsing_parsenet.pth` |

**`ultrasharp-4x`** — لبه‌ها را تیزتر از Real-ESRGAN می‌کند. مجوزِ غیرتجاری (CC BY-NC-SA 4.0).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `ultrasharp` | ۶۴ مگابایت | `36a340b5509b…` | `models\upscale_models\4x-UltraSharp.safetensors` | `Kim2091/UltraSharp@920fe218/4x-UltraSharp.safetensors` |

**`nmkd-siax-4x`** — جزئیاتِ طبیعی و کم‌نویز. مجوزِ این فایل را نتوانستیم تأیید کنیم؛ تا روشن‌شدن غیرتجاری حساب می‌شود.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `siax` | ۶۴ مگابایت | `560424d9f686…` | `models\upscale_models\4x_NMKD-Siax_200k.pth` | `gemasai/4x_NMKD-Siax_200k@6a21e0d6/4x_NMKD-Siax_200k.pth` |

**`codeformer`** — ترمیمِ چهره با کنترلِ وفاداری. مجوزِ غیرتجاری (S-Lab).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `codeformer_v010` | ۳۵۹ مگابایت | `1009e537e0c2…` | `models\facerestore_models\codeformer-v0.1.0.pth` | `leonelhs/gfpgan@454bfc5a/CodeFormer.pth` |

### کنترل و ثبات

| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |
|---|---|---|---|---|---|---|---|
| `controlnet-union-sdxl` | ControlNet یکپارچه برای SDXL (xinsir Promax) | ۲٫۳ گیگابایت | تجاری مجاز (Apache-2.0) | جا می‌شود | `sdxl-base` | بله (قابلیتِ روشن) | سبک‌های طراحی، ثباتِ چهره و سبک |
| `ipadapter-sdxl` | IP-Adapter برای SDXL — تکرارِ سبک و چهره از روی عکسِ مرجع | ۳٫۹ گیگابایت | تجاری مجاز (Apache-2.0 / MIT) | جا می‌شود | `sdxl-base`، `nodes-ipadapter-plus` | بله (قابلیتِ روشن) | سبک‌های طراحی، ثباتِ چهره و سبک |
| `nodes-ipadapter-plus` | نودِ ComfyUI — IPAdapter plus | ۴ مگابایت | تجاری مجاز (GPL-3.0 (local install only)) | جا می‌شود | — | بله (قابلیتِ روشن) | سبک‌های طراحی، ثباتِ چهره و سبک |
| `controlnet-union-flux` | ControlNet یکپارچه برای FLUX (Shakker Union Pro 2.0) | ۴٫۰ گیگابایت | فقط غیرتجاری (FLUX.1 [dev] Non-Commercial) | سنگین و کند | `flux-common` | هرگز | ویرایشِ تصویر با دستور، ثباتِ چهره و سبک |

**`controlnet-union-sdxl`** — یک مدل به‌جای ده‌ها ControlNet: ژستِ بدن، عمق، لبه (canny)، خط، اسکریبل و … برای حفظِ چیدمان و ژستِ تصویر. تجاری مجاز.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `xinsir_union_promax` | ۲٫۳ گیگابایت | `9fae2e50cb43…` | `models\controlnet\controlnet-union-sdxl-1.0-promax.safetensors` | `xinsir/controlnet-union-sdxl-1.0@801a4a3f/diffusion_pytorch_model_promax.safetensors` |

**`ipadapter-sdxl`** — با یک عکسِ مرجع، سبک یا چهرهٔ همان را در تصویرِ تازه نگه می‌دارد (ثباتِ شخصیت و سبک). به نودِ IPAdapter plus و راه‌اندازیِ دوبارهٔ ComfyUI نیاز دارد (همراهش نصب می‌شود).

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `plus_sdxl_vith` | ۸۰۸ مگابایت | `3f5062b8400c…` | `models\ipadapter\ip-adapter-plus_sdxl_vit-h.safetensors` | `h94/IP-Adapter@018e4027/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors` |
| `plus_face_sdxl_vith` | ۸۰۸ مگابایت | `677ad8860204…` | `models\ipadapter\ip-adapter-plus-face_sdxl_vit-h.safetensors` | `h94/IP-Adapter@018e4027/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors` |
| `clip_vision_vith` | ۲٫۴ گیگابایت | `6ca9667da1ca…` | `models\clip_vision\CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | `Comfy-Org/CLIP-ViT-H-14-laion2B-s32B-b79K_repackaged@b1aee1a7/split_files/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` |

**`nodes-ipadapter-plus`** — کدِ نود در پوشهٔ custom_nodes نصب می‌شود (commit ثابت). بعد از نصب ComfyUI را یک بار دوباره راه بیندازید.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `code` | ۴ مگابایت | `a0f451a5113c…` | `custom_nodes\ComfyUI_IPAdapter_plus` | `cubiq/ComfyUI_IPAdapter_plus` |

**`controlnet-union-flux`** — کنترلِ ژست/عمق/لبه روی FLUX dev. مجوزِ غیرتجاری. با FLUX روی ۱۲ گیگابایت کند می‌شود.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `shakker_union_pro2` | ۴٫۰ گیگابایت | `9d03f63f3620…` | `models\controlnet\FLUX.1-dev-ControlNet-Union-Pro-2.0.safetensors` | `Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0@5d700aaa/diffusion_pytorch_model.safetensors` |

### عمق و سه‌بعدی

| بسته | نام | حجم | مجوز | ۱۲GB | نیاز دارد | خودکار | قابلیت‌ها |
|---|---|---|---|---|---|---|---|
| `depth-anything-v2-small` | Depth Anything V2 Small — نقشهٔ عمق از یک عکس | ۱۸۹ مگابایت | تجاری مجاز (Apache-2.0) | جا می‌شود | — | بله (قابلیتِ روشن) | عمق و سه‌بعدی |

**`depth-anything-v2-small`** — برای ویدیوی سه‌بعدی، پارالکس و جداکردنِ پیش‌زمینه از پس‌زمینه. کوچک (حدود ۲۰۰ مگابایت)، Apache-2.0؛ مدل‌های بزرگ‌تر این خانواده غیرتجاری‌اند و عمداً نیامده‌اند.

| فایل | حجم | sha256 | مقصد | منبع |
|---|---|---|---|---|
| `hf_weights` | ۹۵ مگابایت | `3152477ce0d8…` | `models\depth-anything-v2-small\model.safetensors` | `depth-anything/Depth-Anything-V2-Small-hf@5426e4f0/model.safetensors` |
| `hf_config` | ۱ مگابایت | `c56698d3643d…` | `models\depth-anything-v2-small\config.json` | `depth-anything/Depth-Anything-V2-Small-hf@5426e4f0/config.json` |
| `hf_preprocessor` | ۱ مگابایت | `d41175c0d889…` | `models\depth-anything-v2-small\preprocessor_config.json` | `depth-anything/Depth-Anything-V2-Small-hf@5426e4f0/preprocessor_config.json` |
| `onnx_fp32` | ۹۴ مگابایت | `afb6a5c28f3b…` | `models\depth-anything-v2-small\onnx\model.onnx` | `onnx-community/depth-anything-v2-small@4472b736/onnx/model.onnx` |

جمعِ همهٔ بسته‌های این فهرست حدودِ ۱۱۳ گیگابایت است؛ **هیچ‌کدام در مجموعهٔ پیش‌فرضِ گره نیست** (همه اختیاری‌اند) و هیچ فایلِ چندگیگابایتی روی سرورِ سایت دانلود نشده.

**بازبینیِ آدرس‌ها (۱۴۰۵/۰۸/۲۳):** ۰ آدرس روی huggingface.co و hf-mirror.com سنجیده شد؛ ۰ مورد درست و اندازهٔ گزارش‌شدهٔ سرور برابرِ اندازهٔ ثبت‌شده؛ مشکل: ۷۴.

## دانلودِ خودکار

1. هر قابلیت یک سوئیچ دارد (پنل ⇐ دانلودِ مدل‌ها ⇐ «دانلودِ خودکارِ مدل‌ها»). پیش‌فرضِ روشن: ساختِ تصویر، بزرگ‌کردنِ عکس، نرم‌کردنِ حرکت، عمق و سه‌بعدی؛ پیش‌فرضِ خاموش: سبک‌های طراحی، ویدیوی AI سبک، ترمیمِ چهره.
2. سایت با هر heartbeat بلوکِ `models_auto` را می‌فرستد: فهرستِ مرتبِ بسته‌هایی که قابلیت‌های روشن لازم دارند (فقط «تجاری مجاز»)، ذخیرهٔ دیسک (۲۵ گیگابایت) و حدِ «بزرگ» (۱٫۵ گیگابایت).
3. گره (`processing/model_auto.py`، هر ۱۰ دقیقه و بلافاصله پس از عوضِ تنظیم) دیسکِ آزاد را می‌سنجد: آزاد − ذخیره − آنچه همین الان برنامه‌ریزی شده. بسته‌ای که جا نشود شروع نمی‌شود و «جای دیسک کافی نیست» نشان داده می‌شود.
4. بسته‌های کوچک بلافاصله (طبقِ «زمان‌بندیِ دانلود» ِ سرورهای پردازش)، بزرگ‌ها **فقط در بازهٔ شبانه** (حتی اگر حالتِ کلی «الان» باشد) — ادامه‌پذیر (`.part` + Range)، با sha256؛ اگر بازه وسطِ دانلود تمام شود تمیز می‌ایستد و شبِ بعد ادامه می‌دهد.
5. سه شکستِ پیاپیِ یک بسته ⇒ یک روز استراحت (دلیل در پنل)؛ یک کلیکِ دستی یا فردا دوباره تلاش می‌شود.
6. هر چیزی که نصب است (حتی با نامِ دیگر در هر پوشهٔ ComfyUI؛ مثلاً «FLUX.1 [dev] FP8.safetensors») دوباره دانلود نمی‌شود.

## سمتِ سرورِ پردازش (`download_models.py` 1.4)

- `--list` همهٔ بسته‌ها را با مجوز/۱۲GB/وضعیت نشان می‌دهد؛ `--only <بسته>` فایل‌های یک بسته و نیازهایش؛ `--catalog` همهٔ کاتالوگ به‌صورت JSON؛ `--status` وضعیتِ نصب + دیسکِ آزاد.
- `needs`: هر بسته با نیازهایش می‌آید (همهٔ مدل‌های FLUX ⇐ `flux-common`؛ `ipadapter-sdxl` ⇐ `sdxl-base` و `nodes-ipadapter-plus`).
- `--all` مجوزِ «با شرط» و «غیرتجاری» را نمی‌گیرد (فقط وقتی نامشان صریح بیاید)؛ این‌ها همیشه اختیاری‌اند.
- `nodes-ipadapter-plus` یک نودِ ComfyUI است (git در `custom_nodes`، commit سنجاق‌شده) و بعد از نصب باید ComfyUI یک بار دوباره راه بیفتد.

## عمداً نیامد

- **PuLID**: به وزن‌های InsightFace (پژوهشی/غیرتجاری) و ساختِ بومیِ `insightface` روی ویندوز نیاز دارد که بی‌دخالتِ آدم نصب‌شدنی نیست؛ ثباتِ چهره را FLUX Kontext و IP-Adapter پوشش می‌دهند.
- **Depth-Anything V2 Base/Large/Giant**: CC BY-NC 4.0؛ فقط Small (Apache-2.0).
- **نودِ ترمیمِ چهرهٔ ComfyUI** (مثلاً `facerestore_cf`): نیازمندیِ pip ِ سنگین (torch/opencv/…) که ComfyUI را خراب می‌کند و مجوزِ مشخص ندارد؛ فایل‌های GFPGAN/CodeFormer در پوشه‌ای که چنین نودهایی می‌خوانند گذاشته می‌شود.
- **FLUX Fill با fp8 رسمی**: سازنده نسخهٔ fp8 منتشر نکرده؛ بازنشرِ غیررسمی (بدونِ تغییر، همان مجوزِ غیرتجاری) از `wjndd/flux1-fill-dev-fp8` با `provenance` نشانه‌گذاری شده.
- **ModelScope**: آینهٔ دوم نیامد؛ منبع‌ها `huggingface.co` و `hf-mirror.com` هستند (هر دو سنجیده شد و گره هر دو را امتحان می‌کند).

