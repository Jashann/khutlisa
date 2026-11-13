# A batch on the Airwallex sandbox: the record of one real run

Batch `9cd9952cd05d`, started 2026-11-13T07:13:43+00:00, finished 2026-11-13T07:15:09+00:00. Written by `scripts/run_batch.py` from the batch file and from Airwallex's own answers. Nothing here was typed in by hand.

The owners are invented people and their bank details are examples built from Airwallex's live schema for each country. No real owner was paid and no real money moved: every call went to the Airwallex sandbox. Account numbers are cut to their last four digits.

## The plan it is a slice of

The book of Bank of America in California's public file: 26,190 properties worth $75,493,097.67 for owners in 147 countries. The holder did not ask for this plan. Limits: tolerance 0.5 percent, small-claim line 250.00 USD, handover 1 June 2027.

Each demonstration owner is owed the median payable claim of her corridor in that book; the owner in the largest corridor is owed the claim at the ninetieth percentile.

## The payments

| # | Owner (invented) | Country | Rail | Owed | Holder sends | Funded | Paid | Airwallex's fee | Account | Transfer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Meilin Zhaoqing | Taiwan | SWIFT, USD | 6,468.89 USD | 6,468.89 USD | in US dollars | 6,399.47 USD | 25.00 USD | ending 9055 | `ecf816e8-d1f9-4f28-b72f-3a3ad04f5004` |
| 2 | Kaede Hoshimori | Japan | Zengin, JPY | 1,004.02 USD | 1,004.02 USD | one conversion for the batch | 157,567.00 JPY | 1,599.00 JPY | ending 4567 | `8e40987b-0b94-4840-9b2e-7e373db39337` |
| 3 | Ximena Olvareda | Mexico | SPEI, MXN | 232.20 USD | 237.92 USD | one conversion for the batch | 4,178.13 MXN | 93.02 MXN | ending 8232 | `178dca69-9e72-4ddb-b331-ed2019d8137b` |
| 4 | Odile Marchetier | Canada | EFT, CAD | 253.16 USD | 253.16 USD | one conversion for the batch | 353.72 CAD | 4.28 CAD | ending 4567 | `675a5684-4f53-4c7d-979f-9a1a54f673f2` |
| 5 | Dalisay Marquendo | Philippines | InstaPay or PESONet, PHP | 411.50 USD | 411.50 USD | inside its own transfer | 25,509.69 PHP | 5.00 USD | ending 3004 | `82f716b8-d816-415b-825f-b4312369aedf` |
| 6 | Rowan Ashcombe | United Kingdom | Faster Payments, GBP | 343.54 USD | 343.54 USD | one conversion for the batch | 255.17 GBP | 2.27 GBP | ending 0008 | `c9a5ad00-82ec-4179-9461-053a24ff49c0` |
| 7 | Jonas Feldbrunner | Germany | SEPA Instant or SEPA, EUR | 537.06 USD | 537.06 USD | one conversion for the batch | 478.72 EUR | 2.71 EUR | ending 3000 | `8b70be1a-ccf0-4908-8c7b-0169ea131ce2` |
| 8 | Tamsin Wirralee | Australia | BECS, AUD | 300.10 USD | 300.10 USD | one conversion for the batch | 433.42 AUD | 4.41 AUD | ending 5678 | `4ba59cdf-f9ca-4a72-9d9b-b274e0fac126` |
| 9 | Kavya Indurkar | India | NEFT, IMPS or RTGS, INR | 432.78 USD | 432.78 USD | inside its own transfer | 39,742.18 INR | 5.00 USD | ending 6789 | `9978687f-13fa-464c-9a0a-e2689bd5cc4e` |

## The funding

- One deposit of 9,988.97 USD, reference `KHUTLISA-BATCH-9cd9952cd05d`. Airwallex's incoming fee: 29.97 USD. Left to share out: 9,959.00 USD.
- USD: paid in US dollars, nothing converted.
- JPY: converted once, 1,001.01 USD into 159,166.00 JPY (conversion `49384f97-80cd-4d7d-9c99-89d5a2ce21b8`), for 1 payment.
- MXN: converted once, 237.21 USD into 4,364.17 MXN (conversion `7d178f74-9086-430b-bc10-e6b159de8fea`), for 1 payment.
- CAD: converted once, 252.40 USD into 358.00 CAD (conversion `e4070847-03ca-4a70-8826-083f70008369`), for 1 payment.
- PHP: converted inside each transfer. Each payment converts inside its own transfer: Airwallex does not convert US dollars into a held balance of PHP (the sandbox refused the conversion).
- GBP: converted once, 342.51 USD into 257.44 GBP (conversion `78247dba-908f-4fe6-98ae-4a54c1eae98c`), for 1 payment.
- EUR: converted once, 535.45 USD into 481.43 EUR (conversion `6f1e0c05-9c6c-428e-ab98-6eec01cc006c`), for 1 payment.
- AUD: converted once, 299.20 USD into 437.83 AUD (conversion `b7bf2225-8bad-47d5-b1fa-85eb0367a66a`), for 1 payment.
- INR: converted inside each transfer. Each payment converts inside its own transfer: Airwallex does not convert US dollars into a held balance of INR (the sandbox refused the conversion).
- Decided in code (safety): Airwallex booked its fee on the whole deposit as 29.97 USD. Payment by payment the plan expected 0.01 USD more. The difference went to payment 1, the largest, so every dollar the batch holds is given to a payment and none is left over.
- Decided in code (route): 1,001.01 USD was converted once into 159,166.00 JPY at 159.00513 for 1 payment, and shared out in proportion to each payment's dollars.
- Decided in code (route): 237.21 USD was converted once into 4,364.17 MXN at 18.397918 for 1 payment, and shared out in proportion to each payment's dollars.
- Decided in code (route): 252.40 USD was converted once into 358.00 CAD at 1.418374 for 1 payment, and shared out in proportion to each payment's dollars.
- Decided in code (route): 342.51 USD was converted once into 257.44 GBP at 1.33046 for 1 payment, and shared out in proportion to each payment's dollars.
- Decided in code (route): 535.45 USD was converted once into 481.43 EUR at 1.112208 for 1 payment, and shared out in proportion to each payment's dollars.
- Decided in code (route): 299.20 USD was converted once into 437.83 AUD at 0.683363 for 1 payment, and shared out in proportion to each payment's dollars.

