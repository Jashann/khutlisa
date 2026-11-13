# Walk-through notes

`scripts/walkthrough.mjs` drives the built app in a real browser (Chromium, 1920 by 1080) on one server, on
California's whole file, Queensland's register and the demonstration records, with the live Airwallex sandbox and
Metal testnet behind it. It walks the main journey and then each capability in turn, and saves every step as one
numbered sequence in `docs/shots/walk/` (`001-...png` onwards), with the fallback packet's pages in
`docs/shots/walk/packet/`, the notice letter in `docs/shots/walk/letter/` and `docs/shots/walk/summary.json`. On
every screenshot it checks for cut-off text, text under 13 pixels, sideways scrolling, internal state names, long
dashes and emoji, and it records every error in the browser console and every server error. On the screens of the
main path it also checks that nothing says the claim is being sent to the State, and that each main-path screen
fits the window. Before every picture it blurs the cards of real owners, so no picture holds a real person's
record. A part whose service cannot be reached (Metal testnet) is marked skipped with the reason, never faked.

The walk tells one story: a company that owes money to someone who has gone home to another country (the holder)
finds her, checks that it is really her, and pays her at home, with an agent that acts within limits the holder
sets once. A script plays every part: the owner, the holder and, through the sandbox's own simulation calls, the
receiving bank. That is why steps that would take people hours follow each other within seconds.

## The last whole run (13 November 2026 UTC, 101 numbered screenshots, 0 problems reported)

All six parts ran on one server, so each part's claims were in the queue, the funnel and the risk view of the
next.

1. **The main journey, the book, the batch and Queensland**: as described step by step below.
2. **Metal testnet**: Amihan's 412.07 US dollar claim was approved on Metal from the holder's view. The approval
   signed a mandate with the approval's terms; Metal refused a pull one cent over the cap and a pull to another
   payee, each with its own transaction on chain; the pull of 4.13 *USDZ (at 100 US dollars to one *USDZ)
   funded the Airwallex deposit, whose reference is the pull's transaction hash, and 25,573.16 PHP was paid with
   Airwallex's lines at zero.
3. **The holder's own list**: the invented file, the queue of owners abroad, the notices in Spanish and English,
   the funnel, and Marisol answering her notice with the code on the letter; her claim was proven, approved and
   paid in Mexican pesos, and the funnel moved to paid.
4. **The estate**: from "Estates" in the navigation to the demonstration family; shares of 1/3, 2/9, 2/9 and 2/9
   of 4,618.37 US dollars; one refused transfer replaced; the granddaughter paid in a second round; every
   currency at zero. `docs/SANDBOX_RUN_LOG_ESTATE.md` is this run's record.
