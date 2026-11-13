"""The prepared organisations file: what it must hold, the rule that names are read by a person before they are
shown, and a check of every stored figure against the real database when it is on this machine."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

from khutlisa.names import normalise
from khutlisa.registers import DB_PATH
from khutlisa.server import NOTABLE_PATH, shown_as_organisation

ROOT = Path(__file__).resolve().parents[1]
PAIRS = "One well-known name reported by another"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("make_notable", ROOT / "scripts" / "make_notable_organisations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def made():
    return json.loads(NOTABLE_PATH.read_text())


def test_the_file_says_which_register_file_it_was_read_from_and_when(made):
    assert made["register_file_dated"] == "2026-11-04"
    assert made["made_at"].endswith("Z") and len(made["made_at"]) == 20           # 2026-11-12T20:15:03Z
    assert made["database_modified"].endswith("Z")
    assert made["count"] == len(made["examples"])
    assert made["properties_in_these_names"] == sum(e["properties_in_this_name"] for e in made["examples"])


def test_the_leading_group_is_one_well_known_name_reported_by_another(made):
    assert made["categories"][0] == PAIRS
    pairs = [e for e in made["examples"] if e["category"] == PAIRS]
    assert made["examples"][:len(pairs)] == pairs and 6 <= len(pairs) <= 8
    assert [e["owner"] for e in pairs][0] == "STANFORD UNIVERSITY"
    assert pairs[0]["holder"] == "PRESIDENT AND FELLOWS OF HARVARD COLLEGE" and pairs[0]["amount"] == 55690.09
    for e in pairs:
        assert e["pair"] is True and e["holder_shown"] and e["properties_from_this_holder"] >= 1
        assert e["owners_on_record"] == 1                       # nobody else shares the property
    # The opening shows three of them, and nothing else.
    assert [e["opening"] for e in pairs[:3]] == [True, True, True]
    assert sum(1 for e in made["examples"] if e["opening"]) == 3
    assert len({e["owner"] for e in made["examples"]}) == len(made["examples"])   # no organisation listed twice


def test_every_owner_passes_the_organisation_rule_and_every_holder_was_read(made, script):
    for e in made["examples"]:
        assert shown_as_organisation(e["owner"]), e["owner"]
        assert e["holder"] in script.HOLDERS_READ, e["holder"]


def test_the_script_stops_at_a_name_nobody_read(script):
    script.check_names("STANFORD UNIVERSITY", "PRESIDENT AND FELLOWS OF HARVARD COLLEGE")
    with pytest.raises(SystemExit, match="organisation rule"):
        script.check_names("QUILLFEATHER ODALYS", "PRESIDENT AND FELLOWS OF HARVARD COLLEGE")
    with pytest.raises(SystemExit, match="has not been read"):
        script.check_names("STANFORD UNIVERSITY", "TESSELWOOD ODALYS PAYROLL")


def test_without_the_database_the_script_leaves_the_file_alone(script, tmp_path, capsys):
    out = tmp_path / "notable.json"
    out.write_text("kept")
    assert script.main(db=tmp_path / "absent.duckdb", out=out, if_database=True) is None
    assert out.read_text() == "kept" and "left as it is" in capsys.readouterr().out


def test_the_web_build_regenerates_the_file_first_and_does_not_fail_without_the_database(tmp_path):
    package = json.loads((ROOT / "web" / "package.json").read_text())
    assert package["scripts"]["prebuild"] == "node prebuild.mjs"
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    before = NOTABLE_PATH.read_text()
    done = subprocess.run(["node", "prebuild.mjs"], cwd=ROOT / "web", capture_output=True, text=True, timeout=60,
                          env={"PATH": __import__("os").environ["PATH"], "KHUTLISA_DB": str(tmp_path / "absent.duckdb")})
    assert done.returncode == 0, done.stderr
    assert "left as it is" in done.stdout and NOTABLE_PATH.read_text() == before


@pytest.mark.skipif(not DB_PATH.exists(), reason="California's file is not loaded on this machine")
def test_every_stored_count_and_amount_matches_the_database(made):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        assert made["owner_records"] == con.execute("select count(*) from records").fetchone()[0]
        for e in made["examples"]:
            norm = normalise(e["owner"])
            count, total = con.execute(
                "select count(*), coalesce(sum(a), 0) from (select max(amount) a from records where owner_norm = ? "
                "group by source, record_id)", [norm]).fetchone()
            assert e["properties_in_this_name"] == count, e["name"]
            assert e["total_in_this_name"] == round(total, 2), e["name"]
            if e.get("pair"):
                rows = con.execute(
                    "select amount, record_id, owner_city from records where owner_norm = ? and "
                    "starts_with(holder_name, ?) order by amount desc, holder_name, record_id", [norm, e["holder"]]).fetchall()
                assert e["properties_from_this_holder"] == len({r[1] for r in rows}), e["name"]
                owners, = con.execute("select count(*) from records where record_id = ?", [rows[0][1]]).fetchone()
                assert e["owners_on_record"] == owners == 1, e["name"]
            else:
                rows = con.execute(
                    "select amount, record_id, owner_city, holder_name from records where owner_norm = ? "
                    "order by amount desc, holder_name, record_id limit 1", [norm]).fetchall()
                assert rows[0][3].startswith(e["holder"]), e["name"]
            assert e["amount"] == round(rows[0][0], 2), e["name"]
            assert e["city"] == (rows[0][2] or "").strip(" ,"), e["name"]
    finally:
        con.close()
    assert made["total"] == round(sum(e["amount"] for e in made["examples"]), 2)
    assert made["total_in_these_names"] == round(sum(e["total_in_this_name"] for e in made["examples"]), 2)


@pytest.mark.skipif(not (DB_PATH.parent / "totals.json").exists(), reason="the totals have not been made here")
def test_the_totals_on_this_machine_have_no_line_for_north_korea():
    totals = json.loads((DB_PATH.parent / "totals.json").read_text())
    if totals.get("sample"):
        pytest.skip("only sample totals are here")
    codes = {c["code"] for c in totals["by_country"]}
    assert "KP" not in codes and "PRK" not in codes and "KR" in codes
