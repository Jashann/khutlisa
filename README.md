# Khutlisa

**Live public demonstration: https://35-222-83-164.sslip.io** (until 22 November 2026). It searches California's
and Queensland's real files with private owners masked, and runs the demonstration journeys (Marisol, Amihan, the
invented holder file, the estate) with Airwallex sandbox payouts. It has no language-model key: the model's
answers for the demonstration inputs were recorded in advance and are replayed, so a visitor's own words,
documents, recordings or holder file are refused or not read, a claim can be opened only on a demonstration
record, and funding on Metal is off. `deploy/README.md` says what was run.

A company that owes money to someone who has gone home to another country uses Khutlisa to find her, check that
it is really her, and pay her at home in her own currency, inside limits the company sets once. The company is
the holder (the bank, employer or utility that owed the money in the first place); California's public unclaimed
property file is the evidence of what happens when holders cannot reach owners, and the State, which pays only
by a cheque in the post, stays the fallback off the main path.

No holder uses Khutlisa yet. Every payment runs on the Airwallex sandbox or Metal testnet, and the people followed
through a claim are a demonstration. One panel, "What is real here", in the navigation of every screen, says so.
`docs/HOW_IT_WORKS.md` explains every step and how the parts connect.

## Real numbers

- **California's file**: 95,425,821 owner records, searched whole in about two seconds. They describe 89,002,160
  properties worth $12,740,723,727; 234,883 properties worth $275,373,406 have an owner whose last known address
  is in another country, reported by 4,965 holders.
- **Queensland's register**: 2,566,684 records worth 314,265,964.51 Australian dollars, searched in the same pass
  and never added to US dollars.
- **The whole book**: Bank of America's book is 26,190 properties worth $75,493,098 in 147 countries. Raising the
  small-claim line from 250 to 1,000 US dollars moves 6,753 more claims to "the holder bears the fees"; moving the
  handover to 34 days away drops 92 corridors that need SWIFT or a slower rail, 32 million US dollars.
- **A batch on the sandbox**: nine invented owners in nine countries and currencies, one deposit, one conversion
  per currency that can be held, two transfers refused on purpose and replaced, every currency of Airwallex's
  ledger at zero (`docs/SANDBOX_RUN_LOG_BATCH.md`).
- **An estate on the sandbox**: 4,618.37 US dollars shared 1/3, 2/9, 2/9, 2/9 between heirs in Mexico, the
  Philippines, the United Kingdom and Japan, paid in four currencies in two rounds, ledger at zero
  (`docs/SANDBOX_RUN_LOG_ESTATE.md`).
- **Metal testnet**: one claim of 2,316.40 US dollars funded by a pull under a mandate and paid in Mexican pesos,
  and five pulls outside the mandate refused by the chain (`docs/METAL_RUN_LOG.md`). On testnet 1 \*USDZ stands
  for 100 US dollars of the claim, because the faucet gives an address at most 100 \*USDZ.
- **The holder's own list** (an invented file): 3,217 rows read, 937 owners abroad owed 322,462.32 US dollars in
  39 countries, 527 notices prepared in English and 15 other languages.
- **Checks across claims**: on 73 invented claims with three planted rings, 11 of 13 ring claims held before
  payment and 2 of 60 honest claims wrongly held (`docs/RINGS.md`).
- **Demonstration records**: 8 invented records beside the real files (`src/khutlisa/demonstration.json`).
- **Tests**: 833, none of which calls a model or the network.

## What it does, and what is real

