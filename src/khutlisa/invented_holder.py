"""An invented holder's file: the kind of export an employer's payroll system would give, with no real person in it.

The employer is Empacadora Valle Sereno, the invented packing company the demonstration person Marisol worked
for. The file lists a few thousand former workers with uncashed pay. About three in ten have a last known
address in another country, and the countries are weighted the way California's own public file weights them
(the share of properties per country in the file dated 4 Nov 2026; only those shares were taken, no record).

Every family name is put together from syllables, every street name likewise, and every email address ends in
example.com. City names are real places. The first line of the file says that it is invented, and that line is
what marks its records as demonstration records everywhere in the product (holder_file.INVENTED_MARK).

The export is messy on purpose, the way real ones are: three lines above the column titles, titles in payroll
shorthand, amounts and dates written several ways, countries as codes or names, columns nobody needs, and some
rows that cannot be used (no amount, a date that does not exist, a country that cannot be read, a repeat).

The same seed always gives the same file.
"""
from __future__ import annotations

import csv
import io
import random
from datetime import date, timedelta

from .holder_file import INVENTED_MARK, write_excel

HOLDER = {
    "name": "Empacadora Valle Sereno",
    "street": "410 Harvest Row",
    "city": "Salinas", "region": "CA", "postcode": "93901", "country": "US",
    "contact": "Payroll office, unclaimed pay",
    "email": "payroll@valle-sereno.example",
    "phone": "+1 831 555 0142",
}
FIRST_LINE = (f"{INVENTED_MARK}. Every person and address in this file is made up. "
              "Made by scripts/make_invented_holder_file.py")
HEADER = ["EE ID", "Employee Name (Last, First MI)", "Dept", "Hire Dt", "Term Dt", "Last Known Addr 1", "Addr 2",
          "City", "St/Prov", "Zip/Postal", "Ctry", "Pay Type", "Chk No", "Chk Date", "Net Amt", "E-mail", "Phone",
          "Paperless Consent"]
DATE_COLUMNS = {3, 4, 13}

# Share of properties per country among those held for owners abroad in California's file (percent, rounded).
COUNTRY_WEIGHTS = {"JP": 19.5, "MX": 11.5, "GB": 10.3, "CA": 8.5, "CN": 6.9, "TW": 4.5, "AU": 3.3, "DE": 2.8,
                   "FR": 2.2, "IN": 2.1, "HK": 1.9, "CH": 1.4, "SG": 1.4, "PH": 1.3, "IT": 1.3, "KR": 1.2,
                   "BR": 1.2, "IE": 1.0, "NL": 0.9, "IL": 0.9, "RU": 0.8, "NZ": 0.8, "ES": 0.7, "VE": 0.7,
                   "SA": 0.7, "AR": 0.6, "SE": 0.6, "TH": 0.6, "CO": 0.5, "MY": 0.5, "BE": 0.5, "ID": 0.4,
                   "CL": 0.4, "ZA": 0.4, "AE": 0.4, "GR": 0.35, "PT": 0.2, "VN": 0.2, "PE": 0.2, "GT": 0.2}

