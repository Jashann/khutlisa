# One estate settlement on the Airwallex sandbox, as recorded

Written by `scripts/estate_log.py` from the files of a real run through the application on the Airwallex sandbox (`scripts/walkthrough_heirs.mjs`). The owner, the family and every document are invented, and a script played every part (the family and the holder), which is why the steps follow each other within seconds. No real money moved. Bank account numbers are cut to their last four digits; the files never held a key or a token.

## The estate

- Property: 4,618.37 USD, held by HARROWGATE COLD STORAGE.
- Owner (invented): Rafael Ibarra Quintanar, died 2024-03-14, living in CA.
- Basis: intestate; the money was the owner's separate property.
- Final state of the claim: PAID.

| Heir | Relation | Lives in | Fraction | Entitlement (USD) | Paid |
| --- | --- | --- | --- | --- | --- |
| Lucía Beltrán de Ibarra | spouse | MX | 1/3 | 1539.46 | 27,960.86 MXN |
| Carmela Ibarra Solano | child | PH | 2/9 | 1026.31 | 64,153.01 PHP |
| Tomás Ibarra Solano | child | GB | 2/9 | 1026.30 | 765.63 GBP |
| Naomi Ibarra Sato | grandchild | JP | 2/9 | 1026.30 | 160,949 JPY |

The entitlements add up to 4618.37 USD. Each share is rounded down to the cent. The cents left over are given out one each, first to the heirs whose shares lost the largest part of a cent, and on a tie to the heir who comes first in the family. The parts therefore add up to the whole, to the cent.

## The statute steps behind the fractions

1. Probate Code 6401(c)(3)(A): The money is the owner's separate property. The surviving spouse takes one third, because the owner left more than one child.
2. Probate Code 6402(a): The part that does not pass to the surviving spouse (two thirds) passes to the owner's issue.
3. Probate Code 240: The nearest generation with a living member has 2 living and 1 who died leaving living issue, so the part is divided into 3 equal shares of 2/9 of the estate. Each living member takes one share. The share of each member who died is divided among their own issue in the same way.
4. Probate Code 240: The only one in that degree takes 2/9 of the estate.

## First payment

- Deposit reference: `KHUTLISA-4d46e45cc91f96ea-S1`. Planned from the holder: 3592.07 USD (of which the holder adds 0.00 USD under its fee rule). Arrived: 3592.07 USD. Incoming fee booked by Airwallex: 10.78 USD. Left to divide: 3581.29 USD.
- Held in this round, not sent: Naomi Ibarra Sato 1026.30 USD.
- Final state of the round: DONE.

| Heir | Sent for them (USD) | Fees borne by | Route | One dollar bought | Payout fee | Planned | Received | Account | Transfer | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Lucía Beltrán de Ibarra | 1534.84 | the heir | Pay from the balance already held | 18.337670 MXN | 92.84 MXN | 28,053.70 MXN | 27,960.86 MXN | ··············8524 (MX) | `dfd0facf-266a-493e-b309-0fcd45fa4355` | PAID |
| Carmela Ibarra Solano | 1023.23 | the heir | Pay with a locked quote | 63.004440 PHP | 5 USD | 64,153.01 PHP | 64,153.01 PHP | ······7788 (PH) | `94974bc2-29c4-4fc6-b5d4-d297886f30a6` | PAID |
| Tomás Ibarra Solano | 1023.22 | the heir | Convert, then pay | 0.750470 GBP | 2.27 GBP | 765.64 GBP | 765.63 GBP | ····9911 (GB) | `95d9b1ba-34c0-497a-8e4e-cdc8ce70708d` | PAID |

Earlier transfers for Lucía Beltrán de Ibarra:

