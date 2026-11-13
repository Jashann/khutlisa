# One payout on the Airwallex sandbox, as recorded

Written by `scripts/payout_log.py` from the payout file of a real run through the application on the Airwallex sandbox. The claimant is the made-up person of the walk-through, and a script played every part (claimant and holder), which is why the steps follow each other within seconds. No real money moved. Bank account numbers are cut to their last four digits; the file never held a key or a token. Each record in `docs/` is of a separate run, so the amounts differ from one record to another with the rate of the moment.

## The payout

- Deposit reference: `KHUTLISA-c7f5ea3e18d813e5`
- Expected from the holder: 2316.40 USD. Arrived: 2316.40 USD. Incoming fee booked by Airwallex: 6.95 USD.
- Route: Pay from the balance already held.
- Rate: 18.392325 (USD to MXN).
- Left Khutlisa's Airwallex account for the transfer: 42384.19. Payout fee, inside that amount: 93.05 MXN.
- Received: 42291.14 MXN, to Marisol Tolmedo, account ··············7823 (MX).
- Final state: PAID. Airwallex transfer `5615015e-d991-4ede-82de-663c22a66973`, status PAID.
- Staged change of circumstance: The receiving bank refuses the transfer.

## The holder's standing instructions bound into the approval

- Amount: carry on without asking while the claimant would receive no less than 0.5 percent below the planned amount in their currency. Ask the claimant if it would be worse.
- Fees: below a claim of 250.00 USD the holder bears Airwallex's fees, so a small claim is not eaten by them. From that amount upward the fees come out of the claim.
- Route: Compare the routes Airwallex offers for the currency, with its own quotes and the fees it has charged, and take the one that delivers the most to the claimant.
- Deadline: send the money within 14 days of the approval. After that, stop and come back to the holder.
- Never inside these instructions: a different bank account, an amount larger than the one approved, or a second payment of the same claim. Those always come back to a person.
- The claim is 2316.40 USD; under the fee rule the holder sends 2316.40 USD.

## The plan the claimant agreed to

- Pay from the balance already held. The money for this claim is already held in MXN, because the earlier transfer came back in that currency. It is paid from that balance and nothing is converted a second time.
- To send: 42384.19 MXN. Expected payout fee: 93.03 MXN. Expected to be received: 42291.16 MXN.

## Steps

| Time (UTC) | State | Note |
| --- | --- | --- |
| 2026-11-13T07:32:26+00:00 | DEPOSIT_EXPECTED | plan 8880499d-eb41-4a0a-825f-d0313e921fde agreed by the claimant |
| 2026-11-13T07:32:31+00:00 | DEPOSIT_CONFIRMED | deposit f112bce3-c453-4259-95ee-a897fd48d19b SETTLED; incoming fee booked by Airwallex: 6.95 USD |
| 2026-11-13T07:32:32+00:00 | CONVERTED | rate locked by quote 0c6b6ed5-423d-3e3c-ab4d-cf773a1b629f; converts inside the transfer |
| 2026-11-13T07:32:34+00:00 | BENEFICIARY_READY | beneficiary 0742903f-5d57-46ef-98c3-1ff68825b4ce |
| 2026-11-13T07:32:35+00:00 | TRANSFER_CREATED | transfer 08080ffc-13ec-4417-84a8-ce9d7d67d577 SCHEDULED |
| 2026-11-13T07:32:38+00:00 | SENT | transfer 08080ffc-13ec-4417-84a8-ce9d7d67d577 left Airwallex |
| 2026-11-13T07:32:40+00:00 | FAILED | transfer 08080ffc-13ec-4417-84a8-ce9d7d67d577 ended CANCELLED: INCORRECT_ROUTING 90101: Invalid account name/number |
| 2026-11-13T07:32:48+00:00 | CONVERTED | carried on after transfer failed |
| 2026-11-13T07:32:50+00:00 | BENEFICIARY_READY | beneficiary e9db39a9-c0f6-4829-9289-14d9d10a38e5 |
| 2026-11-13T07:32:52+00:00 | TRANSFER_CREATED | transfer 5615015e-d991-4ede-82de-663c22a66973 SCHEDULED |
| 2026-11-13T07:32:54+00:00 | SENT | transfer 5615015e-d991-4ede-82de-663c22a66973 left Airwallex |
| 2026-11-13T07:32:57+00:00 | PAID | transfer 5615015e-d991-4ede-82de-663c22a66973 paid |

## Earlier transfers