_GIVEN = {
    "es": "Marisol Lucia Rafael Tomas Ines Beatriz Joaquin Esteban Paloma Rocio Mateo Camila Hernan Ximena Octavio Renata",
    "ja": "Haruto Yui Sota Akari Ren Mio Daiki Hina Kaito Nanami Riku Saki Takumi Aoi Yuto Kana",
    "zh": "Wei Jing Hao Mei Lin Jun Xia Bo Yan Lei Fang Tao Ning Qing Rui Shan",
    "en": "Oliver Hazel Callum Imogen Rhys Maeve Declan Freya Angus Tamsin Ewan Clara Felix Nora Hugo Ada",
    "de": "Lukas Greta Jonas Frieda Moritz Lena Anton Ida Felix Klara Emil Marta Paul Nele Oskar Thea",
    "fr": "Hugo Manon Leo Camille Jules Elise Theo Chloe Noe Margaux Louis Anais Remi Juliette Gaspard Lea",
    "tl": "Amihan Dalisay Ligaya Bayani Tala Mayumi Makisig Luningning Hiraya Datu Liwayway Marikit Isagani Malaya Dakila Sinag",
    "hi": "Arjun Priya Rohan Anika Vikram Meera Kiran Divya Nikhil Tara Sanjay Leela Aman Ishita Dev Kavya",
    "ko": "Minjun Seoyeon Jiho Hayoon Dohyun Jiwoo Siwoo Yuna Junseo Sua Eunwoo Chaewon Hajun Dain Jimin Soyul",
    "it": "Matteo Giulia Lorenzo Chiara Pietro Elisa Tommaso Bianca Davide Marta Nicolo Irene Simone Alba Fabio Noemi",
    "pt": "Tiago Beatriz Rafael Ines Duarte Leonor Vasco Matilde Caio Luana Heitor Yara Otavio Livia Breno Aline",
    "ru": "Mikhail Anya Timur Vera Lev Nina Yaroslav Zoya Gleb Lada Rodion Mila Fedor Asya Savva Dina",
    "ar": "Yusuf Layla Karim Noor Tariq Salma Idris Hana Rami Dalia Samir Lina Nabil Rana Faris Mona",
    "th": "Anan Mali Krit Dao Somchai Ploy Niran Fah Thanit Mook Pravit Nim Chai Kwan Sak Pim",
    "vi": "Minh Lan Quang Thao Duc Huong Khanh Linh Tuan Nga Phong Yen Hieu Trang Long Chi",
    "nl": "Daan Sanne Bram Lotte Jesse Fenna Ruben Mirte Thijs Noor Sem Roos Gijs Eline Stijn Vera",
    "sv": "Axel Saga Viggo Elsa Nils Maja Arvid Tove Loke Ebba Sixten Alva Ture Signe Malte Liv",
    "id": "Budi Sari Agus Dewi Rizky Putri Fajar Ayu Bayu Indah Dimas Wulan Eko Ratna Yoga Mega",
    "he": "Noam Tamar Itai Yael Omer Shira Eitan Maya Yonatan Noa Amit Liat Gil Dana Ron Hila",
    "el": "Nikos Eleni Yannis Katerina Petros Sofia Stelios Daphne Manos Ioanna Aris Zoe Thanos Melina Kostas Rena",
}
_SYLLABLES = {
    "es": ("Tol Per Val Mon Bar Cas Quin Zal Mer Sol Vel Gar".split(), "me al or an el ar i en".split(),
           "do monte rez dez lla ñuelo guez ral val cia".split()),
    "ja": ("Ha Mi Ka Sa To No Yu Ki Ta Shi Ko Ma".split(), "ra no ka mi shi ta ya ga".split(),
           "moto zaki mura gawa yama da shima no".split()),
    "zh": ("Zh Q X L H W Sh Ch F T".split(), "an ou ei ao en ang ong iu".split(), [""]),
    "en": ("Wel Har Thorn Ash Brid Pen Fair Lock Whit Marl".split(), "den ing ber stead ring wick".split(),
           "worth ley ford ham ton by well".split()),
    "de": ("Stein Wald Berg Hof Lind Kron Feld Brand".split(), "en er el ".split(), "mann huber meier bach dorf hausen".split()),
    "fr": ("Beau Mont Val Roche Clair Du Mar Lav".split(), "e a i ".split(), "mont fort ville nier lard gny".split()),
    "tl": ("Dal Vil Mac San Bat Mag Pan Lak".split(), "a i u ".split(), "say real raeg bayan ngan gat tao".split()),
    "hi": ("Sh Ch Bh Kr Tr V R M".split(), "ar an in ul iv ".split(), "ma ta pur wal kar nath dar".split()),
    "ko": ("Ch P K S Y H J N".split(), "ae o u a i".split(), "ng n k m l".split()),
    "it": ("Bel Mon Cas Ros For Gal Ver Pan".split(), "a i e o".split(), "netti rini lli ccio ldi nzo".split()),
    "pt": ("Car Fig Mon Sal Tav Per Bar Lou".split(), "a e i o".split(), "valho ueira teiro gado res eira".split()),
    "ru": ("Vol Kras Bel Mor Sok Zar Lem Tik".split(), "o a e i".split(), "kov nin sky rev din chenko".split()),
    "ar": ("Al-Ha Al-Ma Al-Sa Al-Na Al-Fa Ba Bin".split(), "r s m d z".split(), "ani awi idi oun ari".split()),
    "th": ("Sri Chai Wong Sak Thong Phon".split(), "a i".split(), "wat porn chai sak rat thep".split()),
    "vi": ("Ng Tr Ph Th L H".split(), "uy an am inh ong".split(), [""]),
    "nl": ("Van der ".split(), "Bel Hoog Zand Veld Dijk Meer".split(), "sma huis ink stra man".split()),
    "sv": ("Lind Berg Sjö Ek Dal Ny".split(), "".split() or [""], "ström qvist gren holm berg lund".split()),
    "id": ("Su Wi Har Pra Kus Hadi".split(), "ta di yo wi sa".split(), "nto wan mo yah di".split()),
    "he": ("Ben Bar Sha Tzur Gal Lev".split(), "-A i o ".split(), "mon ron vi el man".split()),
    "el": ("Papa Kara Mavro Chatzi Kon".split(), "do gi ni tha".split(), "poulos akis idis oglou atos".split()),
}
# country: (culture, cities with a region code, a postcode pattern where # is a digit and @ a letter, street word)
_PLACES: dict[str, tuple[str, list[tuple[str, str]], str, str]] = {
    "MX": ("es", [("Guadalajara", "JAL"), ("Morelia", "MICH"), ("Leon", "GTO"), ("Oaxaca de Juarez", "OAX"), ("Zamora", "MICH"), ("Tijuana", "BC")], "#####", "Calle"),
    "JP": ("ja", [("Osaka", "Osaka"), ("Nagoya", "Aichi"), ("Yokohama", "Kanagawa"), ("Sendai", "Miyagi"), ("Fukuoka", "Fukuoka")], "###-####", "chome"),
    "GB": ("en", [("Leeds", ""), ("Bristol", ""), ("Glasgow", ""), ("Cardiff", ""), ("Norwich", "")], "@@# #@@", "Road"),
    "CA": ("en", [("Vancouver", "BC"), ("Calgary", "AB"), ("Toronto", "ON"), ("Montreal", "QC"), ("Winnipeg", "MB")], "@#@ #@#", "Avenue"),
    "CN": ("zh", [("Guangzhou", "Guangdong"), ("Chengdu", "Sichuan"), ("Hangzhou", "Zhejiang"), ("Xiamen", "Fujian")], "######", "Lu"),
    "TW": ("zh", [("Taichung", ""), ("Kaohsiung", ""), ("Tainan", ""), ("Hsinchu", "")], "###", "Road"),
    "AU": ("en", [("Brisbane", "QLD"), ("Perth", "WA"), ("Adelaide", "SA"), ("Newcastle", "NSW")], "####", "Street"),
    "DE": ("de", [("Leipzig", ""), ("Bremen", ""), ("Nuernberg", ""), ("Freiburg", "")], "#####", "strasse"),
    "FR": ("fr", [("Lyon", ""), ("Nantes", ""), ("Toulouse", ""), ("Lille", "")], "#####", "Rue"),
    "IN": ("hi", [("Pune", "MH"), ("Jaipur", "RJ"), ("Kochi", "KL"), ("Lucknow", "UP")], "######", "Marg"),
    "HK": ("zh", [("Kowloon", ""), ("Sha Tin", ""), ("Tsuen Wan", "")], "", "Road"),
    "CH": ("de", [("Bern", "BE"), ("Luzern", "LU"), ("Winterthur", "ZH")], "####", "gasse"),
    "SG": ("zh", [("Singapore", "")], "######", "Avenue"),
    "PH": ("tl", [("Cebu City", "Cebu"), ("Davao City", "Davao del Sur"), ("Iloilo City", "Iloilo"), ("Quezon City", "NCR")], "####", "Street"),
    "IT": ("it", [("Bologna", "BO"), ("Verona", "VR"), ("Bari", "BA")], "#####", "Via"),
    "KR": ("ko", [("Busan", ""), ("Daegu", ""), ("Incheon", "")], "#####", "ro"),
    "BR": ("pt", [("Curitiba", "PR"), ("Recife", "PE"), ("Campinas", "SP")], "#####-###", "Rua"),
    "IE": ("en", [("Cork", ""), ("Galway", ""), ("Limerick", "")], "@## @@##", "Road"),
    "NL": ("nl", [("Utrecht", ""), ("Groningen", ""), ("Eindhoven", "")], "#### @@", "straat"),
    "IL": ("he", [("Haifa", ""), ("Beer Sheva", ""), ("Netanya", "")], "#######", "Street"),
    "RU": ("ru", [("Kazan", ""), ("Samara", ""), ("Tomsk", "")], "######", "ulitsa"),
    "NZ": ("en", [("Wellington", ""), ("Dunedin", ""), ("Hamilton", "")], "####", "Street"),
    "ES": ("es", [("Valencia", ""), ("Zaragoza", ""), ("Bilbao", "")], "#####", "Calle"),
    "VE": ("es", [("Maracaibo", ""), ("Valencia", ""), ("Barquisimeto", "")], "####", "Avenida"),
    "SA": ("ar", [("Jeddah", ""), ("Dammam", "")], "#####", "Street"),
    "AR": ("es", [("Cordoba", ""), ("Rosario", ""), ("Mendoza", "")], "@####", "Calle"),
    "SE": ("sv", [("Uppsala", ""), ("Malmoe", ""), ("Lund", "")], "### ##", "gatan"),
    "TH": ("th", [("Chiang Mai", ""), ("Khon Kaen", "")], "#####", "Soi"),
    "CO": ("es", [("Medellin", ""), ("Cali", ""), ("Bucaramanga", "")], "######", "Carrera"),
    "MY": ("zh", [("Penang", ""), ("Johor Bahru", "")], "#####", "Jalan"),
    "BE": ("nl", [("Gent", ""), ("Leuven", "")], "####", "straat"),
    "ID": ("id", [("Bandung", ""), ("Surabaya", ""), ("Yogyakarta", "")], "#####", "Jalan"),
    "CL": ("es", [("Valparaiso", ""), ("Concepcion", "")], "#######", "Calle"),
    "ZA": ("en", [("Durban", ""), ("Gqeberha", "")], "####", "Road"),
    "AE": ("ar", [("Sharjah", ""), ("Abu Dhabi", "")], "", "Street"),
    "GR": ("el", [("Thessaloniki", ""), ("Patras", "")], "### ##", "Odos"),
    "PT": ("pt", [("Porto", ""), ("Braga", "")], "####-###", "Rua"),
    "VN": ("vi", [("Da Nang", ""), ("Hue", "")], "######", "Duong"),
    "PE": ("es", [("Arequipa", ""), ("Trujillo", "")], "#####", "Jiron"),
    "GT": ("es", [("Quetzaltenango", ""), ("Antigua Guatemala", "")], "#####", "Calle"),
}
# How each country is written in the export: sometimes a code, sometimes a name, the way people type them.
_COUNTRY_SPELLINGS = {"MX": ["MX", "MX", "Mexico", "MEX", "México"], "JP": ["JP", "Japan", "JPN"], "GB": ["GB", "UK", "United Kingdom"],
                      "CA": ["CAN", "Canada"], "CN": ["CN", "China", "CHN"], "TW": ["TW", "Taiwan"], "DE": ["DEU", "Germany", "Deutschland"],
                      "PH": ["PH", "Philippines", "PHL"], "KR": ["KR", "South Korea", "Korea"], "BR": ["BR", "Brazil", "Brasil"],
                      "IN": ["IND", "India"], "IL": ["ISR", "Israel"], "ID": ["IDN", "Indonesia"]}