| Capability | Real | Simulated or demonstration |
| --- | --- | --- |
| Search and "who is owed" | California's whole file and Queensland's register, every search live; organisations named with the amounts the files give | Real private owners are masked; the people followed are invented |
| The owner's history, by voice, typing or form | Speech transcribed on the machine (whisper.cpp); words read by a language model | The spoken example is a synthetic voice reading a prepared text |
| Proof file | Each document read twice by a model, then compared and checked in code (dates, names, machine-readable lines, issuer) | Documents are SAMPLE images; nothing is verified with the issuing authority |
| Holder's limits and handover date | Tolerance, fee rule, route rule, deadline and handover date applied in code everywhere; California's calendar read at the source | No holder has set them |
| Single payment | Every Airwallex call on the sandbox: quotes, rates, transfers, refusals, ledger lines | Sandbox money; the holder's deposit is staged with the sandbox's own call |
| Funding on Metal | Mandates, pulls and refusals are real signed transactions on Metal testnet | Testnet tokens at a scale of 1 \*USDZ to 100 US dollars; the sandbox is credited by a simulated deposit referenced by the transaction hash |
| The whole book | Computed from California's file and what the sandbox answered for 196 countries | A plan from public figures; no holder asked for one |
| Batches | One deposit, conversions and transfers on the sandbox, read back to zero | From the book: invented owners with example bank details. From the queue: the demonstration claims approved there |
| The holder's own list, notices, funnel | California's notice rules and dormancy periods read on the Controller's pages; every notice checked in code | The file is invented; notices are prepared and never sent (the holder marks them sent); translations made by a model |
| Estates | Shares computed in code under the Probate Code sections read at the source; settlement paid on the sandbox | The family and its eleven documents are invented |
| Checks across claims (risk view) | Every claim compared with every other in code, before every approval and every payment | Measured on invented claims; the points were reasoned, not fitted to real fraud |
| Public demonstration and deployment | Container built and running on Google Cloud behind Caddy with a Let's Encrypt certificate; health and readiness, per-client limits, daily model budget | The model's answers for the demonstration inputs are recorded in advance and replayed; Metal is off in the public copy |
| The State fallback | The claim packet PDF with California's requirements | Nothing is filed; California's own claim form is issued per claim and is not in it |

## How the parts work together

- **One set of standing instructions.** The tolerance, the fee rule, the route rule and the deadline are bound to
  an approval when it is given. A single payment, a batch of approved claims, a Metal mandate and an estate
  settlement all take them from that approval, so the same claim gets the same fee rule however it is paid. The
  book's plan starts from the saved limits. The handover date is shared by the holder's view, the book, the
  holder's list and its notices, and the Metal mandate's expiry.
- **Checks across claims before every approval and every payment.** The risk view (`rings.py`) keeps a salted
  fingerprint of where each claim was opened, including a claim opened from a notice. It refuses an approval of
  a held claim and refuses a payment, an estate settlement, a batch of claims (when written, when approved and
  again before its deposit) and a Metal pull for a claim held after its payment was confirmed.
- **A claim from a notice** is an ordinary claim on the holder's own record (record number `HL-...`, source
  `HOLDER`, or `DEMO` for the invented file). It appears in the holder's queue marked as from a notice, in the
  funnel, and in the risk view, and is paid on its own or in a batch with other approved claims.
- **Estates are never funded on Metal.** A Metal mandate mirrors one approval paid to one account; an estate pays
  several heirs from one deposit. Asking for Metal on an estate is refused with that reason.
- **Paying approved claims together.** In the holder's view, two or more approved claims (not estates, not funded
  on Metal) can be ticked and written into one batch: one deposit, each claim's own fee rule and account. A claim
  stays approved until the batch's deposit arrives, and goes back to approved if the batch stops before then.
- **The public demonstration** (`KHUTLISA_PUBLIC_DEMO=1`) lets a visitor approve, pay, settle, release a hold,
  write or approve a batch, or pull on Metal only for demonstration claims, accepts only the sample documents
  (also on an estate), and never takes a holder file other than the invented one.

The navigation is the same on every screen: the opening (the wordmark), "Who is owed", "For holders" (top
holders, the whole book, your own list and notices, your limits, the queue, risk), "Find your money" (the owner's
journey), "Estates", and "What is real here".

## Run it

