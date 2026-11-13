# The Airwallex flow: US dollars in, local currency out

Reference for `src/khutlisa/airwallex.py`, `src/khutlisa/payouts.py`, `src/khutlisa/instructions.py`, and, for the
whole book and the batch, `src/khutlisa/corridors.py`, `src/khutlisa/book.py` and `src/khutlisa/batch.py`. A holder
(the company that reported the property) sends US dollars for one approved claim, and the claimant is paid into a
local bank account in the Philippines (PHP) or Mexico (MXN). The holder's standing instructions say what the
payment machine may decide by itself on the way. The last three sections go from one claim to everything a
holder owes abroad: what the sandbox was asked about every corridor, the plan made from the answers, and a
batch of payments to nine countries run from the plan.

Everything on this page was run against the live Airwallex sandbox on 12 and 13 November 2026, through the
application and with small scripts, and is written down as it was seen. Where the sandbox behaved differently from
the public API reference or from what we first expected, the section "What the sandbox taught us" says so.
`docs/SANDBOX_RUN_LOG.md` is the record of one real sandbox payout, `docs/SANDBOX_RUN_LOG_REPLACEMENT.md` of one
whose transfer was refused and replaced, and `docs/SANDBOX_RUN_LOG_BATCH.md` of one batch. Each is a separate
run, so their amounts differ with the rate of the moment.

Nothing here has run outside the sandbox. No real money has moved.

## What is true about the money

- There is **one** Airwallex account: Khutlisa's sandbox business account, with one US dollar global account.
  Every claim's deposit lands there. No account is opened per claimant. A deposit is tied to its claim only by
  the reference it carries, `KHUTLISA-<claim number>`.
- The holder's deposit is staged. Khutlisa itself calls the sandbox's deposit simulation when the claimant agrees
  to the plan. No action by a holder triggers it, and no holder uses Khutlisa. For real use each holder would
  have its own account at Airwallex (a connected account) in place of the shared one.
- A claim can be funded on Metal testnet in place of the staged deposit (`docs/METAL.md`). The agent pulls
  \*USDZ under the holder's mandate, the settlement is read from the chain, and the deposit is then simulated
  with the Metal transaction hash as its `reference` in place of `KHUTLISA-<claim number>`. The machine looks
  that hash up in `GET /api/v1/deposits` before it credits anything, so one hash is credited once. Everything
  after the deposit on this page is the same for both.
- Because the account is shared, the application keeps each claim honest from Airwallex's own records: it reads
  `GET /financial_transactions` for the claim's deposit, conversion and transfers after every step, sends only
  what those rows say the claim holds, and shows the rows line by line. A finished payout balances when every
  currency adds up to zero.

## The calls, in order

| Step | Call | Notes |
| --- | --- | --- |
| Login | `POST /api/v1/authentication/login` with `x-client-id` and `x-api-key` | The token lasts 30 minutes; `expires_at` is read from the reply and the client logs in again 2 minutes before it |
| Find the US dollar account | `GET /api/v1/global_accounts` | An `ACTIVE` account with `country_code` US and a `supported_features` entry for USD and LOCAL is reused. `POST /global_accounts/create` only if none exists |
| Check the bank details | `POST /api/v1/beneficiary_api_schemas/generate`, then `POST /api/v1/beneficiaries/validate` | Done when the claimant gives the account, before the holder decides, and again before the beneficiary is created |
| Quote | `POST /api/v1/fx/quotes/create` | `validity` `HR_1` for the plan. The plan shows `client_rate` and `valid_to_at` |
| Deposit (sandbox) | `POST /api/v1/simulation/deposit/create` | Sandbox only, kept in `SandboxSimulator` |
| Confirm the deposit | `GET /api/v1/deposits`, `GET /api/v1/financial_transactions?source_id=<deposit id>` | Waits for `SETTLED` and for the deposit's own ledger row, then takes the fee from the `FEE` row |
| Convert (MXN only) | `POST /api/v1/fx/conversions/create` with the `quote_id` | Looked up first with `GET /fx/conversions?request_id=` |
| Beneficiary | `POST /api/v1/beneficiaries/create` | |
| Transfer | `POST /api/v1/transfers/create` with `fee_paid_by: "BENEFICIARY"` | Looked up first with `GET /transfers?request_id=`. PHP: `source_currency` USD, `source_amount`, `quote_id`. MXN: `source_currency` MXN, `source_amount` from the conversion |
| Push the transfer (sandbox) | `POST /api/v1/simulation/transfers/{id}/transition` | `SENT`, then `PAID`; or `FAILED` when a "what if" case asks for it |
| Read it back | `GET /api/v1/transfers/{id}`, `GET /api/v1/financial_transactions?source_id=<transfer id>` | After every step, and for 24 hours after `PAID` |

