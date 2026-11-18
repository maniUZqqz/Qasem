"""«تلفظ»، دورِ پنجم: اضافهٔ خودکار پس از «هر/هیچ/چند»، ستونِ آوا همان است که Piper می‌گیرد، هر واژهٔ مشترک یک بار، «سُبح»، جدولِ ۴×۳ در API و در سند."""
import pathlib

from rest_framework.test import APIClient

from services.audio.fa_pron import dictionary as D, ezafe_gold, phones as P

from . import services as svc
from .tests import Base


def fa_digits(value) -> str:
    return "".join("۰۱۲۳۴۵۶۷۸۹"[int(c)] if c.isdigit() else c for c in str(value))


class PreviewRound5(Base):
    def preview(self, text, depth="lexicon"):
        r = self.api.post(f"{self.base}/preview/", {"text": text, "depth": depth}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_every_day_is_not_linked(self):
        for text, word, bad in (("هر روز صبح آب گرم بنوش.", "روز", "ruːze"), ("هیچ وقت تمرین را رها نکن.", "وقت", "vaq1te"),
                                ("هر ساعت آب بنوش.", "ساعت", "sɑʔate"), ("مادرم هر روز غذا درست می‌کند.", "روز", "ruːze")):
            d = self.preview(text)
            self.assertNotIn(bad, d["engines"]["piper"]["ipa"], text)
            self.assertFalse(any(w["ezafe"] for w in d["words"] if w["text"] == word), text)

    def test_the_light_verb_and_the_chain(self):
        d = self.preview("تا بدنت عادت کند.")
        self.assertNotIn("ɑdate", d["engines"]["piper"]["ipa"])
        d = self.preview("برای ساخت عضله پروتئین کافی بخور.")
        self.assertTrue(next(w for w in d["words"] if w["text"] == "ساخت")["ezafe"])
        self.assertFalse(next(w for w in d["words"] if w["text"] == "عضله")["ezafe"])

    def test_the_text_engines_get_sobh_with_a_he_that_is_not_final(self):
        d = self.preview("هر روز صبح", depth="lexicon")
        self.assertIn("سُبح", d["engines"]["edge"]["text"])
        self.assertNotIn("سُبه", d["engines"]["edge"]["text"])

    def test_a_spaced_times_sign_and_an_english_date_in_the_normalised_text(self):
        d = self.preview("۴ ست × ۱۲ تکرار، Nov 18")
        self.assertIn("چهار ست در دوازده تکرار", d["normalized"])
        self.assertIn("هجدهم نوامبر", d["normalized"])


class LexiconApiRound5(Base):
    def test_the_shared_table_shows_what_piper_receives_and_each_word_once(self):
        r = self.api.get(f"{self.base}/shared/?limit=2000")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        words = [x["word"] for x in body["rows"]]
        self.assertEqual(len(words), len(set(words)))
        for w in ("سی‌ام", "علاقه‌مند"):
            self.assertEqual(words.count(w), 1, w)
        row = next(x for x in body["rows"] if x["word"] == "چهار")
        self.assertEqual(row["ipa"], "tʃahɑr")
        self.assertEqual(row["ipa_ssml"], P.to_ssml_ipa(P.parse(row["pn"])))

    def test_the_overview_counts_unique_words(self):
        counts = self.api.get(f"{self.base}/").json()["counts"]
        self.assertEqual(counts["shared"], len(D.shared_entries()))

    def test_convert_and_the_store_lexicon_show_the_piper_phonemes(self):
        r = self.api.post(f"{self.base}/convert/", {"respelling": "چَهار"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["ipa"], "tʃahɑr")
        add = self.api.post(f"{self.base}/lexicon/", {"word": "ددلیفت", "respelling": "دِدلیفت"}, format="json")
        self.assertIn(add.status_code, (200, 201), add.content)
        rows = self.api.get(f"{self.base}/lexicon/").json()["rows"]
        self.assertEqual(next(x for x in rows if x["word"] == "ددلیفت")["ipa"], D.piper_ipa(P.parse(rows[0]["pn"])))


class EzafeTableRound5(Base):
    def test_four_sets_three_algorithms_and_the_numbers_of_the_docs(self):
        svc._EZAFE_CHECK.clear()
        rows = self.api.get(f"{self.base}/ezafe-check/").json()["rows"]
        self.assertEqual(len(rows), 12)
        expected = {(k, w): ezafe_gold.measure(fn, text=ezafe_gold.set_text(t))
                    for k, _n, _l, t in ezafe_gold.SET_DEFS for w, _e, fn in ezafe_gold.mark_functions()}
        for x in rows:
            m = expected[(x["set"], x["which"])]
            self.assertEqual((x["said"], x["correct"], x["wrong"], x["missing"], x["gold"]),
                             (m["predicted"], m["correct"], m["wrong"], m["missing"], m["gold"]))
        # ... and the markdown page carries these very numbers (the page and the panel cannot drift apart again)
        doc = pathlib.Path(__file__).resolve().parents[3] / "docs" / "pronunciation" / "ezafe-fa.md"
        if doc.exists():
            text = doc.read_text(encoding="utf-8")
            for x in rows:
                if x["which"] == "after":
                    self.assertIn(f"| {fa_digits(x['sentences'])} | {fa_digits(x['gold'])} | {fa_digits(x['said'])} | {fa_digits(x['correct'])} | "
                                  f"**{fa_digits(x['wrong'])}** | {fa_digits(x['missing'])} |", text)

    def test_the_same_with_login(self):
        self.assertEqual(APIClient().get(f"{self.base}/ezafe-check/").status_code, 401)