You need [uv](https://docs.astral.sh/uv/) and Node 20 or newer.

The quick look, with no database and no keys:

```
uv sync
cd web && npm install && npm run build && cd ..
uv run uvicorn khutlisa.server:app --port 8000
```

Open http://localhost:8000. Without California's file the server searches the eight demonstration records and
says on screen what is not loaded. The holder's view is at `/payer`, the risk view at `/risk`, an owner's notice
at `/n/<code>`.

What the real thing also needs:

- **A language model** for the intake and the document reading: the `claude` program installed and signed in, or
  `ANTHROPIC_API_KEY`. Without one, the form and the search work, but no document is read, so no proof becomes
  ready (`KHUTLISA_READ_DOCUMENTS=0` switches the reading and the proof check off).
- **Speech** (optional): `brew install ffmpeg whisper-cpp` and the multilingual "small" model at
  `data/models/ggml-small.bin` (from huggingface.co/ggerganov/whisper.cpp). `KHUTLISA_WHISPER_MODEL` names
  another file.
- **The Airwallex sandbox keys**: `AWX_CLIENT_ID` and `AWX_API_KEY` in the environment, or in a file
  `~/.airwallex_sandbox` that holds those two values. They are never printed.
- **Metal testnet** (optional): `cd tools/metal && npm ci` installs the pinned Metal command line, and
  `uv run python scripts/metal_setup.py` sets up the keys, the RPC endpoint and the
  holder's account under `~/.khutlisa_metal` (`KHUTLISA_METAL_HOME` names another folder; `METAL_RPC_URL`,
  `KHUTLISA_METAL_SCALE` and `KHUTLISA_METAL_CLI` are optional). Without it, funding on Metal is off and the screens
  say so. `docs/METAL.md` has the steps.
- **The holder's key**: `KHUTLISA_PAYER_KEY`, a value of your choosing. Without it the holder's routes answer 401.

### 1. Load the data

Download the four zip files `01_From_...` to `04_From_...` from
https://www.sco.ca.gov/upd_download_property_records.html into one folder, then:

```
uv run python scripts/load_registers.py /path/to/folder-with-the-zip-files   # data/registers.duckdb, about 5 GB
uv run python scripts/make_totals.py                                         # data/totals.json, for the opening
uv run python scripts/load_queensland.py                                     # data/queensland.duckdb, from the open data portal
uv run python scripts/make_queensland_examples.py
uv run python scripts/make_books.py                                          # data/books.parquet, no owner names
uv run python scripts/discover_corridors.py --conversions                    # asks the sandbox about 196 countries
uv run python scripts/make_sample_documents.py                               # the SAMPLE documents
uv run python scripts/make_invented_holder_file.py                           # the invented holder file
```

