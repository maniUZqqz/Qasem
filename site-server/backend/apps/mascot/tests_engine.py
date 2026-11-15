"""موتورِ ماسکوت: هویت به‌صورتِ داده، ۲۹ ژست، ۸ حالت، ۱۷ پس‌زمینه، ۴ اندازه، استیکر، برگهٔ مدل، کلیدِ رنگ، نگهبانِ ادعا.

SOURCE of the cases: ported from InstAI (maniUZqqz/Instai) tests/test_stick_kit.py @ 82733b0 (spec normalisation and identity words, poses/scenes/expressions
catalogue, deterministic still, the same colours in every pose/scene/expression and a wrongly coloured character is flagged, backgrounds from words, the model
sheet and its Persian labels), adapted to NMarketing (brand roles, sizes, sticker, chest logo, captions, the thumbnail maker's text engine).
"""
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

from . import selftest
from .engine import brand as B
from .engine import compose, copy_guard, parts, poses, qa, scenes, stage, text
from .engine import spec as S

CHAGHER = ["#126F85", "#163F75"]
HERO = {"name": "رامین", "limb_colour": "#2f7fd1", "neck": "scarf", "neck_colour": "#d94a3d", "hat": "cap", "hat_colour": "#e8a22b"}


def coach(logo: bool = False) -> dict:
    return B.spec_from_brand("coach", CHAGHER, "مربی چغر", logo=logo)


# ------------------------------------------------------------------ the spec: identity as data

class SpecTests(SimpleTestCase):
    def test_spec_is_normalised_and_gives_identity_words_and_colour_key(self):
        s = S.normalize({"limb_colour": "#2F7FD1", "hat": "cap", "hat_colour": "#e8a22b", "neck": "scarf", "neck_colour": "#d94a3d", "bogus": 1, "line_width": 99}, name="رامین")
        self.assertNotIn("bogus", s)
        self.assertEqual((s["line_width"], s["limb_colour"]), (26, "#2f7fd1"))
        self.assertTrue({"limbs", "head", "outline", "hat", "neck"} <= {p["role"] for p in S.palette(s)})
        anchor = S.anchor_text(s)
        self.assertIn("blue-limbed stick figure", anchor)
        self.assertIn("amber cap", anchor)
        self.assertIn("red scarf", anchor)
        self.assertEqual(S.spec_hash(s), S.spec_hash(dict(s)))
        self.assertNotEqual(S.spec_hash(s), S.spec_hash({**s, "hat": "none"}))
        a, b = S.normalize({}, name="رامین"), S.normalize({}, name="نگهبان")
        self.assertTrue(a["limb_colour"] != b["limb_colour"] or a["neck"] != b["neck"])     # دو شخصیتِ یک فروشگاه یکسان درنمی‌آیند
        self.assertEqual(S.normalize({}, name="رامین"), S.normalize({}, name="رامین"))      # و ظاهرِ هر نام ثابت است

    def test_catalogue_matches_the_brief(self):
        self.assertEqual(len(S.EXPRESSIONS), 8)
        self.assertEqual(len(poses.ORIGINAL_24), 24)
        self.assertEqual(list(poses.POSES)[:24], list(poses.ORIGINAL_24))
        self.assertGreaterEqual(len(poses.POSES), 29)
        self.assertEqual(len(scenes.BACKGROUNDS), 17)                                     # ۱۳ صحنهٔ InstAI + ۴ صحنهٔ بازاریابی
        self.assertEqual(set(scenes.marketing_keys()), {"counter", "gym", "kitchen", "brand"})
        self.assertEqual(set(compose.SIZES), {"ig_portrait", "ig_square", "story", "wide"})
        self.assertEqual({k: (v["w"], v["h"]) for k, v in compose.SIZES.items()},
                         {"ig_portrait": (1080, 1350), "ig_square": (1080, 1080), "story": (1080, 1920), "wide": (1920, 1080)})
        for p in poses.POSES:
            self.assertIn(p, poses.POSE_LABELS)
        for tag in ("explain", "point", "thumbs_up", "thinking", "cheer", "warn", "exercise"):   # برچسب‌های بازاریابیِ خواسته‌شده
            self.assertTrue(poses.MARKETING_TAGS[tag]["poses"], tag)
            for p in poses.MARKETING_TAGS[tag]["poses"]:
                self.assertIn(p, poses.POSES)

    def test_rig_has_every_part_the_poses_move(self):
        rig = parts.build_rig(S.normalize({}, name="x"))
        rig.validate()
        self.assertTrue({"body", "head", "arm_l", "arm_r", "leg_l", "leg_r", "forearm_r", "shin_l", "thumb"} <= set(rig.parts))
        self.assertEqual(sorted(rig.groups()["mouth"]), sorted("ABCDEFGHX"))
        for name, pose in poses.POSES.items():
            for part in pose:
                self.assertIn(part, rig.parts, (name, part))

    def test_every_choice_can_be_drawn(self):
        """هر کلاه، مو، گردن‌آویز، وسیلهٔ اضافه و وسیله کشیده می‌شود (ردِ هر کدام یک قابِ خالی نمی‌دهد)."""
        base = coach()
        for key, options in S.CHOICES.items():
            for opt in options:
                s = S.normalize({**base, key: opt})
                shot = stage.render_actor({"spec": s, "pose": "hold", "x": 0.5, "y": 0.95, "height": 0.9}, 320, 400, logo=selftest.synthetic_logo() if key == "logo" else None)
                self.assertIsNotNone(shot.bbox, (key, opt))


