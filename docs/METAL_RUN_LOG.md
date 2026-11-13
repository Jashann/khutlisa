# One claim funded on Metal testnet and paid out through the Airwallex sandbox, as recorded

Written by `scripts/metal_log.py` from the record of a real run of `scripts/metal_run.py` on 2026-11-13. The run went through the application's own routes against Metal testnet (`eip155:63825`, `metal-agent` 0.3.3) and the Airwallex sandbox. A script played every part: the owner, the holder and the agent, which is why the steps follow each other within seconds. The owners are the invented people of the walk-through and only the demonstration records were searched. Document reading was off, so no language model was called. No real money moved. Bank account numbers are cut to their last four digits, and no key, credential file or RPC endpoint is in this file.

**Scale: 1 *USDZ on Metal testnet stands for 100 US dollars of the claim, because the testnet faucet gives an address at most 100 *USDZ. Mandates count in *USDZ cents, so one cent on chain stands for 1.00 US dollars and amounts are rounded up to it. No real money moves.**

Every transaction hash below opens on the testnet explorer, https://testnet.metalntwx.com. The addresses:

- The holder's Metal account (pays under the mandate): [`0xA1a662b1Ac52a33A181A83762623B64463645d42`](https://testnet.metalntwx.com/address/0xA1a662b1Ac52a33A181A83762623B64463645d42)
- Khutlisa's settlement address (the only payee a mandate names): [`0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`](https://testnet.metalntwx.com/address/0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec)
- Khutlisa's agent address (pays the gas that records a refusal; used as the wrong payee): [`0x2e472dFc2a8237ef5f985Af38391DCC97F21f634`](https://testnet.metalntwx.com/address/0x2e472dFc2a8237ef5f985Af38391DCC97F21f634)
- The token: *USDZ, `0x000000000000000000000000000000000000B5d5`, 18 decimals

## What Metal refused, in one table

Each refusal was made by the holder's Metal account in the transaction named, which moved nothing. `metal-agent mandate pull --record-refusal` sends a refused pull so that the refusal is on chain.

