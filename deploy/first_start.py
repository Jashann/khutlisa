"""First start: fetch California's public file and build the register database inside the mounted volume.

The image holds no data. On a first start the volume is empty, so this script

  1. finds the four zip files of California's unclaimed property records: already in <data>/zips, or downloaded
     from the addresses in KHUTLISA_REGISTER_URLS, or, failing that, from the links on the Controller's
     download page (KHUTLISA_REGISTER_PAGE);
  2. loads them into <data>/registers.duckdb.building, adds the search columns, writes <data>/totals.json, and
     only then renames the database into place, so the server never opens a half-built file;
  3. fetches the speech model for voice, unless KHUTLISA_FETCH_SPEECH_MODEL=0.

Progress is printed and written to <data>/build_progress.json, which /api/ready reports while the server is
already up on the demonstration records. A second start finds the database and does nothing.

Environment: KHUTLISA_DB (the database to build), KHUTLISA_REGISTER_URLS (zip addresses, separated by spaces or
new lines), KHUTLISA_REGISTER_PAGE, KHUTLISA_FETCH_REGISTER=0 to skip the register, KHUTLISA_FETCH_SPEECH_MODEL=0
to skip the speech model, KHUTLISA_KEEP_ZIPS=1 to keep the downloaded zip files.

Not verified from the machine this was written on: the Controller's download page answers automated requests
with a browser check there, so the links could not be read. If the automatic fetch fails, the progress file says
so, the server keeps running on the demonstration records, and deploy/README.md gives two other ways.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

PAGE = "https://www.sco.ca.gov/upd_download_property_records.html"
ZIP_LINK = re.compile(r'href="([^"]*0[1-4]_From_[^"]*\.zip)"', re.I)
AGENT = "Mozilla/5.0 (compatible; khutlisa-first-start)"


class Progress:
    def __init__(self, path: Path):
        self.path, self.started, self.last = path, time.time(), 0.0
        self.state: dict = {"stage": "starting", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def say(self, stage: str, force: bool = True, **more) -> None:
        self.state.update({"stage": stage, "seconds": round(time.time() - self.started), **more})
        if not force and time.time() - self.last < 5:
            return
        self.last = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        os.replace(tmp, self.path)
        shown = {k: v for k, v in self.state.items() if k not in ("started_at",)}
        print("first start:", json.dumps(shown), flush=True)


def fetch(url: str, target: Path, progress: Progress, stage: str) -> None:
    """Downloads `url` to `target`, through a .part file, reporting bytes as it goes."""
    part = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            progress.say(stage, force=False, file=target.name, bytes_done=done, bytes_total=total or None,
                         percent=round(done / total * 100, 1) if total else None)
    os.replace(part, target)


def zip_addresses(env=os.environ) -> list[str]:
    given = (env.get("KHUTLISA_REGISTER_URLS") or "").split()
    if given:
        return given
    page = env.get("KHUTLISA_REGISTER_PAGE") or PAGE
    request = urllib.request.Request(page, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    found = sorted({urljoin(page, link) for link in ZIP_LINK.findall(html)})
    if not found:
        raise RuntimeError("no zip links were found on the Controller's download page")
    return found


def build(database: Path, zips: list[Path], progress: Progress, loader=None) -> dict:
    """Loads the zip files into `database` by way of a .building file. Returns the totals."""
    from khutlisa import registers

    loader = loader or registers.load_california
    building = database.with_name(database.name + ".building")
    building.unlink(missing_ok=True)
    con = registers.connect(building)
    rows = 0
    try:
        for i, z in enumerate(sorted(zips, reverse=True), start=1):
            progress.say("loading", file=z.name, files_done=i - 1, files=len(zips), rows=rows)
            rows += loader(z, con)
        progress.say("indexing", rows=rows, files_done=len(zips), files=len(zips))
        registers.add_search_column(con)
        progress.say("totals", rows=rows)
        totals = registers.totals(con)
    finally:
        con.close()
    made = {"source": f"California State Controller, unclaimed property records, fetched {time.strftime('%Y-%m-%d', time.gmtime())}",
            "url": PAGE, **totals}
    (database.parent / "totals.json").write_text(json.dumps(made, indent=1))
    os.replace(building, database)
    return made


def main(env=os.environ) -> int:
    from khutlisa import speech
    from khutlisa.registers import DB_PATH

    database = Path(env.get("KHUTLISA_DB") or DB_PATH)
    data = database.parent
    progress = Progress(data / "build_progress.json")
    status = 0
    if database.exists():
        progress.say("done", note="The register database is already in the volume.")
    elif env.get("KHUTLISA_FETCH_REGISTER", "1") == "0":
        progress.say("skipped", note="KHUTLISA_FETCH_REGISTER=0: the register is not fetched. The server runs on "
                                     "the demonstration records.")
    else:
        try:
            folder = data / "zips"
            folder.mkdir(parents=True, exist_ok=True)
            zips = sorted(folder.glob("0[1-4]_From_*.zip"))
            if not zips:
                addresses = zip_addresses(env)
                for n, url in enumerate(addresses, start=1):
                    target = folder / url.rsplit("/", 1)[-1].split("?")[0]
                    fetch(url, target, progress, f"downloading file {n} of {len(addresses)}")
                    zips.append(target)
            totals = build(database, zips, progress)
            if env.get("KHUTLISA_KEEP_ZIPS", "") != "1":
                for z in zips:
                    z.unlink(missing_ok=True)
            progress.say("done", owner_rows=totals.get("owner_rows"), note="California's file is loaded.")
        except Exception as err:                      # the server keeps running on the demonstration records
            progress.say("failed", error=f"{type(err).__name__}: {err}"[:300],
                         note="California's file could not be fetched or built. The server runs on the "
                              "demonstration records. deploy/README.md gives two other ways to load it.")
            status = 1
    model = Path(env.get("KHUTLISA_WHISPER_MODEL") or speech.MODEL_PATH)
    if not model.exists() and env.get("KHUTLISA_FETCH_SPEECH_MODEL", "1") != "0":
        try:
            model.parent.mkdir(parents=True, exist_ok=True)
            fetch(speech.MODEL_URL, model, Progress(data / "speech_progress.json"), "downloading the speech model")
        except Exception as err:
            print(f"first start: the speech model could not be fetched ({type(err).__name__}); voice is off", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