- `2110d452-1334-4242-93bd-5097c99c2898` to the account ending 8113: refused by the bank before it was paid; now CANCELLED (INCORRECT_ROUTING 90101: Invalid account name/number). Came back: 28053.70 MXN. Airwallex kept its fee of 5 USD.
- 2026-11-13T15:08:49+00:00: decided without asking (route). The money for this claim is already held in MXN, because the earlier transfer came back in that currency. It is paid from that balance and nothing is converted a second time.
- 2026-11-13T15:08:50+00:00: decided without asking (tolerance). The replacement would bring 27,960.84 MXN, 0.33 percent less than the 28,053.70 MXN in the plan, because Airwallex charges its payout fee again. That is inside the tolerance, so the family is not asked to agree again. The new bank account still has to come from the heir and be approved by the holder.
- 2026-11-13T15:08:56+00:00: decided without asking (safety). Before sending the replacement, the earlier transfer 2110d452-1334-4242-93bd-5097c99c2898 was read again at Airwallex. It is CANCELLED, so it can no longer pay. One replacement is sent under a new request id, for exactly what Airwallex's records say this claim holds.

What happened, in order:

- 2026-11-13T15:08:21+00:00: The plan was agreed. The holder sends 3592.07 USD with the reference KHUTLISA-4d46e45cc91f96ea-S1.
- 2026-11-13T15:08:27+00:00: 3592.07 USD arrived and Airwallex booked a fee of 10.78 USD. The 3581.29 USD left was divided among 3 heirs: Lucía Beltrán de Ibarra 1534.84 USD, Carmela Ibarra Solano 1023.23 USD, Tomás Ibarra Solano 1023.22 USD.
- 2026-11-13T15:08:45+00:00: Carmela Ibarra Solano was paid 64,153.01 PHP in the Philippines.
- 2026-11-13T15:08:48+00:00: Tomás Ibarra Solano was paid 765.63 GBP in the United Kingdom.
- 2026-11-13T15:08:49+00:00: Lucía Beltrán de Ibarra: the bank refused the transfer (INCORRECT_ROUTING 90101: Invalid account name/number). 28053.70 MXN came back and is held for this heir. The other heirs are not held up.
- 2026-11-13T15:09:01+00:00: Lucía Beltrán de Ibarra was paid 27,960.86 MXN in Mexico.
- 2026-11-13T15:09:01+00:00: Every heir in this round has been paid.

## Second payment

- Deposit reference: `KHUTLISA-4d46e45cc91f96ea-S2`. Planned from the holder: 1026.30 USD (of which the holder adds 0.00 USD under its fee rule). Arrived: 1026.30 USD. Incoming fee booked by Airwallex: 3.08 USD. Left to divide: 1023.22 USD.
- Held in this round, not sent: nobody.
- Final state of the round: DONE.

| Heir | Sent for them (USD) | Fees borne by | Route | One dollar bought | Payout fee | Planned | Received | Account | Transfer | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Naomi Ibarra Sato | 1023.22 | the heir | Convert, then pay | 158.859000 JPY | 1599 JPY | 160,949 JPY | 160,949 JPY | ···4567 (JP) | `95f38763-2fa8-4dff-a249-40d4c3e7b8a1` | PAID |

What happened, in order:

- 2026-11-13T15:09:19+00:00: The plan was agreed. The holder sends 1026.30 USD with the reference KHUTLISA-4d46e45cc91f96ea-S2.
- 2026-11-13T15:09:25+00:00: 1026.30 USD arrived and Airwallex booked a fee of 3.08 USD. The 1023.22 USD left was divided among 1 heirs: Naomi Ibarra Sato 1023.22 USD.
- 2026-11-13T15:09:35+00:00: Naomi Ibarra Sato was paid 160,949 JPY in Japan.
- 2026-11-13T15:09:35+00:00: Every heir in this round has been paid.

## The holder's standing instructions bound into the approval

- Amount: carry on without asking while the claimant would receive no less than 0.5 percent below the planned amount in their currency. Ask the claimant if it would be worse.
- Fees: below a claim of 250.00 USD the holder bears Airwallex's fees, so a small claim is not eaten by them. From that amount upward the fees come out of the claim.
- Route: Compare the routes Airwallex offers for the currency, with its own quotes and the fees it has charged, and take the one that delivers the most to the claimant.
- Deadline: send the money within 14 days of the approval. After that, stop and come back to the holder.
- Never inside these instructions: a different bank account, an amount larger than the one approved, or a second payment of the same claim. Those always come back to a person.
- The holder's small-claim line is applied to each heir's share, because Airwallex charges its payout fee once per transfer. Below the line the holder bears that heir's fees. From the line upward the heir's part of the incoming fee and the payout fee of their own transfer come out of their share. Nobody pays for another heir's transfer.

