# Funding a claim on Metal

Reference for `src/khutlisa/metal.py`, `src/khutlisa/metal_api.py` and the "Funded on Metal" panel. A holder that
approves a claim can fund it on Metal instead of by a bank deposit. Its approval then signs a Metal mandate with
the approval's own terms, Khutlisa's agent pulls the money under that mandate, and the limits are enforced by the
holder's Metal account on chain, not by Khutlisa's code. The owner is paid at home through Airwallex as before.

Everything on this page was run on Metal testnet and the Airwallex sandbox on 13 November 2026.
`docs/METAL_RUN_LOG.md` is the record, with a transaction hash for every step. No real money moved.

## The scale, stated first

**On testnet 1 \*USDZ stands for 100 US dollars of the claim.** The public faucet tops an address up to
100 \*USDZ, so a claim of 2,316.40 US dollars cannot be funded one for one. The scale is a setting
(`KHUTLISA_METAL_SCALE`, 100 unless set) and it is shown wherever an amount on Metal appears: in the panel on the
holder's view and on the payment screen, beside the approval button, in the claim's history, in the payment's
own account of what it decided, in `GET /api/metal`, and in the run log.

Mandates count in whole \*USDZ cents. At a scale of 100 one cent on chain stands for one US dollar, so an amount
is rounded up to the next cent: 2,316.40 US dollars becomes a cap of 23.17 \*USDZ, which stands for 2,317.00.
The chain therefore holds the agent to the approved amount rounded up to the next whole dollar, and the cents
below that are held by our code (the Airwallex deposit is the approved amount to the cent). At a scale of 1 the
cap is the approved amount exactly. Nothing else in the flow depends on the scale.

## The flow

1. **The holder approves and chooses Metal.** `POST /api/payer/claims/{id}/approve` with `{"funding": "metal"}`
   (the button "Approve and fund on Metal"). The approval is recorded as before, bound to its exact terms. The
   claim is marked as funded on Metal.