_HOME_CITIES = [("Salinas", "93905"), ("Salinas", "93906"), ("Watsonville", "95076"), ("Soledad", "93960"),
                ("Greenfield", "93927"), ("King City", "93930"), ("Castroville", "95012"), ("Gonzales", "93926"),
                ("Hollister", "95023"), ("Santa Maria", "93454"), ("Fresno", "93702"), ("Yuma", "85364")]
_STREET_PARTS = ("Lun Fen Tide Lark Pell Brisa Cam Vera Orla Sen Mira Alba Quill Wren Dove".split(),
                 "amar whistle wort moor worth clara dero lume vane field brook".split())
_PAY_TYPES = [("Regular Wages", 46), ("Final Paycheck", 18), ("Vacation Payout", 9), ("Piece Rate Wages", 8),
              ("Bonus", 5), ("Expense Reimb", 5), ("Per Diem", 3), ("", 4), ("Wage Adj", 2)]
_DEPTS = ["Packing", "Field", "Cooler", "Shipping", "Quality", "Sanitation", "Maintenance"]


def _family(rng: random.Random, culture: str) -> str:
    first, middle, last = _SYLLABLES[culture]
    if culture == "nl":
        return rng.choice(["Van ", "De ", ""]) + rng.choice(middle) + rng.choice(last)
    name = rng.choice(first) + rng.choice(middle).strip() + rng.choice(last)
    if culture == "es" and rng.random() < 0.45:      # two family names, as in Mexico
        name += " " + rng.choice(first) + rng.choice(middle).strip() + rng.choice(last)
    return name


