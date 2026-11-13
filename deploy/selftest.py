"""The image's own checks, run by `docker run --rm khutlisa test`. They need no network, no keys and no data.

Each line says what was checked. The exit code is 0 only when every required check passed. A check marked
"optional" reports and does not fail the run: voice needs the speech model, which lives in the volume, and
letters in Chinese, Japanese or Korean need a wide font.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

failed: list[str] = []


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    mark = "ok  " if ok else ("FAIL" if required else "note")
    print(f"{mark}  {name}{': ' + detail if detail and not ok else ''}", flush=True)
    if not ok and required:
        failed.append(name)


def main() -> int:
    for name in ("ANTHROPIC_API_KEY", "AWX_CLIENT_ID", "AWX_API_KEY", "KHUTLISA_PAYER_KEY"):
        os.environ.pop(name, None)                       # the checks must pass with no secret at all
    tmp = Path(tempfile.mkdtemp(prefix="khutlisa-selftest-"))
    os.environ["HOME"] = str(tmp)                        # so no key file from a home folder is read either

    from fastapi.testclient import TestClient

    from khutlisa import invented_holder, llm, notices, packet, public_demo, speech
    from khutlisa.server import WEB_DIST, create_app

    def no_model(*args, **kwargs):
        raise llm.ModelUnavailable("the self-test calls no model")

    llm.ask = no_model
    check("the built web app is in the image", (WEB_DIST / "index.html").exists(), str(WEB_DIST))
    check("ffmpeg is installed", bool(shutil.which("ffmpeg")))
    check("whisper.cpp is installed", bool(shutil.which("whisper-cli")))
    check("the speech model is in the volume", speech.engine() is not None,
          "it is fetched on first start; until then voice is off", required=False)
    fonts = packet._load_fonts()
    check("the bundled fonts load", "KhutlisaSans" in fonts and "KhutlisaSans-Bold" in fonts)
    check("a wide font for Chinese, Japanese and Korean letters is found", "KhutlisaWide" in fonts,
          "set KHUTLISA_WIDE_FONT; without it those notices are in English only", required=False)
    translations = notices.Translations(use_model=False)
    usable = [code for code in notices.LANGUAGES if code != "en" and translations.get(code)]
    check("the shipped translations of the notice pass their checks", len(usable) == len(notices.LANGUAGES) - 1,
          f"{len(usable)} of {len(notices.LANGUAGES) - 1} languages")
    model = public_demo.model_status()
    check("no language model is reachable, as in a container with no key", model["available"] is False,
          f"this machine would use {model['through']}; the checks below replace it and still pass", required=False)

    app = create_app(db_path=tmp / "no-register.duckdb", totals_path=tmp / "totals.json", claims_dir=tmp / "claims",
                     demonstration=True, payer_key="selftest", public_demo_mode=True, outreach_model=False)
    key = {"X-Payer-Key": "selftest"}
    with TestClient(app) as client:
        check("/api/health answers", client.get("/api/health").json() == {"status": "ok"})
        ready = client.get("/api/ready")
        check("/api/ready says the register is not loaded yet", ready.status_code == 503 and ready.json()["register"]["loaded"] is False)
        check("the page is served", client.get("/").status_code == 200 if (WEB_DIST / "index.html").exists() else False)
        found = client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Tolmedo"]})
        check("the search runs over the demonstration records", found.status_code == 200 and len(found.json()["matches"]) > 0)
        table = invented_holder.rows(400)
        up = client.post("/api/holder/list", headers=key, files={"file": (invented_holder.file_name(), invented_holder.as_csv(table), "text/csv")})
        check("the public demonstration refuses a file that is not the invented one", up.status_code == 403)
        loaded = client.post("/api/holder/list/invented", headers=key)
        ok = loaded.status_code == 200
        if ok:
            view = loaded.json()
            mapping = {f: c["column"] for f, c in view["list"]["proposal"]["fields"].items()}
            view = client.put(f"/api/holder/list/{view['list']['id']}/mapping", headers=key, json={"mapping": mapping}).json()
            prepared = client.post("/api/holder/notices/prepare", headers=key).json()
            ok = view["list"]["valid"] > 0 and prepared["notices"]["ready"] > 0
            letter = client.get("/api/holder/notices/batch.pdf?limit=3", headers=key)
            ok = ok and letter.status_code == 200 and letter.content[:4] == b"%PDF"
        check("the invented holder file goes from upload to letters", ok)
        mode = client.get("/api/mode").json()
        check("the public demonstration says what it is", mode["public_demo"] is True and "do not enter real" in mode["notice"])
    print("\n" + ("Every required check passed." if not failed else f"{len(failed)} check(s) failed: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
