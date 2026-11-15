"""ژست‌های ماسکوت (قابِ ثابت) و برچسب‌های بازاریابیِ هر ژست.

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/stick/poses.py @ 82733b0 (the 24 poses and their Persian/English labels), adapted for
NMarketing brand mascots: the video motions and the puppet-library registration are NOT ported; five poses were added for marketing and
fitness content (thumbs_up, stop, curl, lift, squat) and every pose carries marketing tags (explain, point, thumbs_up, thinking, cheer, warn,
exercise, ...) so a store owner picks "what the character should do" instead of an angle.

زاویه‌ها درجه و ساعت‌گردِ صفحه‌اند و برای شخصیتِ رو به راست؛ برای یک عضوِ آویزان، زاویهٔ منفی آن را به جلو (راست) می‌برد. ``forearm_*``/``shin_*``
نسبت به والدشان (آرنج، زانو) هستند. dx/dy پیکسلِ طراحی‌اند؛ وقتی بدن پایین می‌رود پاها (که قطعهٔ ریشه‌اند) هم باید بروند (``_lower``).
"""
from __future__ import annotations

Pose = dict[str, dict[str, float]]


def _lower(pose: Pose, dy: float) -> Pose:
    for part in ("body", "leg_l", "leg_r"):
        pose.setdefault(part, {})["dy"] = pose.get(part, {}).get("dy", 0) + dy
    return pose


