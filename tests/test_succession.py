"""The succession engine: textbook cases with the section behind each step, refusals, and properties that must
hold for every family (the shares add up to exactly 1, the dead take nothing, order does not matter)."""
import random
from datetime import date
from fractions import Fraction

import pytest

from khutlisa import succession as su

TODAY = date(2026, 11, 13)


def person(pid, alive=True, children=None, known=None):
    out = {"id": pid, "name": pid.upper(), "alive": alive, "children": children or []}
    if known is not None:
        out["children_known"] = known
    return out


def family(**kw):
    base = {"decedent": {"name": "Owner", "died_on": "2024-03-02", "domicile_country": "US", "domicile_state": "CA"},
            "disposition": "intestate", "property": "separate", "has_spouse": False, "children": [],
            "children_known": True, "parents": [], "parents_known": True, "siblings": [], "siblings_known": True,
            "predeceased_spouse_recent": False}
    base.update(kw)
    return base


def shares(result):
    assert result["computed"], result.get("refusal")
    return {h["id"]: Fraction(h["share"]) for h in result["heirs"]}


def sections(result, pid=None):
    steps = result["steps"]
    if pid is not None:
        mine = next(h for h in result["heirs"] if h["id"] == pid)["steps"]
        steps = [s for s in steps if s["n"] in mine]
    return [s["section"] for s in steps]


SPOUSE = {"id": "s1", "name": "Spouse", "alive": True}

# ---- the surviving spouse: section 6401 ------------------------------------------------------------------------


def test_spouse_and_two_children_separate_property():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE, children=[person("a"), person("b")]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 3), "a": Fraction(1, 3), "b": Fraction(1, 3)}
    assert sections(got, "s1") == ["6401(c)(3)(A)"]
    assert sections(got, "a") == ["6402(a)"]


def test_spouse_and_one_child_separate_property():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE, children=[person("a")]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 2), "a": Fraction(1, 2)}
    assert sections(got, "s1") == ["6401(c)(2)(A)"]


def test_spouse_and_the_issue_of_one_deceased_child():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE,
                            children=[person("a", False, [person("a1"), person("a2")])]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 2), "a1": Fraction(1, 4), "a2": Fraction(1, 4)}
    assert sections(got, "s1") == ["6401(c)(2)(A)"]


def test_spouse_one_child_and_issue_of_a_deceased_child():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE,
                            children=[person("a"), person("b", False, [person("b1"), person("b2")])]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 3), "a": Fraction(1, 3), "b1": Fraction(1, 6), "b2": Fraction(1, 6)}
    assert sections(got, "s1") == ["6401(c)(3)(B)"]
    assert "240" in sections(got, "b1")


def test_spouse_and_issue_of_two_deceased_children():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE,
                            children=[person("a", False, [person("a1")]), person("b", False, [person("b1")])]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 3), "a1": Fraction(1, 3), "b1": Fraction(1, 3)}
    assert sections(got, "s1") == ["6401(c)(3)(C)"]


def test_spouse_alone_takes_everything():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE), TODAY)
    assert shares(got) == {"s1": Fraction(1)}
    assert sections(got) == ["6401(c)(1)"]


def test_spouse_and_parents_no_issue():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE, parents=[person("m"), person("f")]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 2), "m": Fraction(1, 4), "f": Fraction(1, 4)}
    assert sections(got, "s1") == ["6401(c)(2)(B)"] and sections(got, "m") == ["6402(b)"]


def test_spouse_and_a_sibling_no_issue_no_parent():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE, siblings=[person("x")]), TODAY)
    assert shares(got) == {"s1": Fraction(1, 2), "x": Fraction(1, 2)}
    assert sections(got, "s1") == ["6401(c)(2)(B)"] and sections(got, "x") == ["6402(c)"]


def test_community_property_all_to_the_spouse_in_two_steps():
    got = su.compute(family(has_spouse=True, spouse=SPOUSE, property="community",
                            children=[person("a"), person("b")]), TODAY)
    assert shares(got) == {"s1": Fraction(1)}
    assert sections(got) == ["100(a)", "6401(a)"]
    assert [s["gives"] for s in got["steps"]] == [{"s1": "1/2"}, {"s1": "1/2"}]


