"""Reading a holder's own file: CSV in several dialects, an Excel workbook, and files that cannot be read."""
from datetime import date

import pytest

from khutlisa import holder_file as hf


def test_a_plain_csv_is_read_with_its_titles_and_row_numbers():
    table = hf.read(b"Name,Amount,Check Date\nAda Wren,12.50,2025-01-02\n\nBo Lark,3.00,2025-02-03\n", "list.csv")
    assert table.header == ["Name", "Amount", "Check Date"] and table.kind == "csv" and not table.invented
    assert table.rows == [["Ada Wren", "12.50", "2025-01-02"], ["Bo Lark", "3.00", "2025-02-03"]]
    assert table.row_numbers == [2, 4] and table.header_row == 1


@pytest.mark.parametrize("separator", [";", "\t", "|"])
def test_other_separators_are_recognised(separator):
    text = separator.join(["Name", "Amount", "Date"]) + "\n" + separator.join(["Ada Wren", "1,5", "02.01.2025"]) + "\n"
    table = hf.read(text.encode(), "list.csv")
    assert table.header == ["Name", "Amount", "Date"] and table.rows[0][1] == "1,5"


def test_a_windows_encoded_file_and_a_byte_order_mark_are_read():
    assert hf.read("Name,Amount,City\nJosé Núñez,5.00,León\n".encode("cp1252")).rows[0][0] == "José Núñez"
    assert hf.read("﻿Name,Amount,City\nAda,5.00,Leeds\n".encode("utf-8")).header[0] == "Name"


def test_lines_above_the_titles_are_skipped_and_the_widest_title_row_wins():
    text = ("Outstanding checks report\nRun date,2026-11-13,,Prepared by,Payroll\n\n"
            "EE ID,Employee Name,City,Ctry,Chk Date,Net Amt\nE1,\"Wren, Ada\",Leeds,GB,01/02/2025,12.50\n")
    table = hf.read(text.encode())
    assert table.header[0] == "EE ID" and table.header_row == 4 and table.rows[0][1] == "Wren, Ada"
    assert any("row 4" in note for note in table.notes)


def test_untitled_and_repeated_columns_get_names_of_their_own():
    table = hf.read(b"Name,,Amount,Amount,City\nAda,x,1.00,2.00,Leeds\n")
    assert table.header == ["Name", "Column 2", "Amount", "Amount (2)", "City"]


def test_the_invented_mark_is_found_in_the_first_lines_or_the_file_name():
    marked = f"{hf.INVENTED_MARK}. Made up.\nName,Amount,City\nAda,1.00,Leeds\n".encode()
    assert hf.read(marked).invented and not hf.read(b"Name,Amount,City\nAda,1.00,Leeds\n").invented
    assert hf.read(b"Name,Amount,City\nAda,1.00,Leeds\n", f"x-{hf.INVENTED_MARK}.csv").invented


def test_an_excel_workbook_is_read_with_its_dates_as_dates():
    data = hf.write_excel([["Report"], ["Name", "Amount", "Paid on", "Ref"],
                           ["Ada Wren", 12.5, date(2025, 3, 14), "A-7"], ["Bo Lark", 300, date(2024, 2, 29), 42]], {2})
    table = hf.read(data, "list.xlsx")
    assert table.kind == "excel" and table.header == ["Name", "Amount", "Paid on", "Ref"] and table.header_row == 2
    assert table.rows == [["Ada Wren", "12.5", "2025-03-14", "A-7"], ["Bo Lark", "300", "2024-02-29", "42"]]


def test_excel_day_counts_follow_excels_own_calendar():
    assert hf.excel_date(45730) == "2025-03-14" and hf.excel_date(1) == "1899-12-31"


@pytest.mark.parametrize("data, words", [
    (b"", "empty"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 50, "old .xls kind"),
    (b"PK\x03\x04 not really a zip", "cannot be opened"),
    (b"1,2,3\n4,5,6\n", "No row of column titles"),
    (b"Name,Amount,City\n", "no rows under them"),
    (b"just one line of text\n", "No row of column titles"),
])
def test_files_that_cannot_be_read_say_why(data, words):
    with pytest.raises(hf.FileProblem, match=words):
        hf.read(data)


def test_a_file_that_is_too_large_is_refused():
    with pytest.raises(hf.FileProblem, match="larger than 20 MB"):
        hf.read(b"a" * (hf.MAX_BYTES + 1))


def test_a_workbook_that_declares_entities_is_refused():
    import io
    import zipfile

    good = hf.write_excel([["Name", "Amount", "City"], ["Ada", 1.5, "Leeds"]])
    crafted = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as source, zipfile.ZipFile(crafted, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b"?>", b'?><!DOCTYPE x [<!ENTITY a "aaaa">]>', 1)
            target.writestr(name, data)
    with pytest.raises(hf.FileProblem, match="something a spreadsheet does not"):
        hf.read(crafted.getvalue())
