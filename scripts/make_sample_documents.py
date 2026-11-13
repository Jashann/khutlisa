"""Draws the sample documents of the two demonstration people.

    uv run python scripts/make_sample_documents.py

Writes PNG images into data/samples/ and web/public/samples/: six for Amihan (file names starting sample_),
five for Marisol (file names starting mx_), and eleven for the demonstration estate (file names starting es_):
the death certificate of the invented owner, the marriage, birth and death certificates that tie each heir to
him, and a sample passport page for each of the four heirs, in Mexico, the Philippines, the United Kingdom and
Japan. For each person there are old documents from her years in California
(a staff badge, a payslip, and for Amihan a utility bill) and current ones (the photo page of a sample passport
of the country she lives in, a taxpayer number letter and a bank statement at her present address). The current
ones are what a proof file needs to be ready. The passport page names the government of that country as its
issuer and carries issue and expiry dates and two machine-readable lines in the standard passport format with
correct check digits, because the proof file checks all three. Every layout is our own and copies no real government or bank design. Every
name, address, number and organisation is invented, and every image carries the word SAMPLE. Nothing is taken
from a real register.

The records these two people claim are not made here. They are the demonstration records in
src/khutlisa/demonstration.json, which every search reads beside California's file.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FONTS = ROOT / "src" / "khutlisa" / "fonts"
OUT = ROOT / "data" / "samples"
PUBLIC = ROOT / "web" / "public" / "samples"

# What the sample passport of each country says. The three-letter code is the one the passport standard uses in
# the machine-readable lines; `family_words` is how many words at the end of the full name are the surname.
PASSPORTS = {"Mexico": {"state": "MEX", "of": "Mexico", "family_words": 2},
             "Philippines": {"state": "PHL", "of": "the Philippines", "family_words": 1},
             "United Kingdom": {"state": "GBR", "of": "the United Kingdom", "family_words": 2},
             "Japan": {"state": "JPN", "of": "Japan", "family_words": 2}}
PASSPORT_DATES = ("2023-05-08", "2033-05-07")
PASSPORT_NUMBER = "SAMPLE000"      # nine characters, as the standard asks; plainly not a real number
TAX_OFFICE = "Sample Tax Office"
# The two made-up people and the made-up organisations around them. They are the people in
# src/khutlisa/demonstration.json, and the same names speak in the intake's examples.
AMIHAN = {
    "prefix": "sample_",
    "person": {"name": "Amihan Dalisay", "street": "1420 Larkmoor Street Apt 5", "city": "Daly City", "region": "CA",
               "postcode": "94015"},
    "employer": {"name": "Bayview Mercy Hospital", "street": "300 Seacliff Avenue", "city": "Daly City",
                 "region": "CA", "postcode": "94015"},
    "job": ("Registered Nurse", "Medical-Surgical Unit, 4 West", "BMH-00417"),
    "utility": {"name": "Golden Coast Power and Water", "street": "P.O. Box 7700", "city": "Fresno", "region": "CA",
                "postcode": "93701"},
    "now": {"name": "Amihan Dalisay Villareal", "street": "27 Sampaguita Lane, Lahug", "city": "Cebu City",
            "postcode": "6000", "country": "Philippines"},
    "bank": {"name": "Visayas Sample Bank", "street": "1 Sample Plaza", "city": "Cebu City", "postcode": "6000"},
    "born": ("1984-02-11", "Cebu City"), "signature": "Amihan D. Villareal", "formerly": ("Formerly known as", "Amihan Dalisay"),
    "money": ("PHP", [("2026-09-15", "Opening balance", "18,240.00"), ("2026-09-30", "Salary", "41,500.00"),
                      ("2026-10-02", "Rent", "-14,000.00"), ("2026-10-05", "Electricity", "-2,310.50"),
                      ("2026-10-09", "Groceries", "-3,872.25"), ("2026-10-12", "Mobile plan", "-799.00")],
              "PHP 38,758.25"),
}
MARISOL = {
    "prefix": "mx_",
    "person": {"name": "Marisol Tolmedo", "street": "618 Camino Lunamar Apt 3", "city": "Salinas", "region": "CA",
               "postcode": "93905"},
    "employer": {"name": "Empacadora Valle Sereno", "street": "2400 Harrowgate Road", "city": "Salinas",
                 "region": "CA", "postcode": "93905"},
    "job": ("Line Lead", "Packing Shed 2, Day Shift", "EVS-01186"),
    "utility": {"name": "Punta Clara Water and Light", "street": "P.O. Box 3100", "city": "Salinas", "region": "CA",
                "postcode": "93902"},
    "now": {"name": "Marisol Elena Tolmedo Peralmonte", "street": "Calle Fresno 214, Colonia Americana",
            "city": "Guadalajara, Jalisco", "postcode": "44160", "country": "Mexico"},
    "bank": {"name": "Banco Muestra de Occidente", "street": "Avenida Ejemplo 10", "city": "Guadalajara, Jalisco",
             "postcode": "44100"},
    "born": ("1986-07-23", "Guadalajara"), "signature": "Marisol E. Tolmedo P.", "formerly": ("Also written as", "Marisol Tolmedo"),
    "money": ("MXN", [("2026-09-15", "Opening balance", "6,480.00"), ("2026-09-30", "Salary", "14,200.00"),
                      ("2026-10-02", "Rent", "-5,500.00"), ("2026-10-05", "Electricity", "-412.30"),
                      ("2026-10-09", "Groceries", "-1,937.45"), ("2026-10-12", "Mobile plan", "-299.00")],
              "MXN 12,531.25"),
}
NAVY, INK, SOFT, LINE, PAPER, TEAL, RED = "#12284a", "#1b2438", "#5b6680", "#c9cfdb", "#fbfaf6", "#1d6f78", "#b3261e"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")), size)


def stamp(image: Image.Image, size: int) -> Image.Image:
    """The word SAMPLE across the page, and a plain line at the foot saying the document is invented."""
    width, height = image.size
    layer = Image.new("RGBA", (width * 2, height * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((width, height), "SAMPLE", font=font(size, True), fill=(179, 38, 30, 70), anchor="mm")
    layer = layer.rotate(24, resample=Image.BICUBIC)
    left, top = (layer.width - width) // 2, (layer.height - height) // 2
    image = Image.alpha_composite(image.convert("RGBA"), layer.crop((left, top, left + width, top + height)))
    draw = ImageDraw.Draw(image)
    note = "SAMPLE DOCUMENT. The person and the organisations are made up. Not a real record."
    fit = 19
    while fit > 9 and draw.textlength(note, font=font(fit, True)) > width - 30:
        fit -= 1
    draw.rectangle([0, height - 46, width, height], fill="#fdecea")
    draw.text((width // 2, height - 23), note, font=font(fit, True), fill=RED, anchor="mm")
    return image.convert("RGB")


def rows(draw: ImageDraw.ImageDraw, x: int, y: int, pairs: list[tuple[str, str]], gap: int = 46, label_w: int = 250,
         size: int = 24) -> int:
    for label, value in pairs:
        draw.text((x, y), label, font=font(size - 4), fill=SOFT)
        draw.text((x + label_w, y - 3), value, font=font(size, True), fill=INK)
        y += gap
    return y


def badge(p: dict) -> Image.Image:
    image = Image.new("RGB", (760, 1140), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 760, 190], fill=TEAL)
    d.text((380, 78), p["employer"]["name"], font=font(46, True), fill="white", anchor="mm")
    d.text((380, 140), f"{p['employer']['street']}, {p['employer']['city']}, {p['employer']['region']} {p['employer']['postcode']}",
           font=font(22), fill="#d9f0f2", anchor="mm")
    d.text((380, 240), "STAFF IDENTIFICATION", font=font(26, True), fill=TEAL, anchor="mm")
    # A drawn outline where a photograph would be. No real face is used.
    d.rounded_rectangle([230, 290, 530, 650], radius=14, fill="#dfe5ee", outline=LINE, width=3)
    d.ellipse([320, 350, 440, 470], fill="#aab4c6")
    d.pieslice([270, 480, 490, 760], 180, 360, fill="#aab4c6")
    d.text((380, 628), "photo area", font=font(18), fill=SOFT, anchor="mm")
    d.text((380, 715), p["person"]["name"], font=font(52, True), fill=INK, anchor="mm")
    d.text((380, 775), p["job"][0], font=font(30), fill=INK, anchor="mm")
    d.text((380, 818), p["job"][1], font=font(24), fill=SOFT, anchor="mm")
    d.line([80, 860, 680, 860], fill=LINE, width=2)
    rows(d, 110, 890, [("Employee no.", p["job"][2]), ("Issued", "2009-06-15"), ("Expires", "2019-06-14")],
         gap=52, label_w=220, size=28)
    d.rectangle([110, 1050, 650, 1076], fill=INK)
    for i in range(0, 540, 9):
        if (i // 9) % 3 != 1:
            d.rectangle([110 + i, 1050, 110 + i + 3, 1076], fill=PAPER)
    return stamp(image, 190)


def payslip(p: dict) -> Image.Image:
    image = Image.new("RGB", (1400, 1000), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1400, 130], fill=TEAL)
    d.text((60, 38), p["employer"]["name"], font=font(44, True), fill="white")
    d.text((1340, 50), "EARNINGS STATEMENT", font=font(30, True), fill="white", anchor="ra")
    d.text((60, 150), f"{p['employer']['street']}, {p['employer']['city']}, {p['employer']['region']} {p['employer']['postcode']}",
           font=font(22), fill=SOFT)
    d.text((60, 215), "EMPLOYEE", font=font(20, True), fill=TEAL)
    d.text((60, 248), p["person"]["name"], font=font(34, True), fill=INK)
    d.text((60, 296), p["person"]["street"], font=font(26), fill=INK)
    d.text((60, 332), f"{p['person']['city']}, {p['person']['region']} {p['person']['postcode']}", font=font(26), fill=INK)
    rows(d, 800, 222, [("Employee no.", p["job"][2]), ("Pay period", "2014-03-09 to 2014-03-22"),
                       ("Pay date", "2014-03-28"), ("Position", p["job"][0])], gap=42, label_w=200)
    d.line([60, 410, 1340, 410], fill=LINE, width=2)
    y = 430
    d.text((60, y), "EARNINGS", font=font(20, True), fill=TEAL)
    d.text((760, y), "DEDUCTIONS", font=font(20, True), fill=TEAL)
    y += 44
    earn = [("Regular pay, 72.0 hours", "3,096.00"), ("Night differential, 24.0 hours", "168.00"),
            ("Overtime, 6.0 hours", "387.00")]
    take = [("Federal income tax", "512.40"), ("Social Security", "226.36"), ("Medicare", "52.94"),
            ("California state tax", "181.15"), ("Retirement plan", "182.55")]
    for i, (label, value) in enumerate(earn):
        d.text((60, y + i * 44), label, font=font(24), fill=INK)
        d.text((660, y + i * 44), value, font=font(24), fill=INK, anchor="ra")
    for i, (label, value) in enumerate(take):
        d.text((760, y + i * 44), label, font=font(24), fill=INK)
        d.text((1340, y + i * 44), value, font=font(24), fill=INK, anchor="ra")
    y += 5 * 44 + 16
    d.line([60, y, 1340, y], fill=LINE, width=2)
    d.text((60, y + 18), "Gross pay", font=font(26, True), fill=INK)
    d.text((660, y + 18), "3,651.00", font=font(26, True), fill=INK, anchor="ra")
    d.text((760, y + 18), "Total deductions", font=font(26, True), fill=INK)
    d.text((1340, y + 18), "1,155.40", font=font(26, True), fill=INK, anchor="ra")
    d.rounded_rectangle([760, y + 80, 1340, y + 160], radius=10, fill="#e8f1f2", outline=TEAL, width=2)
    d.text((784, y + 100), "NET PAY", font=font(28, True), fill=TEAL)
    d.text((1316, y + 98), "US$2,495.60", font=font(32, True), fill=INK, anchor="ra")
    d.text((60, y + 96), "Paid by cheque. Tax number on file: not printed on this statement.", font=font(20), fill=SOFT)
    return stamp(image, 250)


def bill(p: dict) -> Image.Image:
    image = Image.new("RGB", (1100, 1420), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1100, 150], fill=NAVY)
    d.text((60, 36), p["utility"]["name"], font=font(46, True), fill="white")
    d.text((60, 98), "Electricity and water service", font=font(24), fill="#c9d6ee")
    d.text((1040, 190), "MONTHLY BILL", font=font(32, True), fill=NAVY, anchor="ra")
    d.text((60, 190), "SERVICE FOR", font=font(20, True), fill=NAVY)
    d.text((60, 224), p["person"]["name"], font=font(34, True), fill=INK)
    d.text((60, 272), p["person"]["street"], font=font(26), fill=INK)
    d.text((60, 308), f"{p['person']['city']}, {p['person']['region']} {p['person']['postcode']}", font=font(26), fill=INK)
    y = rows(d, 620, 250, [("Account no.", "GC-55-204417"), ("Bill date", "2014-04-03"),
                           ("Service period", "2014-03-01 to 2014-03-31"), ("Due date", "2014-04-24")],
             gap=42, label_w=190, size=23)
    d.line([60, y + 20, 1040, y + 20], fill=LINE, width=2)
    y += 50
    d.text((60, y), "CHARGES", font=font(20, True), fill=NAVY)
    y += 44
    for label, value in [("Electricity, 312 kWh", "58.41"), ("Water, 9 units", "37.80"), ("Service charge", "8.50"),
                         ("City utility users tax", "5.24"), ("Previous balance", "0.00")]:
        d.text((60, y), label, font=font(25), fill=INK)
        d.text((1040, y), value, font=font(25), fill=INK, anchor="ra")
        y += 46
    d.line([60, y + 6, 1040, y + 6], fill=LINE, width=2)
    d.rounded_rectangle([560, y + 30, 1040, y + 116], radius=10, fill="#eef2f9", outline=NAVY, width=2)
    d.text((584, y + 52), "AMOUNT DUE", font=font(28, True), fill=NAVY)
    d.text((1016, y + 50), "US$109.95", font=font(32, True), fill=INK, anchor="ra")
    y += 170
    d.text((60, y), "USE IN THE LAST SIX MONTHS (kWh)", font=font(20, True), fill=NAVY)
    for i, (month, used) in enumerate([("Oct", 288), ("Nov", 301), ("Dec", 356), ("Jan", 349), ("Feb", 322), ("Mar", 312)]):
        x = 80 + i * 160
        d.rectangle([x, y + 240 - used // 2, x + 90, y + 240], fill="#9fb3d9")
        d.text((x + 45, y + 262), month, font=font(20), fill=SOFT, anchor="mm")
        d.text((x + 45, y + 222 - used // 2), str(used), font=font(20), fill=INK, anchor="mm")
    y += 320
    d.line([60, y, 1040, y], fill=LINE, width=2)
    d.text((60, y + 20), f"Send payment to {p['utility']['name']}, {p['utility']['street']}, {p['utility']['city']}, "
                         f"{p['utility']['region']} {p['utility']['postcode']}.", font=font(21), fill=SOFT)
    d.text((60, y + 54), "A deposit of US$120.00 is held on this account and is returned when service ends.",
           font=font(21), fill=SOFT)
    return stamp(image, 230)


def passport_facts(p: dict) -> dict:
    """What is printed on a person's sample passport, worked out from her present name, country and date of
    birth alone, so the page always agrees with the rest of her documents."""
    from khutlisa import mrz

    country = p["now"]["country"]
    rule = PASSPORTS[country]
    words = p["now"]["name"].split()
    family_words = p.get("family_words") or rule["family_words"]
    surname, given = " ".join(words[-family_words:]), " ".join(words[:-family_words])
    issued, expires = PASSPORT_DATES
    return {"country": country, "state": rule["state"], "authority": f"Government of {rule['of']}, Passport Office",
            "surname": surname, "given": given, "issued": issued, "expires": expires,
            "machine_readable_lines": mrz.build_td3(surname, given, rule["state"], PASSPORT_NUMBER, p["born"][0],
                                                    expires)}


def passport_id(p: dict) -> Image.Image:
    """The photo page of a sample passport of the country the person lives in. The layout is our own and copies no
    country's passport. It presents itself as what a proof file needs, government photo identification with
    dates and machine-readable lines, so the walk-through meets the same checks a real claim meets; the SAMPLE
    mark says it proves nothing real."""
    facts = passport_facts(p)
    image = Image.new("RGB", (1300, 900), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1300, 140], fill="#4a2f6b")
    d.text((60, 26), facts["country"].upper(), font=font(40, True), fill="white")
    d.text((1240, 30), "PASSPORT", font=font(40, True), fill="white", anchor="ra")
    d.text((60, 90), "SAMPLE page in Khutlisa's own layout. It copies no real passport and proves nothing.",
           font=font(24), fill="#e3d8f2")
    # A drawn outline where a photograph would be. No real face is used.
    d.rounded_rectangle([60, 180, 400, 610], radius=14, fill="#dfe5ee", outline=LINE, width=3)
    d.ellipse([165, 250, 295, 380], fill="#aab4c6")
    d.pieslice([110, 390, 350, 690], 180, 360, fill="#aab4c6")
    d.text((230, 586), "photo area", font=font(18), fill=SOFT, anchor="mm")
    y = rows(d, 460, 176, [("Surname", facts["surname"].upper()), ("Given names", facts["given"].upper()),
                           ("Date of birth", p["born"][0]), ("Place of birth", p["born"][1]),
                           ("Passport no.", PASSPORT_NUMBER), ("Date of issue", facts["issued"]),
                           ("Date of expiry", facts["expires"]), ("Issuing country", facts["country"])],
             gap=50, label_w=230, size=26)
    # A long authority is set smaller so the whole line stays on the page: a line cut off at the edge is a
    # reason for the reader to question the document.
    size = 26
    if d.textlength(facts["authority"], font=font(size, True)) > 1300 - 690:
        while size > 16 and d.textlength(facts["authority"], font=font(size, True)) > 1240 - 690:
            size -= 1
    d.text((460, y), "Authority", font=font(22), fill=SOFT)
    d.text((690, y - 3 + (26 - size)), facts["authority"], font=font(size, True), fill=INK)
    d.line([60, 636, 1240, 636], fill=LINE, width=2)
    d.text((60, 656), "Signature of holder", font=font(20), fill=SOFT)
    d.text((300, 648), p["signature"], font=font(30), fill=INK)
    # The machine-readable lines, one character to a cell so that every filler can be counted.
    for row, line in enumerate(facts["machine_readable_lines"]):
        for i, c in enumerate(line):
            d.text((72 + i * 26.5, 742 + row * 52), c, font=font(30, True), fill=INK, anchor="mm")
    return stamp(image, 230)


def tax_letter_rows(p: dict) -> list[tuple[str, str]]:
    """What the letter prints under the number. One name only: a second name on a tax letter is a fair thing for
    a reader to question, and a questioned document settles nothing."""
    return [("Name on file", p["now"]["name"]), ("Notice", "SAMPLE-TIN-01")]


def tax_letter(p: dict) -> Image.Image:
    """A letter that says a taxpayer number was assigned. Our own layout, not any tax authority's form."""
    image = Image.new("RGB", (1100, 1300), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1100, 150], fill="#3d4a2a")
    d.text((60, 34), TAX_OFFICE.upper(), font=font(46, True), fill="white")
    d.text((60, 98), "SAMPLE letter, from an office that does not exist", font=font(24), fill="#dfe8cf")
    d.text((1040, 200), "Date: 2019-03-12", font=font(24), fill=INK, anchor="ra")
    d.text((60, 200), p["now"]["name"], font=font(30, True), fill=INK)
    d.text((60, 246), p["now"]["street"], font=font(26), fill=INK)
    d.text((60, 282), f"{p['now']['city']} {p['now']['postcode']}", font=font(26), fill=INK)
    d.text((60, 318), p["now"]["country"], font=font(26), fill=INK)
    d.text((60, 410), "Your taxpayer identification number", font=font(34, True), fill="#3d4a2a")
    y = 480
    for line in [f"Dear {p['now']['name']},",
                 "",
                 "This letter confirms that an individual taxpayer identification",
                 "number has been assigned to you. Keep this letter with your records",
                 "and show it when you are asked for proof of your number."]:
        d.text((60, y), line, font=font(26), fill=INK)
        y += 42
    d.rounded_rectangle([60, y + 30, 1040, y + 190], radius=10, fill="#eef2e6", outline="#3d4a2a", width=2)
    d.text((90, y + 52), "Taxpayer identification number", font=font(22), fill=SOFT)
    d.text((90, y + 92), "900-00-0000", font=font(48, True), fill=INK)     # a pattern no tax office issues
    d.text((1010, y + 112), "an invented number", font=font(22), fill=SOFT, anchor="ra")
    y += 250
    rows(d, 60, y, tax_letter_rows(p), gap=50, label_w=270, size=26)
    d.line([60, 1150, 1040, 1150], fill=LINE, width=2)
    d.text((60, 1170), f"{TAX_OFFICE}. This is a made-up office and this letter is an example only.",
           font=font(21), fill=SOFT)
    return stamp(image, 230)