def test_quasi_community_property_needs_a_california_domicile():
    home = family(has_spouse=True, spouse=SPOUSE, property="quasi_community", children=[person("a")])
    assert sections(su.compute(home, TODAY)) == ["101(a)", "6401(b)"]
    away = {**home, "decedent": {**home["decedent"], "domicile_country": "MX", "domicile_state": ""}}
    got = su.compute(away, TODAY)
    assert not got["computed"] and got["refusal"]["section"] == "101(a)"


def test_a_spouse_who_did_not_survive_120_hours_takes_nothing():
    got = su.compute(family(has_spouse=True, spouse={**SPOUSE, "alive": False}, children=[person("a")]), TODAY)
    assert shares(got) == {"a": Fraction(1)}
    assert got["steps"][0]["section"] == "6403(a)"


# ---- no spouse: section 6402, and section 240 -------------------------------------------------------------------

def test_children_take_equally():
    got = su.compute(family(children=[person("a"), person("b"), person("c")]), TODAY)
    assert shares(got) == {k: Fraction(1, 3) for k in "abc"}


def test_section_240_textbook_one_living_child_two_dead_one_with_issue():
    kids = [person("a"), person("b", False, [person("b1"), person("b2")]), person("c", False, [], known=True)]
    assert shares(su.compute(family(children=kids), TODAY)) == {"a": Fraction(1, 2), "b1": Fraction(1, 4),
                                                                 "b2": Fraction(1, 4)}


def test_section_240_divides_at_the_nearest_generation_with_a_living_member():
    """Every child has died. One left one child, the other three. Under section 240 the four grandchildren
    take a quarter each: the division starts at their generation, not at the children's."""
    kids = [person("a", False, [person("a1")]), person("b", False, [person("b1"), person("b2"), person("b3")])]
    got = su.compute(family(children=kids), TODAY)
    assert shares(got) == {k: Fraction(1, 4) for k in ("a1", "b1", "b2", "b3")}
    assert {h["relation"] for h in got["heirs"]} == {"grandchild"}
    assert next(h for h in got["heirs"] if h["id"] == "b2")["line"] == ["b"]


def test_section_240_goes_down_more_than_one_generation():
    kids = [person("a"), person("b", False, [person("b1"), person("b2", False, [person("b2x"), person("b2y")])])]
    assert shares(su.compute(family(children=kids), TODAY)) == {
        "a": Fraction(1, 2), "b1": Fraction(1, 4), "b2x": Fraction(1, 8), "b2y": Fraction(1, 8)}


def test_the_children_of_a_living_child_take_nothing():
    kids = [person("a", True, [person("a1")]), person("b")]
    assert shares(su.compute(family(children=kids), TODAY)) == {"a": Fraction(1, 2), "b": Fraction(1, 2)}


def test_parents_then_siblings_then_nieces():
    assert shares(su.compute(family(parents=[person("m"), person("f", False)]), TODAY)) == {"m": Fraction(1)}
    sibs = [person("x"), person("y", False, [person("y1"), person("y2")])]
    got = su.compute(family(parents=[person("m", False)], siblings=sibs), TODAY)
    assert shares(got) == {"x": Fraction(1, 2), "y1": Fraction(1, 4), "y2": Fraction(1, 4)}
    assert next(h for h in got["heirs"] if h["id"] == "y1")["relation"] == "niece or nephew"


# ---- a will or a court order ------------------------------------------------------------------------------------

def test_a_court_order_names_the_shares():
    named = [{"id": "n1", "name": "Ana", "share": "1/2"}, {"id": "n2", "name": "Ben", "share": "25%"},
             {"id": "n3", "name": "Cy", "share": "0.25"}]
    got = su.compute(family(disposition="court_order", named_shares=named), TODAY)
    assert shares(got) == {"n1": Fraction(1, 2), "n2": Fraction(1, 4), "n3": Fraction(1, 4)}
    assert sections(got) == ["6400"]


def test_named_shares_that_do_not_add_up_are_refused():
    named = [{"id": "n1", "name": "Ana", "share": "1/2"}, {"id": "n2", "name": "Ben", "share": "1/3"}]
    got = su.compute(family(disposition="will", named_shares=named), TODAY)
    assert not got["computed"] and "5/6" in got["refusal"]["reason"] and got["refusal"]["section"] == "6400"


# ---- refusals and flags -----------------------------------------------------------------------------------------

