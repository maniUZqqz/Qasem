from django.test import SimpleTestCase

from apps.growth_engine.core import csvio
from apps.growth_engine.core import normalization as nz

PERSIAN = "نام,شهر\nفروشگاه گل‌سرخ,تهران\nپوشاک آرمان,شیراز\n"


class DecodeTests(SimpleTestCase):
    def test_utf8(self):
        text, enc = csvio.decode_bytes(PERSIAN.encode("utf-8"))
        self.assertEqual((text, enc), (PERSIAN, "utf-8"))

    def test_utf8_bom(self):
        text, enc = csvio.decode_bytes(b"\xef\xbb\xbf" + PERSIAN.encode("utf-8"))
        self.assertEqual((text, enc), (PERSIAN, "utf-8-sig"))

    def test_cp1256_excel_persian(self):
        persian = "نام,شهر\nفروشگاه گلسرخ,تهران\nپوشاک چاپی,گرگان\n"
        # Excel's Windows-1256 has no Persian yeh/kaf; it writes the Arabic ones (that is what real files contain)
        data = persian.replace("ی", "ي").replace("ک", "ك").encode("cp1256")
        text, enc = csvio.decode_bytes(data)
        self.assertEqual(enc, "cp1256")
        self.assertIn("پوشاك چاپي", text)  # پ چ ژ گ survive; yeh/kaf come back as the Arabic letters
        self.assertEqual(nz.normalize_text(text, multiline=True), persian.strip())  # ...and normalising restores Persian

    def test_utf16_excel_unicode_text(self):
        text, enc = csvio.decode_bytes(PERSIAN.encode("utf-16"))
        self.assertEqual((text, enc), (PERSIAN, "utf-16"))

    def test_binary_and_empty_are_refused(self):
        for bad, code in [(b"", "empty_file"), (b"   \n", "empty_file"), (b"PK\x03\x04\x00\x00abc", "binary_file")]:
            with self.subTest(code=code), self.assertRaises(csvio.CsvError) as ctx:
                csvio.decode_bytes(bad)
            self.assertEqual(ctx.exception.code, code)


class ReadTests(SimpleTestCase):
    def test_delimiters_are_sniffed(self):
        for delim in [",", ";", "\t", "|"]:
            with self.subTest(delim=repr(delim)):
                headers, rows, found = csvio.read_table(f"a{delim}b{delim}c\n1{delim}2{delim}3\n4{delim}5{delim}6\n")
                self.assertEqual((headers, found), (["a", "b", "c"], delim))
                self.assertEqual([r[1] for r in rows], [["1", "2", "3"], ["4", "5", "6"]])

    def test_sep_hint_line(self):
        headers, rows, delim = csvio.read_table("sep=;\na;b\n1;2\n")
        self.assertEqual((headers, delim, rows[0][1]), (["a", "b"], ";", ["1", "2"]))

    def test_row_numbers_are_spreadsheet_rows_and_blank_rows_are_skipped(self):
        _, rows, _ = csvio.read_table("name,city\nA,x\n\nB,y\n,\nC,z\n")
        self.assertEqual([n for n, _ in rows], [2, 4, 6])

    def test_quoted_commas_and_newlines(self):
        _, rows, _ = csvio.read_table('name,desc\n"A, Inc","line1\nline2"\n')
        self.assertEqual(rows[0][1], ["A, Inc", "line1\nline2"])

    def test_short_rows_are_padded_and_headers_made_unique(self):
        headers, rows, _ = csvio.read_table("a,a,\n1\n")
        self.assertEqual(headers, ["a", "a (2)", "ستون 3"])
        self.assertEqual(rows[0][1], ["1", "", ""])

    def test_row_limit(self):
        body = "a\n" + "\n".join(str(i) for i in range(50))
        with self.assertRaises(csvio.CsvError) as ctx:
            csvio.read_table(body, max_rows=10)
        self.assertEqual(ctx.exception.code, "too_many_rows")

    def test_no_header(self):
        with self.assertRaises(csvio.CsvError):
            csvio.read_table("\n\n,,\n")


class GuardTests(SimpleTestCase):
    def test_formula_starts_are_guarded(self):
        for cell in ["=1+1", "+98912", "-5+2", "@SUM(A1)", "\tcmd", "\rcmd", "  =HYPERLINK(\"x\")"]:
            with self.subTest(cell=cell):
                self.assertTrue(csvio.guard_cell(cell).startswith("'"))

    def test_safe_cells_and_non_text_untouched(self):
        for cell in ["hello", "فروشگاه", "09121234567", "a=b", "", 42, None]:
            with self.subTest(cell=cell):
                self.assertEqual(csvio.guard_cell(cell), cell)

    def test_unguard_is_the_inverse_only_for_guarded_starts(self):
        for cell in ["=1+1", "+98912", "-5", "@x"]:
            self.assertEqual(csvio.unguard_cell(csvio.guard_cell(cell)), cell)
        self.assertEqual(csvio.unguard_cell("'hello"), "'hello")
        self.assertEqual(csvio.unguard_cell("it's"), "it's")


class WriteTests(SimpleTestCase):
    def test_bom_crlf_and_guard(self):
        data = csvio.build_csv_bytes(["نام", "ایمیل"], [["=cmd|' /C calc'!A0", "a@b.ir"], ["علی، رضایی", "x@y.ir"]])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8-sig")
        self.assertIn("\r\n", text)
        self.assertIn("'=cmd", text)
        headers, rows, _ = csvio.read_table(text)
        self.assertEqual(headers, ["نام", "ایمیل"])
        self.assertEqual(rows[0][1][0], "=cmd|' /C calc'!A0")  # round trip removes the guard
        self.assertEqual(rows[1][1][0], "علی، رضایی")