def bank_statement(p: dict) -> Image.Image:
    """A recent statement that shows her present name and address."""
    image = Image.new("RGB", (1100, 1300), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1100, 150], fill=NAVY)
    d.text((60, 36), p["bank"]["name"], font=font(46, True), fill="white")
    d.text((60, 98), f"{p['bank']['street']}, {p['bank']['city']} {p['bank']['postcode']}", font=font(24), fill="#c9d6ee")
    d.text((1040, 190), "ACCOUNT STATEMENT", font=font(32, True), fill=NAVY, anchor="ra")
    d.text((60, 190), "ACCOUNT HOLDER", font=font(20, True), fill=NAVY)
    d.text((60, 224), p["now"]["name"], font=font(34 if len(p["now"]["name"]) < 26 else 27, True), fill=INK)
    d.text((60, 272), p["now"]["street"], font=font(26), fill=INK)
    d.text((60, 308), f"{p['now']['city']} {p['now']['postcode']}", font=font(26), fill=INK)
    d.text((60, 344), p["now"]["country"], font=font(26), fill=INK)
    y = rows(d, 620, 250, [("Account no.", "ending 4417"), ("Statement date", "2026-10-15"),
                           ("Period", "2026-09-15 to 2026-10-14")], gap=42, label_w=190, size=23)
    y = max(y, 400)
    d.line([60, y + 20, 1040, y + 20], fill=LINE, width=2)
    y += 50
    d.text((60, y), "DATE", font=font(20, True), fill=NAVY)
    d.text((260, y), "DESCRIPTION", font=font(20, True), fill=NAVY)
    d.text((1040, y), f"AMOUNT ({p['money'][0]})", font=font(20, True), fill=NAVY, anchor="ra")
    y += 44
    for when, what, amount in p["money"][1]:
        d.text((60, y), when, font=font(24), fill=INK)
        d.text((260, y), what, font=font(24), fill=INK)
        d.text((1040, y), amount, font=font(24), fill=INK, anchor="ra")
        y += 46
    d.line([60, y + 6, 1040, y + 6], fill=LINE, width=2)
    d.rounded_rectangle([440, y + 30, 1040, y + 116], radius=10, fill="#eef2f9", outline=NAVY, width=2)
    d.text((464, y + 54), "CLOSING BALANCE", font=font(26, True), fill=NAVY)
    d.text((1016, y + 50), p["money"][2], font=font(30, True), fill=INK, anchor="ra")
    d.text((60, 1170), f"{p['bank']['name']} is a made-up bank and this statement is an example only.",
           font=font(21), fill=SOFT)
    return stamp(image, 230)