def test_refuses_a_death_before_1985():
    f = family(children=[person("a")])
    f["decedent"]["died_on"] = "1984-12-31"
    got = su.compute(f, TODAY)
    assert not got["computed"] and got["refusal"]["section"] == "6414(a)"
    assert got["refusal"]["url"].endswith("lawCode=PROB&sectionNum=6414.")


@pytest.mark.parametrize("key", sorted(su.OUTSIDE))
def test_refuses_each_fact_outside_what_was_verified(key):
    got = su.compute(family(children=[person("a")], unusual=[key]), TODAY)
    assert not got["computed"] and got["refusal"]["section"] == su.OUTSIDE[key][0]


def test_refuses_when_nobody_in_the_family_described_takes():
    got = su.compute(family(), TODAY)
    assert not got["computed"] and got["refusal"]["section"] == "6402(d)"
    got = su.compute(family(predeceased_spouse_recent=True), TODAY)
    assert got["refusal"]["section"] == "6402.5(b)"


def test_refuses_with_the_question_while_a_fact_is_missing():
    f = family(children=[person("a", None)])
    got = su.compute(f, TODAY)
    assert not got["computed"] and [q["key"] for q in got["questions"]] == ["alive"]
    assert got["questions"][0]["about"] == "a"


def test_domicile_abroad_computes_the_california_default_and_flags_it():
    f = family(has_spouse=True, spouse=SPOUSE, children=[person("a"), person("b")])
    f["decedent"].update(domicile_country="MX", domicile_state="")
    got = su.compute(f, TODAY)
    assert shares(got)["s1"] == Fraction(1, 3)
    assert got["needs_person"] and got["flags"][0]["key"] == "other_law"
    assert "has not decided which law applies" in got["flags"][0]["text"]
    at_home = su.compute(family(children=[person("a")]), TODAY)
    assert not at_home["needs_person"] and at_home["flags"] == []


# ---- the questions ----------------------------------------------------------------------------------------------

def test_questions_follow_what_the_rule_needs():
    blank = su.clean_family({"decedent": {"name": "Rosa"}})
    keys = [q["key"] for q in su.questions(blank)]
    assert keys == ["disposition", "died_on", "domicile", "has_spouse", "children"]
    f = family(has_spouse=True, spouse={**SPOUSE, "alive": True}, property=None,
               children=[person("a"), person("b", False)])
    assert [(q["key"], q["about"]) for q in su.questions(su.clean_family(f))] == [("children_of", "b")]
    f["children"][1]["children_known"] = True
    assert [q["key"] for q in su.questions(su.clean_family(f))] == ["property"]   # one child: half or all
    f["property"] = "separate"
    assert su.questions(su.clean_family(f)) == []


def test_property_is_not_asked_when_the_spouse_takes_everything_either_way():
    f = family(has_spouse=True, spouse=SPOUSE, property=None)
    assert su.questions(su.clean_family(f)) == []
    assert shares(su.compute(f, TODAY)) == {"s1": Fraction(1)}


def test_parents_and_siblings_are_asked_only_when_there_is_no_issue():
    f = family(children=[], parents=[], parents_known=False, siblings_known=False)
    assert [q["key"] for q in su.questions(su.clean_family(f))] == ["parents"]
    f.update(parents_known=True)
    assert [q["key"] for q in su.questions(su.clean_family(f))] == ["siblings"]
    with_child = family(children=[person("a")], parents_known=False, siblings_known=False)
    assert su.questions(su.clean_family(with_child)) == []


def test_married_with_nothing_known_about_the_spouse_asks_instead_of_dropping_them():
    f = su.clean_family(family(has_spouse=True, children=[person("a")]))
    assert f["spouse"] == {"id": "s1", "name": "", "alive": None, "country": ""}
    assert [q["key"] for q in su.questions(f)] == ["spouse_alive"]


def test_clean_family_keeps_ids_unique_and_ignores_rubbish():
    f = su.clean_family({"children": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}, "nonsense", 7],
                         "property": "gold", "disposition": "maybe", "unusual": ["advancement", "made up"]})
    assert [c["id"] for c in f["children"]] == ["a", "ax"]
    assert f["property"] is None and f["disposition"] is None and f["unusual"] == ["advancement"]


# ---- properties that hold for every family ----------------------------------------------------------------------

def random_person(rng, pid, depth):
    alive = rng.random() < (0.6 if depth else 0.5)
    children = []
    if depth < 3 and rng.random() < 0.6:
        children = [random_person(rng, f"{pid}{i}", depth + 1) for i in range(rng.randint(1, 3))]
    return {"id": pid, "name": pid, "alive": alive, "children": children, "children_known": True}