## The refusals

The sandbox was asked to refuse these transfers after they were sent. The replacement path is the ordinary one: the money comes back, the owner gives another account, the holder approves it, and the tolerance decides whether the owner is also asked to confirm the smaller amount.

- Payment 1 (Meilin Zhaoqing): transfer `0ee4e5e1-b532-4846-bdaa-0a33e3a0a87c` to the account ending 9012 ended CANCELLED (INCORRECT_ROUTING 90101: Invalid account name/number). 6,424.47 USD came back. The replacement is 0.39% less, inside the limit: the owner was not asked to confirm the amount. The corrected account was still asked for, and the holder approves it. Paid $6,399.47, in place of $6,424.47. The replacement went to the account ending 9055.
- Payment 3 (Ximena Olvareda): transfer `9de3425c-946a-496f-85c7-ee5273649346` to the account ending 7712 ended CANCELLED (INCORRECT_ROUTING 90101: Invalid account name/number). 4,271.15 MXN came back. The replacement is 2.18% less. Outside the limit: it stopped and asked the owner. Paid 4,178.13 MXN after the owner agreed, in place of 4,271.15 MXN. The replacement went to the account ending 8232.

What the script did in place of the people, in order:

- Payment 1: the owner gave her second example account, ending 9055.
- Payment 3: the owner gave her second example account, ending 8232.
- Payment 1: the holder approved the corrected account.
- Payment 3: the holder approved the corrected account.
- Payment 3: the owner agreed to the smaller amount, because it was outside the tolerance.

## The whole batch against Airwallex's ledger

27 rows, read again from `GET /api/v1/financial_transactions` for the deposit, every conversion and every transfer. Every currency adds up to zero.

| Currency | Came in | Went out | Left |
| --- | --- | --- | --- |
| AUD | 437.83 | 437.83 | 0.00 |
| CAD | 358.00 | 358.00 | 0.00 |
| EUR | 481.43 | 481.43 | 0.00 |
| GBP | 257.44 | 257.44 | 0.00 |
| JPY | 159,166.00 | 159,166.00 | 0.00 |
| MXN | 8,635.32 | 8,635.32 | 0.00 |
| USD | 16,413.44 | 16,413.44 | 0.00 |

## Planned cost beside actual cost

| | Incoming fee | Payout fees | In all | Transfers |
| --- | --- | --- | --- | --- |
| Planned | 29.96 USD | 50.01 USD | 79.97 USD | 9 |
| Booked by Airwallex | 29.97 USD | 92.01 USD | 121.98 USD | 11 |

Difference: 42.01 USD. A refused transfer keeps its payout fee and the replacement is charged again, so a batch with a refusal costs one more payout fee than planned for each. Payout fees as Airwallex charged them, by currency: 4.41 AUD, 4.28 CAD, 2.71 EUR, 2.27 GBP, 1,599.00 JPY, 186.04 MXN, 60.00 USD. Fees charged in another currency are counted in US dollars at the mid rate of the payment's own quote.

## The run

227 calls to Airwallex in 94 seconds, paced under the sandbox's limit of ten requests a second for one endpoint.

| When | State | What happened |
| --- | --- | --- |
| 2026-11-13T07:13:43+00:00 | Planned. Waits for the holder's approval | batch written; nothing has moved |
| 2026-11-13T07:13:43+00:00 | Approved. Nothing has moved yet | approved on exact terms: 9 payments, 9,988.97 USD to fund |
| 2026-11-13T07:13:43+00:00 | Waiting for the holder's US dollars | started; waiting for the holder's US dollars |
| 2026-11-13T07:13:47+00:00 | Funded. Converting | deposit 7aaa9152-d5e1-4959-9513-509552d0abbb SETTLED; Airwallex's fee 29.97 USD; 9959.00 USD shared out |
| 2026-11-13T07:14:02+00:00 | Paying | 6 conversions booked; 9 payments opened |
| 2026-11-13T07:14:50+00:00 | Paying | payment 1: the owner gave another bank account; it waits for the holder's approval |
| 2026-11-13T07:14:50+00:00 | Paying | payment 3: the owner gave another bank account; it waits for the holder's approval |
| 2026-11-13T07:14:54+00:00 | Paying | payment 1: the holder approved the corrected account ending 9055 |
| 2026-11-13T07:14:54+00:00 | Paying | payment 3: the holder approved the corrected account ending 8232 |
| 2026-11-13T07:14:55+00:00 | Paying | payment 3: the owner agreed to the new amount |
| 2026-11-13T07:15:09+00:00 | Every payment is paid | every payment is paid; Airwallex's rows add up to zero in every currency |
