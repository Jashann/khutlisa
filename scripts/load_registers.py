"""Usage: uv run python scripts/load_registers.py <folder with California zip files>"""
import sys
import time
from pathlib import Path

from khutlisa.registers import add_search_column, connect, describe_totals, load_california, totals

folder = Path(sys.argv[1])
con = connect()
con.execute("create table if not exists loaded (name varchar, rows bigint)")
for z in sorted(folder.glob("0[1-4]_From_*.zip"), reverse=True):
    tag = z.stem
    if con.execute("select count(*) from loaded where name = ?", [tag]).fetchall()[0][0]:
        print("already loaded", tag)
        continue
    t = time.time()
    n = load_california(z, con)
    con.execute("insert into loaded values (?, ?)", [tag, n])
    print(f"{tag}: {n:,} rows in {time.time()-t:.0f}s")
add_search_column(con)
print(describe_totals(totals(con)))