# ---- the demonstration estate: an invented owner who has died, and his heirs in four countries ----------------
#
# The same family as src/khutlisa/demonstration_estate.json. The names are written without accents, as civil
# registers and passports commonly print them; the comparison in the proof file sets accents aside.
OWNER = "Rafael Ibarra Quintanar"
FIRST_WIFE = "Pilar Solano Reyes"
WIDOW, DAUGHTER, SON, LATE_SON, GRANDDAUGHTER = ("Lucia Beltran de Ibarra", "Carmela Ibarra Solano",
                                                 "Tomas Ibarra Solano", "Esteban Ibarra Solano", "Naomi Ibarra Sato")
COUNTY = "County of Monterey, Vital Records (sample)"
ESTATE_PASSPORTS = [
    ("lucia", {"now": {"name": WIDOW, "country": "Mexico"}, "family_words": 3, "born": ("1968-02-19", "Guadalajara"),
               "signature": "Lucia Beltran de I."}),
    ("carmela", {"now": {"name": DAUGHTER, "country": "Philippines"}, "family_words": 2,
                 "born": ("1988-09-03", "Salinas"), "signature": "Carmela Ibarra S."}),
    ("tomas", {"now": {"name": SON, "country": "United Kingdom"}, "born": ("1991-01-17", "Salinas"),
               "signature": "Tomas Ibarra S."}),
    ("naomi", {"now": {"name": GRANDDAUGHTER, "country": "Japan"}, "born": ("2005-11-12", "Osaka"),
               "signature": "Naomi Ibarra Sato"}),
]


