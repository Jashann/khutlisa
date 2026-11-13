// Runs before `npm run build`. It reads the prepared organisations and the holder figures again from California's
// file, so the figures on the opening, the "who is owed" screen and the "For holders" screen are the ones in the
// database on this machine. Without the database
// (or without uv) the file that is already in the repository is left as it is and the build goes on.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const database = process.env.KHUTLISA_DB || resolve(root, "data", "registers.duckdb");

if (!existsSync(database)) {
  console.log(`${database} is not on this machine, so notable_organisations.json is left as it is.`);
  process.exit(0);
}
const run = spawnSync("uv", ["run", "python", "scripts/make_notable_organisations.py", "--if-database"], { cwd: root, stdio: "inherit" });
if (run.error) {
  console.log(`uv could not be started (${run.error.message}), so notable_organisations.json is left as it is.`);
  process.exit(0);
}
// A stop here is on purpose: a name failed the organisation rule or a holder has not been read by a person.
if (run.status !== 0) process.exit(run.status ?? 1);
// The figures on the "For holders" screen are read from the same database in the same way.
const holders = spawnSync("uv", ["run", "python", "scripts/make_holders.py", database], { cwd: root, stdio: "inherit" });
if (holders.status !== 0) process.exit(holders.status ?? 1);
// The books the "Book" screen plans from: every holder's properties for owners abroad, from the same database.
const books = spawnSync("uv", ["run", "python", "scripts/make_books.py", database], { cwd: root, stdio: "inherit" });
process.exit(books.status ?? 1);
