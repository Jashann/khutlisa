"""The invented holder file: no real person, realistic mess, the same file from the same seed."""
import re
from datetime import date

from khutlisa import dormancy, holder_file, holder_list, invented_holder as inv

TODAY = date(2026, 11, 13)


def read(data, kind="csv"):
    table = holder_file.read(data, inv.file_name(kind))
    mapping = {f: g["column"] for f, g in holder_list.propose(table.header, table.rows, use_model=False)["fields"].items()}
    return table, holder_list.validate(table.header, table.rows, table.row_numbers, mapping, today=TODAY)


def test_the_file_is_marked_as_invented_on_its_first_line_and_in_its_name():
    table = inv.rows(200)
    assert table[0] == [inv.FIRST_LINE] and holder_file.INVENTED_MARK in inv.FIRST_LINE
    assert "INVENTED" in inv.file_name() and "INVENTED" in inv.file_name("excel")
    assert inv.as_csv(table).decode("utf-8-sig").startswith(holder_file.INVENTED_MARK)
    assert holder_file.read(inv.as_csv(table)).invented and holder_file.read(inv.as_excel(table)).invented


def test_the_same_seed_gives_the_same_file_and_another_seed_another():
    assert inv.as_csv(inv.rows(300)) == inv.as_csv(inv.rows(300))
    assert inv.as_csv(inv.rows(300, seed=5)) != inv.as_csv(inv.rows(300))


def test_a_few_thousand_former_workers_with_about_three_in_ten_abroad_weighted_like_the_real_file():
    table, result = read(inv.as_csv(inv.rows()))
    assert len(table.rows) > 3000 and table.header == inv.HEADER and table.header_row == 5
    good, bad = result["balances"], result["failed"]
    assert len(good) + len(bad) == len(table.rows) and 0.02 < len(bad) / len(table.rows) < 0.08
    abroad = [b for b in good if b["abroad"]]
    assert 0.25 < len(abroad) / len(good) < 0.35
    counts: dict[str, int] = {}
    for b in abroad:
        counts[b["country"]] = counts.get(b["country"], 0) + 1
    order = sorted(counts, key=counts.get, reverse=True)
    assert order[0] == "JP" and set(order[:5]) == {"JP", "MX", "GB", "CA", "CN"} and len(counts) > 25
    assert abs(counts["JP"] / len(abroad) - 0.195 / (sum(inv.COUNTRY_WEIGHTS.values()) / 100)) < 0.04


def test_the_mess_is_the_kind_a_real_export_has():
    text = inv.as_csv(inv.rows()).decode("utf-8-sig")
    assert re.search(r"\$\d,\d{3}\.\d\d", text) and re.search(r"\d{2}/\d{2}/\d{4}", text) and re.search(r"\d-[A-Z][a-z]{2}-\d{4}", text)
    assert "Mexico" in text and ",MX," in text and "México" in text
    _, result = read(text.encode("utf-8-sig"))
    reasons = " ".join(reason for row in result["failed"] for reason in row["reasons"])
    for words in ("is not a number", "negative", "cannot be used", "in the future", "not one that can be recognised",
                  "no owner name", "repeats row", "There is no country"):
        assert words in reasons, words


def test_the_workbook_and_the_csv_hold_the_same_balances():
    table = inv.rows(500)
    _, from_csv = read(inv.as_csv(table))
    _, from_excel = read(inv.as_excel(table), "excel")
    key = lambda result: sorted((b["row"], b["name"], b["amount"], b["last_activity"], b["country"]) for b in result["balances"])
    assert key(from_csv) == key(from_excel) and len(from_csv["failed"]) == len(from_excel["failed"]) > 0


def test_nothing_in_it_points_at_a_real_person():
    table = inv.rows(800)
    emails = [row[15] for row in table[5:] if row[15]]
    assert emails and all(e.endswith("@example.com") for e in emails)
    phones = [row[16] for row in table[5:] if row[16]]
    assert all(" 555 " in p or p == inv.MARISOL["phone"] for p in phones)
    assert inv.HOLDER["email"].endswith(".example") and "555" in inv.HOLDER["phone"]


def test_the_demonstration_person_is_in_it_with_pay_that_is_on_its_way_to_the_state():
    _, result = read(inv.as_csv(inv.rows()))
    marisol = [b for b in result["balances"] if b["reference"] == inv.MARISOL["id"]]
    assert len(marisol) == 1
    b = marisol[0]
    assert (b["name"], b["amount"], b["country"], b["city"], b["property_class"], b["e_consent"]) == (
        "Marisol E Tolmedo", "1284.60", "MX", "Guadalajara", "wages", True)
    place = dormancy.place(b, TODAY)
    assert place["status"] == "remit" and place["handover"] == "2027-06-01"