2. **The approval signs a mandate.** `metal.wanted_terms` builds the mandate from the approval and nothing else:

   | The approval | The mandate |
   | --- | --- |
   | The money goes to Khutlisa for this claim | One payee: Khutlisa's settlement address |
   | What the holder is to send (the claim, or under the fee rule the claim plus Airwallex's expected fees) | Per-payment cap, at the scale |
   | That amount, once | Total budget, the same figure |
   | "Never a second payment" | One payment (`--max-occurrences 1`) |
   | The deadline in the standing instructions, or the handover date to the State, whichever comes first | Expiry, to the second |
   | The claim number and the approval's terms hash | The mandate's description, and the payment id of the pull |

   `metal-agent mandate credential create` writes the credential, and `metal-agent mandate bind` puts it on the
   holder's Metal account. The command takes the expiry as a duration, so the credential is written again until
   its expiry is the deadline to the second; nothing is on chain until it is. The application then reads the
   mandate back with `metal-agent mandate status` and shows the approval's terms beside what the chain holds,
   term by term, each marked "Same" or "Differs".
3. **The owner agrees to the payout plan**, as before. Nothing has moved yet.
4. **The agent pulls.** While the payout machine expects the deposit, it asks its funding
   (`MetalFunding.before_deposit`). For a claim funded on Metal that is `metal-agent mandate pull` for the
   scaled amount, to the settlement address, under the claim number as payment id. The agent holds the mandate
   key and nothing else of the holder's.
5. **The settlement is read from the chain.** `metal-agent status <hash>` must show a successful transaction
   with exactly one transfer of that amount from the holder's account to the settlement address, and
   `metal-agent mandate verify --tx <hash>` (Metal's own check of the payment against the mandate, from the
   chain alone) must pass. Otherwise nothing is credited and the payment stops for a person.
6. **The bridge to Airwallex.** The Airwallex sandbox cannot receive \*USDZ. The transaction hash becomes the
   payout's deposit reference and is saved. The payout machine then does what it always did with a reference:
   it looks it up in `GET /api/v1/deposits`, and only if no deposit carries it does it call
   `POST /api/v1/simulation/deposit/create` for the approved US dollars with the hash as `reference`.
7. **The payout machine carries on unchanged**: fee, rate, conversion, beneficiary, transfer, ledger check.

If Metal refuses the pull, nothing moved. The payment stops, the approval is withdrawn with the reason Metal
gave, and the claim is back in the holder's queue. A new approval signs a new mandate.

## What the chain enforces, and what our code does

Enforced by the holder's Metal account, in the transaction that would move the money. Each was seen refused on
testnet, and each refusal was recorded on chain in a transaction that moved nothing:

| Limit | Metal's refusal | Seen |
| --- | --- | --- |
| Only Khutlisa's settlement address may be paid | `mandate_payee_not_listed` | yes |
| No pull above the approved amount | `mandate_cap_exceeded` | yes |
| One payment and no more than the approved amount in total | `mandate_budget_spent` | yes |
| Nothing after the holder's deadline | `mandate_expired` | yes |
| Nothing once the holder has revoked | `mandate_revoked` | yes |

Done by Khutlisa's code:

- That the mandate's terms are the approval's. The code builds the mandate from the approval, the screen shows
  the two side by side as read from the chain, and the agent does not pull under a mandate whose approval hash
  is not the live approval's.
- The tolerance. If the rate locked with the plan has run out before the pull, the agent locks a new one and
  compares what the owner would receive with what they agreed to. Outside the holder's tolerance it does not
  pull at all, writes down why, and asks the owner. Inside it, it pulls and notes the new rate.
- The bridge: reading the settlement, crediting it once at Airwallex, and never letting one hash fund two
  claims.
- Everything after the money has arrived at Airwallex.

A test (`test_a_pull_above_the_cap_is_refused_by_the_chain_even_if_our_own_code_asked_for_it`) makes our own
code ask for more than was approved; the chain refuses and nothing is credited.

## Tied to the agent's decisions

- **Standing limits become on-chain terms.** The fee rule decides what the holder sends, which is the cap. The
  deadline is the expiry. "Never another account, a larger amount or a second payment" is the payee list, the
  cap and the single payment.
- **A refused bank transfer never causes a second pull.** A replacement is paid from what Airwallex booked back
  for the claim. Re-approving the corrected bank account signs no new mandate and pulls nothing. If the agent
  tried anyway, the chain refuses: the mandate's budget is spent. Seen on testnet as `mandate_budget_spent`, and
  covered by `test_a_refused_bank_transfer_is_replaced_from_what_came_back_and_the_mandate_is_never_pulled_again`.
- **Outside the tolerance the agent does not pull.** Covered by tests with the fake chain. It was not staged on
  testnet, because it needs a rate lock to run out between the owner's agreement and the pull.
- **Revocation returns the claim.** Before the payment has started, `POST .../metal/revoke` revokes on chain and
  withdraws the approval at once. If the holder revokes from its own wallet while the payment is starting, the
  application does not know; the agent's pull is refused by Metal with `mandate_revoked`, and that sends the
  claim back. Both were run on testnet.

## Guarantees that still hold

- **Never pays twice.** The pull's payment id is the claim number. The command line remembers what it sent under
  its home directory (`~/.khutlisa_metal/home`, always the same), so the same pull asked for again reports
  "already paid, nothing sent" with the first transaction. If that memory were lost, a new pull would be refused
  by the chain, because the budget is spent. The Airwallex side keeps its own request ids as before.
- **The same hash never funds twice.** The hash is saved as the deposit reference before any deposit is made, and
  the machine looks it up in Airwallex's deposits first, so a restart adopts the deposit it finds. A file,
  `<claims>/metal_funded.json`, records which claim each hash funded, and a hash that belongs to one claim is
  refused for another.
- **Restart-safe.** What happened on Metal is kept per claim in `<claims>/<claim id>/metal.json`, written whole
  and swapped into place. A stop between the pull and the deposit is picked up on start: no second pull, one
  deposit (`test_a_restart_between_the_pull_and_the_deposit_neither_pulls_nor_credits_twice`).
- **Approval bound to terms.** A mandate carries the hash of the approval it was signed for. If the approval is
  withdrawn or replaced, the agent does not pull under the old mandate, and the next approval revokes it before
  binding a new one.
- **Ledger reconciliation.** Unchanged. In both paid runs every line Airwallex booked added up to zero.

## Reproduce it from a fresh clone

Node 22.13 or newer, `uv`, and Airwallex sandbox keys in `~/.airwallex_sandbox` as for the rest of the project.

```bash
# 1. The Metal command line, pinned (see "What Metal taught us", 1)
cd tools/metal && npm install && cd ../..

# 2. Testnet keys, funds, an RPC endpoint and the holder's Metal account. Asks the public faucet three times
#    and waits a minute between grants. Writes ~/.khutlisa_metal (mode 700, files 600). Safe to run again.
uv run python scripts/metal_setup.py

# 3. The tests (a fake chain; no network)
uv run pytest -q

# 4. The real run: Metal testnet and the Airwallex sandbox, through the application's routes
uv run python scripts/metal_run.py
uv run python scripts/metal_log.py          # writes docs/METAL_RUN_LOG.md from the record of that run

# 5. On screen
cd web && npm install && npm run build && cd ..
KHUTLISA_PAYER_KEY=choose-a-key uv run uvicorn khutlisa.server:app --port 8000
# open http://localhost:8000/payer, approve a claim with "Approve and fund on Metal"
```

What `scripts/metal_setup.py` does, in the commands it runs (every one with `--network testnet`):

```bash
metal-agent key create --out ~/.khutlisa_metal/agent/key.json          # Khutlisa's agent
metal-agent key create --out ~/.khutlisa_metal/settlement/key.json     # the settlement address
metal-agent fund <agent address>                                       # 100 *USDZ from the faucet
metal-agent pay https://rpc-testnet.metalntwx.com/v1 --key ~/.khutlisa_metal/agent/key.json --method POST \
  --body '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'
#   pays 1 *USDZ; the endpoint's URL comes back in the rpc-aas-endpoint header and is stored in
#   ~/.khutlisa_metal/rpc_url. The URL is its own credential and is never printed.
metal-agent account create --out ~/.khutlisa_metal/holder/owner-key.json   # the holder's Metal account
metal-agent fund <holder's account address>                            # what the holder can be pulled for
```

Settings, all optional:

| Variable | Meaning | Default |
| --- | --- | --- |
| `KHUTLISA_METAL_HOME` | Where the keys, the RPC endpoint and `config.json` are | `~/.khutlisa_metal` |
| `METAL_RPC_URL` | The RPC endpoint, in place of the file `rpc_url` | the file |
| `KHUTLISA_METAL_SCALE` | US dollars one \*USDZ stands for | 100 |
| `KHUTLISA_METAL_CLI` | The `metal-agent` command | `tools/metal/node_modules/.bin/metal-agent` |

Without `~/.khutlisa_metal/config.json` the server runs as before: `GET /api/metal` says Metal is not set up, the
button is not offered, and an approval that asks for Metal is refused before anything is approved.

## Routes

| Route | Who | What |
| --- | --- | --- |
| `GET /api/metal` | anyone | Whether Metal is set up, the network, the scale, the two addresses |
| `POST /api/payer/claims/{id}/approve` with `{"funding": "metal"}` | holder | Approve and sign the mandate |
| `GET /api/claims/{id}/metal` | whoever holds the claim's number | The panel: mandate, terms, pull, verification, refusals |
| `GET /api/payer/claims/{id}/metal` | holder | The same, with what the holder can do |
| `POST /api/payer/claims/{id}/metal/mandate` | holder | Sign the mandate again if signing did not complete |
| `POST /api/payer/claims/{id}/metal/revoke` | holder | Revoke the mandate on chain |
| `POST /api/payer/claims/{id}/metal/attempt` with `{"case": ...}` | holder | Tell the agent to overstep (`over_cap`, `wrong_payee`, `second_pull`) and see Metal refuse |
| `POST /api/payer/claims/{id}/metal/verify` | holder | Run `metal-agent mandate verify` over the whole mandate |

No route returns a key, a credential file or the RPC endpoint. The staged attempts are real pulls signed with
the mandate key. They are built so that the mandate cannot allow them (one cent above the cap, another payee, a
second pull only after the first has paid), and if Metal ever paid one the application says so loudly.

## The code

New files:

- `src/khutlisa/metal.py`: the scale and the terms (pure functions), `MetalCli` (shells out to `metal-agent`),
  `FakeMetal` (the same calls over an in-memory chain that enforces the same limits, for the tests), and
  `MetalFunding` (the mandate, the pull, the settlement check, the hand-over to the payout machine, the view).
- `src/khutlisa/metal_api.py`: the routes above.
- `tools/metal/package.json` and its lock file: the command line, pinned.
- `scripts/metal_setup.py`, `scripts/metal_run.py`, `scripts/metal_log.py`; the browser steps are part 3 of `scripts/walkthrough.mjs`.
- `tests/test_metal.py`: 29 tests.
- `web/src/metal.ts`, `web/src/components/MetalPanel.tsx`, `web/src/metal.css`.
- `docs/METAL.md`, `docs/METAL_RUN_LOG.md`; the screens are in `docs/shots/walk/`.

Existing files that had to change, and why:

| File | Change | Why |
| --- | --- | --- |
| `src/khutlisa/airwallex.py` | `advance` takes an optional `funding` and, while the deposit is expected, calls `funding.before_deposit(payout, client, clock)` before it looks for the deposit (3 lines, and the docstring) | The funding interface. With no `funding` the holder's money is the simulated bank deposit, exactly as before |
| `src/khutlisa/payouts.py` | `PayoutRunner.funding` (None unless set) is passed to `advance`. Two empty tables, `EXPLAINERS` and `VOID_REASONS`, are consulted by `fixed_explanation` and `settle` | So a stop that Metal causes gets its own sentence and its own reason for withdrawing the approval, without Metal's words living in this file |
| `src/khutlisa/claims_api.py` | The approval route accepts an optional body `{"funding": "bank" or "metal"}` and, after the approval is on file, calls `app.state.on_approval` when one is set | The holder chooses the funding with the approval, and the approval signs the mandate. With no body the route behaves as before |
| `src/khutlisa/server.py` | `create_app` takes `metal`, `metal_scale` and `metal_keys` and calls `metal_api.register` | Wiring, and so the tests can hand the app a fake chain |
| `tests/conftest.py` | Points `KHUTLISA_METAL_HOME` at an empty folder for every test | No test may reach the testnet, even on a machine that has the keys |
| `web/src/screens/PayerScreen.tsx` | The button "Approve and fund on Metal", the scale beside it, and the panel under the terms | The holder's screen |
| `web/src/screens/PayoutScreen.tsx` | The panel under the money line, and titles for the three stops Metal adds | The payment screen |
| `web/src/types.ts` | Three more kinds of stop in `PayoutHold["kind"]` | The titles above are typed by it |
| `README.md`, `docs/HOW_IT_WORKS.md`, `docs/AIRWALLEX_FLOW.md` | A short paragraph each, pointing here | They said the holder's deposit is always staged by Khutlisa |

The 375 tests that were there before pass unchanged.

## What Metal taught us

1. **A fresh install of the command line was broken on the day.** `npm install -g @metalntwx/metal-agent@0.3.3`
   pulled `@x402/fetch` 2.31.0, released the day before, beside the `@x402/core` 2.28.0 the package pins.
   `metal-agent pay` then signed a payment, the payment settled, and the command failed reading the answer
   (`this.client.handlePaymentResponse is not a function`). `tools/metal/package.json` holds the three `@x402`
   packages at 2.28.0 with `overrides`, which is why the command line is installed there and not globally.
2. **The first RPC purchase was paid for and lost** to that fault: 1 \*USDZ settled and the endpoint's URL never
   reached us. Paying again with the packages pinned added 1 \*USDZ of credit and returned the same endpoint, as
   the docs say ("an address is handed one endpoint, however often it pays").
3. **A refusal can be put on chain.** `mandate pull --key <a funded key> --record-refusal` sends a pull the
   mandate refuses anyway, and the account records the refusal in a transaction that moves nothing.
   `mandate verify` then lists payments and refusals together. The agent's pulls are sent this way, so a refusal
   of a real pull is evidence too. It also means the agent's own key, not Metal's facilitator, submits the pull
   and pays its gas (about 0.0000000000008 \*USDZ).
4. **A recorded refusal does not use up the mandate's one payment.** Two refusals were recorded before the pull
   on the same mandate, and the pull paid.
5. **The same payment id pays at most once.** Asked for again, the command line answers "already paid, nothing
   sent" with the first transaction. A new payment id under a spent mandate is refused: `mandate_budget_spent`.
6. **The expiry is a duration on the command line** (`--expires-in <seconds>`), counted from the moment the
   command runs. To make it the approval's deadline to the second, the credential is written, compared and
   written again just after the next tick if it is off by one.
7. **Amounts under a mandate are whole \*USDZ cents.** \*USDZ itself has 18 decimals.
8. **The faucet** gives one grant a minute to a client and ten a day to an IP address, each topping an address
   up to 100 \*USDZ. A fresh setup needs three grants. A refusal says how many seconds to wait.
9. **The explorer** opens a transaction at `https://testnet.metalntwx.com/tx/<hash>` and an address at
   `/address/<address>`.

## What is simulated, and limits

- **No real money moves.** Metal testnet and the Airwallex sandbox.
- **The holder.** No holder uses Khutlisa. The holder's owner key sits on the same machine as the application,
  under `~/.khutlisa_metal/holder`, because one script plays every part. In real use the holder signs with its
  own wallet or passkey, binds the mandate itself and hands Khutlisa the credential and the mandate key; nothing
  in `MetalFunding.before_deposit`, which is the agent's side, reads the owner key.
- **One holder account.** Every claim is funded from the same Metal account, as every deposit lands in the same
  Airwallex account.
- **The bridge is a simulated deposit.** The Airwallex sandbox cannot receive stablecoins, so the \*USDZ stays at
  the settlement address on Metal and the same amount is credited by the sandbox's deposit simulation.
- **The scale**, as stated at the top, and the rounding up to the cent on chain that comes with it.
- **The expiry was seen on a mandate of its own**, signed with a deadline one minute away, because a claim's
  mandate expires 14 days after its approval. The code path for a claim is covered by a test with the fake chain.
- **The tolerance case was not staged on testnet.** It is covered by tests.
- **Not built:** a mandate per holder signed in the holder's own wallet, a webhook or indexer watch for a
  revocation made outside the application (it is found when the agent's pull is refused), and the short-deposit
  "what if" for a claim funded on Metal (a pull is exact or it is nothing).
- **Only the scale of 100 was run on testnet.** The scale of 1 is covered by tests of the arithmetic.
- **Limits:** a faucet grant tops the holder's account up to 100 \*USDZ, which is 10,000 US dollars of claims at
  the scale of 100. The RPC endpoint draws on 2 US dollars of prepaid credit; when it runs out the same
  `metal-agent pay` command tops it up by 1 \*USDZ.
