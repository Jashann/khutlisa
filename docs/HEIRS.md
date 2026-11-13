# When the owner has died: who inherits, and what Khutlisa does with it

Reference for `src/khutlisa/succession.py` (the rules), `src/khutlisa/estates.py` (the family, the heirs and their
proof) and `src/khutlisa/estate_settlement.py` (the one settlement that pays every heir).

Every section of statute below was read on the California Legislature's own site,
leginfo.legislature.ca.gov, on 13 Nov 2026, in a browser, and the words quoted are the Legislature's. The address
of a section is
`https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PROB&sectionNum=6401.` with the
number changed (and `lawCode=CIV` for the Civil Code). What the State Controller asks of heirs who claim from the
State is in `docs/CALIFORNIA_CLAIMS.md`, section 3, and is not repeated here.

The marks mean what they mean there:

- **[verified]**: read at the source named, with its own words quoted.
- **[unverified]**: not settled by what was read.
- **[our reading]**: a choice Khutlisa makes that goes beyond the words.

Nothing here is legal advice, and no lawyer has read it. The holder decides.

## 1. The rules that are computed

| Section | What it says | Mark |
| --- | --- | --- |
| Probate Code 6400 | "Any part of the estate of a decedent not effectively disposed of by will passes to the decedent's heirs as prescribed in this part." | [verified] |
| 100(a) | "Upon the death of a person who is married or in a registered domestic partnership, one-half of the community property belongs to the surviving spouse and the other one-half belongs to the decedent." | [verified] |
| 101(a) | The same for quasi-community property, where the person "is domiciled in this state". | [verified] |
| 6401(a), (b) | "As to community property, the intestate share of the surviving spouse is the one-half of the community property that belongs to the decedent under Section 100." The same for quasi-community property under section 101. | [verified] |
| 6401(c)(1) | Separate property: the spouse takes "The entire intestate estate if the decedent did not leave any surviving issue, parent, brother, sister, or issue of a deceased brother or sister." | [verified] |
| 6401(c)(2) | "One-half of the intestate estate in the following cases: (A) Where the decedent leaves only one child or the issue of one deceased child. (B) Where the decedent leaves no issue, but leaves a parent or parents or their issue or the issue of either of them." | [verified] |
| 6401(c)(3) | "One-third of the intestate estate in the following cases: (A) Where the decedent leaves more than one child. (B) Where the decedent leaves one child and the issue of one or more deceased children. (C) Where the decedent leaves issue of two or more deceased children." | [verified] |
| 6402(a) | The part not passing to the spouse, or all of it if there is none, passes "To the issue of the decedent, the issue taking equally if they are all of the same degree of kinship to the decedent, but if of unequal degree those of more remote degree take in the manner provided in Section 240." | [verified] |
| 6402(b) | "If there is no surviving issue, to the decedent's parent or parents equally." | [verified] |
| 6402(c) | "If there is no surviving issue or parent, to the issue of the parents or either of them", equally if of the same degree, otherwise in the manner of section 240. | [verified] |
| 240 | The property "shall be divided into as many equal shares as there are living members of the nearest generation of issue then living and deceased members of that generation who leave issue then living, each living member of the nearest generation of issue then living receiving one share and the share of each deceased member of that generation who leaves issue then living being divided in the same manner among his or her then living issue." | [verified] |
| 6403(a) | "A person who fails to survive the decedent by 120 hours is deemed to have predeceased the decedent for the purpose of intestate succession". It must be shown "by clear and convincing evidence". | [verified] |
| 6406 | "relatives of the halfblood inherit the same share they would inherit if they were of the whole blood." | [verified] |
| 6414(a) | "this part does not apply where the decedent died before January 1, 1985". | [verified] |
| 37, 72 | "'Spouse' includes domestic partner, as defined in Section 37", which means a partnership registered with the Secretary of State. | [verified] |
| 78 | "'Surviving spouse' does not include" a person whose marriage to the owner "has been dissolved or annulled". | [verified] |
| 6450 | A parent and child relationship exists between a person and their natural parents "regardless of the marital status of the natural parents", and between an adopted person and the adopting parents. | [verified] |
| 6411 | "No person is disqualified to take as an heir because that person ... is or has been a person who is not a citizen or national of the United States." This matters here: heirs abroad inherit like anyone else. | [verified] |

### How the engine applies them

1. If a will or a court order disposes of the property, the shares are the ones it names (6400). Khutlisa does not
   interpret a will. The family states the shares, the document is read like any other, and the holder reads it
   too. Shares that do not add up to the whole are refused. **[our reading]** that a decree of distribution
   settles the shares; it is what the Controller itself accepts (`docs/CALIFORNIA_CLAIMS.md`, section 3).
