"""The column mapping (proposed by a model or in code, never from whole files) and the validation of every row."""
import json
from datetime import date
from decimal import Decimal

import pytest

from khutlisa import holder_file as hf
from khutlisa import holder_list as hl
from khutlisa import invented_holder, llm

TODAY = date(2026, 11, 13)
HEADER = ["EE ID", "Employee Name", "Street", "City", "St", "Zip", "Ctry", "Pay Type", "Chk Date", "Net Amt", "E-mail"]
ROWS = [
    ["E-1001", "Wren, Ada", "12 Larkmoor Road", "Leeds", "", "LS1 4AB", "UK", "Regular Wages", "03/14/2025", "$1,284.60", "ada@example.com"],
    ["E-1002", "Bo Lark", "Calle Brisa 4", "Morelia", "MICH", "58000", "Mexico", "Final Paycheck", "2025-02-01", "95.00", ""],
    ["E-1003", "Cy Dove", "9 Pell Street", "Salinas", "CA", "93905", "", "Expense Reimb", "14-Mar-2024", "45", ""],
]
MAPPING = {"reference": "EE ID", "owner_name": "Employee Name", "address_1": "Street", "city": "City", "region": "St",
           "postcode": "Zip", "country": "Ctry", "property_type": "Pay Type", "last_activity": "Chk Date",
           "amount": "Net Amt", "email": "E-mail"}


def validated(rows, mapping=MAPPING, header=HEADER, **more):
    return hl.validate(header, rows, list(range(2, 2 + len(rows))), mapping, today=TODAY, **more)


# ---- single values -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("$1,284.60", "1284.60"), ("1284.6", "1284.6"), ("1.284,60", "1284.60"), ("1 284,60", "1284.60"), (" 95.00 ", "95.00"),
    ("USD 12", "12"), ("(45.00)", "-45.00"), ("-3", "-3"), ("1,234", "1234"), ("12,5", "12.5"), ("1'000.50", "1000.50"),
])
def test_amounts_are_read_in_the_ways_people_write_them(text, value):
    assert hl.money_of(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "TBD", "12 apples", "..", "1,2,3x"])
def test_what_is_not_one_number_is_not_an_amount(text):
    with pytest.raises(ValueError):
        hl.money_of(text)


@pytest.mark.parametrize("text, order, day", [
    ("2025-03-14", "MDY", date(2025, 3, 14)), ("03/14/2025", "MDY", date(2025, 3, 14)), ("14/03/2025", "MDY", date(2025, 3, 14)),
    ("3/4/25", "MDY", date(2025, 3, 4)), ("3/4/25", "DMY", date(2025, 4, 3)), ("14-Mar-2025", "MDY", date(2025, 3, 14)),
    ("March 14, 2025", "MDY", date(2025, 3, 14)), ("14 March 2025", "MDY", date(2025, 3, 14)), ("20250314", "MDY", date(2025, 3, 14)),
    ("45730", "MDY", date(2025, 3, 14)), ("2025-03-14 00:00:00", "MDY", date(2025, 3, 14)), ("14.03.2025", "DMY", date(2025, 3, 14)),
])
def test_dates_are_read_in_the_ways_people_write_them(text, order, day):
    assert hl.date_of(text, order) == day


@pytest.mark.parametrize("text, order, words", [
    ("13/32/2025", "MDY", "month"), ("02/30/2025", "MDY", "no such day"), ("pending", "MDY", "not written as a date"),
    ("", "MDY", "empty"), ("3/4/2025", "mixed", "day first or month first"),
])
def test_a_date_that_cannot_be_used_says_why(text, order, words):
    with pytest.raises(ValueError, match=words):
        hl.date_of(text, order)


def test_the_order_of_a_date_column_is_settled_by_the_dates_that_can_only_be_read_one_way():
    assert hl.date_order(["03/14/2025", "01/02/2025"]) == "MDY"
    assert hl.date_order(["14/03/2025", "01/02/2025"]) == "DMY"
    assert hl.date_order(["14/03/2025", "03/14/2025"]) == "mixed"
    assert hl.date_order(["01/02/2025", "2025-01-02"]) == "MDY"       # nothing settles it: a United States export