def _pattern(rng: random.Random, pattern: str) -> str:
    return "".join(str(rng.randrange(10)) if c == "#" else rng.choice("ABCEGHJKLMNPRSTVWXYZ") if c == "@" else c
                   for c in pattern)


def _street(rng: random.Random, word: str) -> str:
    name = rng.choice(_STREET_PARTS[0]) + rng.choice(_STREET_PARTS[1])
    number = rng.randrange(1, 2400)
    if word in ("Calle", "Rue", "Via", "Rua", "Avenida", "Carrera", "Jalan", "Jiron", "Soi", "Odos", "Duong"):
        return f"{word} {name} {number}"
    if word in ("strasse", "gasse", "straat", "gatan", "ro", "ulitsa"):
        return f"{name}{word} {number}" if word not in ("ro", "ulitsa") else f"{name} {word} {number}"
    if word == "chome":
        return f"{rng.randrange(1, 6)}-{rng.randrange(1, 30)}-{rng.randrange(1, 20)} {name}"
    return f"{number} {name} {word}"


def _amount(rng: random.Random) -> float:
    value = rng.lognormvariate(5.2, 1.15)
    return round(min(max(value, 3.5), 9800.0), 2)


def _write_amount(rng: random.Random, value: float) -> str:
    style = rng.random()
    if style < 0.55:
        return f"{value:.2f}"
    if style < 0.8:
        return f"${value:,.2f}"
    if style < 0.9:
        return f" {value:,.2f} "
    return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{value:.0f}"


