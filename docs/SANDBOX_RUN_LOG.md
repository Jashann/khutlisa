# One payout on the Airwallex sandbox, as recorded

Written by `scripts/payout_log.py` from the payout file of a real run through the application on the Airwallex sandbox. The claimant is the made-up person of the walk-through, and a script played every part (claimant and holder), which is why the steps follow each other within seconds. No real money moved. Bank account numbers are cut to their last four digits; the file never held a key or a token. Each record in `docs/` is of a separate run, so the amounts differ from one record to another with the rate of the moment.

## The payout

- Deposit reference: `KHUTLISA-006e5c16e99551a3`
- Expected from the holder: 125.38 USD. Arrived: 125.38 USD. Incoming fee booked by Airwallex: 0.38 USD.
- Route: Pay with a locked quote.
- Rate: 62.966543 (USD to PHP).
- Left Khutlisa's Airwallex account for the transfer: 125. Payout fee, inside that amount: 5 USD.
- Received: 7555.99 PHP, to Amihan Villareal, account ······7890 (PH).
- Final state: PAID. Airwallex transfer `c22d12d4-fa6d-42ef-b18b-2098e2f12ae0`, status PAID.
- Staged change of circumstance: none.

## The holder's standing instructions bound into the approval

- Amount: carry on without asking while the claimant would receive no less than 0.5 percent below the planned amount in their currency. Ask the claimant if it would be worse.
- Fees: below a claim of 250.00 USD the holder bears Airwallex's fees, so a small claim is not eaten by them. From that amount upward the fees come out of the claim.
- Route: Compare the routes Airwallex offers for the currency, with its own quotes and the fees it has charged, and take the one that delivers the most to the claimant.
- Deadline: send the money within 14 days of the approval. After that, stop and come back to the holder.
- Never inside these instructions: a different bank account, an amount larger than the one approved, or a second payment of the same claim. Those always come back to a person.
- The claim is 120.00 USD; under the fee rule the holder sends 125.38 USD.

## The plan the claimant agreed to

- Pay with a locked quote. Pay with a locked quote would deliver 7,552.93 PHP at Airwallex's quote of 62.941054, after a payout fee of 5.00 USD. Convert, then pay is not open for this currency: Airwallex does not convert US dollars into a held balance of PHP for this account.
- To send: 125.00 USD. Expected payout fee: 5.00 USD. Expected to be received: 7552.93 PHP.

## Steps

| Time (UTC) | State | Note |
| --- | --- | --- |
| 2026-11-13T07:34:08+00:00 | DEPOSIT_EXPECTED | plan 2bde9b29-4622-45b0-821f-f852d9111b33 agreed by the claimant |
| 2026-11-13T07:34:13+00:00 | DEPOSIT_CONFIRMED | deposit 57d5f8e0-c910-40cc-8c54-996a23f8a9a1 SETTLED; incoming fee booked by Airwallex: 0.38 USD |
| 2026-11-13T07:34:14+00:00 | CONVERTED | rate locked by quote c5549107-8bac-31ac-a5df-cb3f49419bf7; converts inside the transfer |
| 2026-11-13T07:34:15+00:00 | BENEFICIARY_READY | beneficiary 8215bd0b-a789-4814-9cd2-ab4b49b4cdcf |
| 2026-11-13T07:34:18+00:00 | TRANSFER_CREATED | transfer c22d12d4-fa6d-42ef-b18b-2098e2f12ae0 SCHEDULED |
| 2026-11-13T07:34:21+00:00 | SENT | transfer c22d12d4-fa6d-42ef-b18b-2098e2f12ae0 left Airwallex |
| 2026-11-13T07:34:23+00:00 | PAID | transfer c22d12d4-fa6d-42ef-b18b-2098e2f12ae0 paid |

## What changed, and what was decided

Lines marked "decided without asking" were settled by the payment machine inside the standing instructions. The others stopped the payment or record that a person agreed.

- 2026-11-13T07:34:08+00:00: decided without asking (fees). The claim is 120.00 USD, which is below your small-claim line of 250.00 USD, so you bear Airwallex's fees. Airwallex is expected to take 0.3 percent of what arrives and about 5.00 USD for the payout. Taken out of the claim that would be 5.36 USD, or 4.5 percent of it. So you send (120.00 + 5.00) / (1 - 0.003) = 125.38 USD: 0.38 USD incoming fee, 5.00 USD payout fee, and 120.00 USD left to convert for the claimant.
- 2026-11-13T07:34:08+00:00: decided without asking (route). Pay with a locked quote would deliver 7,552.93 PHP at Airwallex's quote of 62.941054, after a payout fee of 5.00 USD. Convert, then pay is not open for this currency: Airwallex does not convert US dollars into a held balance of PHP for this account.
- 2026-11-13T07:34:14+00:00: decided without asking (route). The rate locked with the plan was 62.941054, which gives 7,552.93 PHP. A quote taken at the moment of use was 62.966543, which gives 7,555.99 PHP. The better one was used: 3.06 PHP more for the claimant.

## Airwallex's ledger rows for this claim (GET /financial_transactions)

| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |
| --- | --- | --- | --- | --- | --- | --- |
| deposit | DEPOSIT | 125.38 | USD | SETTLED | KHUTLISA-006e5c16e99551a3 | ftx_V9X44MkQQMyMVJlqI_ipoQ |
| deposit | FEE | -0.38 | USD | SETTLED | Deposit to account ······6435 | ftx_pjY2DQXtR3q1F_xzYIME6g |
| transfer | PAYOUT | -125 | USD | SETTLED | Pay 7555.99 PHP to Amihan Villareal (KHUTLISA-006e5c16e99551a3) | ftx_fqL2Xyp_Mcyzgy2auWJiUQ |

| Currency | Came in | Went out | Left |
| --- | --- | --- | --- |
| USD | 125.38 | 125.38 | 0.00 |

Every line Airwallex booked for this claim adds up to zero: what arrived, less Airwallex's fees, is exactly what was sent.
