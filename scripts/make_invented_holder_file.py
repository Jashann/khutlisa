"""Writes the invented holder's file: an employer's export of uncashed pay, with no real person in it.

    uv run python scripts/make_invented_holder_file.py            # data/samples/holder/<name>.csv and .xlsx
    uv run python scripts/make_invented_holder_file.py --rows 500 --seed 7 --out /tmp/holder

Every person, street and email address in the file is made up (src/khutlisa/invented_holder.py says how), and
its first line says so. That line is what marks the file as a demonstration file when it is uploaded.
"""
import argparse
from pathlib import Path

from khutlisa import invented_holder

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rows", type=int, default=3200, help="how many former workers (default 3200)")
    parser.add_argument("--seed", type=int, default=20261113, help="the same seed always gives the same file")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "samples" / "holder")
    args = parser.parse_args()
    table = invented_holder.rows(args.rows, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for kind, data in (("csv", invented_holder.as_csv(table, args.seed)), ("excel", invented_holder.as_excel(table))):
        path = args.out / invented_holder.file_name(kind)
        path.write_bytes(data)
        print(f"{path}: {len(table) - 5:,} rows under the column titles, {len(data):,} bytes. Invented: no real person is in it.")