def _write_date(rng: random.Random, day: date) -> str:
    style = rng.random()
    if style < 0.6:
        return f"{day.month:02d}/{day.day:02d}/{day.year}"
    if style < 0.8:
        return day.isoformat()
    if style < 0.93:
        return f"{day.day}-{day:%b}-{day.year}"
    return f"{day.month}/{day.day}/{day:%y}"


def _check_date(rng: random.Random, today: date) -> date:
    """Pay dates spread so that every part of California's calendar has balances in it: most became payable in
    the last two and a half years, a few long ago."""
    bucket = rng.random()
    start, end = ((today - timedelta(days=880), today - timedelta(days=500)) if bucket < 0.44 else      # next remit
                  (today - timedelta(days=500), today - timedelta(days=140)) if bucket < 0.86 else      # next notice
                  (today - timedelta(days=140), today - timedelta(days=20)) if bucket < 0.95 else       # later
                  (today - timedelta(days=1700), today - timedelta(days=880)))                          # late
    return start + timedelta(days=rng.randrange(max(1, (end - start).days)))


MARISOL = {"id": "EVS-004471", "name": "Tolmedo, Marisol E", "street": "Calle Fresno 214", "street_2": "Colonia Americana",
           "city": "Guadalajara", "region": "JAL", "postcode": "44160", "country": "MX", "pay_type": "Regular Wages",
           "amount": 1284.60, "email": "marisol.tolmedo@example.com", "phone": "+52 33 5550 0188", "consent": "Y"}