2. A surviving spouse or registered partner is counted only if married to the owner at death (78) and alive 120
   hours later (6403).
3. Community or quasi-community property goes wholly to the surviving spouse: one half is already theirs (100,
   101) and the owner's half passes to them (6401(a), (b)). The engine shows both steps.
4. Separate property: the spouse's fraction is all, one half or one third under 6401(c), by counting the owner's
   living children and the children who died leaving living issue.
5. The rest goes to the first of these that exists: issue (6402(a)), parents (6402(b)), the issue of parents
   (6402(c)).
6. Issue of unequal degree divide under section 240: equal shares at the nearest generation that has a living
   member. If every child has died, the grandchildren are that generation and take equally, whichever child they
   descend from.
7. "Alive" always means alive 120 hours after the owner (6403). The intake asks it in those words.

Whether a property in the register is community or separate cannot be read from the register. The engine asks,
and only when the answer changes a share. **[our reading]**

## 2. What the engine refuses, with the section in the way

Each of these was read; none is computed. The engine stops and names the section.

| Section | Why it is refused | Mark |
| --- | --- | --- |
| 6402(d) to (g) | Grandparents and their issue, the issue of a predeceased spouse, next of kin, the parents of a predeceased spouse. The family structure Khutlisa asks about stops at brothers, sisters and their children. | [verified], not computed |
| 6402.5 | Where there is no surviving spouse or issue and a spouse died within 5 years (15 for land), "the portion of the decedent's estate attributable to the decedent's predeceased spouse" goes to that spouse's family; for personal property this applies where the value "in the aggregate is ten thousand dollars ($10,000) or more". | [verified], not computed |
| 6404 | "Part 4 (commencing with Section 6800) (escheat) applies if there is no taker". | [verified], not computed |
| 6409 | A lifetime gift counts as an advance only on a writing by the owner or the heir. | [verified], not computed |
| 6410 | "A debt owed to the decedent is not charged against the intestate share of any person except the debtor." | [verified], not computed |
| 6413 | A person related through two lines takes "only a single share". | [verified], not computed |
| 6451 | An adoption severs the tie with a natural parent unless two conditions are met. | [verified], not computed |
| 6454 | A stepchild or foster child counts only where the relationship began in childhood and an adoption was prevented "but for a legal barrier". | [verified], not computed |
| 6452, 250 | A parent or a killer barred from inheriting. Only the opening words were read. | [unverified], not computed |
| 6407 | Relatives "conceived before the decedent's death but born thereafter inherit as if they had been born in the lifetime of the decedent." The intake does not ask about this. | [verified], not asked |
| 6414 | A death before 1 January 1985. | [verified], refused |

## 3. An owner who did not live in California

- Civil Code 946: "If there is no law to the contrary, in the place where personal property is situated, it is
  deemed to follow the person of its owner, and is governed by the law of his domicile." **[verified]**
- Probate Code 13006(b): a successor without a will is whoever succeeded "under Sections 6401 and 6402 or, if the
  law of a sister state or foreign nation governs succession to the particular item of property, under the law of
  the sister state or foreign nation." **[verified]**
- So where the owner lived elsewhere at death, another state's or another country's law may decide who inherits.
  Which law does apply depends on facts and on rules that were not researched (where the owner was domiciled in
  law, what kind of property it is, treaties, the forced shares many countries give to children or a spouse).
  **[unverified]**

What Khutlisa does: it computes California's default shares, shows them, and marks the estate "other law may
apply". It does not decide the question and does not pretend to. The holder can approve such an estate only by
writing down why the California shares are being used, and that reason is kept with the approval. **[our
reading]**

## 4. Paying heirs without probate: the declaration

- Section 13100: where the owner's property in California does not exceed the limit "and if 40 days have elapsed
  since the death of the decedent, the successor of the decedent may, without procuring letters of administration
  or awaiting probate of the will", collect "money due the decedent". The section prints $166,250 "as adjusted
  periodically in accordance with Section 890". **[verified]**
- Section 13101(a): "an affidavit or a declaration under penalty of perjury under the laws of this state shall be
  furnished to the holder of the decedent's property" stating, among other things, the owner's name, the date and
  place of death, that "At least 40 days have elapsed since the death of the decedent, as shown in a certified
  copy of the decedent's death certificate attached", that no probate is under way, the name of the successor, and
  that "No other person has a superior right". Under (b), "Where more than one person executes the affidavit or
  declaration under this section, the statements required by subdivision (a) shall be modified as appropriate".
  Under (d), a certified copy of the death certificate is attached. **[verified]**
