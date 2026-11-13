# Rings: organised false claims, caught across the whole queue

One forged claim can look sound on its own. A ring shows only when claims are put side by side: one bank account
that receives for several claimants, one picture of an identity card used under several names, one mailbox behind
a handful of near-identical names. Payers that cannot see this freeze whole countries after a few forged claims.

Khutlisa compares every claim with every other claim, in code, with no language model. Linked claims form groups.
Each group gets a rating that is a plain sum of named points. A group at 60 points or more is held before any
money moves, and only a person at the holder can release a claim, with a reason.

The code is `src/khutlisa/rings.py` (the detector) and `src/khutlisa/rings_api.py` (the routes). The screen is
`/risk`.

## The signals

Every signal is looked for across all claims in the store, whatever their state, including paid and rejected ones.

| Signal | The rule | Points | Links claims |
| --- | --- | --- | --- |
| Bank account | The same account (bank country and account number) is on two claims. An heir's account on an estate claim counts as that claim's account. | 60 | yes |
| Document file | The same file (same SHA-256) is in two claims. This is the only comparison made for PDF files. | 60 | yes |
| Near-identical picture | Two photo identification images differ in 8 of 96 tiles or fewer and are not the same file. See "The picture comparison". | 50 | yes |
| Email | The same mailbox on two claims. Compared in lower case; a plus-tag is dropped; dots before the @ are dropped for Gmail only. | 30 | yes |
| Phone | The same last ten digits, when a phone is on file. | 30 | yes |
| Name variants | Two claimant names on different properties that are near-identical and not identical. See the rule below. | 25 | yes |
| Device | The same network and the same browser line. | 20 | no |
| Account name | Accounts with different numbers in the same holder's name. | 15 | no |
| Readings disagree | The same field of the same kind of document disagrees between its two readings in 3 claims or more. | 15 | no |
| Network | The same network, another browser. Ignored when more than 10 claims share the network. | 10 | no |
| Address | The same typed address: same words in any order, common street words in one spelling. | 10 | no |
| Burst | 4 or more claims on different properties of one holder, opened within 30 minutes. | 10 | no |
| Size | 3 or more claims are linked. | 10 | |
| Size | 5 or more claims are linked (in place of the 10). | 20 | |

The name variant rule: the words of both names are compared in any order. Words both names carry are set aside.
What is left must be one word on each side that is one letter apart (two letters for words of seven letters or
more), or two words on each side that are each one letter apart, or a single added initial. Identical names are
never variants, because two honest people can carry the same common name. A shared family name alone is not a
variant either.

## From signals to a hold

1. Two claims are **linked** when the points between them reach **30** and at least one of the signals is a
   linking one (the "yes" rows above).
2. Linked claims form a **group**.
3. The group's rating is the sum of its rows: each signal found between any two claims of the group counts once,
   at its fixed value, plus the points for size.
4. A group at **60 points** or more is **held**.

What reaches 60:

- One shared bank account, or one shared document file, by itself.
- A near-identical identity picture (50) with a third claim on the same picture, or with any one other signal.
- One email or one phone (30) together with name variants (25) and anything else, or together with the other
  contact (30 + 30), or together with a shared device across three claims (30 + 20 + 10).

What never reaches it: a shared network, a shared device, a burst, an address, an account name and a pattern in
the readings cannot link two claims, alone or together, so they never form a group and never hold a claim. They
only add to a group that a linking signal has already formed. A claim that shares only a network with a ring
member is not pulled into the ring.

## Honest situations that are taken out first

- **One person with several properties.** Two claims are one person when the name is the same word for word (in
  any order), the country is the same, and the email, the phone or the typed address is the same. No signal is
  raised between them, so one account and one set of documents on both claims is not a ring. This covers up to
  three properties; from the fourth, the claims are compared like anyone else's, so that one invented identity
  cannot collect many properties without a look.
- **A family at one address.** Two claims are one household when the typed address is the same, the names share a
  word of three letters or more, and the names are neither identical nor variants of each other. Between them an
  address, a network, a device, an email, a phone, a burst and a shared bill mean nothing. A shared bank account,
  a shared identity document and a pattern in the readings still count.