@pytest.mark.parametrize("text, code", [("MX", "MX"), ("mex", "MX"), ("México", "MX"), ("United Kingdom", "GB"), ("UK", "GB"),
                                        ("U.S.A.", "US"), ("Deutschland", "DE"), ("South Korea", "KR"), ("Atlantis", None),
                                        ("XX", None), ("", None)])
def test_countries_are_read_as_codes_or_names(text, code):
    assert hl.country_of(text) == code


@pytest.mark.parametrize("words, kind, settled", [
    ("Regular Wages", "wages", True), ("Final Paycheck", "wages", True), ("Sales commission", "wages", True),
    ("MS01: WAGES, PAYROLL, SALARIES", "wages", True), ("AC02 savings", "bank_account", True),
    ("Money order", "money_order", True), ("Traveler's cheque", "travelers_cheque", True),
    ("Vendor check", "cheque", True), ("Expense Reimb", "other", False), ("", "other", False),
])
def test_the_holders_words_for_the_kind_of_property(words, kind, settled):
    assert hl.property_class(words) == (kind, settled)


# ---- the proposal ------------------------------------------------------------------------------------------------

def test_code_reads_the_columns_from_payroll_shorthand():
    guess = hl.propose_from_code(HEADER, ROWS)
    assert {field: found["column"] for field, found in guess.items()} == MAPPING
    assert all(found["source"] == "title" for found in guess.values())


def test_a_hire_date_or_a_cheque_number_is_not_taken_for_the_balances_own():
    header = ["Name", "Hire Dt", "Term Date", "Check No", "Acct No", "Pay Date", "Amount"]
    rows = [["Ada Wren", "01/02/2015", "03/04/2024", "5567", "A-9", "03/15/2024", "12.50"]] * 3
    guess = {field: found["column"] for field, found in hl.propose_from_code(header, rows).items()}
    assert guess["last_activity"] == "Pay Date" and guess["reference"] == "Acct No" and guess["amount"] == "Amount"


def test_untitled_columns_are_read_from_the_shape_of_their_values():
    header = ["Column 1", "Column 2", "Column 3", "Column 4"]
    rows = [[f"Person {i}", f"{i}.50", f"2025-01-{i + 10}", "MX"] for i in range(1, 12)]
    guess = hl.propose_from_code(header, rows)
    assert guess["amount"] == {"column": "Column 2", "source": "values", "score": 0.5}
    assert guess["last_activity"]["column"] == "Column 3" and guess["country"]["column"] == "Column 4"
    assert "owner_name" not in guess and "the owner's name" in hl.missing_fields({f: g["column"] for f, g in guess.items()})


def test_a_split_name_replaces_the_single_name_column():
    header = ["First Name", "Last Name", "Name", "Amount", "Pay Date"]
    guess = hl.propose_from_code(header, [["Ada", "Wren", "Ada Wren", "1.50", "2025-01-02"]] * 3)
    assert "owner_name" not in guess and guess["first_name"]["column"] == "First Name"


def invented_table():
    return hf.read(invented_holder.as_csv(invented_holder.rows(600)), invented_holder.file_name())


def test_the_sample_for_the_model_is_at_most_twenty_rows_with_every_private_value_masked():
    table = invented_table()
    sample = hl.masked_sample(table.header, table.rows)
    assert 0 < len(sample) <= hl.SAMPLE_ROWS == 20
    at = {title: i for i, title in enumerate(table.header)}
    private = ["EE ID", "Employee Name (Last, First MI)", "Last Known Addr 1", "Addr 2", "City", "Zip/Postal", "E-mail", "Phone"]
    for row in sample:
        for title in private:
            assert not any(c.isalpha() and c not in "Xx" for c in row[at[title]]), (title, row[at[title]])
            assert not any(c.isdigit() and c != "9" for c in row[at[title]]), (title, row[at[title]])
    shown = json.dumps(sample)
    words = {w for r in table.rows for w in (r[at["Employee Name (Last, First MI)"]] + " " + r[at["Last Known Addr 1"]]).replace(",", " ").split()
             if len(w) > 3 and w.isalpha() and w not in ("Street", "Road", "Calle", "Avenue")}
    assert not [w for w in words if w in shown]
    assert "example.com" not in shown and "Regular Wages" in shown       # a repeated label may be seen; a person may not


