# -*- coding: utf-8 -*-
"""Site builder style picker, fixes of the review of 2026-11-13.

* «برگرداندن» (Ctrl+Z) never undid a style: the theme is not in the document history. The theme before the FIRST style is now kept in
  `style_prev` and «برگرداندنِ پوسته به پیش از سبک» (`style/apply/` with `restore: true`) puts colours, fonts, button and radius back;
* «رنگِ اصلیِ برندم همان بماند» kept the CURRENT primary, i.e. the colour of the style applied before - the brand colour was lost on the second try.
"""
from apps.projects.builder import styles as S, theme as T
from apps.projects.models import Project
from apps.projects.tests_builder import API, Base

BRAND = '#126f85'
#: three styles whose own primary is not the brand colour (so «the style changed the colour» is visible)
OTHER = [k for k in S.ORDER if S.STYLES[k]['theme']['colors']['primary'].lower() != BRAND][:3]
A, B, C = OTHER


def brand_theme(**extra):
    th = T.default_theme()
    th['colors']['primary'] = BRAND
    th.update(extra)
    return T.clean_theme(th)


class SnapshotTests(Base):
    def test_the_first_style_keeps_the_original_theme(self):
        th = brand_theme(radius=26)
        out = S.apply_to_theme(th, A)
        self.assertEqual(out['style_prev']['colors']['primary'], BRAND)
        self.assertEqual(out['style_prev']['radius'], 26)
        self.assertEqual(out['style_prev']['font_head'], th['font_head'])
        self.assertNotEqual(out['colors']['primary'], BRAND)             # the style really changed it

    def test_a_second_style_does_not_overwrite_the_snapshot(self):
        a, b = A, B
        first = T.clean_theme(S.apply_to_theme(brand_theme(), a))
        second = T.clean_theme(S.apply_to_theme(first, b))
        self.assertEqual(second['style'], b)
        self.assertEqual(second['style_prev']['colors']['primary'], BRAND, 'the second style replaced the ORIGINAL theme with the first style')

    def test_the_snapshot_survives_the_theme_round_trip_but_not_without_a_style(self):
        styled = T.clean_theme(S.apply_to_theme(brand_theme(), C))
        self.assertIn('style_prev', styled)
        self.assertEqual(T.clean_theme(styled)['style_prev']['colors']['primary'], BRAND)
        plain = dict(styled)
        plain.pop('style')
        self.assertNotIn('style_prev', T.clean_theme(plain), 'a stale snapshot must not outlive the style')

    def test_restore_puts_colours_fonts_button_and_radius_back_and_drops_the_style(self):
        base = brand_theme(radius=26, button='soft')
        styled = T.clean_theme(S.apply_to_theme(base, A))
        back = T.clean_theme(S.restore_theme(styled))
        self.assertNotIn('style', back)
        self.assertNotIn('style_prev', back)
        self.assertNotIn('style_keep', back)
        for key in ('colors', 'font_head', 'font_body', 'button', 'radius', 'width'):
            self.assertEqual(back[key], base[key], key)

    def test_restore_without_a_snapshot_is_none(self):
        self.assertIsNone(S.restore_theme(brand_theme()))
        legacy = brand_theme()
        legacy['style'] = C                                       # a style applied before the snapshot existed
        self.assertIsNone(S.restore_theme(legacy))


class KeepBrandTests(Base):
    def test_keep_brand_keeps_the_brand_not_the_previous_styles_colour(self):
        first = T.clean_theme(S.apply_to_theme(brand_theme(), A))            # tried without the tick: primary is now the style's
        self.assertNotEqual(first['colors']['primary'], BRAND)
        second = T.clean_theme(S.apply_to_theme(first, B, keep_brand=True))
        self.assertEqual(second['colors']['primary'], BRAND, 'the tick kept the previous style colour instead of the brand colour')
        self.assertTrue(second.get('style_keep'))

    def test_keep_brand_on_the_first_style_uses_the_current_primary(self):
        out = T.clean_theme(S.apply_to_theme(brand_theme(), A, keep_brand=True))
        self.assertEqual(out['colors']['primary'], BRAND)

    def test_a_legacy_styled_theme_falls_back_to_the_projects_brand_colour(self):
        legacy = brand_theme()
        legacy.update(S.apply_to_theme(legacy, A))
        legacy.pop('style_prev')                                          # applied before the snapshot existed
        out = S.apply_to_theme(legacy, B, keep_brand=True, project_brand='#126F85')
        self.assertEqual(out['colors']['primary'], '#126f85')
        self.assertIn(out['colors']['on_primary'], ('#ffffff', '#111827'))

    def test_on_primary_is_readable_on_a_light_or_a_dark_brand_colour(self):
        self.assertEqual(S._on_color('#f5d90a'), '#111827')
        self.assertEqual(S._on_color('#126f85'), '#ffffff')
        self.assertEqual(S._on_color('nonsense'), '#ffffff')


class StyleApplyApiTests(Base):
    def post(self, p, body):
        return self.c.post(API % p.slug + 'style/apply/', body, format='json')

    def test_the_whole_try_a_style_and_go_back_flow(self):
        p = self.project('sr1')
        p.brand_color = BRAND.upper()
        p.save()
        theme = brand_theme(radius=26)
        r = self.post(p, {'style': A, 'theme': theme})
        self.assertEqual(r.status_code, 200, r.content)
        styled = r.json()['theme']
        self.assertEqual(styled['style'], A)
        self.assertEqual(styled['style_prev']['colors']['primary'], BRAND)
        # a second try with «keep the brand colour»: the brand, not the first style's colour
        r = self.post(p, {'style': B, 'theme': styled, 'keep_brand': True})
        again = r.json()['theme']
        self.assertEqual(again['colors']['primary'], BRAND)
        self.assertEqual(again['style_prev']['colors']['primary'], BRAND)
        # restore: the original theme, no style
        r = self.post(p, {'restore': True, 'theme': again})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['restored'])
        for key in ('colors', 'radius', 'font_head', 'font_body', 'button'):
            self.assertEqual(body['theme'][key], theme[key], key)
        self.assertNotIn('style', body['theme'])
        self.assertNotIn('style_prev', body['theme'])

    def test_restore_without_a_snapshot_says_so_in_persian(self):
        p = self.project('sr2')
        r = self.post(p, {'restore': True, 'theme': brand_theme()})
        self.assertEqual(r.status_code, 400)
        self.assertIn('پیش از سبک', str(r.json()['error']))

    def test_removing_the_style_layer_also_drops_the_snapshot_and_keeps_the_colours(self):
        p = self.project('sr3')
        styled = self.post(p, {'style': A, 'theme': brand_theme()}).json()['theme']
        r = self.post(p, {'style': '', 'theme': styled})
        out = r.json()['theme']
        self.assertNotIn('style', out)
        self.assertNotIn('style_prev', out)
        self.assertEqual(out['colors'], styled['colors'])                  # «برداشتنِ لایهٔ سبک»: colours and fonts stay

    def test_the_theme_row_keeps_the_snapshot_across_a_reload(self):
        p = self.project('sr4')
        styled = self.post(p, {'style': A, 'theme': brand_theme()}).json()['theme']
        self.assertEqual(self.c.put(API % p.slug + 'theme/', {'theme': styled}, format='json').status_code, 200)
        got = self.c.get(API % p.slug + 'theme/').json()['theme']
        self.assertEqual(got['style'], A)
        self.assertEqual(got['style_prev']['colors']['primary'], BRAND)
        r = self.post(p, {'restore': True, 'theme': got})
        self.assertEqual(r.json()['theme']['colors']['primary'], BRAND)