The client sends no `x-api-version` header. Field names are the ones for API version 2024-09-27 and later
(`transfer_methods`, `transfer_currency`, `transfer_amount`), and the sandbox account accepted them.

## The plan, before any money moves

After the holder's approval the claimant asks for the payout plan (`POST /api/claims/{id}/payout/plan`). It takes
one quote from Airwallex, reads the account's recent transfers for the fees Airwallex really charged, and moves
nothing. It states:

- the **route** and the reason for it. Under the standing instruction "most to the claimant"
  (`airwallex.compare_routes`), every route open for the currency is worked out with the same quote and with the
  payout fee Airwallex charged on the last payout made that way (`airwallex.observed_payout_fees`, from
  `GET /api/v1/transfers`; the expected five US dollars where no such payout exists yet), and the one that
  delivers the most is chosen. A tie goes to *convert, then pay*, which fixes the local amount before any
  transfer is made. The plan lists every route compared, with its fee and what it would deliver. For MXN both
  *convert, then pay* and *pay with a locked quote* are open; for PHP only the second is, because Airwallex will
  not convert into a held PHP balance for this account. Without standing instructions, or with the rule "fixed",
  the route is the one the currency dictates (`airwallex.choose_route`). After a failed transfer the claim's
  money is back in the local currency and the route is *pay from the balance already held*;
- what the holder sends. Under the fee rule a claim below the small-claim line is topped up with Airwallex's
  expected fees, (claim + 5.00) / (1 - 0.003) rounded up to the cent, so the whole claim is left to convert;
- the incoming fee, marked as expected (0.3 percent, what Airwallex has charged on every deposit so far) until
  the deposit is in, then as booked;
- what will leave Khutlisa's account for the claimant, which is never more than arrived for the claim;
- the payout fee, expected at five US dollars or its worth in the local currency, and taken out of the amount
  sent;
- the rate, the quote id and when the lock ends;
- the amount the claimant should receive;
- what will be done if things change.

The claimant agrees to that plan by its id (`POST .../payout/confirm`). Only then does the claim move to "payment
under way" and the deposit get staged.

## The state machine

`Payout` is saved to a JSON file after every step (written to a temporary file, then swapped in).
`advance(payout, client, simulator)` does one step.

| State | What the next `advance` does | Next state |
| --- | --- | --- |
| PLANNED | Nothing. Waits for the claimant to agree to the plan | DEPOSIT_EXPECTED |
| DEPOSIT_EXPECTED | Finds the deposit by reference; with a simulator, stages it. Waits for `SETTLED` and the ledger row, reads the amount and the fee | DEPOSIT_CONFIRMED, or HELD if the amount is not the one approved |
| DEPOSIT_CONFIRMED | Stops for the holder if the deadline has passed. Reads the fee again. If the plan's quote is still valid and made for this amount, takes a short quote beside it (`MIN_1` before a conversion, `MIN_15` before a transfer that converts) and uses whichever delivers more. Otherwise takes a new one-hour quote and compares the local amount with the one agreed. Converts when the route is *convert, then pay* | CONVERTED, or HELD if the amount fell beyond the tolerance (without standing instructions: also whenever the lock ran out) |
| CONVERTED | Schema check, validate, create the beneficiary | BENEFICIARY_READY |
| BENEFICIARY_READY | Checks every earlier transfer is dead, looks for a transfer under the stored `request_id`, stops for the holder if the deadline has passed, creates a transfer only if none exists | TRANSFER_CREATED |
| TRANSFER_CREATED | Reads the transfer. With a simulator, moves it to `SENT` once it is `PROCESSING` | SENT, FAILED, or stays |
| SENT | Reads the transfer. With a simulator, moves it to `PAID`. Stores the proof and the ledger | PAID, FAILED, or stays |
| PAID | Reads the transfer again, for 24 hours and after every restart | PAID, or FAILED if the bank sent it back |
| HELD | Nothing until everyone named in `hold.needs` has agreed | the state in `hold.resume` |
| FAILED | With a `hold`: nothing until the bank details are corrected, the holder has approved and, where it is asked, the claimant has agreed. Without one (the deposit was rejected): nothing | CONVERTED or DEPOSIT_CONFIRMED |