# ------------------------------------------------------------------ pictures

class StillTests(SimpleTestCase):
    def test_still_has_the_right_size_and_is_deterministic(self):
        scene = {"size": "ig_portrait", "background": "gym", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "run_a", "expression": "scared"}],
                 "caption": {"text": "پیش‌نویسِ برنامه", "position": "bottom"}, "bubbles": [{"actor": 0, "text": "الان چه کار کنم؟", "kind": "think"}]}
        a, _ = compose.compose_still(scene)
        b, _ = compose.compose_still(scene)
        self.assertEqual(a.size, (1080, 1350))
        self.assertEqual(a.tobytes(), b.tobytes())                                          # همان صحنه، همان پیکسل

    def test_the_same_character_in_four_sizes_and_every_pose_keeps_the_colour_key(self):
        pal = S.palette(coach())
        logo = selftest.synthetic_logo()
        spec = coach(logo=True)
        for size in compose.SIZES:
            w, h = selftest.canvas_for(size)
            for pose in poses.POSES:
                shot = compose.figure_layer({"spec": spec, "pose": pose, "expression": "happy", **compose.actor_defaults(size)}, w, h, logo=logo, inside=0.02)
                res = qa.check_figure(shot.layer, pal)
                self.assertTrue(res["ok"], (size, pose, res["notes"]))
        self.assertEqual({(s["w"], s["h"]) for s in compose.SIZES.values()}, {(1080, 1350), (1080, 1080), (1080, 1920), (1920, 1080)})

    def test_every_size_has_exact_pixels_and_every_background_renders(self):
        for size, d in compose.SIZES.items():
            img, info = compose.compose_still({"size": size, "background": "brand", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "wave"}]})
            self.assertEqual(img.size, (d["w"], d["h"]), size)
            self.assertEqual(info["size"], [d["w"], d["h"]])
        for key in scenes.keys():
            im = scenes.draw(key, 270, 340, CHAGHER)
            self.assertEqual(im.size, (270, 340))
            self.assertGreaterEqual(len(im.getcolors(maxcolors=100000) or [0] * 100000), 4, key)    # بوم خالی نیست

    def test_marketing_backgrounds_use_the_brand_colours(self):
        a = scenes.draw("brand", 200, 250, ["#126F85", "#163F75"]).tobytes()
        b = scenes.draw("brand", 200, 250, ["#d94a3d", "#7a1f1a"]).tobytes()
        self.assertNotEqual(a, b)
        self.assertEqual(a, scenes.draw("brand", 200, 250, ["#126F85", "#163F75"]).tobytes())

    def test_a_wrongly_coloured_character_is_flagged(self):
        pal = S.palette(coach())
        other = {**coach(), "limb_colour": "#2e9e5b", "hat_colour": "#8a4fd1", "prop_colour": "#2e9e5b"}      # (وسیله هم‌رنگِ هدبندِ اصلی نماند)
        shot = compose.figure_layer({"spec": other, "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9}, 400, 500)
        bad = qa.check_figure(shot.layer, pal)
        self.assertFalse(bad["ok"])
        self.assertEqual({n["code"] for n in bad["notes"]}, {"colour_missing"})
        good = qa.check_figure(compose.figure_layer({"spec": coach(), "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9}, 400, 500).layer, pal)
        self.assertTrue(good["ok"] and good["palette_score"] == 1.0)

    def test_a_background_of_the_same_colour_cannot_hide_a_missing_colour(self):
        """نسخهٔ InstAI این را «محدودیت» می‌دانست (پس‌زمینهٔ هم‌رنگ می‌تواند رنگِ گمشده را پنهان کند)؛ این‌جا بررسی روی لایهٔ خودِ شخصیت است."""
        pal = S.palette(coach())
        other = {**coach(), "hat_colour": "#8a4fd1", "prop_colour": "#8a4fd1"}            # کلاه بنفش به‌جای فیروزه‌ای
        img, info = compose.compose_still({"size": "ig_square", "background": "brand", "brand": CHAGHER, "actors": [{"spec": other, "pose": "stand"}]}, keep_shots=True)
        self.assertFalse(qa.check_figure(info["shots"][0].layer, pal)["ok"])

    def test_empty_frame_is_flagged(self):
        res = qa.check_figure(Image.new("RGBA", (200, 200), (0, 0, 0, 0)), S.palette(coach()))
        self.assertFalse(res["ok"])
        self.assertIn("figure_blank", {n["code"] for n in res["notes"]})

    def test_lying_down_stays_inside_the_frame(self):
        img, info = compose.compose_still({"size": "ig_square", "background": "brand", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "lying"}]})
        x0, y0, x1, y1 = info["figure_bbox"][0]
        self.assertTrue(x0 >= 0 and y0 >= 0 and x1 <= 1080 and y1 <= 1080, info["figure_bbox"])

    def test_caption_does_not_cover_the_character(self):
        img, info = compose.compose_still({"size": "ig_portrait", "background": "gym", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "stand"}],
                                           "caption": {"text": "پیش‌نویسِ برنامه در کمتر از یک دقیقه", "position": "bottom"}})
        self.assertLessEqual(info["figure_bbox"][0][3], info["caption"][1])              # پای شخصیت بالای نوارِ کپشن است

    def test_story_keeps_text_and_caption_out_of_the_platform_zones(self):
        img, info = compose.compose_still({"size": "story", "background": "counter", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "thumbs_up"}],
                                           "bubbles": [{"actor": 0, "text": "با چغر چغر تر شو", "kind": "say"}], "caption": {"text": "یک قدمِ کوچک", "position": "top"}})
        h = 1920
        self.assertGreaterEqual(info["caption"][1], int(0.13 * h) - 1)                    # زیرِ ۱۳٪ِ بالای استوری
        self.assertGreaterEqual(info["bubbles"][0]["box"][1], info["caption"][3])         # حباب زیرِ کپشنِ بالا
        self.assertLessEqual(info["figure_bbox"][0][3], int(0.82 * h) + 2)               # پای شخصیت بالای ۱۸٪ِ پایین
        img2, info2 = compose.compose_still({"size": "story", "background": "counter", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "stand"}],
                                             "caption": {"text": "یک قدمِ کوچک", "position": "bottom"}})
        self.assertLessEqual(info2["caption"][3], int(0.82 * h) + 2)

    def test_props_follow_the_pose(self):
        spec = coach()
        _, a = compose.compose_still({"size": "ig_square", "actors": [{"spec": spec, "pose": "thumbs_up"}]})
        _, b = compose.compose_still({"size": "ig_square", "actors": [{"spec": spec, "pose": "stand"}]})
        _, c = compose.compose_still({"size": "ig_square", "actors": [{"spec": spec, "pose": "curl"}]})
        _, d = compose.compose_still({"size": "ig_square", "actors": [{"spec": spec, "pose": "lift"}]})
        _, e = compose.compose_still({"size": "ig_square", "actors": [{"spec": spec, "pose": "stand", "prop": "none"}]})
        self.assertEqual((a["props"], b["props"], c["props"], d["props"], e["props"]), (["none"], ["clipboard"], ["dumbbell"], ["barbell"], ["none"]))

    def test_logo_sits_on_the_chest_and_is_never_mirrored(self):
        logo = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        logo.paste((220, 30, 30, 255), (0, 0, 50, 100))                                   # چپ قرمز
        logo.paste((30, 30, 220, 255), (50, 0, 100, 100))                                 # راست آبی
        spec = {**coach(logo=True), "limb_colour": "#2e2e2e"}

        def centers(flip):
            shot = stage.render_actor({"spec": spec, "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9, "flip": flip, "shadow": False, "prop": "none"}, 600, 760, logo=logo)
            px = shot.layer.convert("RGB")
            red, blue = [], []
            for y in range(shot.bbox[1], shot.bbox[3]):
                for x in range(shot.bbox[0], shot.bbox[2]):
                    r, g, b = px.getpixel((x, y))
                    if r > 190 and g < 70 and b < 70:
                        red.append(x)
                    elif b > 190 and r < 70 and g < 70:
                        blue.append(x)
            return (sum(red) / len(red), sum(blue) / len(blue)) if red and blue else None

        for flip in (False, True):
            c = centers(flip)
            self.assertIsNotNone(c, flip)
            self.assertLess(c[0], c[1], f"the logo is mirrored (flip={flip})")
        plain = stage.render_actor({"spec": coach(logo=False), "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9, "shadow": False}, 600, 760)
        with_logo = stage.render_actor({"spec": coach(logo=True), "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9, "shadow": False}, 600, 760, logo=logo)
        self.assertNotEqual(plain.layer.tobytes(), with_logo.layer.tobytes())

    def test_a_held_prop_does_not_cover_the_chest_logo(self):
        """وسیلهٔ دست (برگهٔ برنامه) جلوی شخصیت می‌ایستد؛ لوگوی روی سینه در ژستِ ایستاده دیده می‌شود."""
        logo = Image.new("RGBA", (100, 100), (220, 30, 30, 255))
        spec = {**coach(logo=True), "limb_colour": "#2e2e2e"}
        with_prop = stage.render_actor({"spec": spec, "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9, "shadow": False}, 600, 760, logo=logo)
        self.assertEqual(with_prop.prop, "clipboard")
        px = with_prop.layer.convert("RGB")
        red = sum(1 for y in range(with_prop.bbox[1], with_prop.bbox[3]) for x in range(with_prop.bbox[0], with_prop.bbox[2])
                  if px.getpixel((x, y))[0] > 190 and px.getpixel((x, y))[1] < 70 and px.getpixel((x, y))[2] < 70)
        self.assertGreater(red, 600)                                                      # کاشیِ لوگو (۴۵×۴۵ پیکسل) تقریباً کامل دیده می‌شود

    def test_head_position_follows_the_pose(self):
        a = stage.render_actor({"spec": coach(), "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9}, 600, 760)
        b = stage.render_actor({"spec": coach(), "pose": "squat", "x": 0.5, "y": 0.95, "height": 0.9}, 600, 760)
        self.assertGreater(b.head[1], a.head[1] + 40)                                    # در اسکوات سر پایین‌تر است؛ حباب باید همان‌جا بنشیند


class StickerAndSheetTests(SimpleTestCase):
    def test_sticker_is_transparent_and_tight(self):
        img, info = compose.sticker(coach(), pose="thumbs_up", expression="happy", height_px=700)
        self.assertEqual(img.mode, "RGBA")
        a = img.getchannel("A")
        self.assertEqual(a.getpixel((0, 0)), 0)                                           # گوشه شفاف
        self.assertEqual(a.getpixel((img.width - 1, img.height - 1)), 0)
        self.assertGreater(a.point(lambda v: 255 if v > 200 else 0).getbbox()[2], img.width * 0.5)
        self.assertEqual(info["prop"], "none")                                            # در «شستِ بالا» دست خالی است
        res = qa.check_figure(img, S.palette(coach()))
        self.assertTrue(res["ok"], res["notes"])

    def test_bust_sticker_is_the_upper_part_with_the_same_colours(self):
        full, _ = compose.sticker(coach(), pose="thumbs_up", height_px=700)
        bust, info = compose.sticker(coach(), pose="thumbs_up", height_px=700, crop="bust")
        self.assertEqual(info["crop"], "bust")
        self.assertLess(bust.height, full.height * 0.6)
        self.assertGreater(bust.height, 80)
        self.assertEqual(bust.getchannel("A").getpixel((0, 0)), 0)

    def test_model_sheet_is_drawn(self):
        im = compose.model_sheet(coach(logo=True), title="مربی چغر", store_name="چغر", version=1, logo=selftest.synthetic_logo())
        self.assertEqual(im.size, (2000, 1600))
        self.assertGreater(len(im.convert("RGB").getcolors(maxcolors=300000)), 20)

    def test_a_persian_model_sheet_names_its_roles_colours_and_expressions_in_persian(self):
        """InstAI 0.11.0: the sheet of a Persian series had English labels. The NMarketing sheet is Persian from the start."""
        seen: list[str] = []
        real = text.draw_text

        def spy(canvas, txt, *a, **k):
            seen.append(txt)
            return real(canvas, txt, *a, **k)

        with mock.patch.object(text, "draw_text", spy):
            compose.model_sheet(coach(), title="مربی چغر", store_name="چغر", version=2)
        joined = " | ".join(seen)
        self.assertNotIn("MODEL SHEET", joined)
        for en in ("neutral", "happy", "limbs", "Front view"):
            self.assertNotIn(en, seen)
        for fa in ("خنثی", "شاد", "کلیدِ رنگ", "نمای اصلی", "شستِ بالا"):
            self.assertIn(fa, seen)
        self.assertTrue(any(t.startswith("دست و پا") for t in seen))
        self.assertTrue(any("نسخهٔ ۲" in t for t in seen))

    def test_contact_sheets(self):
        sheet = compose.contact_poses(coach(), ["stand", "wave", "thumbs_up", "curl"], cell=160, cols=2, brand=CHAGHER)
        self.assertEqual(sheet.size[0], 2 * 160 + 3 * 10)
        sizes = compose.contact_sizes(coach(), brand=CHAGHER, txt="سلام!", height=200)
        self.assertEqual(sizes.height, 270)


class TextEngineTests(SimpleTestCase):
    def test_bubble_and_caption_text_come_from_the_thumbnail_makers_engine(self):
        """متنِ حباب و کپشن با تایپوگرافیِ تامنیل‌ساز (raqm روی این سرور) کشیده می‌شود، نه با شکل‌دهندهٔ جدا."""
        from apps.thumbs import typo

        self.assertIs(text.typo(), typo)
        with mock.patch.object(typo, "render_text", wraps=typo.render_text) as spy:
            compose.compose_still({"size": "ig_square", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "wave"}],
                                   "bubbles": [{"actor": 0, "text": "با چغر، *چغر‌تر* شو"}], "caption": {"text": "پیش‌نویس"}})
        self.assertGreaterEqual(spy.call_count, 2)

    def test_bubble_has_ink_and_the_highlight_word_gets_the_brand_colour(self):
        no_text, _ = compose.compose_still({"size": "ig_square", "background": "brand", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "wave"}]})
        with_text, info = compose.compose_still({"size": "ig_square", "background": "brand", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "wave"}],
                                                 "bubbles": [{"actor": 0, "text": "با چغر، *چغر‌تر* شو", "kind": "say"}]})
        self.assertNotEqual(no_text.tobytes(), with_text.tobytes())
        x0, y0, x1, y1 = info["bubbles"][0]["box"]
        crop = with_text.crop((x0, y0, x1, y1)).convert("RGB")
        teal = sum(1 for p in crop.getdata() if abs(p[0] - 0x12) < 30 and abs(p[1] - 0x6f) < 30 and abs(p[2] - 0x85) < 30)
        self.assertGreater(teal, 150)

    def test_the_three_bubble_kinds(self):
        out = []
        for kind in compose.BUBBLE_KINDS:
            img, info = compose.compose_still({"size": "ig_square", "brand": CHAGHER, "actors": [{"spec": coach(), "pose": "think"}], "bubbles": [{"actor": 0, "text": "سؤالی داری؟", "kind": kind}]})
            self.assertIsNotNone(info["bubbles"][0]["box"], kind)
            out.append(img.tobytes())
        self.assertEqual(len(set(out)), 3)


# ------------------------------------------------------------------ roles, brand, guard

class BrandRoleTests(SimpleTestCase):
    def test_five_roles_with_persian_names(self):
        self.assertEqual(set(B.ROLES), {"coach", "shopkeeper", "cook", "courier", "advisor"})
        self.assertEqual({r["fa"] for r in B.ROLES.values()}, {"مربی", "فروشنده", "آشپز", "پیک", "مشاور"})
        for key, r in B.ROLES.items():
            self.assertIn(r["background"], scenes.BACKGROUNDS)
            self.assertIn(r["pose"], poses.POSES)
            for tag in r["tags"]:
                self.assertIn(tag, poses.MARKETING_TAGS)

    def test_chagher_colours_land_on_the_right_parts(self):
        s = coach()
        self.assertEqual(s["hat"], "headband")
        self.assertEqual(s["hat_colour"], "#126f85")                                      # رنگِ اصلیِ برند روی هدبند
        self.assertLess(B._hsl(s["limb_colour"])[2], 0.4)                                 # دست و پا تیره (رنگِ دومِ برند)
        self.assertEqual(S.normalize(s), s)
        self.assertEqual(B.spec_from_brand("coach", CHAGHER, "مربی چغر", logo=True)["logo"], "chest")
        self.assertEqual(B.spec_from_brand("coach", CHAGHER, "مربی چغر")["logo"], "none")

    def test_every_role_is_drawn_with_a_complete_colour_key_for_any_brand(self):
        for colours in (CHAGHER, ["#d94a3d"], [], ["#f4f1ea", "#fafafa"], ["#0b1020", "#0b1020"]):
            for role in B.ROLES:
                spec = B.spec_from_brand(role, colours, "x")
                shot = compose.figure_layer({"spec": spec, "pose": "stand", "x": 0.5, "y": 0.95, "height": 0.9}, 400, 500)
                res = qa.check_figure(shot.layer, S.palette(spec))
                self.assertTrue(res["ok"], (colours, role, res["notes"]))

    def test_roles_look_different(self):
        looks = {key: S.spec_hash(B.spec_from_brand(key, CHAGHER, "x")) for key in B.ROLES}
        self.assertEqual(len(set(looks.values())), 5)


class CopyGuardTests(SimpleTestCase):
    def test_claims_are_found_in_persian_and_english(self):
        cases = {
            "price": ["فقط ۵۰۰ هزار تومان", "قیمت: 600,000 تومان", "$20 only", "تخفیف ۳۰ درصدی"],
            "statistic": ["۹۸٪ رضایت", "بیش از ۵۰۰ مربی", "98% satisfied"],
            "result_claim": ["نتیجه تضمینی", "۱۰ کیلو کم کن", "guaranteed results"],
            "testimonial": ["مشتری‌های ما می‌گویند عالیه", "نظر مشتری: خوب بود"],
            "medical": ["درمان کمردرد", "جایگزین پزشک", "cures back pain"],
            "superlative": ["بهترین برنامه در ایران"],
        }
        for code, texts in cases.items():
            for t in texts:
                self.assertIn(code, {f["code"] for f in copy_guard.check_text(t)}, t)

    def test_the_verified_and_generic_lines_are_clean(self):
        for line in copy_guard.GENERIC_LINES + tuple(t for rows in copy_guard.VERIFIED_LINES.values() for t, _ in rows):
            self.assertEqual(copy_guard.check_text(line), [], line)

    def test_suggested_lines_for_chagher_carry_the_verified_facts_and_their_source(self):
        rows = copy_guard.suggested_lines("چغر")
        texts = [r["text"] for r in rows]
        self.assertIn("با چغر چغر تر شو", texts)
        self.assertIn("پیش‌نویسِ برنامه در کمتر از یک دقیقه", texts)
        self.assertTrue(all(r["source"] != "generic" for r in rows[:4]))
        self.assertTrue(all("brand-facts" in r["source"] for r in rows[:4]))
        other = copy_guard.suggested_lines("فروشگاهِ نمونه")
        self.assertTrue(all(r["source"] == "generic" for r in other))
        self.assertGreaterEqual(len(other), 8)


class SelfTestTests(SimpleTestCase):
    def test_all_poses_in_all_four_sizes_pass_on_the_cpu(self):
        res = selftest.run()
        self.assertTrue(res["ok"], res["failed"][:3])
        self.assertEqual((res["poses"], res["sizes"], res["total"]), (len(poses.POSES), 4, len(poses.POSES) * 4))