def test_the_model_sees_titles_and_masked_rows_only_and_its_answer_is_checked_against_the_file(monkeypatch):
    table = invented_table()
    prompts = []

    def model(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"mapping": {"owner_name": "Employee Name (Last, First MI)", "amount": "Net Amt", "last_activity": "Chk Date",
                                       "country": "Ctry", "reference": "No Such Column", "city": "Net Amt", "made_up": "City"},
                           "date_order": "MDY", "notes": "mixed date formats"})

    monkeypatch.setattr(llm, "ask", model)
    proposal = hl.propose(table.header, table.rows)
    assert proposal["by"] == "model" and proposal["sample_rows_sent"] <= 20 and proposal["notes"] == "mixed date formats"
    fields = proposal["fields"]
    assert fields["owner_name"] == {"column": "Employee Name (Last, First MI)", "source": "model"}
    # A column the file does not have, a column used twice and a field that does not exist are dropped;
    # what the model left out is filled in code from the columns still free.
    assert fields["reference"] == {"column": "EE ID", "source": "title"} and fields["city"]["source"] == "title"
    assert "made_up" not in fields and proposal["missing"] == []
    assert len(prompts) == 1 and len(prompts[0]) < 12000
    at = table.header.index("Employee Name (Last, First MI)")
    assert not [r[at] for r in table.rows if r[at] and r[at] in prompts[0]]
    assert "example.com" not in prompts[0] and "EVS-0" not in prompts[0]


def test_without_a_model_the_proposal_is_made_in_code_and_says_so():
    table = invented_table()
    proposal = hl.propose(table.header, table.rows)          # conftest: the model refuses
    assert proposal["by"] == "code" and "read in code" in proposal["model_note"] and proposal["missing"] == []
    assert proposal["unused_columns"] == ["Dept", "Hire Dt", "Term Dt", "Chk No"]


def test_a_model_answer_that_is_not_a_mapping_falls_back_to_code(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: '{"columns": []}')
    proposal = hl.propose(HEADER, ROWS)
    assert proposal["by"] == "code" and "did not fit" in proposal["model_note"]
    assert {f: g["column"] for f, g in proposal["fields"].items()} == MAPPING


