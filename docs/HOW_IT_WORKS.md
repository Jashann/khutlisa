# How Khutlisa works

A company that owes money to someone who has gone home to another country uses Khutlisa ("return" in Sesotho) to
find her, check that it is really her, and pay her at home. The agent acts within limits the company sets once.

The company is the holder: the business that reported the money in the first place, and the user Khutlisa is
built for. The screens on which a person tells her history, proves the record is hers and gives her bank account
are her side of the same story. California's public file is the evidence of what happens when holders cannot
reach owners. The State remains the fallback, off the main path, and it pays by a cheque in the post. No holder
uses Khutlisa yet.

The first part of this page is the main journey, one claim from the register to the owner's bank account. The
second part is each capability beyond one claim. The third says how they connect, the fourth what is real and
what is simulated, and the last what is not built.

## The main journey

1. **The register, as evidence.** `scripts/load_registers.py` loads California's four bulk files into one local
   database: 95,425,821 owner records, which describe 89,002,160 properties worth $12,740,723,727. A property
   with several owners has one owner record per owner, each carrying the full balance, so every money figure
   counts a property once. 234,883 properties worth $275,373,406 have at least one owner whose last known address
   is in another country. Queensland's public unclaimed-money register is loaded beside it: 2,566,684 records
   worth 314,265,964.51 Australian dollars, read from the State's open data portal and checked against the count
   and total the portal reports. Its money is never added to California's US dollars, and the screens that show
   it carry the attribution its licence asks for. The opening leads with one fact from the file (Stanford
   University's money, reported by Harvard), runs one real search as it opens and shows the time it took. The
   "who is owed" screen names real organisations that are owners in either file; people are never named there.

2. **The history.** The person tells where they have lived and worked, aloud in their own language, typed, or in
   a form. Speech is turned into words on the machine (whisper.cpp). A hosted language model returns names,
   places and employers in a fixed shape and may ask one follow-up question. The person sees and can correct
   everything before it is searched.

3. **The search.** One search runs over California's 95,425,821 owner records, over Queensland's 2,566,684 where
   that register is loaded, and over the eight demonstration records Khutlisa keeps in a table of its own
   (`src/khutlisa/demonstration.json`). A match is strong only under a stated rule: the family name and a given
   name in full, and one more tie such as a holder the person named together with the postcode. The street is
   never shown and never used by the search, a private owner's name is shown only as first letters, and the
   State's property number never leaves the server. Searches are counted per client address. A record from
   Queensland can be found here; it is claimed from the Public Trustee of Queensland.

4. **The proof file.** The person opens a claim and adds photos or PDFs. Each is read twice by a hosted language
   model that reports only what is printed on it. Everything after that is code: names and addresses are
   compared with the claimant and the register record, each of California's requirements is marked proven,
   partly proven or missing with the reason, dates and machine-readable passport lines are checked, and the issuer
   must be a government of the claimant's country or of the United States. The tie between claimant and owner
   can rest only on photo identification or a document that links the two names. Where code cannot settle a
   point the document is held for a person to look at. Nobody verifies a document with the authority that issued
   it, and the result says so.

5. **The holder's limits and the handover date.** The holder sets its standing instructions once: a tolerance
   for what the claimant receives in local currency, a fee rule (below a small-claim line the holder bears
   Airwallex's fees), a route rule (the route that delivers most to the claimant) and the days within which the
   money must be sent after an approval. Beside them it keeps the date it hands unclaimed property to the State
   (California's schedule, Code of Civil Procedure 1530(d) and 1532(a); the next 1 June until set). When the
   proof is ready the agent pays; when it is not and there is time in hand it asks the owner for what is
   missing; when the date is close it pays what is proven and releases the rest to the State process. All of
   it is arithmetic in code (`instructions.py`, `handover.py`).

6. **Checks across claims.** Every claim is compared with every other claim in the queue (`rings.py`): one bank
   account for different claimants, one document file or a near-identical identity picture under different
   names, shared contacts, name variants, and weaker signals that never link claims on their own. A group of
   linked claims at 60 points or more is held. A held claim cannot be approved or paid; an approval given before
   the link appeared is suspended; money that had already left is recorded and not called back. Only a person
   releases a claim, with a reason, in the risk view (`/risk`). This rule is fixed: the holder cannot switch it
   off.

7. **The holder's decision.** The holder sees the claims behind a key. The claimant gives a bank account in her
   own name first. The holder, not Khutlisa, approves, and the approval covers exact terms: the amount and
   currency, the claimant's name, a hash of the bank details, a hash of every document, and the standing
   instructions as they stood. Any change withdraws it. One property is paid once.

8. **The payment.** Before any money moves Khutlisa writes the plan: the routes compared with Airwallex's own
   quote and fees, what the holder sends under the fee rule, the locked rate and the amount to expect. The
   claimant agrees to it, and the money moves on the Airwallex sandbox, US dollars in and local currency out,
   with Airwallex's records read back after every step. Inside the limits the machine carries on by itself;
   outside them it stops and asks. A refused or returned transfer is waited out, a replacement is planned from
   the money that came back, the claimant gives a corrected account and the holder approves it, and the
   claimant is asked about the amount only if it falls outside the tolerance. Each decision is shown as a card
   of four short lines: what happened, what the limits allowed, what the agent did, the result in money
   (`cards.py`). `docs/AIRWALLEX_FLOW.md` has the details.

9. **Funding on Metal, if the holder chooses it.** With the approval the holder can fund the claim on Metal
   testnet instead of by a bank deposit. The approval signs a mandate with its own terms (one payee, a cap of what
   the holder sends, one payment, an expiry at the deadline or the handover date, whichever is first), and the
   agent pulls under it. A pull over the cap, to another address, a second time, after the expiry or after a
   revocation is refused by the holder's Metal account on chain. On testnet 1 \*USDZ stands for 100 US dollars of
   the claim, and the screens say so beside every amount. `docs/METAL.md` has the details.

10. **The fallback.** If the holder does not pay, the claimant can claim from the State herself, on a tab of its
    own: Khutlisa prepares a PDF with the property, the claimant's details, the checklist and a guide to signing
    from abroad. It files nothing.

## Beyond one claim

### The whole book

A book is everything one holder reported for owners abroad in California's file, one line per property with the
country, the amount and the kind of money and no owner's name or street (`make_books.py`, `book.py`). For a
chosen holder the agent plans how to pay all of it, in code: each claim's route from what the Airwallex sandbox
answered for its country (local rails, SWIFT, or no transfer), its cost and who bears it under the fee rule, what
owners would receive in their own currency, how each currency is funded from real quotes at six sizes, which
corridors can still finish before the handover and in what order. The "Book" screen recomputes the plan as the
small-claim line, the tolerance and the handover date move, and says what moved. Bank of America's book is
26,190 properties worth $75,493,098 in 147 countries. The plan is made from public figures; no holder asked for
one.

### Batches

A slice of a book's plan runs for real on the sandbox (`batch.py`, the "Batch" screen): one invented owner in each
of up to nine corridors, each owed the median claim of her corridor, with example bank details checked against
Airwallex's live schema. The holder approves exact terms. One deposit funds the batch, each currency that can be
held is converted once, and every payment is carried by the same payout machine as a single claim, so nothing is
paid twice and a restart carries on. At the end every ledger row is read back and each currency must add up to
zero. `docs/SANDBOX_RUN_LOG_BATCH.md` is the record of a run to nine countries.

The holder can also pay approved claims from its own queue together. It ticks two or more approved claims (not
estates, not funded on Metal, without a payment of their own) and writes a batch. Each payment keeps its claim's
approval, its own fee rule from the instructions bound to that approval, and its own account; only the deposit is
shared. Claims approved under different instructions cannot share a batch. Each claim is checked again when the
batch is written, when it is approved and before its deposit. A claim stays approved until the deposit arrives,
then pays, and is marked paid when its transfer is; if the batch stops before the deposit the claim goes back to
being approved, to be paid another way.

### The holder's own list, the notices and the funnel

California's file is money already handed over. A holder can start from its own records while the money is still
with it.

- **The file.** The holder uploads its list of dormant balances as CSV or Excel (`holder_file.py`). A language
  model proposes which column is which from the titles and at most 20 rows in which every name, address, contact
  and reference has been replaced by its shape; without a model the proposal is made in code. The holder
  confirms the columns, the mapping is remembered, and every row is validated in code with the reasons for the
  ones that fail (`holder_list.py`).
- **The dormancy picture.** Each balance is placed on California's calendar (`dormancy.py`): wages count as
  unclaimed after one year and most other property after three; what is dormant on 30 June goes on the Notice
  Report due before 1 November, and to the State the next June. The queue lists what is owed abroad, soonest
  handover first.
- **The notice the law requires.** For each owner of 50 US dollars or more the agent prepares the notice of Code
  of Civil Procedure 1520(b) (`notices.py`): the heading the law gives, the date the property goes to the State,
  the statements the law wants in bold, a form to return, and a personal link with a short code. It is always in
  English, with a second page in the owner's likely language. The facts are put into both languages by code and
  checked to stand in each exactly as in the English. A notice with a required element missing is held back.
- **Nothing is sent.** The holder sends each notice and marks it sent; until then its code opens nothing.
- **The owner answers.** The link opens the notice in her language, without her name or street. She confirms who
  she is and a claim opens on that exact record (number `HL-...`, source `HOLDER`, or `DEMO` for the invented
  file). From there it is the main journey: the checks across claims, proof, bank account, approval, payment,
  alone or in a batch. The holder's records are looked up only by their own number; the open search never runs
  over them.
- **The funnel and three decisions.** The holder sees prepared, sent, opened, answered, proven and paid, with the
  days to the handover. The agent decides, in code and shown as cards, who is notified first, when a reminder is
  due, and at the handover date what to pay, what to hold for proof and what to release to the State.

`docs/CALIFORNIA_CLAIMS.md`, section H11, has the rules with their sources and what stayed unverified.

### Estates

A large share of dormant money belongs to people who have died. The "Estates" page leads to the estate view of a
claim (`#estate/<claim>`). The claimant says in her own language who has died and who the family is; a model
turns the words into the family structure, and `succession.py` computes each heir's share under California's
Probate Code as an exact fraction, with the section behind each step, asking one question at a time for what the
rule still needs, or refusing with the section in the way. Each heir is tied to the owner by certificates read
twice. The holder approves the estate on the exact shares, heirs and accounts. One settlement then pays every
proven heir at home in their own currency from one deposit, holds the share of an heir not yet proven for a later
round, and reads the ledger back to zero. Where the owner lived outside California the default is computed and
the holder must write down why it is used. An estate is never funded on Metal: a mandate mirrors one approval
paid to one account. `docs/HEIRS.md` has the law and the rules for fees and cents.

### A copy anyone can open

`Dockerfile` builds one container: the server, the built pages, whisper.cpp and ffmpeg, and fonts for the
letters, with no data and no credentials. A first start fetches and builds California's file in the mounted
volume while serving the demonstration records, with its progress on `/api/ready`. `KHUTLISA_PUBLIC_DEMO=1` turns
on the public demonstration (`public_demo.py`): the search, the holders' screens and the demonstration journeys
stay; a claim can be opened only on a demonstration record; only the sample documents (for a claim and for an
estate) and the demonstration sound are accepted; only the invented holder file can be loaded; approving, paying,
settling an estate, releasing a hold, writing or approving a batch of claims, and every Metal step work only on
demonstration claims; the model's answers for the demonstration inputs are replayed from a recording, and with
a key a small number of live calls a day are allowed; funding on Metal is off; and every request is counted per
client address. `deploy/README.md` has the commands that were run on Google Cloud.

## How the parts connect

- **One set of standing instructions.** They are bound to each approval. A single payment, a batch of approved
  claims, a Metal mandate and an estate settlement read them from that approval, so a claim gets the same fee
  rule, tolerance and deadline whichever way it is paid. A later change does not touch an approval already given.
  The book's plan starts from the saved instructions.
- **One handover date.** Kept beside the instructions, it drives the deadline choice on each claim, the book's
  plan, the holder's list and its notices and funnel, and the expiry of a Metal mandate.
- **The checks across claims run everywhere money is decided.** Before every approval (single claims, estates, a
  batch of claims) and before every payment (a single payment, an estate settlement, a batch before its deposit, a
  Metal pull). A claim opened from a notice keeps the same fingerprint as one opened from the search, so it is
  compared like any other, and it appears in the queue, the funnel and the risk view.
- **One payout machine.** Single payments, both kinds of batch and each heir's share use the same machine, with
  the same protection against paying twice and the same replacement path after a refusal.
- **One navigation.** Every screen carries the same links: the opening, who is owed, for holders (top holders,
  the whole book, the holder's own list and notices, the limits, the queue, risk), find your money, estates, and
  "What is real here".

## Where a language model is used, and where it is not

A model reads speech transcripts and document images, turns an estate claimant's words into a family, rewords
the sentence that explains a change in a payment (kept only if every figure in it is one the code supplied),
proposes the columns of a holder's file from masked rows, and translated the notice's sentences once, with
placeholders and no owner's details. It makes no decision. Matching, proof, readiness, approval terms, the
standing instructions, routes, amounts, fees, tolerances, deadlines, duplicate protection, every change of state,
the book's plan, batches and their reconciliation, the shares of an estate, the checks across claims, the
validation of a holder's file, the dormancy calendar, the elements of a notice and the funnel's decisions are
code. The tests replace the model with a table.

The public copy has no model key. Its answers for the demonstration's fixed inputs (the sound files, the sample
documents, the invented holder file, the demonstration people's words) were recorded once on a developer's
machine (`scripts/record_demo_answers.py`) and are replayed by a hash of the exact prompt and file bytes
(`recorded.py`); both readings of each document were recorded, so the comparison still runs. Payment
explanations there use the fixed sentences. A copy run with a key, or on a developer's machine, calls the model
live.

## What is real and what is simulated

Real:

- California's published records, loaded whole, and Queensland's register, loaded whole and matching the portal;
  every total, every holder's book and every figure on the holders' screens computed from them.
- The search over both files, every time.
- The reading of documents and the checks that follow, and California's requirements as read on the
  Controller's pages (`docs/CALIFORNIA_CLAIMS.md`), including the notice rules and the dormancy periods.
- Every Airwallex call, on the sandbox: corridors, rates, quotes, transfers, refusals, fees and ledger lines are
  what it returned.
- Every Metal mandate, pull and refusal: a signed transaction on Metal testnet, with its explorer link.
- The arithmetic of the instructions, the estate shares and the checks across claims.

Simulated or demonstration. The "What is real here" panel says this once, on every screen:

- **No real money moves.** Sandbox money and testnet tokens only. On Metal testnet 1 \*USDZ stands for 100 US
  dollars of a claim. The sandbox cannot receive \*USDZ, so a settled pull is credited there as a simulated
  deposit whose reference is the Metal transaction hash.
- **The holder.** No holder uses Khutlisa, and none has been asked. The holder's view is the same application
  behind a shared key; its deposit is staged with the sandbox's deposit call into Khutlisa's single sandbox
  account. On Metal the holder's key is held by the same machine, because a script plays every part.
- **The people.** Marisol and Amihan, their seven records and documents, the owner of the demonstration estate
  (an eighth record), his four heirs and their eleven documents, the owners in a batch from the book, and the
  owners in the holder's list are all invented. Documents carry the word SAMPLE. Marisol's voice is a synthetic
  macOS voice; its transcription is real.
- **The holder's list and the notices.** The file is invented (an employer's export of uncashed pay for about
  3,200 former workers). Notices are prepared and never sent; the holder marks them sent. No Notice Report or
  Remit Report is filed. The translations were made by a model and checked in code; no translator or lawyer has
  read them.
- **A book's plan.** Computed from public figures and the sandbox; it says what could be paid if every owner
  claimed and proved her property.
- **The "what if" cases.** A short deposit, a refused or returned transfer and an expired rate lock are staged
  with the sandbox's own simulation calls; what the product does about them is its real behaviour.
- **The checks across claims.** Measured on invented claims; the points were reasoned, not fitted to real fraud.
- **The law.** Paying an owner abroad by bank transfer under Code of Civil Procedure 1532(b) and 1560(b) is our
  reading; the Controller's pages neither name nor rule it out.
- **Filing.** Nothing is sent to California; the packet is for the claimant to sign and send.

## What is not built

- A claim on a record from Queensland's register (it is searched, and claimed from the Public Trustee), and any
  other register.
- Verifying a document with the authority that issued it, and a way for a person to release a held document.
- Sign-in for claimants (a claim is open to whoever holds its 16-character number), encryption of stored
  documents, and webhooks (payments are followed by reading Airwallex again).
- A holder's own Airwallex account; every holder shares the one sandbox account.
- Funding an estate or a batch on Metal.
- In the holder's list: currencies other than US dollars, shares and safe deposit boxes, a holder's own fiscal
  year end, notices in scripts the PDF library cannot set (Arabic, Hebrew, Thai, the Indic scripts get English
  only), and the claim screens after the notice in the owner's language.
- In an estate: a signed declaration from each heir (it is a tick), and more than one person answering for the
  family.
- Sending anything outside the application: no notice, reminder or message to an owner, and no report to the
  Controller.