def certificate(title: str, issuer: str, number: str, sections: list[tuple[str, list[tuple[str, str]]]],
                issued: str, colour: str = NAVY) -> Image.Image:
    """A civil certificate in Khutlisa's own layout: who it is about, the people it names with the part each
    plays printed beside the name, and the date it was issued. It copies no real register's design."""
    height = 330 + sum(70 + 50 * len(pairs) for _, pairs in sections) + 150
    image = Image.new("RGB", (1300, height), PAPER)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, 1300, 150], fill=colour)
    d.text((60, 28), title.upper(), font=font(44, True), fill="white")
    d.text((60, 96), "SAMPLE certificate in Khutlisa's own layout. It copies no real register and proves nothing.",
           font=font(22), fill="#dfe6f2")
    d.text((60, 180), issuer, font=font(30, True), fill=INK)
    d.text((1240, 186), f"Certificate no. {number}", font=font(22), fill=SOFT, anchor="ra")
    y = 250
    for heading, pairs in sections:
        d.line([60, y, 1240, y], fill=LINE, width=2)
        d.text((60, y + 16), heading.upper(), font=font(22, True), fill=colour)
        y = rows(d, 60, y + 70, pairs, gap=50, label_w=330, size=28)
    d.line([60, y, 1240, y], fill=LINE, width=2)
    rows(d, 60, y + 26, [("Date of issue", issued), ("Issued by", issuer)], gap=44, label_w=330, size=24)
    return stamp(image, 220)