Why a restart cannot pay twice: the request ids are created with the payout and stored before any call. Every
retry and every restart sends the same ids. Before creating a transfer or conversion the machine asks Airwallex
whether that id already made one, and if the create call still reports a duplicate it adopts the existing object.
Without a simulator the machine only reads and waits, which is how it would run in production.

## When things change

Each case below can be staged on the sandbox from the payment screen ("What if something changes on the way?").
The staging uses Airwallex's own simulation calls; what happens next is the product's ordinary behaviour.

| Change | How it is staged | What the machine does | Without standing instructions | With them |
| --- | --- | --- | --- | --- |
| The deposit arrives short | The simulated deposit is 85 percent of the amount expected | Reads what Airwallex booked | Stops. The holder approves the new amount (the first approval is withdrawn), then the claimant agrees | Within the tolerance: carries on, notes it, and checks the local amount again at the rate step. Beyond it: stops as on the left |
| The rate lock runs out | The plan's quote is made with `MIN_1` and the conversion is held back until it has expired | Takes a new one-hour quote and compares the amount with the one agreed | Stops. The claimant agrees to the new amount. The approved dollars did not change, so the approval stands | Carries on and notes old rate, new rate and shortfall if the claimant would receive no less than the tolerance allows. Otherwise stops for the claimant |
| A new quote is needed for another reason (the booked fee differs from the expected one) | Not staged; covered by tests | The same comparison | Within 0.5 percent: carries on and notes it. Beyond: stops for the claimant | The same test as the row above |
| The receiving bank refuses the transfer | After `SENT`, the transfer is pushed to `FAILED` | Waits for Airwallex to book the money back, sets the transfer aside, makes new request ids, changes the route to *pay from the balance already held*, plans a replacement from what came back | The claimant gives the bank account again, the holder approves the new terms, the claimant agrees | The claimant gives the bank account again and the holder approves it: a different account is never inside the instructions. The claimant is asked to agree only if the replacement is beyond the tolerance |
| The bank returns it after `PAID` | After `PAID`, the transfer is pushed to `FAILED` | The same. The claim stops counting as paid | The same | The same |
| The deadline passes before the money is sent | Not staged; covered by tests | Sends nothing | No deadline exists | Stops. The holder approves again, which sets a new deadline |

Each thing the machine decides by itself is kept in the payout file as a dated line with its reason and the
instruction it rests on (`Payout.decide`), and the payment screen lists them under "Decided without asking".

The sentence that explains a change is built in code from the figures. A language model may reword it; its
answer is kept only if it contains exactly the same figures. Amounts, limits and decisions never come from the
model.

The lock on a replacement: before a replacement transfer is created, every earlier transfer for the claim is read
from Airwallex again and must be `FAILED` or `CANCELLED`. If one is not, nothing is sent. The replacement has its
own `request_id`, made and saved at the moment the first transfer is set aside, and it sends exactly what the
ledger says came back.

## Corridors: what the sandbox is asked, once

`scripts/discover_corridors.py` asks the live sandbox about every country an owner in the books lives in and
keeps the answers, each with the time it was fetched, in `src/khutlisa/airwallex_corridors.json`. What the file
holds is not asked again, so the discovery runs once and is reused (`--refresh` asks everything again, `--rates`
only the rates and quotes). The client paces its calls 0.11 seconds apart, under the sandbox's documented limit
of ten requests a second for one endpoint, and a 429 is retried. The run of 13 Nov 2026 covered 196 countries in
about nine minutes.