- **The same common name.** Identical names are not a signal. Two people with the same name in different
  countries share at most the weak "account name" signal, which links nothing.

## What is stored about where a claim came from

When a claim is opened through `POST /api/claims`, a creation hook stores this in `claim["origin"]` and nothing
else:

- `network`: a keyed hash (HMAC-SHA-256, cut to 16 characters) of the client address the connection came from.
- `agent`: the same kind of hash of the browser's User-Agent line.
- `at`: the time.

The address and the User-Agent line themselves are never stored. The key is a random value kept in
`origin_salt.txt` beside the claims, so the hashes cannot be turned back into addresses by trying addresses
without that file. When a forwarding header is present the connection came through a proxy, so no network hash is
kept at all. The claimant never sees `origin`. The holder's risk view shows only the words "one network" or "one
device".

Why it is kept: several claims opened from one device in a few minutes is one of the few things a ring cannot
easily hide. Why it is weak: honest people share networks. A family, a library, a mobile carrier and an office
each put many people behind one address. So a network or a device is worth 10 or 20 points, never links claims,
and can never hold a claim by itself.

## The picture comparison

One whole-image hash of 64 or 256 bits could not do this job. Measured on sample cards, "the same picture with the
name changed" and "another person's card printed from the same template" sat about as many bits apart. So the
picture is hashed tile by tile: it is made grey, stretched to full contrast and shrunk to 96 by 64 points, which is
12 by 8 tiles. Two tiles are the same when their brightness is within 24 grey levels and their pattern is within 8
grey levels on average. The distance between two pictures is the number of tiles that differ, from 0 to 96. The
hash is worked out once per file and kept in `image_hashes.json` beside the claims, keyed by SHA-256.

Measured on generated sample cards (3 draws of 40 people):

| Pair | Tiles that differ, of 96 |
| --- | --- |
| One card saved again at another size, brightness and JPEG quality (84 pairs) | 0 |
| One card with the name changed (198 pairs) | median 4, most 7 |
| Two people's cards from one template, both flat scans (2,340 pairs) | 9 at the closest |
| Two people's cards from one template, both photographed (2,340 pairs) | 45 at the closest |

The line is 8. The gap between 7 and 9 is thin, which is why a near-identical pair is worth 50 points and is not
held alone.

Pictures are compared only among photo identification. Bills and letters printed from one template differ in a
few words by nature (2 to 8 tiles on sample bills), so they are compared as whole files only. PDF files are
compared by SHA-256 only.

## What the agent does

- **Hold.** A claim in a held group cannot be approved and cannot be paid. The detector registers an approval
  check and a payment check on the claim store; both refuse with a sentence. The holder's sentence names the
  signals. The claimant's sentence says only that a safety check has paused the payment and says nothing about
  any other claim.
- **Suspend.** An approval given before the ring showed is suspended while payment has not started. The approval
  is not withdrawn. One dated line goes into the claim's history and into `claim["risk"]`, once.
- **Money already left.** A claim that is being paid or has been paid when the link shows is recorded as such,
  with the date and the amount. Nothing is called back. The other claims of the group are held.
- **Release.** `POST /api/payer/risk/claims/{id}/release` with `{"reason"}` (3 to 500 characters) lifts the hold on
  one claim. The reason, the time and the links the claim had at that moment are kept in `claim["risk"]` and in
  the history. A released claim stays in its group, shown as released.
- **Held again only on a new signal.** A link is a signal together with the other claim it leads to. A released
  claim is held again only when it has a link that was not there at the release: a new claim on the same account,
  or a new kind of signal with a claim it was already linked to.
- **When the link goes away** (for example the claimant gives a different account), the hold ends and a dated line
  says so.

Inside the holder's standing instructions (`instructions.py`) this is a fixed safety rule, like the "safety" rule
of the payment machine: the holder cannot switch it off, and the agent never releases a claim. The card says so:
"A fixed rule, not yours to switch off: linked claims are held before any money moves. Only a person releases
one, with a reason."

The risk state is brought up to date whenever the risk view is read and inside both checks. The analysis is made
again only when a claim file has changed in a part the analysis reads.

