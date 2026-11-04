"""CSV reading and writing for the Growth Engine.

Reading
    * decodes UTF-8, UTF-8 with BOM, UTF-16 (Excel "Unicode text") and
      Windows-1256 (what Excel saves for Persian text when you pick plain "CSV");
    * sniffs the delimiter (`,` `;` tab `|`) - Persian Excel writes `;`;
    * refuses binary files.

Writing
    * UTF-8 **with BOM**, so Excel shows Persian correctly;
    * CRLF line ends;
    * formula-injection guard: a text cell that starts with ``= + - @`` TAB or CR
      gets a leading ``'`` so a spreadsheet shows it as text instead of running
      it. ``unguard_cell`` undoes exactly that on re-import, so an exported file
      imports back without the apostrophes.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator

BOM = "﻿"
DELIMITERS = [",", ";", "\t", "|"]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class CsvError(ValueError):
    """The file cannot be read as a table. ``message`` is Persian, for the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- reading


def decode_bytes(data: bytes) -> tuple[str, str]:
    """(text, encoding name). Raises ``CsvError`` for empty / binary input."""
    if not data or not data.strip():
        raise CsvError("empty_file", "فایل خالی است.")
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16").lstrip(BOM), "utf-16"
        except UnicodeError as exc:
            raise CsvError("bad_encoding", "کدگذاریِ فایل خوانده نشد.") from exc
    if b"\x00" in data:
        raise CsvError("binary_file", "این فایل متنی (CSV) نیست. از اکسل «Save as ← CSV» بزنید.")
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeError as exc:
            raise CsvError("bad_encoding", "کدگذاریِ فایل خوانده نشد.") from exc
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    # Excel's Persian "CSV (comma delimited)" is Windows-1256; every byte maps to a character.
    return data.decode("cp1256", errors="replace"), "cp1256"


def sniff_delimiter(text: str) -> str:
    """Most likely delimiter, judged on the first lines (outside quotes it is
    whichever candidate appears the same number of times on most lines)."""
    lines = [ln for ln in text.splitlines()[:30] if ln.strip() and not ln.lower().startswith("sep=")]
    if not lines:
        return ","
    best, best_score = ",", -1
    for delim in DELIMITERS:
        counts = []
        for row in csv.reader(lines, delimiter=delim):
            counts.append(len(row) - 1)
        if not counts or max(counts) == 0:
            continue
        first = counts[0]
        consistent = sum(1 for c in counts if c == first)
        score = consistent * 1000 + first
        if first > 0 and score > best_score:
            best, best_score = delim, score
    return best


def unguard_cell(value: str) -> str:
    """Undo the export guard: ``'=1+1`` -> ``=1+1`` (only for the guarded starts)."""
    if len(value) > 1 and value[0] == "'" and value[1] in "=+-@\t\r":
        return value[1:]
    return value


def read_table(text: str, *, max_rows: int | None = None) -> tuple[list[str], list[tuple[int, list[str]]], str]:
    """(headers, rows, delimiter). ``rows`` are ``(row_number, cells)`` where ``row_number`` is the
    spreadsheet row (the header is row 1), so an error message can say "row 14" exactly like Excel.
    Blank rows are dropped; cells are stripped and unguarded.

    Raises ``CsvError`` when there is no header or more than ``max_rows`` data rows.
    """
    text = text.lstrip(BOM)
    # Excel's optional first line "sep=;" tells the delimiter; it is not data.
    lines = text.splitlines()
    forced = None
    if lines and lines[0].lower().startswith("sep=") and len(lines[0]) == 5:
        forced = lines[0][4]
        text = "\n".join(lines[1:])
    delimiter = forced or sniff_delimiter(text)
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False)
        record_no = 0
        raw_header = None
        for raw in reader:
            record_no += 1
            if any(c.strip() for c in raw):
                raw_header = raw
                break
        if raw_header is None:
            raise CsvError("no_header", "ردیفِ عنوان ستون‌ها در فایل پیدا نشد.")
        header_row = record_no
        headers = _unique_headers([c.strip() for c in raw_header])
        rows: list[tuple[int, list[str]]] = []
        for raw in reader:
            record_no += 1
            if not any(c.strip() for c in raw):
                continue
            row = [unguard_cell(c.strip()) for c in raw]
            if len(row) < len(headers):
                row += [""] * (len(headers) - len(row))
            rows.append((record_no - header_row + 1, row))
            if max_rows is not None and len(rows) > max_rows:
                raise CsvError("too_many_rows", f"فایل بیشتر از {max_rows} ردیف دارد؛ آن را به چند فایل تقسیم کنید.")
    except csv.Error as exc:
        raise CsvError("malformed_csv", f"ساختار فایل CSV خراب است ({exc}).") from exc
    return headers, rows, delimiter


def _unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for index, name in enumerate(headers, 1):
        base = name or f"ستون {index}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out


# --------------------------------------------------------------------------- writing


def guard_cell(value: object) -> object:
    """Protect a text cell against spreadsheet formula injection. Non-text is untouched."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    if isinstance(value, str) and value.lstrip().startswith(_FORMULA_START[:4]) and value != value.lstrip():
        return "'" + value
    return value


def stream_csv(header: list[str], rows: Iterable[list[object]]) -> Iterator[bytes]:
    """UTF-8 (BOM) CSV, one chunk per row, every text cell guarded."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([guard_cell(c) for c in header])
    yield (BOM + buffer.getvalue()).encode("utf-8")
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow([guard_cell(c) for c in row])
        yield buffer.getvalue().encode("utf-8")


def build_csv_bytes(header: list[str], rows: Iterable[list[object]]) -> bytes:
    return b"".join(stream_csv(header, rows))