| Asked | Call | What is kept |
| --- | --- | --- |
| Is there a local rail? | `POST /api/v1/beneficiary_api_schemas/generate` with the country, its own currency, `LOCAL`, `PERSONAL` | available or not (`SCHEMA_DEFINITION_NOT_FOUND`), the required fields, the clearing systems offered |
| Is there SWIFT in that currency, or in US dollars? | the same call with `SWIFT`, twice | the same |
| The rate today | `GET /api/v1/fx/rates/current` | units of the currency for one US dollar |
| Does the rate depend on the amount? | `POST /api/v1/fx/quotes/create`, `MIN_1`, at 10, 100, 1,000, 10,000, 100,000 and 1,000,000 US dollars | client rate, mid rate and the spread between them at each size |
| What does a lock cost? | the same at 1,000 US dollars with `MIN_1`, `MIN_15` and `HR_1` | the three rates |
| What does turning money back cost? | a quote from the currency into US dollars | what 1,000 US dollars come back as |
| Can the currency be held? | `POST /api/v1/fx/conversions/create` for one US dollar of sandbox money (`--conversions`) | settled, or refused with Airwallex's words |
| What were the fees? | `GET /api/v1/transfers` | the fee Airwallex charged on each transfer this account has made, by rail and currency |

What came back on 13 Nov 2026: a local schema for 87 countries, a SWIFT schema in the country's own currency for
133, a SWIFT schema in US dollars for 174, and none at all for 22 (among them Russia, Venezuela, Iran, Cuba and
Syria). 86 currencies were quoted. One US dollar converted into a held balance in 26 currencies and was refused
in 18 (PHP, INR, IDR, SAR and others), with "Restricted capabilities: sell USD, buy INR is not supported in
CANADA": the sandbox account is registered in Canada, and what can be held follows from that.

Three kinds of fact are kept apart in every figure of a plan (`corridors.py`):

- **Discovered**: the table above, from the sandbox.
- **Documented**: Airwallex's own pages, each with its address, read on 13 Nov 2026. The price of a transfer from
  the fee schedule for US customers (https://www.airwallex.com/en-us/terms/fee-schedule, last updated 5 Nov
  2026: 1, 2, 3 or 7 US dollars for a local transfer depending on the currency, 5 for all other currencies, 0.10
  percent for CNY, nothing within the United States and Canada, 15 for SWIFT shared and 25 for SWIFT with the
  payer option). The scheme and the "flight time" in business days from each country's payout guide
  (https://www.airwallex.com/docs/payouts/payout-network/bank-accounts: 0 to 1 for SPEI, Zengin, Faster Payments,
  EFT and InstaPay; 0 to 2 for SEPA, BECS and NEFT; 2 to 3 for UAEFTS; 0 to 3 for SWIFT everywhere). What a local
  rail does not carry (Zengin at most 1,000,000 JPY, SPEI a monthly 25,000 US dollars for each beneficiary, and
  so on), and that local CNY payouts are described for e-commerce sellers only. Which currencies can be held
  (https://www.airwallex.com/docs/transactional-fx/supported-regions-and-currencies).
- **An estimate, and marked so**: the fee of a corridor that has never been paid from this account is the
  documented price. Where a corridor has been paid, the fee that was charged is used. The two differ: the
  sandbox has charged 5.00 US dollars on local payouts in MXN, PHP and INR, about 3.00 on GBP, EUR, CAD and AUD,
  and 1,599 JPY (about 10.00) on JPY, where the fee schedule says 1, 1, 2, 1, 1, 0, 1 and 7. For a country whose
  guide was not read, the rail time is the SWIFT figure, marked as an estimate.

## The whole book: the plan

A book is everything one holder reported in California's file for owners abroad (`scripts/make_books.py` writes
them all to `data/books.parquet`: 234,883 lines with the holder, the owner's country, the amount and the property
type, and no owner's name or street). `book.plan` works out, for one book and four inputs (the small-claim line,
the tolerance, the handover date and the days an owner needs to send a document), in integer cents:

