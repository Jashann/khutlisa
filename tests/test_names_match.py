from khutlisa.match import History, Place, score
from khutlisa.names import Person, is_organisation, normalise, orderings, romanisations, tokens


def rec(owner, city="", region="", zip_="", country="US", holder="", street=""):
    return {"owner_name": owner, "owner_norm": normalise(owner), "owner_city": city, "owner_region": region,
            "owner_postcode": zip_, "owner_country": country, "holder_name": holder, "owner_street": street, "amount": 900.0}


def test_normalise_strips_accents_and_punctuation():
    assert normalise("Núñez-O'Brien, María") == "NUNEZ OBRIEN MARIA"
    assert tokens("ESTATE OF MARIA DELA CRUZ JR") == ["MARIA", "DELA", "CRUZ"]


def test_family_keys_cover_joined_and_split_particles():
    keys = Person(given=["Maria"], family=["dela Cruz"]).family_keys()
    assert {"DELA CRUZ", "DELACRUZ", "CRUZ"} <= keys


def test_romanisations_offer_common_respellings():
    assert "ESTEFANO" in romanisations("ESTEPHANO") or "ESTEFANO" in romanisations("ESTEPHANO", 40)
    assert "BILLANUEBA" in romanisations("VILLANUEVA", 60) or "BILLANUEVA" in romanisations("VILLANUEVA", 60)


def test_orderings_put_family_first_and_last():
    o = orderings(Person(given=["Maria", "Luz"], family=["Santos"]))
    assert "SANTOS MARIA" in o and "MARIA SANTOS" in o


def test_same_person_at_a_known_address_scores_high():
    h = History(Person(["Maria", "Luz"], ["Santos", "dela Cruz"]), [Place(city="Daly City", region="CA", postcode="94015")],
                ["Kaiser Foundation Hospitals"], "PH")
    m = score(rec("SANTOS MARIA L", "DALY CITY", "CA", "94015", holder="KAISER FOUNDATION HOSPITALS"), h)
    assert m.score >= 0.75, (m.score, m.reasons, m.doubts)


def test_same_name_in_a_place_never_mentioned_scores_lower():
    h = History(Person(["Maria", "Luz"], ["Santos"]), [Place(city="Daly City", region="CA", postcode="94015")], [], "PH")
    near = score(rec("SANTOS MARIA L", "DALY CITY", "CA", "94015"), h).score
    far = score(rec("SANTOS MARIA", "FRESNO", "CA", "93701"), h).score
    assert near - far >= 0.15


def test_different_given_name_is_penalised():
    h = History(Person(["Maria"], ["Santos"]), [Place(city="Daly City", region="CA")], [], "PH")
    assert score(rec("SANTOS ROBERTO", "DALY CITY", "CA"), h).score < 0.5


def test_organisation_is_not_a_person():
    h = History(Person(["Maria"], ["Santos"]), [], [], "PH")
    assert is_organisation("SANTOS TRUCKING INC")
    assert score(rec("SANTOS MARIA TRUCKING INC"), h).score < 0.45


def test_married_name_is_found_under_either_surname():
    h = History(Person(["Luz"], ["Reyes", "Villanueva"]), [Place(postcode="90011")], [], "MX")
    assert score(rec("VILLANUEVA LUZ", zip_="90011"), h).score >= 0.6
    assert score(rec("REYES LUZ", zip_="90011"), h).score >= 0.6


def test_phonetic_key_survives_respelling():
    from khutlisa.names import phonetic
    assert phonetic("VILLANUEVA") == phonetic("BILLANUEBA")
    assert phonetic("ESTEPHANO") == phonetic("ESTEFANO")
    assert phonetic("SANTOS") != phonetic("REYES")


def test_sql_phonetic_matches_python():
    import duckdb
    from khutlisa.names import phonetic
    from khutlisa.registers import _phon_sql
    con = duckdb.connect()
    for w in ["VILLANUEVA", "ESTEPHANO", "NAKAMURA", "ZHANG", "OBRIEN", "MCDONALD", "LEE", "XIAO", "SCHMIDT", "A"]:
        assert con.execute(f"select {_phon_sql('?')}", [w] * _phon_sql('?').count('?')).fetchall()[0][0] == phonetic(w), w