- The limit: 13101(g) gives $166,250 for a death before 1 April 2022 and, after that, "the adjusted dollar amount,
  published in accordance with subdivision (c) of Section 890". Section 890 adjusts it every three years. The
  Controller's form prints $184,500 from 1 April 2022 and $208,500 from 1 April 2025
  (`docs/CALIFORNIA_CLAIMS.md`); the Judicial Council's published list was not read. **[the mechanism verified,
  the two later figures unverified]**
- The holder is the party the statute names: the declaration goes "to the holder of the decedent's property".
  That fits Khutlisa's user. **[verified]**

What Khutlisa does with it: the proof file checks in code that the death certificate has been read and that 40
days have passed since the date of death on it, and it records each heir's statement that the declaration's
points are true. It does not check the size of the whole estate, which only the family knows, and a recorded
statement in this build is not a signed declaration under penalty of perjury. **[our reading]**, and marked on
the screen as simulated.

## 5. What ties each heir to the owner

The Controller's own list for heirs without a will is "marriage, death and certified birth certificates that show
the relationship" (`docs/CALIFORNIA_CLAIMS.md`, section 3, verified there). Khutlisa asks for the same chain, link
by link, and compares the names in code:

| Heir | Documents that make the chain |
| --- | --- |
| Spouse | A marriage certificate that names the heir and the owner |
| Child | The heir's birth certificate, naming the owner as a parent |
| Grandchild | The heir's birth certificate naming their parent, that parent's birth certificate naming the owner, and that parent's death certificate |
| Parent | The owner's birth certificate, naming the heir as a parent |
| Brother or sister | The heir's birth certificate and the owner's, sharing a parent |
| Niece or nephew | The heir's birth certificate naming their parent, that parent's and the owner's birth certificates sharing a parent, and that parent's death certificate |
| Named in a will or court order | The will or the order, naming the heir |

Every heir also needs government photo identification in their own name, and the estate needs the owner's death
certificate, whose name must match the owner on the record. Each document is read twice and put through the same
checks as any other (`docs/HOW_IT_WORKS.md`, step 4). What is not done: nobody verifies a certificate with the
registry that issued it, and a certificate in another language is read by the model without a certified
translation, which the Controller would ask for.

## 6. The settlement: shares, fees and cents

All of this is code (`src/khutlisa/estate_settlement.py`), and the tests check each rule.

- **Entitlements.** The property's amount is divided by the exact fractions. Each heir first gets their share
  rounded down to the cent. The cents left over are handed out one each, to the heirs whose shares lost the
  largest part of a cent in the rounding; a tie goes to the heir who comes first in the family (spouse, then
  children in order, and so on). The entitlements therefore always add up to the property's amount, to the cent.
- **Fees, under the holder's fee rule.** The holder's small-claim line is applied to each heir's entitlement,
  because Airwallex charges its payout fee once per transfer. An heir whose entitlement is below the line has
  Airwallex's fees borne by the holder: the holder adds that heir's expected payout fee and that heir's part of
  the incoming fee. For an heir at or above the line, the heir's part of the incoming fee (in proportion to the
  entitlement) and the payout fee of their own transfer come out of their share. Nobody pays for another heir's
  transfer. **[our reading]** of a rule the holder set for single claims.
- **What is sent.** The holder makes one deposit for the heirs being paid. When Airwallex has booked it and its
  fee, what is left is divided among those heirs in proportion to the planned amounts, with the same
  largest-remainder rounding, so the amounts sent add up to exactly what Airwallex holds for the estate.
- **Each heir is paid on their own.** Each has their own conversion, beneficiary and transfer, each with its own
  request ids, saved before any call. A transfer the bank refuses stops that heir only: the others are paid, the
  refused amount is held in that heir's currency, and a replacement goes out only after the heir corrects the
  account, the holder approves it, and Airwallex reports the first transfer as dead.
- **An heir who is not proven yet** is left out of the deposit. The proven heirs are paid their shares, the
  unproven share stays with the holder, and the screens say so. When the proof is ready the holder approves
  again and a second round pays that heir alone. An heir who has been paid is never paid again.
- **Reconciliation.** After every step Airwallex's own ledger rows are read again: the deposit, its fee, and
  every heir's conversion and transfer. The settlement balances when the rows add up to zero in every currency.

## Still open

1. Which law governs when the owner lived outside California. Flagged for a person in every such case.
2. The 13101 limit for deaths on or after 1 April 2022 and 1 April 2025, against the Judicial Council's list.
3. Sections 250 and 6452 in full.
4. Whether a holder may rely on a declaration signed outside the United States, and how it is notarised there.
5. Whether a holder may apply its small-claim fee rule heir by heir. It is the holder's own rule, so the holder
   can say.
