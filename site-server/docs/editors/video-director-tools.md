# کارگردانِ ویدیو — فهرستِ ابزارها (TOOL CATALOG)

هر مرحلهٔ کارگردان یک «فراخوانی ابزار» است: `{"tool": "...", "params": {...}, "why": "..."}`. 
این ابزارها همان کارهای ادیتورِ دستی‌اند؛ پس هر چه کارگردان بسازد در حالت دستی قابل‌ویرایش است. 
مقدارها پیش از اجرا بررسی می‌شوند: عددها در بازهٔ مجاز بریده می‌شوند، گزینهٔ ناشناخته به پیش‌فرض برمی‌گردد، ابزارِ ناشناخته کنار گذاشته می‌شود.

## ساختار و برش

### `set_format` — قابِ پروژه

Set the frame: reel 9:16, feed 4:5, square 1:1 or wide 16:9.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `preset` | قاب | choice | reel | reel / feed / square / wide |
| `fps` | فریم در ثانیه | int | 30 | 24 … 60 |

### `add_clip` — افزودنِ قطعه

Put a video, photo or sound from the media bin on the timeline.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `ref` | منبع (لازم) | ref |  |  |
| `track` | ترک | choice | main | main / overlay / speech / music / sfx |
| `at` | زمان | text | end |  |
| `start` | از ثانیهٔ منبع | num | 0 | 0 … 86400 ث |
| `end` | تا ثانیهٔ منبع | num |  | 0 … 86400 ث |
| `duration` | مدت (عکس) | num | 3 | 0.3 … 60 ث |
| `fit` | جا دادن | choice | cover | cover / contain / stretch |
| `label` | نام | text |  |  |
| `id` | نشانی برای مراحلِ بعد | text |  |  |

### `trim_clip` — کوتاه‌کردنِ قطعه

Change a clip's source in/out (seconds of the source file).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `start` | از ثانیهٔ منبع | num |  | 0 … 86400 |
| `end` | تا ثانیهٔ منبع | num |  | 0 … 86400 |

### `split_clip` — برشِ قطعه

Cut a clip in two at a timeline time (linked sound is cut too).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `at` | زمان (لازم) | num |  | 0 … 86400 ث |

### `remove_range` — برداشتنِ یک بازه

Remove a time range from every track and close the gap (a cut).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `from` | از ثانیه (لازم) | num |  | 0 … 86400 ث |
| `to` | تا ثانیه (لازم) | num |  | 0 … 86400 ث |
| `ripple` | بستنِ فاصله | bool | True |  |

### `delete_clip` — حذفِ قطعه

Delete clips (optionally closing the gap on their tracks).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `ripple` | بستنِ فاصله | bool | False |  |

### `move_clip` — جابه‌جاییِ قطعه

Move a clip to a timeline time.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `at` | زمان (لازم) | num |  | 0 … 86400 ث |

### `reorder_clips` — ترتیبِ قطعه‌ها

Re-sequence listed clips of the main track back-to-back in the given order.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `order` | ترتیب (لازم) | list |  |  |

### `set_speed` — سرعتِ قطعه

Change playback speed of a clip (0.25-4x).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `speed` | سرعت (لازم) | num |  | 0.25 … 4 × |

### `speed_ramp` — منحنیِ سرعت

Apply a speed-ramp preset (fast/slow/fast) to a clip.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `preset` | الگو | choice | montage | montage / hero / flash_in / flash_out / bullet |

### `close_gaps` — بستنِ فاصله‌ها

Butt the clips of a track against each other (no black gaps).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `track` | ترک | choice | main | main / overlay |

### `fit_length` — جا دادن در مدتِ هدف

Shorten the main track to a target length by trimming clip tails (or speeding up).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `seconds` | مدت (لازم) | num |  | 3 … 600 ث |
| `mode` | روش | choice | trim | trim / speed |

### `cut_to_beats` — برش روی ضرب

Re-cut the main track so every cut lands on the music beats (beat-synced edit).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `music` | موسیقی (قطعه یا منبع) (لازم) | clip |  |  |
| `every` | هر چند ضرب | int | 2 | 1 … 8 |
| `clips` | نماهای مبدأ | list |  |  |

### `transition` — گذار

Set the transition that brings a clip in from the previous one (or all joins of the main track).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعهٔ واردشونده | clip | all |  |
| `kind` | نوع | text | crossfade |  |
| `duration` | مدت | num | 0.4 | 0.1 … 2 ث |

## متن و زیرنویس

### `add_title` — عنوان / متن