5. **The risk view**: 73 planted claims were copied into the same queue. The view looked at 80 claims (the
   walk's own claims among them, including 1 from a notice and 1 estate), held 11 and suspended 2 approvals in 4
   flagged groups, recorded 2 paid before their link showed, released one honest claim with a reason, and the
   holder's card of a held claim said why it was held.

Model readings differ between runs. In one of the five runs made while the walk was put together, one of the two
readings of an heir's passport disagreed on the expiry date, the heir was held for a person to look at, and the
estate part stopped there; that is the design (a disagreement holds a document), not a fault of the walk.

## The main journey in detail (from an earlier run of the same day; amounts differ with the rate of the moment)

1. The opening, in ten seconds. "Stanford University is owed $55,690.09. Harvard reported it." Then the whole
   file, $12.74 billion in 89 million properties; the counter running up to $275,373,406 in 234,883 properties
   owed to people whose last known address is in another country; the live line "95,425,821 owner records
   searched in 2.6 seconds, just now, with Queensland's 2,566,684 beside them"; "The State's only way to pay is
   a cheque in the post."; and one line on what Khutlisa does.
2. Who is owed. The prepared pairs, led by Stanford's money reported by Harvard, and a typed name: 4 properties
   owned by an organisation with "university of tokyo" in its name, from 95,425,821 owner records in 0.3 seconds.
   Then the second register. The "Queensland" tab listed eight organisations with their amounts in Australian
   dollars (Telstra Corporation 21,424.35 AUD, sent by Energex, at the top), and the panel beside it read
   "2,566,684 records worth 314,265,964.51 AUD, searched in the same pass. Australian dollars, kept apart from
   California's US dollars", with the attribution. A typed name, "telstra", found 3 properties in California's
   file and 20 in Queensland's register, each on its own list in its own currency.
3. For holders. 4,965 holders, 234,883 properties, $275,373,406; the largest were Bank of America, Charles
   Schwab, Union Bank, CATHAY BANK and APPLE INC. "Who can pay, and why it would": any holder with a bank account
   can pay by transfer today and the State cannot, with five duties the law already puts on a holder, each a
   link to its source, and "What these duties cost any one holder is not published, and no figure for it is
   given here." By kind of money: bank accounts and deposits $162,666,763 in 69,622 properties; shares,
   dividends and brokerage balances $83,977,002; bank cheques $6,398,400; refunds and customer credit balances
   $5,614,179; vendor payments $3,822,697; wages, payroll and commissions $1,445,038 in 8,593 properties. By kind
   of holder, where the name says it, with 305 holders that reported wages counted as employers by what they
   reported. The law in a sentence and 200 days to the next handover, 1 June 2027.
4. What is real here. One panel, opened from the top bar, says the caveats once: the demonstration person, her
   documents and the owners in a batch, sandbox money, no holder uses Khutlisa yet and a book is a plan made
   from public figures, documents read and not verified, and that paying by bank transfer abroad under those
   two sections is our reading.
5. The holder's view. Locked without the key (the API answered 401). With the key the holder saw the days left
   and set its limits once: 0.5 percent, 250 US dollars, the best route, 14 days to send the money, and 30 days
   before the handover as the point where it stops waiting for documents.
6. The whole book of Bank of America, opened from the holders list: 26,190 properties, $75,493,098, in 147
   countries. $41,574,796 by local rails in 80 countries, $32,950,285 by SWIFT in 51, $964,628 not payable by
   transfer in 14, and 854 claims ($3,389) smaller than the fees to send them. Fees $439,888, which is 0.59
   percent of the $74,525,080 paid in time. The screen said that the plan was computed from the holder's figures
   in California's public file and from Airwallex's sandbox and that the holder did not ask for it. The six
   decision cards, four lines each: the routes; the fee rule ("8,390 claims below $250.00; 16,124 at or above
   it. ... The holder adds $55,955 so the small claims arrive whole."); the claims smaller than their fees
   ("Sending them would cost $9,012 to deliver $3,389."); the funding ("Airwallex quoted the same rate at 6
   sizes, 10 to 1,000,000 USD. ... Once per currency in 26 currencies; inside each transfer in 54 that cannot be
   held ahead. The holder funds $74,581,035. Saves $0.00 and 17,837 conversions."); the order of work (China,
   Taiwan and Japan first); and what a refused transfer would do under the tolerance.
7. The plan changes when the limits change. The small-claim line raised from $250 to $1,000: claims on which
   the holder bears the fees 8,390 to 15,143, what the holder adds $55,955 to $127,236, what the holder funds
   $74,581,035 to $74,652,316. The handover date moved to 34 days away: corridors that can finish in time 131 to
   39, dollars paid in time $74,525,080 to $42,370,199, $32,154,882 too close to the handover, and 92 corridors
   dropped (China, Taiwan, Saudi Arabia and 89 more: the ones that need SWIFT or a slower rail). The tolerance
   raised from 0.5 to 2 percent: claims that would be re-sent after a refusal without asking about the amount
   8,459 to 15,037.
8. Two other books. APPLE INC, chosen from the list: 49,055 properties worth $11,923,589, of which 32,167 claims
   ($137,342, mostly dividends of a few dollars) are smaller than their fees and stay with the State process;
   $8,913,776 by local rails and $2,852,820 by SWIFT. HERBALIFE INTERNATIONAL OF AMERICA INC, opened by typing
   "herbalife": 5,812 properties worth $987,186; $656,437 local, $60,735 SWIFT, and $270,014 not payable, most
   of it owed to owners in Russia, for which Airwallex returned no schema at all.
9. A batch from the plan. A request without the holder's key was refused (401). "Run a slice on the sandbox"
   wrote batch `09643fdd3e83`: nine invented owners in nine countries and nine currencies, each owed the median
   payable claim of her corridor in the book (the first, in Taiwan, the claim at the ninetieth percentile), and
   nothing moved until the holder approved. After the approval: one deposit of 10,089.62 US dollars, on which
   Airwallex booked 30.27; six conversions, one for each currency that can be held (AUD, CAD, EUR, GBP, JPY,
   MXN); PHP and INR converted inside their transfers. Seven payments were paid and two transfers, staged to be
   refused, stopped for people. Meilin Zhaoqing in Taiwan (6,468.89 US dollars by SWIFT): the replacement was
   0.39 percent less, inside the limit, so she was not asked to confirm the amount; her second account was
   asked for and the holder approved it. Ximena Olvareda in Mexico (232.20 US dollars, fees borne by the
   holder): 2.18 percent less, outside the limit, so after the corrected account and the holder's approval she
   was also asked to agree. Each button on screen is marked for who presses it ("Demonstration owner", "Holder").
   Paid: 6,399.46 USD, 157,539 JPY, 4,179.12 MXN, 419.97 CAD, 25,518.45 PHP, 258.21 GBP, 500.61 EUR, 438.70 AUD
   and 41,780.17 INR. The screen ended on "Every currency adds up to zero" for AUD, CAD, EUR, GBP, JPY, MXN and
   USD, and on the planned cost, 92.26 US dollars for 9 transfers, beside what Airwallex booked, 122.29 for 11:
   the difference of 30.03 is the two second payout fees (25.00 US dollars and 93.03 MXN) and two cents on the
   incoming fee. 211 calls to Airwallex.
10. Marisol's account. A synthetic voice read a prepared account, the same file was transcribed on this
    machine, and the words on screen were what the recogniser heard. "Searched 97,992,505 owner records in
    California's and Queensland's public files, and 7 demonstration records, in 1.5 seconds"; 8 cards were
    shown, 5 of them real owners (masked on the page, blurred in the pictures). The follow-up question was
    headed "One more question: the old postcode" and asked "What was the postcode of where you lived in Salinas,
    California?" Her spoken answer lifted the wages record from possible (0.75) to strong (0.87), and the card
    said about 42,409.04 MXN today at an indicative rate that is not locked.
11. The proof. The staff badge was refused as photo identification. With 200 days in hand the deadline card on
    her claim read: "Time in hand: it asked the owner for photo identification and 2 more." The passport was read
    twice and checked in code, and with the tax number letter and the bank statement the proof became ready.
12. Her bank account (ending 7771), then "The holder decides next." The claim never passed through the packet
    for the State. The holder saw the proof, the sentence that Khutlisa read the documents and has not verified
    them with the issuing authority, the deadline card, the fee card and the exact terms, and approved.
13. The payout plan as two decision cards. Fee: "A claim of $2,316.40. Fees are about $11.95, 0.5% of it. From
    $250.00 up, fees come out of the claim. The holder sends $2,316.40. $2,304.45 is left to convert for the
    owner." Route: "Two routes to MXN, priced with Airwallex's own quote and fees. Take the route that delivers
    the most to the owner. Chose: pay with a locked quote. 42,367.05 MXN expected. The other route would bring
    about the same." The two routes differed by 1.11 MXN, which is not given as a figure on the card any more.
14. The refusal. $2,316.40 arrived and Airwallex booked $6.95. The first transfer, to the account ending 7771,
    was refused (Invalid account name/number) and shown as a red stop on the money's line; 42,384.19 MXN came
    back. The decision card: "0.18% less, inside the limit: did not ask the owner to confirm the amount. Still
    asked: the corrected account and the holder's approval. 42,291.16 MXN in place of 42,367.05 MXN." She gave a
    corrected account ending 7823, the holder approved it, and one replacement was paid: 42,291.14 MXN, transfer
    `5615015e-d991-4ede-82de-663c22a66973`, reference P261113-1TJU6SZ. The first transfer
    (`08080ffc-13ec-4417-84a8-ce9d7d67d577`) is CANCELLED at Airwallex. Airwallex's five lines add up to zero in
    both currencies. `docs/SANDBOX_RUN_LOG_REPLACEMENT.md` is the record of this payout.
15. The same event on a small claim. Her 95.00 dollar deposit from another holder was opened and approved off
    screen through the same routes, to the same first account. The holder sent $100.31 under the fee rule, the
    bank refused that transfer too, and 1,747.49 MXN came back. The card: "The replacement is 5.29% less. Outside
    the limit: it stopped and asked the owner. 1,654.44 MXN in place of 1,746.78 MXN." The holder's view put the
    two claims side by side under one heading, "The same event, the same limits, two outcomes", with the line
    "A corrected account is always asked for, and you always approve it." She then agreed, and 1,654.44 MXN was
    paid (transfer `af3cbd2c-7d1e-4009-83c8-399042f289a4`), with the lines adding up to zero.
16. A small claim under the fee rule. Amihan's account was typed in Tagalog. The fee card: "A claim of $120.00.
    Fees would take $5.36, 4.5% of it. Below $250.00 the holder bears the fees. The holder sends $125.38. The
    owner gets the whole $120.00." $125.38 arrived, Airwallex booked $0.38, and 7,555.99 PHP was paid (transfer
    `c22d12d4-fa6d-42ef-b18b-2098e2f12ae0`), 3.06 PHP more than agreed because a better rate was on offer when
    it was used. Three lines, adding up to zero. `docs/SANDBOX_RUN_LOG.md` is the record of this payout.
17. The handover date decides. Amihan's wages claim of $1,840.55 had only a staff badge, and the API refused to
    approve it (409). With 200 days left the card read "Time in hand: it asked the owner for photo identification
    and 2 more." The holder then set its date to 1 December 2026, 18 days away, and the card read "Too close to
    wait: this property is released to the State process. $1,840.55 goes on the Remit Report. The owner claims
    it from the State." Across the queue: "Near the date: it pays what is proven (3 claims) and releases the rest
    (1 claim) to the State process. $2,531.40 to owners. $1,840.55 goes on the Remit Report."
18. The fallback, off the main path. Her claim screen showed the same card with a button to "If the holder does
    not pay: claim it from the State yourself". The packet was downloaded there and its 6 pages rendered.
19. The last numbered picture is the paid claim with its whole history. Apart from the numbered pictures, a second
    server was started without the register database, and it said that California's file is not loaded and only
    the demonstration records were searched.

The records in `docs/` are of separate runs: `SANDBOX_RUN_LOG.md` and `SANDBOX_RUN_LOG_REPLACEMENT.md` are from
this walk, and `SANDBOX_RUN_LOG_BATCH.md` is from a batch run by `scripts/run_batch.py` an hour earlier (batch
`9cd9952cd05d`), so its amounts differ from the batch of step 9 with the rate of the moment.

## What is still not good

1. No real person and no real holder has used this. Every paid claim is on an invented record with documents
   the builders drew themselves, and the holder is the same application behind a key.
2. A book's plan says what could be paid if every owner claimed and proved her property. Nobody has, the holder
   whose book it is did not ask for the plan, and most of the money in the file is already with the State.
3. The owners in a batch are invented and have no documents behind them. Their approval is the holder's approval
   of the batch on screen, and a script, or a person pressing a button marked "Demonstration owner", plays them
   after a refusal.
4. The funding decision saved nothing on the rate: the sandbox quoted the same spread at every size from 10 to
   1,000,000 US dollars in all 86 currencies. What converting once saves is conversions. Whether a production
   account is quoted the same way was not tested.
5. The payout fee is what the sandbox charged for the corridors that have been paid from this account (eight
   currencies by local rails, and SWIFT) and Airwallex's published price, marked as an estimate, for the rest. Where both are
   known they differ, and the sandbox account is registered in Canada while the published prices read are for
   US customers.
6. The days a corridor needs are an owner's 30 days for documents plus the rail's longest documented time. For
   a country whose guide was not read the SWIFT time is used and marked as an estimate, which is why some local
   corridors drop out together with the SWIFT ones when the handover date is moved close.
7. "Asking the owner" and "releasing to the State process" are choices the agent makes and shows on the holder's
   and the owner's screens. No message leaves the application, no claim changes state, and no report is filed
   with the Controller.
8. The handover date is the holder's own setting. California's schedule is verified (1 to 15 June, or 1 to 15
   December for life insurance companies); the walk uses 1 December to bring the date near, which is the life
   insurance window, although the demonstration holders are not insurers.
9. The refusal is staged from a control on the payment screen with the sandbox's own simulation call, and the
   first account is not really wrong: the sandbox refuses it because it was told to.
10. The follow-up question is written by the model, so its words differ on every run. The model is told to ask
    for the postcode first, the heading above it is set in code from what the history lacks, and the walk fails
    if the question asks for anything else or if none is asked.
11. The documents are read by a model, twice, and a point either reading raises blocks by design, so one run can
    differ from the next. Reading a document does not show that it is genuine.
12. Queensland's register is searched and shown; a claim on one of its records is not built. It has no street
    and no city, only a postcode, so a match in it rests on less than a match in California's file.
13. The rate-lock case, the short deposit, the returned transfer and the 14-day sending deadline are not walked
    in the browser. They are covered by the tests.
14. One shared Airwallex account holds every claim's and every batch's money. A real version needs an account
    per holder. Whether Khutlisa would count as an investigator under Code of Civil Procedure 1582, and whether a
    bank transfer abroad counts as reuniting property under 1532(b) and 1560(b), are open questions. They have
    not been put to a lawyer or to the Controller's office.