The corridors file (`src/khutlisa/airwallex_corridors.json`) and the notice translations are in the repository,
so the book and the notices work without the keys. `npm run build` also refreshes the prepared organisation,
holder and book files from the database when it is on the machine. Queensland's data: Unclaimed monies register,
The Public Trustee of Queensland, Queensland Government Open Data Portal
(https://www.data.qld.gov.au/dataset/unclaimed-monies), used under Creative Commons Attribution 4.0; the figures
shown from it were computed by Khutlisa.

### 2. Start the API and the pages

```
KHUTLISA_PAYER_KEY=choose-one uv run uvicorn khutlisa.server:app --port 8000
cd web && npm run dev            # development, on http://localhost:5173, passing /api to port 8000
```

When `web/dist` exists the API serves it, so one process shows the whole product.

Environment variables, all optional:

| Variable | What it does |
| --- | --- |
| `KHUTLISA_DB`, `KHUTLISA_TOTALS`, `KHUTLISA_QUEENSLAND`, `KHUTLISA_BOOKS`, `KHUTLISA_WEB` | Other places for the data files and the built pages |
| `KHUTLISA_CLAIMS` | The claims folder (default `data/claims`). Claims, payouts, batches (`batches/`), estates, the risk fingerprint salt and the holder's list (`outreach/`: settings, mappings, uploads, notices) are all written there |
| `KHUTLISA_PAYER_KEY` | The holder's key |
| `KHUTLISA_ID_SECRET` | Keeps our own ids for register rows the same across restarts |
| `KHUTLISA_DEMONSTRATION=0` | Switches the demonstration records off |
| `KHUTLISA_READ_DOCUMENTS=0` | Switches the document reading off |
| `KHUTLISA_SEARCHES_PER_MINUTE`, `KHUTLISA_SEARCHES_PER_HOUR` | Searches per client address (30 and 300; 0 switches a limit off) |
| `KHUTLISA_PUBLIC_DEMO=1` | The public demonstration (above) |
| `KHUTLISA_PUBLIC_URL` | The address owners are sent to in a notice |
| `KHUTLISA_TRUSTED_PROXY=1` | Count requests by the address our own proxy passes on; never set it without that proxy |
| `KHUTLISA_MODEL_CALLS_PER_DAY` | The daily model budget in the public demonstration (150) |
| `KHUTLISA_REQUESTS_PER_MINUTE`, `KHUTLISA_REQUESTS_PER_HOUR` | Per-client limits in the public demonstration (240 and 3000) |
| `KHUTLISA_REGISTER_URLS`, `KHUTLISA_REGISTER_PAGE`, `KHUTLISA_FETCH_REGISTER`, `KHUTLISA_FETCH_SPEECH_MODEL`, `KHUTLISA_KEEP_ZIPS` | The container's first start |

### 3. Run the tests

```
uv run pytest -q
```

The tests build their own small register of invented records and use stand-ins for Airwallex and for Metal.
`tests/conftest.py` makes any call to a language model, the speech engine or the network fail, and hides any
Airwallex or Metal keys on the machine. Tests that compare a prepared file with California's file run only when
`data/registers.duckdb` is there. `tests/test_working_together.py` covers the capabilities together: estates and
Metal, the checks across claims for notice claims, estates, batches and Metal pulls, a notice claim paid alone
and in a batch, one set of instructions, and the public demonstration over every money route.

### 4. The walk-through

```
cd web && npm run build && cd ..
node scripts/walkthrough.mjs
```

It drives the built app in a real browser at 1920 by 1080, on California's file, the Airwallex sandbox and Metal
testnet, starting and stopping its own servers with fresh claims folders. It walks the main journey (the
opening, who is owed, for holders, the limits, one owner from her spoken history to her payment at home with a
refused transfer replaced inside the tolerance), then each capability: the whole book, a batch, the Queensland
search, funding on Metal, the holder's own list and an answered notice, an estate settlement, and the risk view.
Screenshots go to `docs/shots/walk/` in one numbered sequence, with `summary.json`. On every screenshot it checks
for small text, cut-off text, sideways scrolling, console errors, long dashes and internal state names, and on the
main path that no screen says the claim goes to the State. A journey whose service cannot be reached is marked
skipped with the reason. It needs Playwright with Chromium (`PLAYWRIGHT_DIR` names a folder with
`node_modules/playwright`), the `claude` program, the sandbox keys, `pdftoppm`, and the data of step 1.
`docs/WALKTHROUGH_NOTES.md` says what the last run did.

`node scripts/record_demo.mjs` records the main journey as video clips to a folder outside the repository.

### 5. One container, and a public copy

```
docker build -t khutlisa .
docker run --rm khutlisa test
uv run python deploy/selftest.py          # the same checks without a container
```

The image holds no data and no credentials. On a first start it fetches and builds California's file in the
mounted volume, with the progress on `/api/ready`, while serving the demonstration records. `deploy/README.md`
has the variables, the proxy and compose files, the Google Cloud commands, the cost and the teardown. The image
was built and is running on a Google Cloud VM (`deploy/README.md`, "What was run").

The public copy has no model key. `uv run python scripts/record_demo_answers.py` asks the model once, on a
developer's machine, for every model call the demonstration journeys make (the intake of Marisol and Amihan with
their follow-up answers, both readings of every sample document, the estate family and its documents, the holder
file's column mapping) and keeps the answers in `src/khutlisa/recorded_answers.json`, keyed by a hash of the exact
prompt and file bytes (`src/khutlisa/recorded.py`). In public demonstration mode a call with a recorded answer
gets it; any other call takes the usual path, which without a key says plainly that there is no model.
`node scripts/walkthrough.mjs` with `WALK_BASE=https://...` runs the walk against a public copy from outside.

## Deeper documents

- `docs/HOW_IT_WORKS.md`: every step, how the parts connect, what is real and what is not built.
- `docs/AIRWALLEX_FLOW.md`: the payment machine, the book's plan and the batch, step by step.
- `docs/CALIFORNIA_CLAIMS.md`: California's requirements for owners, heirs and holders, with sources (H11 is the
  holder's list: the notice and the periods).
- `docs/METAL.md` and `docs/METAL_RUN_LOG.md`: funding on Metal, and the record of the real run.
- `docs/HEIRS.md`: the Probate Code sections and the rules for an estate.
- `docs/RINGS.md`: the checks across claims, the points and the measured counts.
- `docs/SANDBOX_RUN_LOG.md`, `SANDBOX_RUN_LOG_REPLACEMENT.md`, `SANDBOX_RUN_LOG_BATCH.md`,
  `SANDBOX_RUN_LOG_ESTATE.md`: the records of real sandbox runs.
- `deploy/README.md`: the container and the public copy.
- `docs/WALKTHROUGH_NOTES.md`: the last walk-through.

## How well the search finds people

`uv run python scripts/measure_matcher.py 150` measures the matcher on the real file and prints counts only. In
the last run (150 sampled owners abroad, 2,345 searches) a record with the person's name and city came back in
the first three results for 144 of 150 when typed in the record's order, 102 of 150 given name first, 143 of 150
with the middle name dropped and 132 of 135 with one letter of the given name dropped or changed. A match is
labelled strong only when the family name and a given name match in full and one more thing ties the record to
the person; a street never counts, so a search cannot tell a stranger where a private person lived. The label
only orders the results; the proof file decides whether the money is paid.

## Where the code is

- `src/khutlisa/server.py`: the API, the search and the privacy rule. `match.py`, `names.py`: the matcher.
- `claims.py`, `claims_api.py`: claims, the terms an approval covers, the holder's queue. `instructions.py`,
  `handover.py`, `cards.py`: the limits, the handover date, the decision cards.
- `airwallex.py`, `payouts.py`: the Airwallex client and the payout machine. `metal.py`, `metal_api.py`: Metal.
- `book.py`, `corridors.py`, `batch.py`, `book_api.py`: the book, the corridors, batches (from the book and from
  the queue).
- `holder_file.py`, `holder_list.py`, `dormancy.py`, `notices.py`, `outreach.py`, `outreach_api.py`,
  `invented_holder.py`: the holder's own list and the notices.
- `succession.py`, `estates.py`, `estate_settlement.py`, `estates_api.py`: estates. `rings.py`, `rings_api.py`:
  the risk view.
- `public_demo.py`, `clients.py`: the public demonstration, health and readiness. `llm.py`: the only door to a
  language model. `speech.py`, `intake.py`: speech and the history. `documents.py`, `proof.py`, `checks.py`,
  `mrz.py`: the proof file. `queensland.py`, `registers.py`: the registers.
- `web/src/App.tsx` and `web/src/components/SiteNav.tsx`: which screen is shown for which address, and the one
  navigation. `web/src/screens/`, `web/src/outreach/`, `web/src/estate/`, `web/src/risk/`: the screens.
- `scripts/`: loading, prepared files, sandbox and testnet runs, the walk-through.
