"""The deployment files: no secret in them, the first start builds through a temporary file, the self-test passes."""
import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
sys.path.insert(0, str(DEPLOY))

import first_start  # noqa: E402


def test_the_image_holds_no_data_and_no_credentials():
    dockerfile = (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text().split()
    assert {"data", ".env", "*.env", ".venv", ".git", ".airwallex_sandbox"} <= set(ignore)
    for name in ("ANTHROPIC_API_KEY", "AWX_API_KEY", "AWX_CLIENT_ID", "KHUTLISA_PAYER_KEY", "KHUTLISA_ID_SECRET"):
        assert not re.search(rf"^\s*(ENV|ARG)\b.*{name}", dockerfile, re.M), name
    assert "uv sync --frozen --no-dev" in dockerfile and "whisper-cli" in dockerfile and "ffmpeg" in dockerfile
    assert "npm run build" in dockerfile and 'VOLUME ["/data"]' in dockerfile and "HEALTHCHECK" in dockerfile and "/api/health" in dockerfile
    assert "USER khutlisa" in dockerfile and "COPY data" not in dockerfile


def test_every_secret_in_the_example_file_is_empty_and_the_compose_file_names_none():
    example = (DEPLOY / "khutlisa.env.example").read_text()
    values = dict(line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#"))
    for name in ("KHUTLISA_PAYER_KEY", "KHUTLISA_ID_SECRET", "ANTHROPIC_API_KEY", "AWX_CLIENT_ID", "AWX_API_KEY"):
        assert values[name] == "", name
    compose = (DEPLOY / "docker-compose.yml").read_text()
    assert "env_file" in compose and "/etc/khutlisa/khutlisa.env" in compose and "API_KEY" not in compose
    assert '"443:443"' in compose and "8000:8000" not in compose and "80:80" not in compose       # HTTPS only, the app not published
    caddy = (DEPLOY / "Caddyfile").read_text()
    assert "disable_http_challenge" in caddy and "reverse_proxy app:8000" in caddy


def test_the_entrypoint_serves_tests_and_fetches():
    script = (DEPLOY / "entrypoint.sh").read_text()
    assert script.startswith("#!/bin/sh") and (DEPLOY / "entrypoint.sh").stat().st_mode & 0o111
    for command in ("serve)", "test)", "fetch)", "uvicorn khutlisa.server:app", "deploy/selftest.py", "deploy/first_start.py"):
        assert command in script


def test_the_deploy_notes_give_the_commands_the_labels_the_stop_date_the_cost_and_the_teardown():
    text = (DEPLOY / "README.md").read_text()
    for words in ("gcloud compute instances create", "--max-run-duration=72h", "--instance-termination-action=STOP", "--labels=",
                  "gcloud compute disks create", "--allow=tcp:443", "gcloud compute firewall-rules create", "sslip.io",
                  "## Cost estimate", "Three days", "## Teardown", "gcloud compute instances delete", "gcloud compute disks delete",
                  "gcloud compute addresses delete", "gcloud compute networks delete", "ANTHROPIC_API_KEY", "## What was run",
                  "recorded_answers.json"):
        assert words in text, words
    assert "tcp:80" not in text and "\u2014" not in text


def test_zip_addresses_come_from_the_environment_or_are_read_from_the_page(monkeypatch):
    assert first_start.zip_addresses({"KHUTLISA_REGISTER_URLS": "https://x.example/01_From_a.zip\nhttps://x.example/02_From_b.zip"}) == [
        "https://x.example/01_From_a.zip", "https://x.example/02_From_b.zip"]
    page = b'<a href="/files/04_From_0_To_10.zip">a</a> <a href="https://y.example/01_From_500.zip">b</a> <a href="other.zip">c</a>'

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return page

    monkeypatch.setattr(first_start.urllib.request, "urlopen", lambda request, timeout=0: Reply())
    assert first_start.zip_addresses({"KHUTLISA_REGISTER_PAGE": "https://sco.example/dl.html"}) == [
        "https://sco.example/files/04_From_0_To_10.zip", "https://y.example/01_From_500.zip"]
    page = b"<html>Just a moment...</html>"
    with pytest.raises(RuntimeError, match="no zip links"):
        first_start.zip_addresses({})


def test_the_database_is_built_under_another_name_and_moved_into_place_only_when_whole(tmp_path):
    database = tmp_path / "registers.duckdb"
    progress = first_start.Progress(tmp_path / "build_progress.json")
    seen = []

    def loader(zip_path, con):
        seen.append((zip_path.name, database.exists(), (tmp_path / "registers.duckdb.building").exists()))
        con.execute("insert into records (source, record_id, owner_name, owner_city, owner_region, owner_postcode, owner_country_raw, "
                    "owner_country, amount, currency, holder_name, property_type) values "
                    "('US-CA', ?, 'QUILLFEATHER ODALYS', 'FRESNO', 'CA', '93701', '', 'US', 12.5, 'USD', 'A BANK', 'AC02')", [zip_path.name])
        return 1

    zips = [tmp_path / "01_From_a.zip", tmp_path / "02_From_b.zip"]
    totals = first_start.build(database, zips, progress, loader)
    assert seen == [("02_From_b.zip", False, True), ("01_From_a.zip", False, True)]      # never the final name while loading
    assert database.exists() and not (tmp_path / "registers.duckdb.building").exists()
    con = duckdb.connect(str(database), read_only=True)
    assert con.execute("select count(*) from records").fetchone()[0] == 2
    assert "owner_norm" in [row[1] for row in con.execute("pragma table_info('records')").fetchall()]     # the search columns
    con.close()
    assert totals["owner_rows"] == 2 and json.loads((tmp_path / "totals.json").read_text())["owner_rows"] == 2
    said = json.loads((tmp_path / "build_progress.json").read_text())
    assert said["stage"] == "totals" and said["rows"] == 2


def test_a_first_start_that_cannot_fetch_says_so_and_leaves_no_database(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("no network in the tests")

    monkeypatch.setattr(first_start.urllib.request, "urlopen", refuse)
    env = {"KHUTLISA_DB": str(tmp_path / "registers.duckdb"), "KHUTLISA_FETCH_SPEECH_MODEL": "0"}
    assert first_start.main(env) == 1
    said = json.loads((tmp_path / "build_progress.json").read_text())
    assert said["stage"] == "failed" and "OSError" in said["error"] and "demonstration records" in said["note"]
    assert not (tmp_path / "registers.duckdb").exists()
    assert first_start.main({**env, "KHUTLISA_FETCH_REGISTER": "0"}) == 0
    assert json.loads((tmp_path / "build_progress.json").read_text())["stage"] == "skipped"
    (tmp_path / "registers.duckdb").write_bytes(b"already here")
    assert first_start.main(env) == 0 and json.loads((tmp_path / "build_progress.json").read_text())["stage"] == "done"


def test_the_images_own_checks_pass_outside_a_container(tmp_path):
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("the web app has not been built (cd web && npm run build)")
    import shutil

    if not (shutil.which("ffmpeg") and shutil.which("whisper-cli")):
        pytest.skip("ffmpeg and whisper.cpp are in the image; this machine has not both")
    code = ("import httpx, sys\n"
            "def no_network(self, request):\n"
            "    raise AssertionError('the self-test tried to reach the network: ' + str(request.url))\n"
            "httpx.HTTPTransport.handle_request = no_network\n"
            "sys.argv = ['selftest.py']\n"
            "import runpy; runpy.run_path(sys.argv[1] if len(sys.argv) > 1 else %r, run_name='__main__')\n" % str(DEPLOY / "selftest.py"))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, cwd=ROOT,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(tmp_path)})
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert "Every required check passed." in done.stdout and "FAIL" not in done.stdout