1. **The route of every claim.** Local rails where a local schema exists, a rate is quoted, the guide does not
   keep the rail for another purpose, and the claim is inside what the rail carries. Otherwise SWIFT in the
   country's currency, otherwise SWIFT in US dollars, otherwise no transfer: the property stays with the State
   process. SWIFT is always sent with the payer option, so the amount stated is the amount that arrives (with
   the shared option the banks on the way take what nobody can state beforehand).
2. **The cost.** Airwallex's 0.3 percent on what arrives and the payout fee of the claim's route. Below the
   small-claim line the holder sends (claim + fee) / (1 - 0.003), rounded up, so the claim arrives whole. From
   the line up the fees come out of the claim. A claim whose fees are at least the claim itself is not sent.
3. **What owners would receive** in their own currency, at the rate Airwallex quoted.
4. **The funding.** For each currency, "convert each payment as it is approved" against "convert once for the
   batch", both worked out with the quotes the sandbox really gave: each payment at the spread of the size
   nearest to it, the batch at the spread of the size nearest to the batch. The cheaper is taken and the
   difference is the saving. A currency that cannot be held converts inside each transfer whatever the quotes
   say. Nothing is converted for an owner before the holder has approved the claim: buying a currency and
   turning it straight back cost 1.0 percent in EUR, GBP, JPY and CAD and 2.1 percent in MXN on the day.
5. **The order of work.** A corridor needs the days an owner needs to send a document and then the longest time
   its rail takes. Corridors that still fit before the handover are worked, most dollars for each day first; the
   others are released to the State process with the Remit Report.
6. **The tolerance.** A refused transfer costs a second payout fee. For each claim the plan says whether a
   replacement would stay inside the tolerance, in which case the owner is not asked to confirm the amount, or
   would stop and ask. The corrected account and the holder's approval of it are asked for in every case.

What was measured about the funding, and it is the opposite of what one might assume: across all 86 currencies
the spread between the client rate and the mid rate was the same at every one of the six sizes (0.5 percent for
EUR, GBP, JPY, CAD, AUD and the other major currencies, 1.0 percent for MXN and its group, 1.7 to 3.3 percent for
the rest). So converting once saves nothing on the rate itself, and the plan claims no saving for it. What
converting once does is replace thousands of conversions with one for each currency and pay every owner in a
currency at one rate fixed on one day. A one-hour lock was quoted 0.12 to 0.13 percent worse than a one-minute
quote in every currency looked at.

Each decision is a card of four lines built in code from these figures (`book.cards`), and `book.changes` says
what a change of an input moved. No language model takes part.

## A batch

`batch.py` runs several approved payments together through the same payout machine.

| Step | What happens | The guard |
| --- | --- | --- |
| Written | One line for each owner with the claim, what the holder sends under the fee rule, the rail and the bank account. Nothing moves | |
| Approved | The holder approves the exact terms: every owner, amount and account, the limits, and how each currency is funded. A hash of them is kept | Before the deposit, before every conversion and before every payment the hash is worked out again; if it differs, nothing moves |
| Funded | One deposit for the whole batch, found by its reference `KHUTLISA-BATCH-<id>` before one is made. The fee is read from Airwallex's own row | The deposit must be exactly what was approved. What is left after the fee is shared out to the cent; the cent or two by which Airwallex's fee on the whole differs from the plan's fees payment by payment goes to the largest payment |
| Converted | One conversion for each currency the plan converts once, with a quote, under a request id stored when the batch was written | `GET /fx/conversions?request_id=` first; a duplicate reply adopts the conversion already made. One conversion a step, saved before the next |
| Opened | Each payment becomes an ordinary `Payout` that starts holding its share: the local currency where it was converted for the batch, US dollars with a one-hour quote where the currency cannot be held, US dollars for SWIFT in US dollars | The share (`Payout.allocation`) is the most the payment may ever send: its share, less everything Airwallex has booked for its own transfers |
| Paid | `airwallex.advance` carries each payment: schema check, validate, beneficiary, transfer, SENT, PAID | The same request ids and the same look-ups as for a single claim |
| Refused | The same path as for a single claim: the money comes back, the owner gives another account, the holder approves it, the tolerance decides whether the owner is asked to confirm the amount, one replacement is sent once Airwallex reports the first transfer dead | A payment whose bank account changed is no longer what was approved and is not sent until the holder approves it |
| Reconciled | Every row Airwallex booked for the deposit, each conversion and each transfer is read again and added up by currency | The batch balances when every payment is paid and every currency is zero |