def estate_documents() -> dict[str, Image.Image]:
    """The eleven documents of the demonstration estate, by file name."""
    registry_mx = "Registro Civil de Guadalajara, Jalisco (sample)"
    registry_jp = "City of Osaka, Family Register Office (sample)"
    out = {
        "es_death_certificate": certificate(
            "Certificate of death", COUNTY, "SAMPLE-D-2024-0311",
            [("The person who died", [("Name of the deceased", OWNER), ("Date of death", "2024-03-14"),
                                      ("Place of death", "Salinas, California"), ("Date of birth", "1961-08-27"),
                                      ("Usual residence", "Salinas, California")]),
             ("Family", [("Surviving spouse", WIDOW)]),
             ("Registration", [("Local registrar (official)", "D. Okafor"), ("Informant (official)", "Harrowgate Sample Clinic")])],
            "2024-03-22"),
        "es_marriage_certificate": certificate(
            "Certificate of marriage", registry_mx, "SAMPLE-M-2016-0457",
            [("The two people married", [("Spouse", OWNER), ("Spouse", WIDOW), ("Date of marriage", "2016-05-21"),
                                         ("Place of marriage", "Guadalajara, Jalisco")]),
             ("Registration", [("Civil registry judge (official)", "M. Arriaga")])],
            "2016-05-21", colour="#6b2f4a"),
        "es_death_esteban": certificate(
            "Certificate of death", COUNTY, "SAMPLE-D-2019-0806",
            [("The person who died", [("Name of the deceased", LATE_SON), ("Date of death", "2019-08-02"),
                                      ("Place of death", "Salinas, California"), ("Date of birth", "1985-04-09")]),
             ("Registration", [("Local registrar (official)", "D. Okafor")])],
            "2019-08-09"),
    }
    for key, child, born, place, issuer, number in (
            ("carmela", DAUGHTER, "1988-09-03", "Salinas, California", COUNTY, "SAMPLE-B-1988-2204"),
            ("tomas", SON, "1991-01-17", "Salinas, California", COUNTY, "SAMPLE-B-1991-0153"),
            ("esteban", LATE_SON, "1985-04-09", "Salinas, California", COUNTY, "SAMPLE-B-1985-0931")):
        out[f"es_birth_{key}"] = certificate(
            "Certificate of birth", issuer, number,
            [("The child", [("Name of the child", child), ("Date of birth", born), ("Place of birth", place)]),
             ("Parents", [("Father", OWNER), ("Mother", FIRST_WIFE)]),
             ("Registration", [("Local registrar (official)", "D. Okafor")])],
            born[:4] + "-" + born[5:7] + "-28", colour=TEAL)
    out["es_birth_naomi"] = certificate(
        "Certificate of birth", registry_jp, "SAMPLE-B-2005-7718",
        [("The child", [("Name of the child", GRANDDAUGHTER), ("Date of birth", "2005-11-12"), ("Place of birth", "Osaka")]),
         ("Parents", [("Father", LATE_SON), ("Mother", "Haruka Sato")]),
         ("Registration", [("Registrar (official)", "K. Morita")])],
        "2005-11-25", colour=TEAL)
    for key, person in ESTATE_PASSPORTS:
        out[f"es_passport_{key}"] = passport_id(person)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for name, image in estate_documents().items():
        image.save(OUT / f"{name}.png", optimize=True)
        shutil.copyfile(OUT / f"{name}.png", PUBLIC / f"{name}.png")   # safe to publish: nothing on them is real
        print(f"wrote {OUT / name}.png and {PUBLIC / name}.png")
    drawn = {"staff_badge": badge, "payslip": payslip, "utility_bill": bill, "passport_id": passport_id,
             "tax_number_letter": tax_letter, "bank_statement": bank_statement}
    for person, kinds in ((AMIHAN, list(drawn)), (MARISOL, [k for k in drawn if k != "utility_bill"])):
        for kind in kinds:
            name = f"{person['prefix']}{kind}.png"
            drawn[kind](person).save(OUT / name, optimize=True)
            shutil.copyfile(OUT / name, PUBLIC / name)   # safe to publish: nothing on them is real
            print(f"wrote {OUT / name} and {PUBLIC / name}")


if __name__ == "__main__":
    main()