Add a title or text overlay with a template (Persian-ready).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `text` | متن (لازم) | text |  |  |
| `text2` | زیرعنوان | text |  |  |
| `at` | زمان | num | 0 | 0 … 86400 ث |
| `duration` | مدت | num | 2.5 | 0.5 … 20 ث |
| `template` | قالب | choice | title_center | plain / lower_bar / lower_box / lower_line / title_center / title_big / quote / sticker / bubble |
| `position` | جا | choice |  | — / top / middle / bottom |
| `size` | اندازه | num |  | 2 … 20 ٪ |
| `color` | رنگ | text |  |  |
| `id` | نشانی | text |  |  |

### `add_captions` — زیرنویس

Auto-caption the speech of a clip (needs speech recognition) or place given lines.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |
| `style` | سبک | choice | pop | pop / box / karaoke / clean |
| `lines` | خط‌ها (اختیاری) | list |  |  |

### `caption_style` — سبکِ زیرنویس‌ها

Re-style every caption line at once (look and vertical position, kept clear of the platform UI).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `style` | سبک | choice | pop | pop / box / karaoke / clean |
| `y` | جای عمودی | num |  | 0.3 … 0.95 |

### `end_card` — کارتِ پایانی

Close the video with a full-frame call-to-action card.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `text` | متنِ اصلی | text | همین حالا سفارش بده |  |
| `text2` | زیرعنوان | text |  |  |
| `duration` | مدت | num | 2.5 | 1.5 … 6 ث |
| `bg` | رنگِ زمینه | text | #0f172a |  |
| `accent` | رنگِ تأکید | text | #ffd400 |  |

## تصویر

### `color_look` — رنگ و حال‌وهوا

Apply a colour look (cinematic, vivid, warm…) to clips.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |
| `look` | حال‌وهوا | choice | vivid | cinematic / warm_vintage / faded_film / bw / bw_contrast / cool_blue / vivid / moody / golden_hour / matte / cross_process / pastel / sepia / neon_night / fresh_food |
| `amount` | شدت | num | 60 | 0 … 100 ٪ |

### `crop` — برشِ لبه‌ها

Crop the edges of a clip (fractions 0-0.9 of each side; the edge becomes transparent).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `l` | چپ | num | 0 | 0 … 0.9 |
| `r` | راست | num | 0 | 0 … 0.9 |
| `t` | بالا | num | 0 | 0 … 0.9 |
| `b` | پایین | num | 0 | 0 … 0.9 |

### `reframe` — بازتنظیمِ قاب (۹:۱۶ خودکار)

Reframe a clip to an aspect, following the subject (faces/motion).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `aspect` | نسبت | text | 9:16 |  |
| `follow` | دنبالِ سوژه | choice | auto | auto / center |
| `zoom` | زوم | num | 1 | 1 … 2 |

### `zoom` — زومِ آرام

Slow push-in or pull-out on a clip (animated scale).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `from_scale` | از اندازه | num | 1 | 0.5 … 3 |
| `to_scale` | تا اندازه | num | 1.12 | 0.5 … 3 |
| `easing` | نرمی | choice | ease_in_out | linear / ease_in / ease_out / ease_in_out |

### `punch_in` — زومِ پرشی (جامپ‌کات)

Jump-cut punch-in: every n-th clip of the main track is scaled up a little (hides cuts, adds energy).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `every` | هر چندمین قطعه | int | 2 | 2 … 6 |
| `scale` | اندازه | num | 1.12 | 1.03 … 1.5 |

### `sticker` — استیکر

Place a built-in sticker (badge or emoji) over the picture.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `key` | استیکر (لازم) | text |  |  |
| `at` | زمان | num | 0.5 | 0 … 86400 ث |
| `duration` | مدت | num | 2 | 0.5 … 20 ث |
| `x` | جای افقی | num | 0.62 | 0 … 0.95 |
| `y` | جای عمودی | num | 0.12 | 0 … 0.95 |
| `width` | پهنا | num | 0.26 | 0.05 … 0.9 |

### `shape` — شکل

Draw a shape (badge background, burst, bar) over the picture.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `kind` | شکل | choice | rounded | rect / rounded / ellipse / triangle / star / polygon / heart / arrow / burst |
| `fill` | رنگ | text | #ef4444 |  |
| `at` | زمان | num | 0 | 0 … 86400 ث |
| `duration` | مدت | num | 2 | 0.3 … 30 ث |
| `x` | جای افقی | num | 0.3 | 0 … 0.95 |
| `y` | جای عمودی | num | 0.4 | 0 … 0.95 |
| `width` | پهنا | num | 0.4 | 0.05 … 1 |
| `height` | ارتفاع | num | 0.12 | 0.03 … 1 |
| `id` | نشانی | text |  |  |

### `overlay_image` — لوگو / عکسِ روی تصویر