POSES: dict[str, Pose] = {
    "stand": {"leg_l": {"rot": 3}, "leg_r": {"rot": -3}, "arm_l": {"rot": 5}, "arm_r": {"rot": -5}},
    "walk_a": {"leg_l": {"rot": -28}, "shin_l": {"rot": 8}, "leg_r": {"rot": 22}, "shin_r": {"rot": 30}, "arm_l": {"rot": 24}, "forearm_l": {"rot": 14},
               "arm_r": {"rot": -26}, "forearm_r": {"rot": -22}, "body": {"rot": 2}},
    "walk_b": {"leg_l": {"rot": 22}, "shin_l": {"rot": 30}, "leg_r": {"rot": -28}, "shin_r": {"rot": 8}, "arm_l": {"rot": -26}, "forearm_l": {"rot": -22},
               "arm_r": {"rot": 24}, "forearm_r": {"rot": 14}, "body": {"rot": 2}},
    "run_a": {"body": {"rot": 14}, "head": {"rot": -8}, "leg_l": {"rot": -72}, "shin_l": {"rot": 28}, "leg_r": {"rot": 34}, "shin_r": {"rot": 96},
              "arm_l": {"rot": -58}, "forearm_l": {"rot": -86}, "arm_r": {"rot": 52}, "forearm_r": {"rot": -78}},
    "run_b": {"body": {"rot": 14}, "head": {"rot": -8}, "leg_l": {"rot": 34}, "shin_l": {"rot": 96}, "leg_r": {"rot": -72}, "shin_r": {"rot": 28},
              "arm_l": {"rot": 52}, "forearm_l": {"rot": -78}, "arm_r": {"rot": -58}, "forearm_r": {"rot": -86}},
    "wave": {"arm_r": {"rot": -150}, "forearm_r": {"rot": -24}, "head": {"rot": 4}},
    "point_right": {"arm_r": {"rot": -92}, "forearm_r": {"rot": -2}, "body": {"rot": 3}, "head": {"rot": 3}},
    "point_up": {"arm_r": {"rot": -122}, "forearm_r": {"rot": -48}, "head": {"rot": -3}},
    "hands_up": {"arm_l": {"rot": 128}, "forearm_l": {"rot": 38}, "arm_r": {"rot": -128}, "forearm_r": {"rot": -38}},
    "surrender": {"arm_l": {"rot": 108}, "forearm_l": {"rot": 74}, "arm_r": {"rot": -108}, "forearm_r": {"rot": -74}, "head": {"rot": -3}},
    "shrug": {"arm_l": {"rot": 52}, "forearm_l": {"rot": 38}, "arm_r": {"rot": -52}, "forearm_r": {"rot": -38}, "head": {"rot": -5}},
    "think": {"arm_r": {"rot": -30}, "forearm_r": {"rot": -132}, "head": {"rot": 7}, "arm_l": {"rot": 8}},
    "cheer": _lower({"arm_l": {"rot": 128}, "forearm_l": {"rot": 40}, "arm_r": {"rot": -128}, "forearm_r": {"rot": -40}, "leg_l": {"rot": 22}, "leg_r": {"rot": -22},
                     "shin_l": {"rot": 10}, "shin_r": {"rot": -10}}, -34),
    "punch": {"body": {"rot": 12}, "arm_r": {"rot": -84}, "forearm_r": {"rot": -6}, "arm_l": {"rot": 40}, "forearm_l": {"rot": -60}, "leg_l": {"rot": -30},
              "leg_r": {"rot": 24}, "shin_r": {"rot": 20}},
    "kick": {"body": {"rot": -10}, "leg_l": {"rot": -88}, "shin_l": {"rot": 4}, "leg_r": {"rot": 6}, "arm_l": {"rot": 60}, "arm_r": {"rot": -40}},
    "push": {"body": {"rot": 8}, "arm_l": {"rot": -72}, "forearm_l": {"rot": -4}, "arm_r": {"rot": -78}, "forearm_r": {"rot": -2}, "leg_l": {"rot": -24},
             "leg_r": {"rot": 22}, "shin_r": {"rot": 14}},
    "shock": {"body": {"rot": -12}, "head": {"rot": -8}, "arm_l": {"rot": 70}, "forearm_l": {"rot": 46}, "arm_r": {"rot": -58}, "forearm_r": {"rot": -40},
              "leg_l": {"rot": 16}, "leg_r": {"rot": -26}, "shin_r": {"rot": 24}},
    "tired": {"body": {"rot": 14}, "head": {"rot": 14}, "arm_l": {"rot": -8}, "arm_r": {"rot": -14}, "forearm_r": {"rot": -10}, "leg_l": {"rot": -6}, "leg_r": {"rot": 8}},
    "hold": {"arm_r": {"rot": -62}, "forearm_r": {"rot": -30}, "arm_l": {"rot": 8}},
    "crouch": _lower({"body": {"rot": 24, "dx": -70}, "head": {"rot": -14, "dx": -70}, "leg_l": {"rot": -80, "dx": -70}, "shin_l": {"rot": 94}, "leg_r": {"rot": -70, "dx": -70}, "shin_r": {"rot": 88},
                      "arm_l": {"rot": -20}, "forearm_l": {"rot": -64}, "arm_r": {"rot": -34}, "forearm_r": {"rot": -76}}, 136),
    "hide": _lower({"body": {"rot": 30, "dx": -70}, "head": {"rot": 10, "dx": -70}, "leg_l": {"rot": -80, "dx": -70}, "shin_l": {"rot": 94}, "leg_r": {"rot": -70, "dx": -70}, "shin_r": {"rot": 88},
                    "arm_l": {"rot": 125, "dx": 0}, "forearm_l": {"rot": 100}, "arm_r": {"rot": -125}, "forearm_r": {"rot": -100}}, 136),
    "sneak": _lower({"body": {"rot": 16}, "head": {"rot": -8}, "leg_l": {"rot": -40}, "shin_l": {"rot": 62}, "leg_r": {"rot": 14}, "shin_r": {"rot": 38},
                     "arm_l": {"rot": 20}, "forearm_l": {"rot": -40}, "arm_r": {"rot": -34}, "forearm_r": {"rot": -50}}, 52),
    "sit": _lower({"leg_l": {"rot": -88}, "shin_l": {"rot": 86}, "leg_r": {"rot": -90}, "shin_r": {"rot": 90}, "arm_l": {"rot": -20}, "forearm_l": {"rot": -50},
                   "arm_r": {"rot": -24}, "forearm_r": {"rot": -56}}, 158),
    "lying": _lower({"body": {"rot": 88, "dx": -40}, "head": {"rot": 4}, "leg_l": {"rot": 88, "dx": -40}, "leg_r": {"rot": 92, "dx": -40}, "shin_l": {"rot": 4}, "shin_r": {"rot": -2},
                     "arm_l": {"rot": 70}, "forearm_l": {"rot": 10}, "arm_r": {"rot": 110}, "forearm_r": {"rot": 8}}, 300),
    # ---- ژست‌های بازاریابی و ورزشی (تازه در NM)
    "thumbs_up": {"arm_r": {"rot": -52}, "forearm_r": {"rot": -128}, "head": {"rot": -3}, "arm_l": {"rot": 6}},
    "stop": {"arm_r": {"rot": -88}, "forearm_r": {"rot": -88}, "body": {"rot": 3}, "head": {"rot": 2}, "arm_l": {"rot": 6}},
    "curl": {"arm_r": {"rot": -14}, "forearm_r": {"rot": -128}, "arm_l": {"rot": 6}, "head": {"rot": -2}},
    "lift": {"arm_l": {"rot": 150}, "forearm_l": {"rot": 28}, "arm_r": {"rot": -150}, "forearm_r": {"rot": -28}, "leg_l": {"rot": 7}, "leg_r": {"rot": -7}},
    "squat": _lower({"body": {"rot": 10, "dx": -34}, "head": {"rot": -8, "dx": -34}, "leg_l": {"rot": -62, "dx": -34}, "shin_l": {"rot": 76}, "leg_r": {"rot": -56, "dx": -34},
                     "shin_r": {"rot": 72}, "arm_l": {"rot": -84}, "forearm_l": {"rot": -4}, "arm_r": {"rot": -88}, "forearm_r": {"rot": -4}}, 96),
}
POSE_LABELS = {  # fa / en
    "stand": ("ایستاده", "Standing"), "walk_a": ("قدم اول", "Walk A"), "walk_b": ("قدم دوم", "Walk B"), "run_a": ("دویدن ۱", "Run A"), "run_b": ("دویدن ۲", "Run B"),
    "wave": ("دست تکان‌دادن", "Wave"), "point_right": ("اشاره به جلو", "Point ahead"), "point_up": ("اشاره به بالا", "Point up"),
    "hands_up": ("دست‌ها بالا", "Hands up"), "surrender": ("تسلیم", "Surrender"), "shrug": ("شانه بالا", "Shrug"), "think": ("فکر", "Think"),
    "cheer": ("شادی", "Cheer"), "punch": ("مشت", "Punch"), "kick": ("لگد", "Kick"), "push": ("هل‌دادن", "Push"), "shock": ("جا خوردن", "Shock"),
    "tired": ("خسته", "Tired"), "hold": ("نگه‌داشتن چیزی", "Hold an item"), "crouch": ("خم شدن", "Crouch"), "hide": ("پنهان شدن", "Hide"),
    "sneak": ("دزدکی", "Sneak"), "sit": ("نشسته", "Sitting"), "lying": ("روی زمین", "Lying down"),
    "thumbs_up": ("شستِ بالا", "Thumbs up"), "stop": ("وایسا! (هشدار)", "Stop / warning"), "curl": ("جمعِ دمبل", "Dumbbell curl"),
    "lift": ("بالابردنِ هالتر", "Overhead lift"), "squat": ("اسکوات", "Squat"),
}
ORIGINAL_24 = tuple(list(POSES)[:24])           # ۲۴ ژستِ اصلیِ InstAI؛ پنج ژستِ بعدی را NM افزوده است
SHEET_POSES = ("stand", "wave", "point_up", "thumbs_up", "think", "cheer", "stop", "curl")