- `08080ffc-13ec-4417-84a8-ce9d7d67d577`, sent to the account ending 7771: refused by the bank before it was paid; now CANCELLED (INCORRECT_ROUTING 90101: Invalid account name/number). Came back: 42384.19 MXN.

The transfer that was paid went to the account ending 7823, which is a different account from the one the bank refused.

## What changed, and what was decided

Lines marked "decided without asking" were settled by the payment machine inside the standing instructions. The others stopped the payment or record that a person agreed.

- 2026-11-13T07:32:25+00:00: decided without asking (fees). The claim is 2,316.40 USD, which is not below your small-claim line of 250.00 USD, so Airwallex's fees come out of the claim. Airwallex is expected to take 0.3 percent of what arrives (6.95 USD) and about 5.00 USD for the payout: 11.95 USD in all, or 0.5 percent of the claim. That leaves 2,304.45 USD to convert for the claimant.
- 2026-11-13T07:32:25+00:00: decided without asking (route). Pay with a locked quote would deliver 42,367.05 MXN at Airwallex's quote of 18.384884, after a payout fee of 5.00 USD. Convert, then pay would deliver 42,365.94 MXN, after a payout fee of 93.03 MXN. The first was chosen: 1.11 MXN more reaches the claimant.
- 2026-11-13T07:32:32+00:00: decided without asking (route). The rate locked with the plan was 18.384884, which gives 42,367.05 MXN. A quote taken at the moment of use was 18.392325, which gives 42,384.19 MXN. The better one was used: 17.14 MXN more for the claimant.
- 2026-11-13T07:32:40+00:00: decided without asking (route). The money for this claim is already held in MXN, because the earlier transfer came back in that currency. It is paid from that balance and nothing is converted a second time.
- 2026-11-13T07:32:40+00:00: The receiving bank refused the transfer because the account name or number was invalid (INCORRECT_ROUTING 90101), and 42,384.19 MXN came back and is held for your claim. Airwallex kept its 5.00 USD payout fee, so a replacement sent to corrected bank details would bring about 42,291.16 MXN, which is 0.18 percent less than the 42,367.05 MXN agreed and within the 0.5 percent tolerance, so you are not being asked to agree again.
- 2026-11-13T07:32:41+00:00: decided without asking (tolerance). The replacement would bring 42,291.16 MXN. That is 0.18 percent less than the 42,367.05 MXN the claimant agreed to, because Airwallex charges its payout fee again. It is inside the tolerance of 0.5 percent, so the claimant is not asked to agree again. The new bank account still has to come from the claimant and be approved by the holder.
- 2026-11-13T07:32:48+00:00: Everyone who had to agree after the transfer failed has agreed.
- 2026-11-13T07:32:51+00:00: decided without asking (safety). Before sending the replacement, the earlier transfer 08080ffc-13ec-4417-84a8-ce9d7d67d577 was read again at Airwallex. It is CANCELLED, so it can no longer pay. One replacement is sent under a new request id, for exactly what Airwallex's records say this claim holds.

## Airwallex's ledger rows for this claim (GET /financial_transactions)

| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |
| --- | --- | --- | --- | --- | --- | --- |
| deposit | DEPOSIT | 2316.4 | USD | SETTLED | KHUTLISA-c7f5ea3e18d813e5 | ftx_8RK848RTQlmV7qiX_UjRmw |
| deposit | FEE | -6.95 | USD | SETTLED | Deposit to account ······6435 | ftx_I-36nWumQXyGcWEm6mDgig |
| earlier transfer | PAYOUT | -2309.45 | USD | SETTLED | Pay 42384.19 MXN to Marisol Tolmedo (KHUTLISA-c7f5ea3e18d813e5) | ftx_KC-j-opTNIK1HnBKR13fRA |
| earlier transfer | PAYOUT_REVERSAL | 42384.19 | MXN | SETTLED | Refund for failed payment P261113-714GW9Y | ftx_RGIjmDHoPYymitkhKEZObw |
| transfer | PAYOUT | -42384.19 | MXN | SETTLED | Pay 42291.14 MXN to Marisol Tolmedo (KHUTLISA-c7f5ea3e18d813e5) | ftx_qdBpamHgP2-haETnqU369g |

| Currency | Came in | Went out | Left |
| --- | --- | --- | --- |
| MXN | 42384.19 | 42384.19 | 0.00 |
| USD | 2316.4 | 2316.40 | 0.00 |

Every line Airwallex booked for this claim adds up to zero: what arrived, less Airwallex's fees, is exactly what was sent.