The batch file is written whole and swapped into place after every step and each payment is its own payout
file, so `batch.advance` can be called again at any point, also by a new process. `tests/test_batch.py` runs a
batch with a fresh client for every step and with a conversion whose answer was lost, and counts one deposit,
one conversion for each held currency and one transfer for each payment.

The run of 13 Nov 2026 (`docs/SANDBOX_RUN_LOG_BATCH.md`): nine invented owners in Taiwan (SWIFT in US dollars),
Japan, Mexico, Canada, the Philippines, the United Kingdom, Germany, Australia and India; one deposit of 9,988.97
US dollars; six conversions (JPY, MXN, CAD, GBP, EUR, AUD); PHP and INR converted inside their transfers; two
transfers refused on purpose and replaced to corrected accounts; nine of nine paid in 94 seconds with 227 calls;
27 ledger rows adding up to zero in seven currencies. The plan expected 79.97 US dollars of fees and Airwallex
booked 121.98: two refusals cost a second payout fee each (25.00 and 5.00), and the local fees charged on GBP,
EUR, CAD, AUD and INR were higher than the published prices the plan had used as estimates. After that run the
fees it was charged are in the cache, and the next plan uses them as observed.

## What the sandbox taught us

1. **A deposit's fee is not there at first.** The simulation call answers `PENDING` with no fee. About two to
   three seconds later `GET /deposits` shows `SETTLED` with `fee: {amount, currency}`, and
   `GET /financial_transactions?source_id=<deposit id>` shows a `DEPOSIT` row and a separate `FEE` row. Reading
   the deposit straight after the simulation call gives a fee of zero. The machine waits for both.
2. **The incoming fee has been 0.3 percent every time** (0.36 on 120.00, 2.23 on 742.18, 5.52 on 1,840.55). It
   is booked as its own row, not netted from the deposit.
3. **A stand-alone USD to PHP conversion is refused**: HTTP 400 `unable_to_resolve_valid_value_date`,
   "Restricted capabilities: sell USD, buy PHP is not supported" for the account's country. PHP is paid with a
   quote inside the transfer. Even so, when a PHP transfer fails Airwallex books the refund **in PHP**, that
   balance can be paid from directly, and a PHP to USD quote is offered.
4. **Local payouts are not free on the sandbox.** A LOCAL payout carried USD 5.00 when funded from US dollars and
   its worth in the local currency when funded from a local balance (319.24 PHP, 92.98 MXN).
5. **`fee_paid_by` decides who is short.** By default (`PAYER`) the fee is charged on top: a 119.64 payout took
   124.64 from the wallet, with a separate `FEE` row. With `fee_paid_by: "BENEFICIARY"` exactly the
   `source_amount` leaves the wallet, the ledger has one `PAYOUT` row, and `amount_beneficiary_receives` is net of
   the fee. The machine always sends `BENEFICIARY`, so the fee comes out of the claim's own money.
6. **A new transfer is `SCHEDULED`**, and moves to `PROCESSING` by itself a few seconds later. A transition
   before then is answered with HTTP 500. The machine waits for `PROCESSING` before pushing to `SENT`.
7. **`FAILED` cannot be forced from `PROCESSING`** (HTTP 500). It can from `SENT` and from `PAID`.
8. **A failed transfer reads `FAILED` only for a moment.** The transition's own reply carries the failure (we
   asked for `INVALID_ACCOUNT_NAME_OR_NUMBER`; the reply said `failure_type` `INCORRECT_ROUTING` and
   `failure_reason` "90101: Invalid account name/number"). A read a few seconds later says `CANCELLED` with both failure fields empty. The machine keeps
   the reason from the reply that carries it.