def rows(count: int = 3200, seed: int = 20261113, today: date | None = None) -> list[list]:
    """The whole export as rows of cells: three lines, the column titles, then one row per uncashed payment.
    Dates are `date` objects in the three date columns of good rows, so a workbook can store them as dates."""
    rng = random.Random(seed)
    today = today or date(2026, 11, 13)
    codes = list(COUNTRY_WEIGHTS)
    weights = [COUNTRY_WEIGHTS[c] for c in codes]
    out: list[list] = [[FIRST_LINE], [f"{HOLDER['name']} : outstanding payroll checks, all pay groups"],
                       ["Run date", today.isoformat(), "", "Prepared by", "Payroll"], [], list(HEADER)]
    body: list[list] = []
    for n in range(count):
        abroad = rng.random() < 0.30
        code = rng.choices(codes, weights)[0] if abroad else "US"
        if abroad:
            culture, cities, postcode, street_word = _PLACES[code]
            city, region = rng.choice(cities)
            street = _street(rng, street_word)
            post = _pattern(rng, postcode)
            country = rng.choice(_COUNTRY_SPELLINGS.get(code, [code, code, None])) or code
            if country == code and rng.random() < 0.5:
                from .countries import COUNTRIES
                country = COUNTRIES[code]["name"]
        else:
            culture = rng.choices(["es", "es", "es", "tl", "en", "vi", "zh"], [38, 20, 10, 9, 14, 4, 5])[0]
            city, post = rng.choice(_HOME_CITIES)
            region, street, country = ("AZ" if city == "Yuma" else "CA"), _street(rng, "Street"), rng.choice(["", "", "US", "USA"])
        given = rng.choice(_GIVEN[culture].split())
        family = _family(rng, culture)
        initial = f" {rng.choice('ABCDEGJLMRST')}" if rng.random() < 0.35 else ""
        paid = _check_date(rng, today)
        hired = paid - timedelta(days=rng.randrange(60, 2600))
        pay_type = rng.choices([p for p, _ in _PAY_TYPES], [w for _, w in _PAY_TYPES])[0]
        has_email = rng.random() < (0.42 if abroad else 0.3)
        email = f"{given}.{family.split()[0]}{rng.randrange(10, 99)}@example.com".lower().replace("-", "") if has_email else ""
        email = email.encode("ascii", "ignore").decode()
        body.append([f"EVS-{rng.randrange(100, 99999):06d}", f"{family}, {given}{initial}", rng.choice(_DEPTS), hired,
                     paid + timedelta(days=rng.randrange(0, 20)), street,
                     f"Apt {rng.randrange(1, 40)}" if rng.random() < 0.18 else "", city, region, post, country,
                     pay_type, str(rng.randrange(200000, 899999)), paid, _amount(rng), email,
                     f"+{rng.randrange(1, 90)} 555 01{rng.randrange(10, 99)}" if rng.random() < 0.25 else "",
                     rng.choice(["Y", "Yes", "N", ""]) if email else ""])
    # The demonstration person, with pay that became payable in the cycle now on its way to the State.
    m = MARISOL
    marisol_paid = date(today.year - 1, 2, 14) if today >= date(today.year, 7, 1) else date(today.year - 2, 2, 14)
    body.insert(len(body) // 3, [m["id"], m["name"], "Packing", date(2008, 3, 3), date(2015, 10, 30), m["street"],
                                m["street_2"], m["city"], m["region"], m["postcode"], m["country"], m["pay_type"],
                                "418772", marisol_paid, m["amount"], m["email"], m["phone"], m["consent"]])
    # Rows that cannot be used, the kinds a real export has.
    def spoil(share: float, change) -> None:
        for row in rng.sample(body, int(len(body) * share)):
            if row[0] != m["id"]:
                change(row)

    spoil(0.008, lambda r: r.__setitem__(14, rng.choice(["", "TBD", "VOID", "see note"])))
    spoil(0.006, lambda r: r.__setitem__(14, -abs(r[14]) if isinstance(r[14], float) else r[14]))
    spoil(0.006, lambda r: r.__setitem__(13, rng.choice(["13/32/2025", "02/30/2025", "pending", ""])))
    spoil(0.004, lambda r: r.__setitem__(13, today + timedelta(days=rng.randrange(20, 300))))
    spoil(0.005, lambda r: r.__setitem__(10, rng.choice(["XX", "Overseas", "??", "N/A"])))
    spoil(0.004, lambda r: r.__setitem__(1, ""))
    spoil(0.003, lambda r: (r.__setitem__(10, ""), r.__setitem__(8, "")))
    for row in rng.sample(body, int(len(body) * 0.005)):          # the same payment exported twice
        if row[0] != m["id"]:
            body.insert(body.index(row) + 1, list(row))
    for row in body:
        if isinstance(row[14], float):
            row[14] = row[14] if row[14] < 0 else row[14]
    return out + body


def as_csv(table: list[list], seed: int = 20261113) -> bytes:
    """The export as a CSV file, with amounts and dates written the several ways a payroll system and its
    users write them."""
    rng = random.Random(seed + 1)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in table:
        cells = []
        for i, value in enumerate(row):
            if isinstance(value, date):
                cells.append(_write_date(rng, value))
            elif isinstance(value, float):
                cells.append(f"({abs(value):.2f})" if value < 0 else _write_amount(rng, value))
            else:
                cells.append(value)
        writer.writerow(cells)
    return buffer.getvalue().encode("utf-8-sig")


def as_excel(table: list[list]) -> bytes:
    """The same export as a workbook: dates stored as Excel dates, amounts as numbers."""
    return write_excel(table, DATE_COLUMNS)


def file_name(kind: str = "csv") -> str:
    return f"valle-sereno-outstanding-payroll-INVENTED.{'xlsx' if kind == 'excel' else 'csv'}"