| Attempt | Amount | Metal's reason | Transaction |
| --- | --- | --- | --- |
| Pull one *USDZ cent more than the cap | 23.18 *USDZ | `mandate_cap_exceeded` | [`0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38`](https://testnet.metalntwx.com/tx/0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38) |
| Pull to an address other than Khutlisa's settlement address | 23.17 *USDZ | `mandate_payee_not_listed` | [`0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299`](https://testnet.metalntwx.com/tx/0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299) |
| Pull a second time after the claim was funded | 23.17 *USDZ | `mandate_budget_spent` | [`0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df`](https://testnet.metalntwx.com/tx/0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df) |
| Pull after the mandate's expiry | 1.00 *USDZ | `mandate_expired` | [`0x3564008dacd5cbc75e474d008871b7b093a1db32b0b994995140509c2ab9ffbf`](https://testnet.metalntwx.com/tx/0x3564008dacd5cbc75e474d008871b7b093a1db32b0b994995140509c2ab9ffbf) |
| Pull after the holder revoked the mandate | 1.26 *USDZ | `mandate_revoked` | [`0xf550156e3843ab41f90d2ff8b7bba5d3a8c4cc41f2169dd4e47fa57a9398490d`](https://testnet.metalntwx.com/tx/0xf550156e3843ab41f90d2ff8b7bba5d3a8c4cc41f2169dd4e47fa57a9398490d) |

## 1. A claim funded by a pull under a mandate and paid in Mexican pesos

Claim `35afd281248f47b7`. The holder approved 2316.40 USD and chose Metal, so the approval signed a mandate.

- Mandate `0x2da4ebc066583771b8be5a010666de847266c3f41821c44e61ca734b3231c6a3`, bound on the holder's account in [`0x902e4294e8478ec78a68196b028d08085c4f04178767c99aa828a67cb6dafc83`](https://testnet.metalntwx.com/tx/0x902e4294e8478ec78a68196b028d08085c4f04178767c99aa828a67cb6dafc83).

### The approval's terms beside the mandate's, as the chain holds them

| Term | The approval | The mandate | Same |
| --- | --- | --- | --- |
| Who may be paid | Khutlisa's settlement address, and no other | 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec | yes |
| Most per payment | 2,316.40 USD, what the holder is to send for this claim | 23.17 *USDZ, which stands for 2,317.00 USD | yes |
| Most in total | 2,316.40 USD, once | 23.17 *USDZ, which stands for 2,317.00 USD | yes |
| Number of payments | One. A second payment is never inside the limits | 1 | yes |
| Until | 2026-11-27T06:52:55+00:00 (the deadline in the holder's standing instructions) | 2026-11-27T06:52:55+00:00 | yes |
| Reference | Claim 35afd281248f47b7, approval terms 659f735ec6ae6c24 | Khutlisa claim 35afd281248f47b7 approval 659f735ec6ae6c24 | yes |

### The pull

- The agent pulled 23.17 *USDZ under payment id `35afd281248f47b7` (the claim number). It stands for 2316.40 USD of the claim at the scale above (2317.00 USD when the cent on chain is counted whole).
- Transaction: [`0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348`](https://testnet.metalntwx.com/tx/0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348).
- Read back from the chain (`metal-agent status`): status success, block 27071871, submitted by `0x2e472dfc2a8237ef5f985af38391dcc97f21f634` (Khutlisa's agent address, which submitted the pull itself and paid the gas, so that a refusal would have been recorded on chain too); transfer of 23.17 *USDZ from `0xA1a662b1Ac52a33A181A83762623B64463645d42` to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`.
- Metal's own verification of that transaction against the mandate (`metal-agent mandate verify --credential <credential> --issuer <issuer public key> --tx 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348 --network testnet`): verified yes.
  - step 1 pass: The mandate is bound on the principal's account: hash(C), the limits, the payees, the mandate key and the issuer key are on chain
  - step 2 pass: The credential in hand hashes to the bound hash(C) and states the bound limits, payees and mandate key
  - step 3 pass: The credential's signatures: the issuer's under a trusted key that is the one recorded at binding, the owner's under the key the issuer bound
  - step 4 pass: Each payment and refusal is the mandate key's per-payment mandate, rebuilt from its transaction, inside the mandate at its block

### The bridge to Airwallex, and the payout

The Airwallex sandbox cannot receive *USDZ. Once the pull had settled and been verified, the application looked the transaction hash up among Airwallex's deposits (`GET /api/v1/deposits`), found none, and made one simulated deposit of the approved dollars with the hash as its reference.

- Deposit `3166dd92-16d0-4cce-a7ff-d1ec8344202f`: 2316.40 USD, reference `0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348`.
- Incoming fee booked by Airwallex: 6.95 USD.
- Route: Pay with a locked quote. Rate: 18.403402 (USD to MXN).
- Transfer `99e5d01e-6210-44eb-9ba1-8b1c2d1b166f`: PAID. Received: 42409.72 MXN, to Marisol Tolmedo, account ··············7771 (MX).
- Final state: PAID. Every line Airwallex booked for this claim adds up to zero: what arrived, less Airwallex's fees, is exactly what was sent.

| Time (UTC) | State | Note |
| --- | --- | --- |
| 2026-11-13T06:53:23+00:00 | DEPOSIT_EXPECTED | plan f83c36a0-2b4f-4514-91e2-06b3d6f38099 agreed by the claimant |
| 2026-11-13T06:54:42+00:00 | DEPOSIT_CONFIRMED | deposit 3166dd92-16d0-4cce-a7ff-d1ec8344202f SETTLED; incoming fee booked by Airwallex: 6.95 USD |
| 2026-11-13T06:54:44+00:00 | CONVERTED | rate locked by quote af507b37-5e3b-3095-a1e9-8a6fe9ca2e9a; converts inside the transfer |
| 2026-11-13T06:54:45+00:00 | BENEFICIARY_READY | beneficiary c9266774-74e3-44fe-9efa-dae14f672a47 |
| 2026-11-13T06:54:47+00:00 | TRANSFER_CREATED | transfer 99e5d01e-6210-44eb-9ba1-8b1c2d1b166f SCHEDULED |
| 2026-11-13T06:54:50+00:00 | SENT | transfer 99e5d01e-6210-44eb-9ba1-8b1c2d1b166f left Airwallex |
| 2026-11-13T06:54:53+00:00 | PAID | transfer 99e5d01e-6210-44eb-9ba1-8b1c2d1b166f paid |

Airwallex's ledger rows for this claim (`GET /financial_transactions`):

| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |
| --- | --- | --- | --- | --- | --- | --- |
| deposit | DEPOSIT | 2316.4 | USD | SETTLED | 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348 | ftx_MWbdkhbQTM6n_9Hsg0QgLw |
| deposit | FEE | -6.95 | USD | SETTLED | Deposit to account ······6435 | ftx_Htxogw1UTB-WI4E5jrx09A |
| transfer | PAYOUT | -2309.45 | USD | SETTLED | Pay 42409.72 MXN to Marisol Tolmedo (0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348) | ftx_eUX-k7rnOvqnWahY_YpsMQ |

| Currency | Came in | Went out | Left |
| --- | --- | --- | --- |
| USD | 2316.4 | 2316.40 | 0.00 |

What the agent decided without asking:

- 2026-11-13T06:53:23+00:00: Applied the fee rule (Your fee rule). The claim is 2,316.40 USD, which is not below your small-claim line of 250.00 USD, so Airwallex's fees come out of the claim. Airwallex is expected to take 0.3 percent of what arrives (6.95 USD) and about 5.00 USD for the payout: 11.95 USD in all, or 0.5 percent of the claim. That leaves 2,304.45 USD to convert for the claimant.
- 2026-11-13T06:53:23+00:00: Chose the route (Your route rule). Pay with a locked quote would deliver 42,403.78 MXN at Airwallex's quote of 18.400826, after a payout fee of 5.00 USD. Convert, then pay would deliver 42,402.77 MXN, after a payout fee of 93.02 MXN. The first was chosen: 1.01 MXN more reaches the claimant.
- 2026-11-13T06:53:36+00:00: Pulled the holder's funds under the Metal mandate (Your mandate on Metal, enforced by the chain). Pulled 23.17 *USDZ from the holder's Metal account under its mandate, which stands for 2,316.40 US dollars of this claim. The settlement was read from the chain and passed Metal's own verification. Transaction 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348. The Airwallex sandbox cannot receive *USDZ, so the same amount is credited as a simulated deposit whose reference is that transaction hash.
- 2026-11-13T06:54:44+00:00: Used a better rate than the one locked (Your route rule). The rate locked with the plan was 18.400826, which gives 42,403.78 MXN. A quote taken at the moment of use was 18.403402, which gives 42,409.72 MXN. The better one was used: 5.94 MXN more for the claimant.

### The attempts to overstep, and the double pull

Before the pull the agent was told to overstep the mandate twice; after it, to pull a second time. Each attempt was signed with the mandate key and sent.
- 2026-11-13T06:53:10+00:00: Pull one *USDZ cent more than the cap: 23.18 *USDZ to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`. Refused: `mandate_cap_exceeded` (the amount is above the mandate's per-payment cap). [`0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38`](https://testnet.metalntwx.com/tx/0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38)
- 2026-11-13T06:53:17+00:00: Pull to an address other than Khutlisa's settlement address: 23.17 *USDZ to `0x2e472dFc2a8237ef5f985Af38391DCC97F21f634`. Refused: `mandate_payee_not_listed` (the address is not the one the mandate allows). [`0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299`](https://testnet.metalntwx.com/tx/0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299)
- 2026-11-13T06:54:59+00:00: Pull a second time after the claim was funded: 23.17 *USDZ to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`. Refused: `mandate_budget_spent` (the mandate's budget is spent, so nothing more can be pulled under it). [`0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df`](https://testnet.metalntwx.com/tx/0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df)
- 2026-11-13T06:55:04+00:00: The same pull under the same payment id again: outcome paid, already paid: True, transaction 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348 (the first one). Nothing was sent.

`metal-agent mandate verify` over the whole mandate afterwards: verified yes. What it listed from the chain:

- refusal (mandate_cap_exceeded): 23.18 *USDZ to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`, block 27071581, [`0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38`](https://testnet.metalntwx.com/tx/0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38)
- refusal (mandate_payee_not_listed): 23.17 *USDZ to `0x2e472dFc2a8237ef5f985Af38391DCC97F21f634`, block 27071707, [`0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299`](https://testnet.metalntwx.com/tx/0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299)
- payment: 23.17 *USDZ to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`, block 27071871, [`0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348`](https://testnet.metalntwx.com/tx/0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348)
- refusal (mandate_budget_spent): 23.17 *USDZ to `0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec`, block 27073258, [`0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df`](https://testnet.metalntwx.com/tx/0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df)

The mandate on chain after all of it: spent 23.17 of 23.17 *USDZ, 1 payment.

## 2. A mandate revoked before the pull

Claim `9839a46853f7393b`, 120.00 USD to the Philippines. Under the holder's fee rule it sends 125.38 USD, so the mandate's cap was 1.26 *USDZ.

- 2026-11-13T06:55:54+00:00: The holder approved and signed mandate 0x63dc7db31a739697d9a57139bf71a015a7a01b0ddbfbd4dede75212c0bb85bb6 (cap 1.26 *USDZ, which stands for 126.00 USD), bound in 0x7cabc71e3de9c2b8cc18e1081c8efa564a726364d131117ee55b5e09c8edcb1b.
- 2026-11-13T06:56:03+00:00: The holder revoked it before the payment started, in 0x4045614a588d3879b2c8e37ac8a1ef24fd59d0c1682a61a1dd70fd11aa16c6f4. The claim is PROOF_NEEDED again; the approval was withdrawn because the holder revoked the Metal mandate before any money was pulled.
- 2026-11-13T06:56:10+00:00: The holder approved again and signed mandate 0xe5906b385a2640d12c093b48f38ca1f8dee7997fd1ea79fa89b83efded0291ba (number 2), bound in 0xa0e6832a1195c4449be6ac228ebad906bf6e9a678055952c41a0dbf9d29ce0b9.
- 2026-11-13T06:56:17+00:00: The holder revoked that mandate on chain, outside the application, in 0xcb10f030af81b540a699f0b5e34ede9988b0ac35e38ab0de4bcb8416deb8df61. The owner then agrees to the plan and the agent tries to pull.
- 2026-11-13T06:56:27+00:00: Metal refused the pull: mandate_revoked, recorded on chain in 0xf550156e3843ab41f90d2ff8b7bba5d3a8c4cc41f2169dd4e47fa57a9398490d. Payout state HELD, claim state PAYMENT_HELD. The holder revoked the Metal mandate before any money was pulled. Metal refused the agent's pull (mandate_revoked), nothing moved, and the claim is back with the holder. A new approval signs a new mandate. Deposits made at Airwallex for this claim: none.

The mandates on this claim, oldest first:

- Mandate 1 `0x63dc7db31a739697d9a57139bf71a015a7a01b0ddbfbd4dede75212c0bb85bb6`: revoked. Bound in [`0x7cabc71e3de9c2b8cc18e1081c8efa564a726364d131117ee55b5e09c8edcb1b`](https://testnet.metalntwx.com/tx/0x7cabc71e3de9c2b8cc18e1081c8efa564a726364d131117ee55b5e09c8edcb1b), revoked in [`0x4045614a588d3879b2c8e37ac8a1ef24fd59d0c1682a61a1dd70fd11aa16c6f4`](https://testnet.metalntwx.com/tx/0x4045614a588d3879b2c8e37ac8a1ef24fd59d0c1682a61a1dd70fd11aa16c6f4) (on chain: revoked yes, spent 0 *USDZ).
- Mandate 2 `0xe5906b385a2640d12c093b48f38ca1f8dee7997fd1ea79fa89b83efded0291ba`: revoked. Bound in [`0xa0e6832a1195c4449be6ac228ebad906bf6e9a678055952c41a0dbf9d29ce0b9`](https://testnet.metalntwx.com/tx/0xa0e6832a1195c4449be6ac228ebad906bf6e9a678055952c41a0dbf9d29ce0b9) (on chain: revoked yes, spent 0 *USDZ).

Payout state at the end: HELD; claim state: PAYMENT_HELD. No deposit was made at Airwallex for this claim and nothing left the holder's Metal account.

## 3. A pull after the expiry

A claim's mandate expires at the holder's deadline, 14 days after the approval in this run, so the expiry cannot be waited for on a claim. A mandate with the same shape and a deadline one minute away was signed on the same account instead.

- Mandate `0x1388204258577a2afa3bc84b3dd2942e33fdde3cade92bce3f927d9f02aec484`: cap and budget 1.00 *USDZ, one payment, payee the settlement address, expiry 2026-11-13T06:57:27+00:00. Bound in [`0x77a35ac42538fc8d5a02a843b519fc08a9a03978343ecfc825aa7293b2ba758f`](https://testnet.metalntwx.com/tx/0x77a35ac42538fc8d5a02a843b519fc08a9a03978343ecfc825aa7293b2ba758f).
- 2026-11-13T06:57:40+00:00: A pull of 1.00 *USDZ at 2026-11-13T06:57:40+00:00, after the expiry. Metal's answer: refused, mandate_expired. Recorded on chain in 0x3564008dacd5cbc75e474d008871b7b093a1db32b0b994995140509c2ab9ffbf.
- 2026-11-13T06:57:43+00:00: metal-agent mandate verify over that mandate: verified True; refusal mandate_expired 1 *USDZ

## 4. The same through the holder's screen, paid in Philippine pesos

Written from the record of a browser run that drove the holder's view against a running server: the approval, the attempts to overstep and the verification were clicks on the screen. The owner's steps went through the routes the owner's screens use. The same steps are now part 3 of `scripts/walkthrough.mjs`, whose screens are in `docs/shots/walk/`.

Claim `4ca8ba10092a82b2`: 1840.55 USD to Amihan Villareal, account ······7890 (PH).

- 2026-11-13T07:02:44+00:00: Amihan opened claim 4ca8ba10092a82b2 on a demonstration record of 1,840.55 USD and gave a bank account in PHP.
- 2026-11-13T07:02:45+00:00: In the holder's view: clicked "Approve and fund on Metal".
- 2026-11-13T07:02:53+00:00: Mandate 0x25520370a2214b94eb8f4f15729d651cc647c199a11293245504e5aced164fa2 bound in 0xd53403b9aebf9271600d35c5536963138f032ca6b39e0f4775ba2c6539a21a9f; every term the same as the approval: true.
- 2026-11-13T07:03:03+00:00: Clicked "Pull one *USDZ cent more than the cap". Metal refused: mandate_cap_exceeded, recorded on chain in 0xdfaa48a5116f2f2c0196dc8df43dd0c7648fcfc5ca7dc9b9183954ed0e98c3ef.
- 2026-11-13T07:03:12+00:00: Clicked "Pull to an address other than Khutlisa's settlement address". Metal refused: mandate_payee_not_listed, recorded on chain in 0x5fe5b3e58ff8b0500629d26ce06192783a64b79481be2d337b1b59fd7414fbee.
- 2026-11-13T07:03:14+00:00: The owner agreed to the plan (115127.52 PHP expected).
- 2026-11-13T07:03:45+00:00: Pull 18.41 *USDZ in 0xb689d0dd4abdd9f92f95e558ed1fc1ec9c9579814a08c837c35afc1e1c966599; Metal's verification passed: true. Airwallex deposit 62722b09-18b3-4d2c-8b6a-631e31bfee81 with reference 0xb689d0dd4abdd9f92f95e558ed1fc1ec9c9579814a08c837c35afc1e1c966599; payout PAID; transfer 950a0886-dedc-403c-ab80-3e5cfa5e3d01 PAID; received 115174.15 PHP; ledger balanced: true.
- 2026-11-13T07:03:53+00:00: Clicked "Pull a second time after the claim was funded". Metal refused: mandate_budget_spent, recorded on chain in 0x58aecb42e1bcc0d95d2f8bc5b291eea8f4452678e38d8cb8671de11c58cf58f3.
- 2026-11-13T07:04:02+00:00: Clicked "Verify the mandate from the chain": verified true; refusal mandate_cap_exceeded 18.42 *USDZ; refusal mandate_payee_not_listed 18.41 *USDZ; payment 18.41 *USDZ; refusal mandate_budget_spent 18.41 *USDZ.

| What | Transaction or id |
| --- | --- |
| Mandate bound | [`0xd53403b9aebf9271600d35c5536963138f032ca6b39e0f4775ba2c6539a21a9f`](https://testnet.metalntwx.com/tx/0xd53403b9aebf9271600d35c5536963138f032ca6b39e0f4775ba2c6539a21a9f) |
| Pull of 18.41 *USDZ, standing for 1840.55 USD | [`0xb689d0dd4abdd9f92f95e558ed1fc1ec9c9579814a08c837c35afc1e1c966599`](https://testnet.metalntwx.com/tx/0xb689d0dd4abdd9f92f95e558ed1fc1ec9c9579814a08c837c35afc1e1c966599) |
| Refused: `mandate_cap_exceeded` (pull one *usdz cent more than the cap) | [`0xdfaa48a5116f2f2c0196dc8df43dd0c7648fcfc5ca7dc9b9183954ed0e98c3ef`](https://testnet.metalntwx.com/tx/0xdfaa48a5116f2f2c0196dc8df43dd0c7648fcfc5ca7dc9b9183954ed0e98c3ef) |
| Refused: `mandate_payee_not_listed` (pull to an address other than khutlisa's settlement address) | [`0x5fe5b3e58ff8b0500629d26ce06192783a64b79481be2d337b1b59fd7414fbee`](https://testnet.metalntwx.com/tx/0x5fe5b3e58ff8b0500629d26ce06192783a64b79481be2d337b1b59fd7414fbee) |
| Refused: `mandate_budget_spent` (pull a second time after the claim was funded) | [`0x58aecb42e1bcc0d95d2f8bc5b291eea8f4452678e38d8cb8671de11c58cf58f3`](https://testnet.metalntwx.com/tx/0x58aecb42e1bcc0d95d2f8bc5b291eea8f4452678e38d8cb8671de11c58cf58f3) |
| Airwallex deposit, reference the pull's hash | `62722b09-18b3-4d2c-8b6a-631e31bfee81` |
| Airwallex transfer, PAID: 115174.15 PHP | `950a0886-dedc-403c-ab80-3e5cfa5e3d01` |

Every line Airwallex booked for this claim adds up to zero: what arrived, less Airwallex's fees, is exactly what was sent.

## Setting up, the same day

Done once, by hand and then by `scripts/metal_setup.py`. Three faucet grants were used.

- The agent's key 0x2e472dFc2a8237ef5f985Af38391DCC97F21f634 funded with 100 *USDZ by the public faucet: [`0x00626967938b52f519d54353d7a5d23ebea07906e7234e05fc919b53b5bdda81`](https://testnet.metalntwx.com/tx/0x00626967938b52f519d54353d7a5d23ebea07906e7234e05fc919b53b5bdda81)
- First purchase of an RPC endpoint for 1 *USDZ over x402. The payment settled, but the command line failed while reading the answer (`this.client.handlePaymentResponse is not a function`), so the endpoint's URL was lost. Cause: a fresh install pulled @x402/fetch 2.31.0, released the day before, beside the @x402/core 2.28.0 the command line pins. tools/metal/package.json now holds all three x402 packages at 2.28.0: [`0xdced1524f1fc3875ef829e13ca82317775e2f183b234db20ca793ae1b0b57108`](https://testnet.metalntwx.com/tx/0xdced1524f1fc3875ef829e13ca82317775e2f183b234db20ca793ae1b0b57108)
- Second purchase with the packages pinned: 1 *USDZ more of credit, and the same endpoint returned in the `rpc-aas-endpoint` header: [`0xfd44d00f7ecc9d5d5f14f10d7f17f9728cdf9e78f2bf15f03abb013ef883cf44`](https://testnet.metalntwx.com/tx/0xfd44d00f7ecc9d5d5f14f10d7f17f9728cdf9e78f2bf15f03abb013ef883cf44)
- The holder's Metal account 0xA1a662b1Ac52a33A181A83762623B64463645d42 deployed by its owner key 0x14B0f1cB8C0d1faf7e6Fc6154dcAf161bf87e221 (which the faucet funded first): [`0x22404432314fe1b228a8c73ebaba6fcccd79dfa45dfaebde9c59f7197e9f1b91`](https://testnet.metalntwx.com/tx/0x22404432314fe1b228a8c73ebaba6fcccd79dfa45dfaebde9c59f7197e9f1b91)
- The holder's Metal account funded with 100 *USDZ by the public faucet: [`0x41465b915d76d02d9b0be9f015fc0e9b55de7b8985e7dbc8e0b63513f5b9bc13`](https://testnet.metalntwx.com/tx/0x41465b915d76d02d9b0be9f015fc0e9b55de7b8985e7dbc8e0b63513f5b9bc13)
- A first trial mandate by hand (cap and budget 0.05 *USDZ, one payment, payee the settlement address), bound: [`0x4798426223a9dc1ccee8ec3040f45933dc175cc049096b81a0b38c0e26f2dac5`](https://testnet.metalntwx.com/tx/0x4798426223a9dc1ccee8ec3040f45933dc175cc049096b81a0b38c0e26f2dac5)
- Trial: a pull of 0.06 *USDZ refused, mandate_cap_exceeded: [`0x81f7403a6096a4cc948231f6ca454a4851bf6e8ae97ae023aaa79408d9547683`](https://testnet.metalntwx.com/tx/0x81f7403a6096a4cc948231f6ca454a4851bf6e8ae97ae023aaa79408d9547683)
- Trial: a pull of 0.05 *USDZ to the agent's own address refused, mandate_payee_not_listed: [`0x05e711c3f3f5e47684ddbafcb5a0ee2bc83f4719ee966a8ee4b918667db80c8f`](https://testnet.metalntwx.com/tx/0x05e711c3f3f5e47684ddbafcb5a0ee2bc83f4719ee966a8ee4b918667db80c8f)
- Trial: a pull of 0.05 *USDZ to the settlement address paid: [`0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60`](https://testnet.metalntwx.com/tx/0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60)
- Trial: a second pull of 0.05 *USDZ under a new payment id refused, mandate_budget_spent: [`0xf688fbe9f99497b3614f0211247bafe700f430c0fadd0f58b6b4a810e2eaeeac`](https://testnet.metalntwx.com/tx/0xf688fbe9f99497b3614f0211247bafe700f430c0fadd0f58b6b4a810e2eaeeac)

## The run, line by line

| Time (UTC) | What happened |
| --- | --- |
| 2026-11-13T06:52:51+00:00 | Metal: Metal testnet (eip155:63825), metal-agent 0.3.3. Scale: 1 *USDZ on Metal testnet stands for 100 US dollars of the claim, because the testnet faucet gives an address at most 100 *USDZ. Mandates count in *USDZ cents, so one cent on chain stands for 1.00 US dollars and amounts are rounded up to it. No real money moves. |
| 2026-11-13T06:52:53+00:00 | The holder's Metal account 0xA1a662b1Ac52a33A181A83762623B64463645d42 holds 99.95 *USDZ. Khutlisa's settlement address 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec holds 0.05 *USDZ. |
| 2026-11-13T06:52:55+00:00 | Marisol opened claim 35afd281248f47b7 on a demonstration record of 2,316.40 USD held by EMPACADORA VALLE SERENO, and gave a bank account in MXN. |
| 2026-11-13T06:53:04+00:00 | The holder approved 2316.40 USD and signed mandate 0x2da4ebc066583771b8be5a010666de847266c3f41821c44e61ca734b3231c6a3, bound in 0x902e4294e8478ec78a68196b028d08085c4f04178767c99aa828a67cb6dafc83. Every term matches the approval: True. |
| 2026-11-13T06:53:12+00:00 | Staged: Pull one *USDZ cent more than the cap (23.18 *USDZ to 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec). Metal refused: mandate_cap_exceeded. Recorded on chain in 0x3503706bc4ce4b95849a43b30ab2bb953f5307281b6d5e73c9e11effb76f3c38. |
| 2026-11-13T06:53:20+00:00 | Staged: Pull to an address other than Khutlisa's settlement address (23.17 *USDZ to 0x2e472dFc2a8237ef5f985Af38391DCC97F21f634). Metal refused: mandate_payee_not_listed. Recorded on chain in 0x4fd2d768d9c43c4e605940841a7792a187a3b4dc1abcc63f56be949696fbc299. |
| 2026-11-13T06:53:23+00:00 | The plan: Pay with a locked quote; the owner should receive 42403.78 MXN. The owner agrees. |
| 2026-11-13T06:54:54+00:00 | Pull: 23.17 *USDZ, transaction 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348; Metal's verification passed: True. |
| 2026-11-13T06:54:54+00:00 | Airwallex: deposit 3166dd92-16d0-4cce-a7ff-d1ec8344202f of 2316.40 USD with reference 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348; payout state PAID; transfer 99e5d01e-6210-44eb-9ba1-8b1c2d1b166f PAID; received 42409.72 MXN; ledger balanced: True. |
| 2026-11-13T06:55:02+00:00 | Staged: Pull a second time after the claim was funded. Metal refused: mandate_budget_spent. Recorded on chain in 0xb267af7b6b0b7c2e0cfdcd1ecb95f53761c133a22b2ce09122da3cd5373a38df. |
| 2026-11-13T06:55:04+00:00 | The same pull under the same payment id again: outcome paid, already paid: True, transaction 0x2cc29c3b7f167a610d3772f30fdf801f4a690b9c84832b782e94444608cb0348 (the first one). Nothing was sent. |
| 2026-11-13T06:55:13+00:00 | metal-agent mandate verify over the whole mandate: verified True; refusal mandate_cap_exceeded 23.18 *USDZ; refusal mandate_payee_not_listed 23.17 *USDZ; payment 23.17 *USDZ; refusal mandate_budget_spent 23.17 *USDZ |
| 2026-11-13T06:55:14+00:00 | After the run the holder's account holds 76.78 *USDZ and the settlement address 23.22 *USDZ. |
| 2026-11-13T06:55:42+00:00 | Metal: Metal testnet (eip155:63825), metal-agent 0.3.3. Scale: 1 *USDZ on Metal testnet stands for 100 US dollars of the claim, because the testnet faucet gives an address at most 100 *USDZ. Mandates count in *USDZ cents, so one cent on chain stands for 1.00 US dollars and amounts are rounded up to it. No real money moves. |
| 2026-11-13T06:55:44+00:00 | The holder's Metal account 0xA1a662b1Ac52a33A181A83762623B64463645d42 holds 76.78 *USDZ. Khutlisa's settlement address 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec holds 23.22 *USDZ. |
| 2026-11-13T06:55:46+00:00 | Amihan opened claim 9839a46853f7393b on a demonstration record of 120.00 USD held by GOLDEN COAST POWER AND WATER, and gave a bank account in PHP. |
| 2026-11-13T06:55:54+00:00 | The holder approved and signed mandate 0x63dc7db31a739697d9a57139bf71a015a7a01b0ddbfbd4dede75212c0bb85bb6 (cap 1.26 *USDZ, which stands for 126.00 USD), bound in 0x7cabc71e3de9c2b8cc18e1081c8efa564a726364d131117ee55b5e09c8edcb1b. |
| 2026-11-13T06:56:03+00:00 | The holder revoked it before the payment started, in 0x4045614a588d3879b2c8e37ac8a1ef24fd59d0c1682a61a1dd70fd11aa16c6f4. The claim is PROOF_NEEDED again; the approval was withdrawn because the holder revoked the Metal mandate before any money was pulled. |
| 2026-11-13T06:56:10+00:00 | The holder approved again and signed mandate 0xe5906b385a2640d12c093b48f38ca1f8dee7997fd1ea79fa89b83efded0291ba (number 2), bound in 0xa0e6832a1195c4449be6ac228ebad906bf6e9a678055952c41a0dbf9d29ce0b9. |
| 2026-11-13T06:56:17+00:00 | The holder revoked that mandate on chain, outside the application, in 0xcb10f030af81b540a699f0b5e34ede9988b0ac35e38ab0de4bcb8416deb8df61. The owner then agrees to the plan and the agent tries to pull. |
| 2026-11-13T06:56:27+00:00 | Metal refused the pull: mandate_revoked, recorded on chain in 0xf550156e3843ab41f90d2ff8b7bba5d3a8c4cc41f2169dd4e47fa57a9398490d. Payout state HELD, claim state PAYMENT_HELD. The holder revoked the Metal mandate before any money was pulled. Metal refused the agent's pull (mandate_revoked), nothing moved, and the claim is back with the holder. A new approval signs a new mandate. Deposits made at Airwallex for this claim: none. |
| 2026-11-13T06:56:32+00:00 | A mandate with a deadline one minute away: 0x1388204258577a2afa3bc84b3dd2942e33fdde3cade92bce3f927d9f02aec484, cap 1.00 *USDZ, expiry 2026-11-13T06:57:27+00:00, bound in 0x77a35ac42538fc8d5a02a843b519fc08a9a03978343ecfc825aa7293b2ba758f. |
| 2026-11-13T06:57:40+00:00 | A pull of 1.00 *USDZ at 2026-11-13T06:57:40+00:00, after the expiry. Metal's answer: refused, mandate_expired. Recorded on chain in 0x3564008dacd5cbc75e474d008871b7b093a1db32b0b994995140509c2ab9ffbf. |
| 2026-11-13T06:57:43+00:00 | metal-agent mandate verify over that mandate: verified True; refusal mandate_expired 1 *USDZ |
| 2026-11-13T06:57:44+00:00 | Done. The holder's account holds 76.78 *USDZ. |