#: برچسب‌های بازاریابی: «شخصیت چه کار کند؟» ⇒ ژست‌هایی که برایش مناسب‌اند (ترتیب = پیشنهادِ اول)
MARKETING_TAGS: dict[str, dict] = {
    "explain": {"fa": "توضیح‌دادن", "poses": ("point_up", "wave", "hold", "shrug")},
    "point": {"fa": "اشاره", "poses": ("point_right", "point_up")},
    "thumbs_up": {"fa": "تأیید (شستِ بالا)", "poses": ("thumbs_up",)},
    "thinking": {"fa": "فکر و پرسش", "poses": ("think", "shrug")},
    "cheer": {"fa": "شادی و جشن", "poses": ("cheer", "hands_up")},
    "warn": {"fa": "هشدار و دقت", "poses": ("stop", "shock", "surrender")},
    "exercise": {"fa": "ورزش و تمرین", "poses": ("curl", "lift", "squat", "run_a", "run_b", "kick", "punch")},
    "greet": {"fa": "سلام و خوشامد", "poses": ("wave", "stand", "walk_a")},
    "rest": {"fa": "استراحت و آرامش", "poses": ("sit", "tired", "stand")},
}

#: وسیله‌ای که با ژست می‌آید وقتی کاربر «خودکار» بگذارد
PROP_FOR_POSE = {"curl": "dumbbell", "lift": "barbell"}
#: ژست‌هایی که شست را نشان می‌دهند
SHOW_THUMB = {"thumbs_up"}
#: ژست‌هایی که در حالتِ «خودکار» وسیلهٔ دستِ شخصیت را نگه می‌دارند (در ژست‌های اشاره، تأیید، سلام و هشدار دست خالی است)
PROP_POSES = {"stand", "walk_a", "walk_b", "run_a", "run_b", "hold", "sit", "tired", "squat", "curl", "lift"}


def names() -> list[str]:
    return list(POSES)


def tags_of(pose: str) -> list[str]:
    return [k for k, v in MARKETING_TAGS.items() if pose in v["poses"]]


def label_fa(pose: str) -> str:
    return POSE_LABELS.get(pose, (pose, pose))[0]