Pin a logo or product photo to a corner for a while (inside the platform safe zone).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `ref` | منبع (لازم) | ref |  |  |
| `corner` | گوشه | choice | tr | tr / tl / br / bl |
| `size` | اندازه | num | 0.2 | 0.08 … 0.6 |
| `at` | زمان | num | 0 | 0 … 86400 ث |
| `duration` | مدت | text | all |  |

## صدا

### `add_music` — موسیقیِ پس‌زمینه

Put background music under the whole video (looped/trimmed, fade-out, ducked under speech).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `ref` | موسیقی | ref |  |  |
| `query` | جست‌وجو | text |  |  |
| `volume_db` | بلندی | num | -18 | -30 … 0 dB |
| `duck` | کم‌شدن زیرِ گفتار | bool | True |  |
| `fade_out` | محوِ پایان | num | 2 | 0 … 6 ث |
| `start` | از ثانیهٔ آهنگ | num | 0 | 0 … 3600 ث |
| `id` | نشانی | text |  |  |

### `ducking` — کم‌شدنِ موسیقی زیرِ گفتار

Turn music ducking under speech on/off.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `on` | روشن | bool | True |  |
| `amount_db` | مقدار | num | 12 | 3 … 30 dB |

### `set_loudness` — بلندیِ استانداردِ شبکه‌ها

Normalise the final mix for social media (about -14 LUFS, true-peak -1 dB).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `on` | روشن | bool | True |  |
| `target` | هدف (LUFS) | num | -14 | -24 … -8 LUFS |
| `tp` | سقفِ اوج | num | -1 | -3 … 0 dB |

### `clean_voice` — صدای تمیز

Denoise (RNNoise) and polish speech clips.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |
| `level` | شدت | choice | light | light / strong |

### `remove_silence` — حذفِ سکوت‌ها

Cut the silent pauses out of speech clips (ripple on their own tracks).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |
| `min_silence` | کمترین سکوت | num | 0.6 | 0.3 … 3 ث |
| `keep` | نگه‌داشتنِ مکث | num | 0.15 | 0 … 0.5 ث |

### `remove_fillers` — حذفِ «اِم و اوم»

Cut hesitation sounds (um/uh/ام/اوم) out of speech using the transcript; soft fillers only on request.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |
| `include_soft` | «خب، یعنی، ببین» هم | bool | False |  |
| `min_len` | کمترین طولِ صدا | num | 0.12 | 0.05 … 1 ث |

### `add_voiceover` — گویندگی

Add a voice-over: an audio asset, or text turned into speech (needs a TTS engine).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `ref` | صدا | ref |  |  |
| `text` | متن (برای ساختِ گفتار) | text |  |  |
| `voice` | صدای گوینده | text |  |  |
| `at` | زمان | num | 0 | 0 … 86400 ث |

### `add_sfx` — جلوهٔ صوتی

Place a sound effect at a time.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `ref` | صدا (لازم) | ref |  |  |
| `at` | زمان (لازم) | num |  | 0 … 86400 ث |
| `volume_db` | بلندی | num | -10 | -40 … 6 dB |

### `clip_volume` — بلندیِ قطعه

Set a clip's volume in dB (0 = unchanged, -60 = silent).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `db` | بلندی (لازم) | num |  | -60 … 9.5 dB |

### `fade` — محو شدن

Fade a clip in and/or out (seconds).

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه (لازم) | clip |  |  |
| `fade_in` | محوِ ابتدا | num | 0 | 0 … 10 ث |
| `fade_out` | محوِ انتها | num | 0 | 0 … 10 ث |

### `auto_mix` — تنظیمِ خودکارِ میکس

Balance levels so speech is clearly above music; duck music; social loudness.

### `mark_beats` — نشانگرِ ضرب‌ها

Drop beat markers for a music clip (or ref) on the timeline.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `music` | موسیقی (قطعه یا منبع) (لازم) | clip |  |  |

## تدوینِ خودکارِ حرفه‌ای (دستورِ «polish»)

ابزارهای تازه‌ای که تدوینِ خودکارِ یک ویدیوی گفتاری می‌سازند؛ شرح و دلیل‌ها: `docs/editors/autoedit-fa.md`.

### `crop_content` — بریدنِ نوارهای سیاه

Cut away the black bars around the real picture (a phone screen recorded inside a landscape frame, a 4:3 clip in 16:9) so the picture fills the frame; a portrait picture is shown whole (no further crop). Does nothing when there are no bars.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |

### `split_shots` — جداکردنِ نماها

Cut a clip where the picture changes shot (a camera shot, then a screen recording, then the camera again) so light, colour and framing are decided per shot. Nothing is removed and no gap is made.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | main |  |
| `sensitivity` | حساسیت | choice | normal | low / normal / high |

### `smart_cuts` — برشِ هوشمندِ مکث‌ها

Cut dead air and tighten short pauses, but keep the pauses a script may intend (after a question, a punchy phrase, a slide change). Cuts land between words. Doubtful pauses are asked in the panel and the owner's remembered answers are applied.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |

### `remove_retakes` — حذفِ دوباره‌گویی‌ها

Cut an earlier try at a sentence when the speaker stumbles and says it again: the words show the same opening twice, the LAST take stays. Conservative: a single repeated word or a repeat further than a few seconds away is emphasis, not a retake.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |

### `auto_look` — نور و رنگِ خودکار

Fix exposure, contrast, highlights, white balance, noise and sharpness of each clip from measurements (skin-tone safe). Leaves a correct shot alone; the owner's own slider values win.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `clip` | قطعه | clip | all |  |

### `background` — پس‌زمینه (نگه‌دار / محو / جایگزین)

Keep, blur or replace the background behind the speaker/subject. The subject is cut out by the processing server's GPU (video matting); a long clip is cut into pieces. 'keep' changes nothing.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `mode` | حالت | choice | blur | keep / blur / color / image |
| `amount` | شدتِ محو | num | 70 | 10 … 100 |
| `color` | رنگِ ساده | text | #0f172a |  |
| `ref` | عکسِ پس‌زمینه | ref |  |  |
| `clip` | قطعه | clip | main |  |

### `pick_music` — موسیقیِ مناسبِ ویدیو

Pick background music from the library by the video's mood, tempo and energy (calm under a talking person, driving for a fast sale), then lay it under the whole video.

| پارامتر | معنی | نوع | پیش‌فرض | بازه یا گزینه‌ها |
|---|---|---|---|---|
| `mood` | حال‌وهوا | choice | auto | auto / calm / warm / happy / energetic / inspiring / dramatic |
| `volume_db` | بلندی | num | -18 | -30 … 0 dB |
| `duck` | کم‌شدن زیرِ گفتار | bool | True |  |

## قالب‌ها (Recipes)

- **معرفیِ محصول** (`product_showcase`): نماهای پرجذبه، تیتر، موسیقی و دعوت به خرید
- **جعبه‌گشایی** (`unboxing`): ترتیبِ فیلم حفظ می‌شود؛ سکوت‌ها حذف، زیرنویس و زومِ کوچک
- **قبل و بعد** (`before_after`): دو نما با برچسبِ «قبل» و «بعد» و گذارِ پاک‌کننده
- **حراج و تخفیف** (`sale`): برچسبِ درشتِ تخفیف، برش‌های تند و کارتِ پایانی
- **نظرِ مشتری** (`testimonial`): حرفِ مشتری بدون مکث، زیرنویسِ درشت و نامِ گوینده
- **اسلایدشوی عکس** (`slideshow`): عکس‌ها با حرکتِ آرام، گذارِ نرم و موسیقی
- **ویدیوی گفتاری — تدوینِ حرفه‌ای** (`polish`): کلِ ویدیو به ترتیبِ خودتان؛ مکثِ بی‌دلیل کوتاه (مکثِ عمدی می‌ماند و مبهم پرسیده می‌شود)، دوباره‌گویی و «اِم و اوم» حذف، نور و رنگ، قابِ دنبالِ چهره، زیرنویس، موسیقیِ هم‌خوان و صدای ‎−۱۴ LUFS

## نسخه‌ها (Variants)

- `a` — تند و ضرب‌دار: ریتم fast، زیرنویس «درشت و پرانرژی»، گذار برش ساده، حرکت punch
- `b` — آرام و حرفه‌ای: ریتم slow، زیرنویس «ساده و تمیز»، گذار crossfade، حرکت push
- `c` — پرتأکید و جذاب: ریتم normal، زیرنویس «کارائوکه (هایلایت)»، گذار slideleft، حرکت push

## پلتفرم‌ها

- `reels` — ریلز اینستاگرام: قابِ reel، هدفِ 22 ثانیه، تا 60 ثانیه
- `story` — استوری: قابِ reel، هدفِ 12 ثانیه، تا 15 ثانیه
- `tiktok` — تیک‌تاک: قابِ reel، هدفِ 24 ثانیه، تا 60 ثانیه
- `shorts` — شورتسِ یوتیوب: قابِ reel، هدفِ 24 ثانیه، تا 60 ثانیه
- `feed` — پستِ اینستاگرام: قابِ feed، هدفِ 20 ثانیه، تا 60 ثانیه
- `square` — پستِ مربع: قابِ square، هدفِ 20 ثانیه، تا 60 ثانیه
- `youtube` — یوتیوب / آپارات: قابِ wide، هدفِ 45 ثانیه، تا 180 ثانیه

## سبک‌های زیرنویس فارسی

- `pop` — درشت و پرانرژی
- `box` — کادرِ تیره
- `karaoke` — کارائوکه (هایلایت)
- `clean` — ساده و تمیز