## Routes

Both need the holder's key in `X-Payer-Key`.

- `GET /api/payer/risk`: the counts, the queue with each claim's risk state, the groups with their nodes, edges,
  shared elements, points table and decision card, the rule, and the measured figures when a measurement file is
  beside the claims.
- `POST /api/payer/risk/claims/{id}/release`: the release.

Everything shown about a shared element is masked: account numbers to the last four digits, emails to the first
letter and the domain, phones to the last two digits, addresses to their first six characters, claimant names to
a first name and initials. No network address exists to show.

## The measurement

`scripts/make_ring_claims.py` writes 73 demonstration claims: 60 honest ones and 13 in three planted rings. Every
person is invented and every generated image carries the word SAMPLE. It writes `ground_truth.json` beside the
claims. Only the measurement reads that file; the detector is given the claims folder and nothing else.

The honest set holds these look-alikes: three people with two properties and one account each, two married
couples at one address (one couple sends the same bill), two pairs of unrelated people with the same name in
different countries, five claims for one large holder inside the same hour from different networks, a family on
one home network, a helper's device used by three unrelated people, two siblings whose names are one letter apart,
and a daughter who opens claims for three relatives with her own email address on her own laptop.

The rings: a mule account (five claimants, one account; the first was paid before the second existed, the second
already had an approval), a forged identity (one card picture under four names: three edited copies of the file
and one that was printed and photographed again), and a burst of name variants (four claims in a few minutes, one
mailbox written four ways, one device).

Results, as counts. Seed 7 is the set the screen shows.

| Seed | Ring claims held before payment | Paid before the ring showed | Missed | Honest claims wrongly held | Honest claims linked, not held |
| --- | --- | --- | --- | --- | --- |
| 7 | 11 of 13 | 1 | 1 | 2 of 60 | 2 |
| 11 | 11 of 13 | 1 | 1 | 2 of 60 | 2 |
| 23 | 11 of 13 | 1 | 1 | 3 of 60 | 2 |
| 42 | 11 of 13 | 1 | 1 | 3 of 60 | 2 |
| Twelve more seeds (100 to 111), together | 132 of 156 | 12 | 12 | 27 of 720 | 24 |

Per ring, seed 7:

| Ring | Held | Points | Signals that caught it | Held from its claim number |
| --- | --- | --- | --- | --- |
| Mule account | 4 of 5 (1 paid before) | 105 | bank account, name variants, size | 2 |
| Forged identity | 3 of 4 (1 missed) | 75 | near-identical picture, readings disagree, size | 3 |
| Name variant burst | 4 of 4 | 110 | email, name variants, device, account name, burst, size | 2 |

What the numbers say, plainly:

- **The paid claim is not caught.** The first claim of the mule ring was paid before a second claim existed. No
  detector that works across claims can stop the first claim of a ring. It is recorded, with the amount.
- **The re-photographed card is missed, in every seed.** A forged card that is printed and photographed again
  differs in almost every tile. That claim shares nothing else with its ring, so it stays clear.
- **The forged ring is held from its third claim.** Two near-identical pictures are 50 points. The first two
  forged claims are linked and shown, and are held only when the third arrives.
- **The honest claims that are held are the daughter's.** One email address and one device behind three different
  claimants is exactly what a small ring looks like (30 + 20 + 10). The holder sees the group and releases the
  claims with a reason. In seeds where one of her three had already been paid, two are held and one is recorded.
- **The seeds change names, pictures, amounts and timing, not the structure.** The same three rings and the same
  look-alikes are in every set, so the counts barely move. They show that the result does not hang on one draw of
  names and pictures. They do not show how the detector does on kinds of rings that were not planted.

## Weaknesses

- A ring whose members share nothing the detector reads (different accounts, different pictures, different
  contacts, different devices, slow timing) is not seen.
- A forger who replaces the portrait as well as the name, or photographs the forged card again, defeats the
  picture comparison. Pictures other than photo identification are compared as exact files only.
- Two honest flat scans of different people's cards from one template came as close as 9 tiles in the trial, one
  tile from the line. A pair inside the line would be linked at 50 points and shown, not held, unless a third
  claim or another signal joined it.