def random_family(rng):
    has_spouse = rng.random() < 0.5
    return family(
        has_spouse=has_spouse, spouse={"id": "s1", "name": "S", "alive": rng.random() < 0.85} if has_spouse else None,
        property=rng.choice(["separate", "separate", "community", "quasi_community"]),
        children=[random_person(rng, f"c{i}", 0) for i in range(rng.randint(0, 4))],
        parents=[{"id": f"p{i}", "name": f"p{i}", "alive": rng.random() < 0.4} for i in range(rng.randint(0, 2))],
        siblings=[random_person(rng, f"b{i}", 0) for i in range(rng.randint(0, 3))],
        predeceased_spouse_recent=rng.random() < 0.1)


def living_ids(f):
    return {p["id"] for p in su.everyone(su.clean_family(f)) if p.get("alive") is True}


@pytest.mark.parametrize("seed", range(8))
def test_every_computed_family_adds_up_to_exactly_one(seed):
    rng = random.Random(seed)
    computed = 0
    for _ in range(1500):
        f = random_family(rng)
        got = su.compute(f, TODAY)
        if not got["computed"]:
            assert got["refusal"]["reason"]
            continue
        computed += 1
        held = shares(got)
        assert sum(held.values(), Fraction(0)) == 1                   # exactly, as fractions
        assert all(v > 0 for v in held.values())
        assert set(held) <= living_ids(f)                              # the dead take nothing
        assert all(s["url"].startswith("https://leginfo.legislature.ca.gov/") for s in got["steps"])
        for heir in got["heirs"]:                                      # every share has a statute step behind it
            assert heir["steps"] and all(1 <= n <= len(got["steps"]) for n in heir["steps"])
        given = {}
        for step in got["steps"]:                                      # and the steps give exactly the shares
            for pid, part in step["gives"].items():
                given[pid] = given.get(pid, Fraction(0)) + Fraction(part)
        assert given == held
    assert computed > 900


@pytest.mark.parametrize("seed", range(4))
def test_order_of_brothers_and_sisters_and_children_does_not_change_a_share(seed):
    rng = random.Random(100 + seed)
    for _ in range(400):
        f = random_family(rng)
        a = su.compute(f, TODAY)
        g = {**f, "children": f["children"][::-1], "siblings": f["siblings"][::-1], "parents": f["parents"][::-1]}
        b = su.compute(g, TODAY)
        assert a["computed"] == b["computed"]
        if a["computed"]:
            assert shares(a) == shares(b)


@pytest.mark.parametrize("seed", range(4))
def test_structural_properties_of_section_6401_and_6402(seed):
    rng = random.Random(200 + seed)
    for _ in range(800):
        f = random_family(rng)
        got = su.compute(f, TODAY)
        if not got["computed"]:
            continue
        held = shares(got)
        spouse_lives = f["has_spouse"] and f["spouse"]["alive"]
        if spouse_lives and f["property"] != "separate":
            assert held == {"s1": Fraction(1)}
        elif spouse_lives:
            assert held["s1"] in (Fraction(1), Fraction(1, 2), Fraction(1, 3))
        relations = {h["relation"] for h in got["heirs"]} - {"spouse"}
        # issue shut out parents, and parents shut out brothers and sisters: one class takes the rest
        classes = {"issue" if r in ("child", "grandchild", "great-grandchild", "issue") else
                   "parent" if r == "parent" else "collateral" for r in relations}
        assert len(classes) <= 1
        # a living child's own descendants never take
        for child in f["children"]:
            if child["alive"]:
                below = {p["id"] for p in su.everyone({"children": child["children"]})}
                assert not below & set(held)


def test_a_living_child_never_takes_less_than_a_grandchild_through_a_dead_one():
    rng = random.Random(7)
    for _ in range(600):
        f = random_family(rng)
        got = su.compute(f, TODAY)
        if not got["computed"]:
            continue
        by = {h["id"]: h for h in got["heirs"]}
        kids = [Fraction(h["share"]) for h in by.values() if h["relation"] == "child"]
        grand = [Fraction(h["share"]) for h in by.values() if h["relation"] == "grandchild"]
        if kids and grand:
            assert min(kids) >= max(grand)