9. **A failure or a return books a `PAYOUT_REVERSAL` row** in the transfer's currency for
   `amount_beneficiary_receives`, described as "Refund for failed payment". The payout fee is not given back.
10. **`POST /transfers/{id}/cancel` works only while the transfer is `SCHEDULED`.** After that it answers HTTP
    400 `update_unsupported`. A cancelled transfer also loses its fee.
11. **Quotes.** `MIN_1`, `MIN_15` and `HR_1` were accepted, each with its own `client_rate` (a longer lock gave a
    slightly worse rate). The reply carries `valid_from_at`, `valid_to_at`, `mid_rate` and `awx_rate`. A transfer
    that names an expired quote is refused with HTTP 400 `quote_expired`; the machine then goes back to the rate
    step instead of failing.
12. **A reused `request_id`** on a transfer is refused with HTTP 400 `duplicate_request_id`, and `details.id`
    names the transfer already made. `GET /transfers?request_id=` finds it.
13. **The schema paths.** `/api/v1/beneficiary_api_schemas/generate` returned 17 fields for a personal PHP
    account. `/api/v1/beneficiaries/schema` also answered, with no fields, so the order they are tried in
    matters.
14. **Ledger rows carry the id of what caused them**: the deposit id, the conversion id (`CONVERSION_SELL` and
    `CONVERSION_BUY`), or the transfer id (`PAYOUT`, `PAYOUT_REVERSAL`, `FEE`).
15. **A US dollar to MXN payout with a quote works too.** A transfer with `source_currency` USD, `source_amount`
    8.00 and a `MIN_15` quote was accepted: `transfer_amount` 146.93 MXN at 18.365725, `fee_amount` 5 USD,
    `amount_beneficiary_receives` 55.10 MXN. So MXN has two routes, and they can be compared.
16. **A longer lock costs a little.** Quotes for 2,316.40 US dollars taken within seconds of each other on
    13 Nov 2026: MXN 18.380585 (`MIN_1`), 18.365725 (`MIN_15`), 18.358295 (`HR_1`), 18.343435 (`HR_4`), 18.324860
    (`HR_24`), with the same `mid_rate` 18.5749; PHP 63.125044 (`MIN_1`) to 62.933510 (`HR_24`). A one-minute
    quote was 0.12 percent better than a one-hour one. This is why the machine tries a short quote beside the
    lock at the moment of use.
17. **The indicative rate.** `GET /api/v1/fx/rates/current?sell_currency=USD&buy_currency=MXN` answers with
    `rate` (the client rate) and `rate_details` for the Airwallex and client levels. It locks nothing. The match
    cards and the plan summary use it, kept for 60 seconds.
18. **Fees are on the transfer list.** `GET /api/v1/transfers` gives `fee_amount`, `fee_currency` and
    `fee_paid_by` for each recent transfer: 5 USD on every payout funded from US dollars, and between 92.95 and
    93.05 MXN and between 319.10 and 319.26 PHP on payouts funded from a held local balance.
19. **The local payout fee cannot be known to the centavo beforehand.** Five dollars at the quote's `mid_rate`
    was within 0.2 percent of what Airwallex booked (318.74 expected, 319.24 booked). The plan marks it as
    expected and the screen shows the booked figure.
20. **Some pairs are quoted the other way round.** A quote from US dollars into GBP, EUR, AUD or NZD answers
    with `currency_pair` `GBPUSD` and a `client_rate` of US dollars for one pound (1.329267, above the mid rate of
    1.32243). Multiplying dollars by that rate gives the wrong amount. `corridors.per_usd` turns such a rate
    over, and a batch works from the amounts Airwallex booked.
21. **The rate did not depend on the amount.** Quotes for 10 and for 1,000,000 US dollars carried the same
    client rate in every one of 86 currencies, and conversions of one US dollar were accepted (159 JPY, 0.75 GBP).
22. **SWIFT fees are as published.** A SWIFT transfer with `swift_charge_option` `SHARED` was charged 15 US
    dollars and one with `PAYER` 25, both taken from the amount sent when `fee_paid_by` is `BENEFICIARY`.