def test_nicknames_work_in_both_directions():
    from khutlisa.names import NICKNAMES, nickname_forms
    for formal, short in [("WILLIAM", "BILL"), ("ROBERT", "BOB"), ("MARGARET", "PEGGY"), ("JOSE", "PEPE"),
                          ("FRANCISCO", "CHITO"), ("FRANCISCO", "PACO"), ("GUADALUPE", "LUPE"), ("ELIZABETH", "BETTY"),
                          ("ANTONIO", "TONY"), ("ANTHONY", "TONY"), ("JUNIOR", "JUN"), ("MAGDALENA", "NENA")]:
        assert short in nickname_forms(formal) and formal in nickname_forms(short), (formal, short)
    assert "BILL" in nickname_forms("WILL")               # two short forms of one name find each other
    assert "ANTONIO" not in nickname_forms("ANTHONY")     # but two formal names that share a short form do not
    assert nickname_forms("MARISOL") == frozenset()
    pairs = sum(len(v) for v in NICKNAMES.values())
    assert 60 * 2 <= pairs


def test_near_spelling_is_exactly_one_letter_and_never_the_same_name():
    from khutlisa.names import near_spelling
    assert near_spelling("MARISAL", "MARISOL") and near_spelling("MARISL", "MARISOL") and near_spelling("MARISOLL", "MARISOL")
    assert near_spelling("JUAN", "JUANA") and near_spelling("JAN", "JUAN")
    assert not near_spelling("MARISOL", "MARISOL")        # the same name is a full match, not a near one
    assert not near_spelling("MARISOL", "MARIBEL") and not near_spelling("ANA", "ANN") and not near_spelling("LI", "LIN")


def test_sql_pattern_for_near_spellings_agrees_with_the_python_rule():
    import re
    from khutlisa.names import near_spelling, near_spelling_pattern
    words = ["MARIA", "MARIO", "MARA", "MARIAN", "MRIA", "MARTA", "MARIANA", "ANA", "ANNA", "DANA", "AN", "JUAN",
             "JUANA", "JAN", "JUN", "JOHN", "JON", "JOAN", "LEE", "LEES", "LE"]
    for typed in words:
        pattern = re.compile("^(" + "|".join(near_spelling_pattern(typed) or ["(?!)"]) + ")$")
        for written in words:
            if written != typed:
                assert bool(pattern.match(written)) == near_spelling(typed, written), (typed, written)


def test_joined_particle_surnames_offer_their_split_spellings():
    from khutlisa.names import droppable_rest, split_joined
    assert split_joined("DELACRUZ") == ["DE LA CRUZ", "DELA CRUZ"]
    assert split_joined("MCDONALD") == ["MC DONALD"] and split_joined("DEAN") == []
    assert {"DE LA CRUZ", "DELA CRUZ", "DELACRUZ"} <= Person(given=[], family=["Delacruz"]).family_keys()
    assert {"DE LA CRUZ", "DELA CRUZ", "DELACRUZ", "CRUZ"} <= Person(given=[], family=["De la Cruz"]).family_keys()
    assert {"DE LA CRUZ", "DELA CRUZ", "DELACRUZ", "CRUZ"} <= Person(given=[], family=["Dela Cruz"]).family_keys()
    assert {"MC DONALD", "MCDONALD"} <= Person(given=[], family=["McDonald"]).family_keys()
    assert "CRUZ" not in Person(given=[], family=["Delacruz"]).family_keys()      # a joined name is not cut down
    assert droppable_rest("DELACRUZ") == "CRUZ" and droppable_rest("DELEON") == "LEON" and droppable_rest("DEAN") == ""


def test_score_gives_a_label_and_keeps_the_fields_other_code_reads():
    h = History(Person(["Maria", "Luz"], ["Santos"]), [Place(city="Daly City", region="CA", postcode="94015")], [], "PH")
    m = score(rec("SANTOS MARIA L", "DALY CITY", "CA", "94015"), h)
    assert m.strength in ("strong", "possible") and m.record["owner_city"] == "DALY CITY"
    assert isinstance(m.score, float) and isinstance(m.reasons, list) and isinstance(m.doubts, list)
    assert m.strength == "possible"                       # one given name in full, an initial and a postcode


def test_no_text_calls_the_number_a_probability():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    files = [root / "README.md", root / "scripts" / "measure_matcher.py", root / "web/src/screens/HistoryScreen.tsx",
             root / "web/src/components/MatchCard.tsx", *sorted((root / "src" / "khutlisa").glob("*.py"))]
    for f in files:
        text = f.read_text().lower()
        assert "calibrated" not in text, f
        if f.name in {"match.py", "names.py", "measure_matcher.py", "HistoryScreen.tsx", "MatchCard.tsx"}:
            for line in text.splitlines():
                assert "probab" not in line or "not a probability" in line or "is not a measured" in line, (f, line)