- Honest siblings whose names are one letter apart and who also share an email address and a network would be
  held (30 + 25 + 10). So would a person with four or more properties under one name and account.
- A ring can dodge the weak signals by typing one address and one family name, which makes its members a
  household. A shared account, a shared identity document and a pattern in the readings still count.
- The account is compared by bank country and account number only. Two banks in one country that issue the same
  number would look like one account.
- A fingerprint is kept only for claims opened through the API, and none behind a proxy. The salt file must be
  kept with the claims.
- The whole queue is compared pair by pair for names and pictures. That is fine for thousands of claims and would
  need an index beyond that.
- The risk state of a claim is brought up to date when the risk view is read or a check runs, not at the moment
  another claim changes. The checks always run before an approval is recorded or a payment is planned, so no
  money moves on a stale state.
- The points were chosen by reasoning about what each signal means. They were not fitted to labelled fraud cases,
  because there are none.

## How to run it

```
# the demonstration claims and the measurement (seed 7, then seeds 11, 23 and 42 in temporary folders)
.venv/bin/python scripts/make_ring_claims.py

# the server on those claims; open http://localhost:8031/risk and type the key "demo"
KHUTLISA_CLAIMS=data/ring_demo/claims KHUTLISA_PAYER_KEY=demo KHUTLISA_READ_DOCUMENTS=0 \
KHUTLISA_DB=data/ring_demo/no-register.duckdb \
  .venv/bin/python -m uvicorn khutlisa.server:app --port 8031

# the walk in a browser on its own (it is also part 6 of scripts/walkthrough.mjs, in docs/shots/walk/)
node scripts/walkthrough_rings.mjs

# the tests
.venv/bin/python -m pytest -q tests/test_rings.py tests/test_rings_api.py
```

The server needs the built front end (`cd web && npm run build`). It does not need the register database: with
`KHUTLISA_DB` pointing at a file that does not exist it starts and says the register is not loaded. With
`KHUTLISA_READ_DOCUMENTS=0` an approval is not held back by the proof file, so the screenshot of a refused
approval shows the hold and nothing else. With document reading on, the risk view works the same.

## README section

### Rings: organised false claims, caught across the whole queue

Payers freeze whole countries after a handful of forged claims, because one forged claim looks sound on its own.
Khutlisa compares every claim with every other claim, in code, with no language model.

- **Signals.** One bank account receiving for different claimants (60 points). One document file in different
  claims (60). A near-identical picture of an identity card under different names (50). One email or phone behind
  different claimants (30 each). Claimant names a letter or two apart (25). One device (20), accounts in one
  holder's name (15), the same field disagreeing between readings in three claims (15), one network (10), one
  typed address (10), a burst of claims for one holder (10).
- **Groups and points.** Claims joined by a linking signal form a group. The group's rating is the plain sum of
  its named points, each counted once. A group at 60 points or more is held. A shared network, a device, a burst
  or an address can never link claims or hold one alone.
- **Not flagged.** One person with up to three properties and one account. A family at one address. Two people
  with the same common name.
- **What the agent does.** A held claim cannot be approved or paid. An approval given before the ring showed is
  suspended. Money that had already left is recorded and not called back. Only a person releases a claim, with a
  reason, and it is held again only on a new signal. This is a fixed rule the holder cannot switch off.
- **Measured.** On 73 invented claims with three planted rings (seed 7): 11 of 13 ring claims held before
  payment, 1 paid before its ring existed, 1 missed (a forged card that was printed and photographed again). 2 of
  60 honest claims wrongly held: a daughter who opened three relatives' claims with her own email address on her
  own laptop. Three other seeds gave 11 of 13 each and 2 or 3 of 60. Twelve more gave 132 of 156 and 27 of 720.
- **Limits.** A ring that shares nothing the detector reads is not seen. The picture comparison follows an edited
  copy of a file, not a new photograph of a forged card. The points were reasoned, not fitted to real fraud cases.

The holder sees each group at `/risk` as a picture with the shared things in the middle, a points table and a
four-line decision card. The rules, the stored fingerprint and every number are in `docs/RINGS.md`.