23. **Local fees are not as published.** See "Corridors" above: 5.00 US dollars on MXN, PHP and INR, about 3.00
    on GBP, EUR, CAD and AUD, about 10.00 on JPY. A payout from a held balance is charged in that currency.
24. **A refused SWIFT transfer in US dollars comes back in US dollars**, less its fee, and is paid again from
    that balance like any other replacement.
25. **A schema is not a promise.** `beneficiary_api_schemas/generate` returns a local CNY schema for a person
    in China, and the country guide keeps local CNY payouts for e-commerce sellers with order information. The
    plan follows the guide and routes China by SWIFT.
26. **Example bank details pass validation** when they follow the schema's patterns: a sort code and eight
    digits, a German IBAN with a correct checksum, a three-digit institution and five-digit transit number, an
    eleven-character IFSC, a six-digit BSB, a four-digit bank code with a three-digit branch. The batch builds
    each demonstration owner's account that way and checks it against the live schema before it is written.

## An estate: one deposit, several heirs

`src/khutlisa/estate_settlement.py` pays the heirs of one estate. It uses one `Payout` only for its deposit step
(reference `KHUTLISA-<claim>-S<round>`), divides what Airwallex holds after its fee among the heirs in whole
cents, and then runs one `Payout` per heir from the heir's part, with `advance` as above. Each heir's payout has
its own request ids and its own file, so the rules above (no second transfer on one id, no replacement until the
first is dead) hold heir by heir, and an error on one never reaches another. `docs/HEIRS.md` gives the rules for
fees and cents, and `docs/SANDBOX_RUN_LOG_ESTATE.md` is the record of one real run.

Seen on the sandbox on 13 Nov 2026 while building it:

20. **Pounds are quoted the other way round.** A USD to GBP quote has `currency_pair` `GBPUSD` and a
    `client_rate` of about 1.33, with `buy_amount` 15.02 for `sell_amount` 20. Multiplying dollars by that rate
    would promise more pounds than dollars. The estate code works every amount out from the quote's own
    `buy_amount` and `sell_amount`. The single-owner flow pays only MXN and PHP, both quoted from the dollar.
21. **GBP and JPY can be bought into a held balance** and paid from it by a LOCAL transfer. The payout fee was
    2.27 GBP and 1,599 JPY, not five dollars' worth. Yen have no decimals.
22. **Bank details.** GBP: `account_routing_type1` `sort_code` with six digits and an 8-digit account number,
    and the pair is checked together (20-00-00 with 55779911 passed; a random pair was refused with error code
    010). JPY: `bank_code` (4 digits), `branch_code` (3 digits), a 7-digit account number and
    `bank_account_category` Checking or Savings.
23. **A refused GBP transfer had no refund booked.** Pushed to `FAILED` after `SENT`, the transfer read `FAILED`
    and its ledger still showed only the `PAYOUT` row twenty minutes later. MXN and PHP book a `PAYOUT_REVERSAL`
    within seconds. The machine waits for the row and sends nothing more for that heir until it is there, and
    the reconciliation says the amount is outstanding.

## Limits

- A batch on the sandbox is for demonstration owners. Paying real owners of a book needs each of them to claim
  and prove the property first; the plan says what could be paid, not that anyone has been.
- The fee schedule read is the one for US customers, and the sandbox account is registered in Canada. What it
  can hold and what it is charged may differ for a holder's own account.
- Local rail limits are applied as the guides give them. A monthly limit for each beneficiary is treated as a
  limit for each claim, and a claim over it goes by SWIFT; splitting a claim over several months is not planned.
- The days a corridor needs are the days an owner needs for documents plus the rail's longest flight time. Time
  for a holder's own approvals is not counted.
- One shared account. Per-claim separation rests on the reference and the ledger rows, not on separate accounts.
- The payment is followed by reading Airwallex again (every second while it runs, less often after `PAID`).
  Webhooks are not used.
- The deposit is found by its reference among the deposits of the last 30 days.
- `beneficiaries/create` takes no `request_id`, so a crash at that step can leave a second, unused beneficiary.
  No money moves on a beneficiary.
- The payout file holds the beneficiary's name and bank account number. It lives under `data/`, which is not in
  version control.