## Airwallex's ledger rows for this estate (GET /financial_transactions)

| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |
| --- | --- | --- | --- | --- | --- | --- |
| The holder's deposit | DEPOSIT | 3592.07 | USD | SETTLED | KHUTLISA-4d46e45cc91f96ea-S1 | ftx_Ys9rAXONRFSdSawXGuW77A |
| The holder's deposit | FEE | -10.78 | USD | SETTLED | Deposit to account ······6435 | ftx_HO6uacB9STCzMNgGEc7DiQ |
| Lucía Beltrán de Ibarra | PAYOUT | -1534.84 | USD | SETTLED | Pay 28053.70 MXN to Lucia Beltran de Ibarra (KHUTLISA-4d46e45cc91f96ea-S1-s1) | ftx_bIcp7ujUOZyVDCvJUXTopw |
| Lucía Beltrán de Ibarra | PAYOUT_REVERSAL | 28053.7 | MXN | SETTLED | Refund for failed payment P261113-317EWN4 | ftx_6XnZ972eM9Ob13MHJmERWg |
| Lucía Beltrán de Ibarra | PAYOUT | -28053.7 | MXN | SETTLED | Pay 27960.86 MXN to Lucia Beltran de Ibarra (KHUTLISA-4d46e45cc91f96ea-S1-s1) | ftx_0CzJqpueOimg-Nas-puCgw |
| Carmela Ibarra Solano | PAYOUT | -1023.23 | USD | SETTLED | Pay 64153.01 PHP to Carmela Ibarra Solano (KHUTLISA-4d46e45cc91f96ea-S1-c1) | ftx_VJjHKQIkN6aabgl2UUCAig |
| Tomás Ibarra Solano | CONVERSION_BUY | 767.9 | GBP | SETTLED |  | ftx_Z0RwDq8ZPMGBNp_rHQeABw |
| Tomás Ibarra Solano | CONVERSION_SELL | -1023.22 | USD | SETTLED |  | ftx_1F8fmFd9NMui5oiDH6FD7A |
| Tomás Ibarra Solano | PAYOUT | -767.9 | GBP | SETTLED | Pay 765.63 GBP to Tomas Ibarra Solano (KHUTLISA-4d46e45cc91f96ea-S1-c2) | ftx_8YtOUNLbNieueyveqipN9w |
| The holder's deposit | DEPOSIT | 1026.3 | USD | SETTLED | KHUTLISA-4d46e45cc91f96ea-S2 | ftx_VVmCOqzXTh-aQBsRyPEXuA |
| The holder's deposit | FEE | -3.08 | USD | SETTLED | Deposit to account ······6435 | ftx_PLwX52FmTVeUK83zWvC9hg |
| Naomi Ibarra Sato | CONVERSION_SELL | -1023.22 | USD | SETTLED |  | ftx_OJDmL4f4NbGqYqgOIyjI0w |
| Naomi Ibarra Sato | CONVERSION_BUY | 162548 | JPY | SETTLED |  | ftx_57LXvhi5MruGJQoFsf2kYw |
| Naomi Ibarra Sato | PAYOUT | -162548 | JPY | SETTLED | Pay 160949 JPY to Naomi Ibarra Sato (KHUTLISA-4d46e45cc91f96ea-S2-c3_1) | ftx_A7JgPtNnOYS2vyW4690yWg |

| Currency | Came in | Went out | Left |
| --- | --- | --- | --- |
| GBP | 767.9 | 767.9 | 0.0 |
| JPY | 162548 | 162548 | 0 |
| MXN | 28053.7 | 28053.7 | 0.0 |
| USD | 4618.37 | 4618.37 | 0.00 |

Every line Airwallex booked for this estate adds up to zero in every currency: what arrived, less Airwallex's fees, is exactly what was sent to the heirs.