def test_a_remembered_mapping_is_offered_again_for_the_same_titles_and_no_model_is_asked(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a remembered mapping needs no model"))
    proposal = hl.propose(HEADER, ROWS, remembered={"mapping": MAPPING, "defaults": {"property_class": "wages"}})
    assert proposal["by"] == "remembered" and proposal["defaults"] == {"property_class": "wages"}
    assert all(found["source"] == "remembered" for found in proposal["fields"].values())
    assert hl.signature(HEADER) == hl.signature([h.upper() for h in reversed(HEADER)]) != hl.signature(HEADER[:-1])


def test_a_corrected_mapping_is_checked_against_the_file():
    assert hl.clean_mapping({**MAPPING, "email": None}, HEADER)["amount"] == "Net Amt"
    for raw, words in [({**MAPPING, "amount": "Nope"}, "no column called Nope"), ({**MAPPING, "city": "Net Amt"}, "used for two fields"),
                       ({"amount": "Net Amt"}, "the owner's name, the date of last activity"), ({**MAPPING, "shoe_size": "Zip"}, "no field called")]:
        with pytest.raises(ValueError, match=words):
            hl.clean_mapping(raw, HEADER)


# ---- every row, in code ------------------------------------------------------------------------------------------

def test_good_rows_become_balances_with_cleaned_values():
    result = validated(ROWS)
    assert result["failed"] == [] and [b["row"] for b in result["balances"]] == [2, 3, 4]
    ada, bo, cy = result["balances"]
    assert ada == {**ada, "name": "Ada Wren", "amount": "1284.60", "currency": "USD", "last_activity": "2025-03-14", "country": "GB",
                   "abroad": True, "property_class": "wages", "reference": "E-1001", "email": "ada@example.com", "street": "12 Larkmoor Road"}
    assert bo["country"] == "MX" and bo["abroad"] and bo["amount"] == "95.00"
    assert cy["country"] == "US" and not cy["abroad"] and cy["property_class"] == "other" and not cy["class_settled"]
    assert any("not one of the named kinds" in note for note in result["notes"])
    assert any("no currency column" in note for note in result["notes"])


@pytest.mark.parametrize("change, words", [
    ({1: ""}, "There is no owner name."),
    ({9: "TBD"}, 'The amount "TBD" is not a number.'),
    ({9: ""}, "There is no amount."),
    ({9: "(45.00)"}, "The amount is negative"),
    ({9: "0.00"}, "The amount is zero"),
    ({9: "99,000,000.00"}, "more than 10 million"),
    ({9: "CAD 15.00"}, "The amount is in CAD. This build handles balances held in US dollars only."),
    ({8: "13/32/2025"}, 'The date "13/32/2025" cannot be used'),
    ({8: ""}, "There is no date of last activity."),
    ({8: "2027-01-01"}, "is in the future"),
    ({8: "1950-01-01"}, "is before 1970"),
    ({6: "Atlantis"}, 'The country "Atlantis" is not one that can be recognised.'),
    ({6: "", 4: ""}, "There is no country, and the state or province is not one of the United States."),
    ({6: "CA", 4: "CA"}, 'The country and the state both read "CA"'),
])
def test_a_row_that_cannot_be_used_is_reported_with_its_reason(change, words):
    row = list(ROWS[0])
    for at, value in change.items():
        row[at] = value
    result = validated([row, ROWS[1]])
    assert [b["row"] for b in result["balances"]] == [3]
    assert result["failed"][0]["row"] == 2 and any(words in reason for reason in result["failed"][0]["reasons"])


def test_a_repeated_row_fails_and_names_the_row_it_repeats():
    result = validated([ROWS[0], ROWS[1], list(ROWS[0])])
    assert len(result["balances"]) == 2 and result["failed"] == [
        {"row": 4, "reasons": ["This row repeats row 2: the same owner, reference, amount and date."], "reference": "1001"}]


def test_a_row_can_fail_for_several_reasons_at_once_and_the_summary_counts_each_kind():
    bad = ["", "", "", "", "", "", "Atlantis", "", "pending", "TBD", ""]
    result = validated([bad, ROWS[0], ["E-9", "Di Finch", "", "", "", "", "Narnia", "", "2025-01-01", "5.00", ""]])
    assert len(result["failed"][0]["reasons"]) == 4
    summary = hl.failure_summary(result["failed"])
    assert summary[0] == {"reason": "The country is not one that can be recognised.", "rows": 2, "first_rows": [2, 4]}
    assert {s["reason"] for s in summary} >= {"There is no owner name.", "The amount is not a number.", "The date cannot be used."}


def test_a_mixed_date_column_uses_only_the_dates_that_can_be_read_one_way():
    rows = [["E-1", "Ada Wren", "", "", "CA", "", "", "Wages", "14/03/2025", "5.00", ""],
            ["E-2", "Bo Lark", "", "", "CA", "", "", "Wages", "03/14/2025", "5.00", ""],
            ["E-3", "Cy Dove", "", "", "CA", "", "", "Wages", "03/04/2025", "5.00", ""]]
    result = validated(rows)
    assert result["date_order"] == "mixed" and [b["row"] for b in result["balances"]] == [2, 3]
    assert "day first or month first" in result["failed"][0]["reasons"][0]


def test_a_file_with_no_kind_column_takes_the_kind_the_holder_chose_and_names_are_put_in_order():
    header = ["First", "Last", "Amount", "Pay Date", "State"]
    mapping = {"first_name": "First", "last_name": "Last", "amount": "Amount", "last_activity": "Pay Date", "region": "State"}
    result = hl.validate(header, [["Ada", "Wren", "5.00", "2025-01-02", "CA"]], [2], mapping, {"property_class": "wages"}, TODAY)
    assert result["balances"][0]["name"] == "Ada Wren" and result["balances"][0]["property_class"] == "wages"
    assert hl.tidy_name("Tolmedo, Marisol E") == "Marisol E Tolmedo" and hl.tidy_name("Acme, Inc., The") == "Acme, Inc., The"
