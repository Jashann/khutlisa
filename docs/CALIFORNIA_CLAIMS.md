# What California requires to claim unclaimed property

Reference for `src/khutlisa/california.py`, the claim checklist and the claim packet. Everything below was read on
the California State Controller's own pages (sco.ca.gov and claimit.ca.gov) on 11 Nov 2026. No form was submitted
and no name was entered into any search.

Each fact is marked:

- **[verified]**: read on the page named, with the Controller's own words quoted.
- **[unverified]**: the Controller's pages do not settle it, or only an old page mentions it. The packet tells the
  claimant to ask the Controller.
- **[our reading]**: a choice Khutlisa makes that goes beyond the Controller's words.

## Sources

| Short name | Page |
| --- | --- |
| OWNER | https://www.sco.ca.gov/Files-UPD/02eClaimFilingOwnerInstructions.pdf (rev. 4/6/2022) |
| HEIR | https://www.sco.ca.gov/Files-UPD/02fClaimFilingHeirInstructions.pdf (rev. 5/5/2022) |
| BIZ | https://sco.ca.gov/Files-UPD/02gClaimFilingBusinessInstructions.pdf (rev. 1/11/2018) |
| FORM | https://www.sco.ca.gov/Files-UPD/02dClaimFilingClaimForm.pdf |
| REG | https://sco.ca.gov/Files-UPD/02cClaimFilingAmendedRegLanguageJune5.pdf (2 CCR 1180.59 to 1180.65) |
| FAQ | https://claimit.ca.gov/app/faq-claim |
| INVFAQ | https://claimit.ca.gov/app/faq-investigators |
| HB | https://www.sco.ca.gov/files-upd/guide_investigator_handbook.pdf (January 2023) |
| LAW | https://www.sco.ca.gov/files-upd/guide_upd_updlaw.pdf (February 2026) |
| GUIDE | https://sco.ca.gov/Files-UPD/guide_upd_claiming.pdf (January 2022) |
| 13101 | https://claimit.ca.gov/docs/CA_Declaration_Under_Probate_Code.pdf (rev. 9/2022) |
| PAY | https://www.sco.ca.gov/upd_faq_payment.html |
| FORMS | https://www.sco.ca.gov/upd_form_claim.html |
| HOWTO | https://claimit.ca.gov/app/claim/how-to-submit and https://claimit.ca.gov/app/claim/how-to-complete |
| WARRANT | https://www.sco.ca.gov/warrant_inquiries.html |

## 1. Owner claims

The list in OWNER is introduced as "please provide the following if able or other similar documents".

| Item | What the Controller says | Mark |
| --- | --- | --- |
| Claim form | "Completed Claim Affirmation Form signed by the property owner. In general, a Power of Attorney instead of the reported owner's signature will not be accepted." (OWNER) | [verified] |
| Photo identification | "Copy of your current Driver License or State-Issued Photo Identification Card." A military identity card or a "Color copy of the first and last page of your valid passport" is also listed. (OWNER) | [verified] |
| Social Security number | A Social Security card, a pay stub or W-2 showing the full number, a medical card, or an ITIN authorization letter. (OWNER) | [verified] |
| No Social Security number | "If you are a foreign citizen and do not have a SSN or ITIN, provide all of the following: Completed and signed ... IRS Form W-8 BEN ... and Color copy of the first and last page of your valid passport." (OWNER) | [verified] |
| Current mailing address | An original pay stub; a W-2, 1098 or 1099; a mortgage statement or property tax bill; an "Original telephone, cable, or utility bill"; an "Original bank or credit card statement". (OWNER) | [verified] |
| Reported address | "Proof that you received mail at the reported address." The same kinds of document, or an "Original bill or account statement from the reporting company". "If you cannot provide this documentation with your claim, we may contact you for additional information." (OWNER) | [verified] |
| No reported address | Proof the property is yours, such as an original bank statement, a "Stock certificate or original account statement", an invoice or receipt. (OWNER) | [verified] |
| Cashier's cheques and money orders | "You will be asked to send the original cashier's check, money order, or check." (FAQ) | [verified] |
| Securities | "Original stock certificate; Original dividend check; Original bond; Original debenture; or Account statement"; a lost instrument bond may be required. (GUIDE) | [verified] |
| Name change | A marriage certificate or court document. (OWNER) | [verified] |

In the checklist the reported address item is shown but does not block the packet, because the Controller says it
may follow up when it is missing. **[our reading]** A lease counts towards it as a "similar document"; the
Controller's list names bills, statements and pay stubs, not leases. **[our reading]**

## 2. Notarisation

- "You must notarize the Claim Affirmation Form if: 1) The total value of the claim is $1,000 or greater; 2) The
  claim is for safe deposit box contents; or 3) The claim is for securities". The same words are in OWNER, HEIR and
  BIZ. **[verified]**
- The regulation: "A claim form must be notarized if: the total value of the claim is $1,000.00 or greater; the
  claim is for the contents of a safety deposit box; or the claim is for securities." (REG, section 1180.60)
  **[verified]**
- INVFAQ gives a different figure: "If the total value of the cash properties is $10,000 or more, the claimant's
  signature must be notarized." HB (2023) says $1,000. Khutlisa uses $1,000, the figure in the regulation.
  **[verified that the two pages disagree]**
- "A claim initiated on the Controller's website and signed electronically shall constitute a claim." (REG). FORMS:
  "If your claim is eligible, you will be given the option to file electronically". **[verified]**
- The dollar limit for electronic claims, and whether an electronic claim skips the notary. Press releases from 2015
  and 2018 give US$5,000 (https://www.sco.ca.gov/eo_pressrel_16749.html,
  https://www.sco.ca.gov/eo_pressrel_19704.html). No current page states the limit. **[unverified]**
- Which register property types count as "securities". The code treats share and fund types as securities and
  dividend or other cash types as cash. **[our reading]**

## 3. Heir claims

- The heir sends the claim form, their own photo identification, Social Security number proof and current address
  proof, as in section 1. The notary rule is the same. (HEIR) **[verified]**
- "Each claimant must sign a Claim Affirmation Form." (HEIR) **[verified]**
- "All pages of the deceased owner's certified final death certificate." Proof of the owner's Social Security
  number and reported address is needed only if the death certificate does not show them. (HEIR) **[verified]**
- Trust: "A complete and signed copy of the deceased owner's trust, including all codicils and amendments". (HEIR)
  **[verified]**
- Personal representative: "Endorsed and/or Filed copy of your Letters Testamentary or Administration signed by a
  judicial officer". (HEIR) **[verified]**
- Beneficiary of a probated estate: "An endorsed/filed copy of a court ordered Final Decree of Distribution". "We
  will not accept a petition or an unsigned order". (HEIR) **[verified]**
- Will without probate: a complete copy of the signed will plus the Declaration under Probate Code section 13101.
  No will: the declaration, a Table of Heirship, and marriage, death and certified birth certificates that show the
  relationship. (HEIR) **[verified]**
- The declaration: "At least 40 days have elapsed since the death of the Decedent, as shown in a certified copy of
  the Decedent's death certificate attached". Estate limit printed on the form: "If the Decedent died prior to
  April 1, 2022 $166,250 / on or after April 1, 2022 $184,500 / on or after April 1, 2025 $208,500". (13101)
  **[verified as printed on the form]**
- HEIR's own footnote still shows older limits ($150,000 and $166,250). The limit for deaths on or after 1 April
  2025 was not checked against the statute. **[unverified]**
- The Table of Heirship "must be completed in full and notarized" according to GUIDE (2022). The current form could
  not be read. **[unverified]**

## 4. Claimants living outside the United States

- A passport is accepted: a colour copy of the first and last page. Without one, "a minimum of two forms of
  government-issued identification", for example a certified birth certificate "and, if it is in a language other
  than English, a certified English translation", or a consular identity card. "We may contact you for
  authentication of foreign documents." (OWNER, HEIR) **[verified]**
- A death outside the United States: "you must submit both a copy of the certified final death certificate and a
  certified English translation." (HEIR) **[verified]**
- Translations, in the handbook written for investigators: "The translation must be authenticated. If the document
  is translated at an embassy, the seal of the embassy must be affixed". (HB) **[verified]**
- The claim form has "STATE/PROVINCE" and "COUNTRY" fields and gives (916) 323-2827 for callers outside the United
  States. (FORM) **[verified]**
- Foreign notaries, notarisation at a United States embassy or consulate, and apostilles. The Controller's pages say
  nothing about them. The form's notary section is a United States style jurat ("State of ___, County of ___"). The
  packet names the two common routes, says neither is confirmed, and tells the claimant to phone the Controller
  first. **[unverified]**

## 5. How payment is issued

- "You will receive a warrant (a check from the state) in the mail ... There is no option for direct deposit" (PAY).
  "Warrants (state checks) are mailed to the address provided on the claim form." (FAQ) **[verified]**
- "Payments can be sent to a foreign country; additional documentation may be required." (HB) Which documents is
  not stated. **[verified, detail unverified]**
- "State Controller's warrants are valid for one year after the original issue date" (WARRANT, a general page, not
  an unclaimed property page). **[verified on the general page]**
- Securities: "The State returns securities to an owner or their heir by transferring the securities to the owner
  or by providing the net proceeds from the sale" (FAQ). **[verified]**
- "Interest shall not be payable on any claim paid under this chapter." (Code of Civil Procedure 1540(c), LAW)
  **[verified]**
- The Controller "does not withhold taxes", and debts to California state, city or county agencies may be
  intercepted from the payment. (FAQ) **[verified]**

What this means for Khutlisa: California pays by a paper cheque in US dollars sent by post, with no bank transfer.
The payout screen shows the step after that as it would work if the payer could pay into a US dollar account in the
claimant's name. Today that step runs only in the Airwallex sandbox, and a real claimant would still have to bank
California's cheque.

## 6. Timing and where to send a claim

- "Unclaimed property law allows up to 180 days from the date that we receive a complete claim package" (FAQ; Code
  of Civil Procedure 1540(b)). **[verified]**
- "Property owner claims that involve cash only may be processed in as little as 30 to 60 days. More complex claims,
  such as those filed by heirs, involving multiple owners, or involving businesses are generally processed within
  180 days." (FAQ) **[verified]**
- Securities can take "an additional 120 days to one year". (PAY) **[verified]**
- Post: State Controller's Office, Unclaimed Property Division, P.O. Box 942850, Sacramento, CA 94250-5873.
  **[verified]** HOWTO prints the ZIP code as 94250-9873, which looks like a typing error on that page.
- Courier or by hand: 10600 White Rock Road, Suite 141, Rancho Cordova, CA 95670. **[verified]**

## 7. Starting a claim, and third parties

- A claim starts on the website: search, choose Claim, enter the claimant's details, sign electronically. "Click
  SUBMIT to officially create a claim and generate a claim number." (HOWTO) **[verified]**
- "Can I print a blank claim form? No. ... claims are processed securely through our website. If you cannot find
  property ... you may call the Contact Center at (800) 992-4647." (FAQ) **[verified]**
- So Khutlisa's packet cannot contain the official form. It holds the property details, the claimant's details, the
  document checklist and the signing guide, and it tells the claimant to create the claim on the website themselves.
- A search by phone or in writing, with the form then posted to the claimant, appears only in GUIDE (2022).
  **[unverified]**
- Paid helpers: "It is against the law for investigators to charge a fee greater than 10% of the value of the
  property that is returned to you. (California Code of Civil Procedure Section 1582)" (FAQ). The agreement must be
  in writing, disclose "the nature and value of the property, that the Controller is in possession of the property,
  and the address where the owner can directly claim the property", be signed by the owner, and cannot require a fee
  before the claim is paid. (LAW) **[verified]**
- Khutlisa charges the claimant nothing. Whether a service that prepares claims without charging the owner is an
  "investigator" under section 1582 was not checked with the Controller or a lawyer. **[unverified]**

## 8. Organisations as owners

- The signer is "an individual with signatory authority for the business, such as an officer, general partner, or
  sole proprietor, or a corporate employee who has been delegated signatory authority by a corporate officer."
  (BIZ) **[verified]**
- Proof of authority: for a corporation a corporate resolution, the latest Statement of Information or a
  Certificate of Dissolution, and a letter of authorization for an employee; for an LLC the operating agreement or
  articles of organization; for a partnership the partnership agreement; for a sole proprietor a tax return with
  Schedule C, a business licence or a fictitious business name filing. (BIZ) **[verified]**
- Federal employer identification number: an IRS confirmation letter or a 1098 or 1099. "We will not accept tax
  returns or IRS Form SS-4 application or W-9 to verify FEIN." (BIZ) **[verified]**
- Proof of the current mailing address and of the reported address; the same notary rule. A parent corporation "is
  not the rightful owner of its subsidiary's unclaimed property." (BIZ) **[verified]**

## Still open

1. The current dollar limit for electronic claims and whether they need a notary.
2. Which notarisations from outside the United States the Controller accepts.
3. What "additional documentation" a payment to a foreign address needs.
4. The section 13101 estate limit for deaths on or after 1 April 2025, against the statute.
5. Whether the current Table of Heirship form must be notarised.
6. Whether Khutlisa counts as an investigator under Code of Civil Procedure 1582.

## Holders: what the law asks of them before the money goes to the State

A holder is the business that owes the money in the first place: a bank, an employer, an insurer, a broker, a
retailer. Everything below was read on 12 Nov 2026 on the State Controller's holder pages and guides, and in the
Controller's own printing of the Code of Civil Procedure (LAW, February 2026). Five sections (1520, 1530, 1532, 1560
and 1577) were also compared with the Legislature's site and agreed in substance. No report was filed and no form was submitted.
The marks mean the same as in the sections above.

| Short name | Page |
| --- | --- |
| RPT | https://www.sco.ca.gov/upd_rptg.html |
| HOW | https://www.sco.ca.gov/upd_how_to_report.html |
| ABOUT | https://www.sco.ca.gov/upd_about_holder_reporting.html |
| DD | https://www.sco.ca.gov/Files-UPD/upd_duediligence.pdf (rev. 12/2022) |
| LETTER | https://www.sco.ca.gov/Files-UPD/outreach_rptg_notice_duediligencesample.pdf |
| DORM | https://www.sco.ca.gov/Files-UPD/outreach_rptg_hol_dormancy.pdf (rev. 07/2023) |
| STEPS | https://www.sco.ca.gov/Files-UPD/outreach_rptg_hol_genrptinfo.pdf (rev. 10/2026) |
| REMIT | https://www.sco.ca.gov/Files-UPD/upd_remitting_property_factsheet.pdf (rev. 4/2026) |
| RCHECK | https://www.sco.ca.gov/Files-UPD/upd_holder_remit_report_checklist.pdf |
| OTHER | https://www.sco.ca.gov/Files-UPD/upd_other_report_types.pdf (rev. 12/2022) |
| REDUCE | https://www.sco.ca.gov/Files-UPD/upd_reduce_UCP_liability.pdf (rev. 12/2022) |
| REIMB | https://www.sco.ca.gov/Files-UPD/QuickGuide_HolderReimburseRequest_2017.pdf (rev. 12/2022) |
| HCR | https://claimit.ca.gov/docs/CA_HCR1.pdf (form HCR-1, rev. 12/2015) |
| SCONOTE | https://www.sco.ca.gov/Files-UPD/SCONoticetoOwners.pdf |
| HFAQ | https://claimit.ca.gov/app/faq-report |
| GFAQ | https://claimit.ca.gov/app/faq-general |
| LEG | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CCP&sectionNum=1532. (change the number for other sections) |
| CODES | https://www.sco.ca.gov/Files-UPD/upd_naupa_II_codes_dormancy_periods.pdf (linked from https://sco.ca.gov/upd_rptg2.html; read 13 Nov 2026) |
| RFAQ | https://www.sco.ca.gov/upd_reporting_portal_faq.html (read 13 Nov 2026) |
| NCHECK | https://www.sco.ca.gov/Files-UPD/upd_holder_notice_report_checklist.pdf (read 13 Nov 2026) |
| REDEF | https://sco.ca.gov/Files-UPD/outreach_rptg_notice_2005_0801nauparedef.pdf (a 2005 notice on securities codes; read 13 Nov 2026) |

### H1. The notice a holder must send before reporting

- Who gets it and the threshold: "if the holder has in its records an address for the apparent owner of property
  valued at fifty dollars ($50) or more, which the holder's records do not disclose to be inaccurate, the holder
  shall make reasonable efforts to notify the owner by mail or, if the owner has consented to electronic notice,
  electronically". (Code of Civil Procedure 1520(b), LAW and LEG) **[verified]**
- The Controller's summary: owners "with unclaimed property valued at $50 or more (and all securities and safe
  deposit boxes regardless of value)". (DD) Banks and financial organisations follow 1513.5, where accounts "of less
  than fifty dollars ($50)" need no notice; shares follow 1516(d) and safe deposit boxes 1514, neither with a
  dollar floor. (LAW) **[verified]**
- When: "not less than 6 nor more than 12 months before the time when the owner's property held by the business
  becomes reportable". (1520(b)) A bank may instead send it "Not less than two years nor more than two and one-half
  years after the date of last activity". (1513.5(a)) **[verified]**
- How: by post to the address on record, or by email only with consent. "Yes, if a customer has agreed to receive
  electronic correspondence from your company, then you can email a due diligence notice." (HFAQ, DD) **[verified]**
- What it must say: the heading "THE STATE OF CALIFORNIA REQUIRES US TO NOTIFY YOU THAT YOUR UNCLAIMED PROPERTY MAY
  BE TRANSFERRED TO THE STATE IF YOU DO NOT CONTACT US," or similar words; the date the property will go to the
  State and that a claim will then be needed; in bold or larger type, that there has been no activity, an account
  identifier of up to four digits, that the property is in danger of going to the State, and that the law requires
  the transfer after the inactive period; and a form for the owner to return. "In lieu of returning the form, the
  holder may provide a telephone number or other electronic means to enable the owner to contact the holder."
  (1520(b); the Controller's sample is LETTER) **[verified]**
- A bad address: holders "are not required to send due diligence letters to owners if the address of record is a
  known 'bad address' or mail has been returned undeliverable", and need not send a second letter. (DD) **[verified]**
- A missed window: the holder "is encouraged to send a due diligence letter to the owner as soon as possible, then
  proceed with the reporting process". (DD) **[verified]**
- Extra notices are allowed "at any time between the date of last activity by, or communication with, the owner and
  the date the holder transfers the property to the Controller." (1520(c)) **[verified]**
- The holder may charge the owner for the notice, at most the cost of sending it and "in no case to exceed two
  dollars ($2)". (1520(b)) **[verified]**

### H2. How long before property counts as unclaimed

From the Controller's table (DORM), with the statute where it was read in LAW. The table cites section 1513 with
older lettering than the current statute; the periods agree.

| Property | Years | Mark |
| --- | --- | --- |
| Wages or salaries | 1 ("more than one year after the wages or salaries become payable", 1513(a)(7)) | [verified] |
| Checking, savings, matured time deposits | 3 (1513(a)(1) and (2)) | [verified] |
| Cashier's cheques and other written instruments of a bank | 3 (1513(a)(4)) | [verified] |
| Other uncashed cheques, refunds, any other property | 3 (1520(a)) | [verified] |
| Dividends, stocks and bonds | 3 (1516) | [verified] |
| Life insurance funds | 3 after they "became due and payable" (1515(a)) | [verified] |
| Money orders | 7 (1513(a)(5)) | [verified] |
| Traveler's cheques | 15 (1513(a)(3)) | [verified] |
| Refunds ordered by a court or agency | 1 (1519.5) | [verified] |

HFAQ: "The dormancy period for payroll, wages, and commissions is one year. Most other property has a dormancy
period of three years". **[verified]**

### H3. The calendar: two reports, with the Controller's own letters between them

- The Notice Report "shall be filed before November 1 of each year as of June 30 or fiscal yearend next preceding";
  life insurers file "before May 1". (1530(d), LAW and LEG) "Do not remit property at this time." (HOW) **[verified]**
- Between the two reports the Controller writes to the owners: "Within 165 days after the final date for filing the
  report ... the Controller shall mail a notice to each person having an address listed in the report who appears
  to be entitled to property of the value of fifty dollars ($50) or more". Where the report has a Social Security
  number, the Controller first asks the Franchise Tax Board for a newer address. (1531(b), LAW) RPT gives the
  Controller's deadline as mid-April (mid-October for life insurance). **[verified]**
- That letter sends the owner back to the holder: "You must contact the business or entity listed below, before
  [date], to prevent the transfer of your property to the SCO." and "Your property currently resides with the
  business or entity listed above. The State Controller's Office does not have your property." (SCONOTE)
  **[verified]**
- The Remit Report and the payment: "no sooner than seven months and no later than seven months and 15 days after
  the final date for filing the report, pay or deliver to the Controller all escheated property specified in the
  report." (1532(a), LAW and LEG) In practice "between June 1-15, or December 1-15 for life insurance companies";
  the exact date is in the Remit Reminder Letter (14F). (HOW, RCHECK) **[verified]**
- Cash of $2,000 or more must go by electronic funds transfer. (1532(a), REMIT) **[verified]**
- A business that is closing may send a Remit Report "without completing due diligence notifications, and without
  submitting a Notice Report." (OTHER) **[verified]**

### H4. Paying the owner directly before the handover

- The statute: "If a person establishes their right to receive any property specified in the report to the
  satisfaction of the holder before that property has been delivered to the Controller ... the holder shall not pay
  or deliver the property to the Controller but shall instead file a report with the Controller". (1532(b), LAW and
  LEG) **[verified]**
- The Controller's guides say the same in plain words. "If an owner responds to a due diligence notice confirming
  interest in the property, the holder must reunite the owner with the property, for example by reissuing a dormant
  check or reactivating an inactive account." "Once contact is made the holder is expected to reunite property with
  the rightful property owner instead of remitting it to the state." "Properties that were reunited with owners
  should be removed from the Remit Report." (STEPS) **[verified]**
- "If contact efforts by either the business or the state are successful prior to the Remit Report due date, the
  business reunifies the property with the owner directly and does not send it to the state." Holders are told: "Do
  not refer them to the state until the property has been transferred." (REDUCE) **[verified]**
- If every property on the Notice Report was returned to its owner, a Remit Report is still due, as a Nil Report.
  (HFAQ, OTHER) **[verified]**
- Owner contact can stop the clock: with the returned form or another recorded contact the account "shall be deemed
  to remain currently active and shall recommence the escheat period." (1520(b)) DD adds "Depending on the property
  type". **[verified]**
- How the holder pays the owner. The pages give reissuing a cheque and reactivating an account as examples and say
  nothing for or against a bank transfer, in the United States or abroad. **[unverified]** Treating a transfer to
  the owner's own bank account as a way to "reunite" the property is **[our reading]**.

### H5. After the handover: the holder can still pay and be repaid

- "Any holder who has paid moneys to the Controller pursuant to this chapter may make payment to any person
  appearing to that holder to be entitled thereto, and upon filing proof of the payment and proof that the payee
  was entitled thereto, the Controller shall forthwith reimburse the holder for the payment without deduction of
  any fee or other charges." (1560(b), as worded on LEG; LAW prints an older wording with the same meaning)
  **[verified]**
- The request is form HCR-1, signed by an officer and "notarized if the property value is $1,000 or greater, or it
  is a security-related property", with "proof that payment was made or the owner's account was reinstated and that
  the payee was entitled to the property". Before paying, the holder should look the property up on the
  Controller's site and tell CAHCR@sco.ca.gov "to avoid a duplicate return." (REIMB, HCR) **[verified]**
- A holder that delivered property and had sent the owner notice "in substantial compliance with Sections 1513.5,
  1514, 1516, and 1520 ... is relieved of all liability to the extent of the value of the property so paid or
  delivered". (1560(a), LAW) **[verified]**
- How long the Controller takes to repay a holder is not stated on these pages. **[unverified]**

### H6. Interest and fines

- Late or missing reports and payments: "interest at the rate of 12 percent per annum on that property or value
  thereof from the date the property should have been reported, paid, or delivered", unless there was reasonable
  cause. A report filed on time but not in the required form caps that interest at $10,000. (1577(a) and (b), LAW
  and LEG) **[verified]**
- Wilful failure "to render any report or perform other duties": "a fine of one hundred dollars ($100) for each day
  ... but not more than ten thousand dollars ($10,000)". Wilful refusal to pay or deliver: "not less than five
  thousand dollars ($5,000) nor more than fifty thousand dollars ($50,000)". Nobody is treated as wilful until they
  have ignored a certified letter from the Controller. (1576, LAW) **[verified]**
- Paying $2,000 or more other than by electronic funds transfer: "a civil penalty of 2 percent of the amount".
  (1532(h), LAW) **[verified]**
- Property kept back under 1532(b) and later found to belong in the report "shall not be subject to the interest
  provision of Section 1577." (1532(c), LAW) **[verified]**
- Failing to send the owner notice has no fine of its own in the sections read. The stated consequence is in
  1560(a): the release from liability is given to a holder that made those efforts. Whether the notice counts among
  the "other duties" of 1576 is **[our reading]** and was not checked with the Controller or a lawyer.
- The Voluntary Compliance Program waives the 1577 interest for an enrolled holder that reviews ten years of
  records, notifies owners "no less than 30 days prior to submitting the report", and reports and remits on the
  program's dates. (1577.5, LAW; https://www.sco.ca.gov/upd_vcp.html) **[verified]**

### H7. Owners whose address is outside the United States

- Such property comes to California only from a California holder: intangible property is covered if "The last
  known address, as shown on the records of the holder, of the apparent owner is in a foreign nation and the holder
  is (1) domiciled in this state or (2) a government or governmental subdivision or agency of this state."
  (1510(d), LAW) **[verified]**
- The notice sections (1513.5, 1514, 1516, 1520) make no exception for a foreign address. The duty depends on the
  holder having an address its records do not show to be wrong, and the post is the default. **[verified that the
  text has no exception]**
- No holder page read gives separate guidance for owners abroad: nothing on international post, on email in place
  of post, or on paying an owner in another country. **[unverified]**
- The Controller's own letter under 1531(b) goes to "each person having an address listed in the report". Whether
  it is in fact posted to addresses abroad is not stated. **[unverified]**

### H8. How the State pays, and what it publishes about the programme

- Read again on 12 Nov 2026: "You will receive a warrant (a check from the state) in the mail from the State
  Controller's Office. There is no option for direct deposit for unclaimed property payments." (PAY) "Unclaimed
  property is returned to owners in the form of a check from the state." (GFAQ) **[verified]**
- Size: "safeguarding more than $15 billion in unclaimed property, representing over 84 million individual
  properties waiting to be returned to nearly 39 million Californians." (press release of 5 Feb 2026,
  https://www.sco.ca.gov/eo_pressrel_27367.html) Other pages of the Controller still show $14 billion
  (https://www.sco.ca.gov/outreach-resources.html) and $13 billion (a 2025 flier). **[verified that the pages
  differ]**
- Letters matched with tax records: about 130,000 letters in June 2026; the first mailing, in December 2025, sent
  "more than 100,000 letters" and "helped reunite property owners with more than $30.4 million". Those owners
  "receive a check in about two weeks." (press release of 4 June 2026,
  https://www.sco.ca.gov/eo_pressrel_27508.html) **[verified]**
- No count of holders, of reports filed each year, or of dollars returned by holders before the handover was found
  on the Controller's site. **[unverified]**

### H9. Property type codes, and the kinds of money on the "For holders" screen

California's file writes each property's type as a code and a short description ("MS01: WAGES, PAYROLL,
SALARIES"). `src/khutlisa/property_types.py` groups the codes into kinds of money, and `scripts/make_holders.py`
adds them up for owners abroad.

- The lettered codes are "the National Association of Unclaimed Property Administrators (NAUPA) standard codes
  used by California" (CODES; the reporting page calls it the list of "Required codes for completing owner detail
  information", and RFAQ says "Refer to the Property Codes with Dormancy Periods guide for standard NAUPA II
  reporting codes"). The families as the Controller heads them: AC Accounts, CK Checks, CS Educational Savings
  Accounts, CT Court Deposits, HS Health Savings Accounts, IN Insurance, IR IRAs, MI Mineral Interest/Proceeds, MS
  Miscellaneous, SC Share-Related, SD Tangible Property, TR Trust Properties, UT Utilities, ZZ All Others.
  **[verified]** The PDF's text layer drops some letter pairs ("Royal es"), so its wording was read with those
  restored.
- The codes the grouping leans on, as CODES lists them: MS01 Wages, Payroll, Salary and MS02 Commissions (both
  dormant after one year); MS04 Payment for Goods & Services, MS08 Accounts Payable and CK13 Vendor Checks; MS05
  Customer Overpayments, MS07 Un-refunded Overcharges, MS09 Credit Balance, Accounts Receivable, MS10 Discounts
  Due, MS11 Refunds Due, MS12 Unredeemed Gift Certificates and CK12 Credit Checks or Memos; CK01 Cashier's Checks,
  CK07 Money Orders, CK15 Other Outstanding Official Checks; SC01 Dividends, SC12 Underlying Shares or Other
  Outstanding Certificates, SC20 Credit Balances. **[verified]**
- How they are grouped is ours: bank accounts and deposits (AC, HS); shares, dividends and brokerage balances
  (SC); cashier's cheques, money orders and other bank cheques (CK01 to CK09, CK15, CK16); wages, payroll and
  commissions (MS01, MS02); vendor payments and accounts payable (MS04, MS08, CK13); refunds, overpayments and
  customer credit balances (MS05, MS07, MS09 to MS12, CK12, UT); insurance (IN, MS03); retirement accounts and
  pensions (IR, MS14, CK11); royalties and mineral proceeds (MI); escrow, trust and court funds (TR, CT); safe
  deposit boxes and other tangible property (SD); and everything else (the remaining MS and CK codes, CS, ZZ).
  **[our reading]**
- The file also carries older numeric codes, written like "81: Non Standard NAUPA Code for - Salaries/wages". No
  page of the Controller that was read describes them or uses the words "Non Standard NAUPA Code". REDEF, a 2005
  notice, maps some old numbers for securities only, and one of its pairs (76 with "Funds for Stocks & Bonds")
  does not agree with the file's "76: ... Other". So the numeric codes are grouped by the description the file
  itself prints beside each one, and every figure says how much of it rests on them. **[unverified]** In the
  file of 4 Nov 2026 that is 52,534 of the 234,883 properties for owners abroad and $47.8 million of the $275.4
  million.
- AC55 ("Formerly AC51-53 accounts") is in the file and not in CODES. It is counted with bank accounts and marked
  **[unverified]**.
- REDEF also gives California meanings for some share codes that differ from CODES (SC12 "Beneficial Interest",
  SC20 "Liquidating Funds Earnings (Credit Balances)"). Which meaning older rows in the file carry was not
  checked. **[unverified]**
- The kind of holder is told from its name only where the name says it (a bank, a credit union, an insurer, a
  payroll company, a university, a utility) or where a well-known platform was read by hand (`holders.KINDS`).
  3,121 of the 4,965 holders carry no such word and are left as "not classified from the name". Employers are
  counted by what they reported: the holders with at least one wages property for an owner abroad. **[our
  reading]**

### H10. What the rules already ask of a holder, in figures

Read on 13 Nov 2026 in LAW, DD, RFAQ and NCHECK. These are the lines behind "Who can pay, and why it would" on the
"For holders" screen. No holder's own costs are known to us and none is given anywhere.

- The holder writes its own notices: "No, California's unclaimed property law requires holders to write and send
  due diligence letters independently." (RFAQ) **[verified]**
- What a bank may charge for the notice is capped: "If the deposit, account, shares, or other interest has a
  value greater than two dollars ($2), the banking or financial organization may impose a service charge ... in an
  amount not to exceed the administrative cost of mailing or electronically sending the notice and form and in no
  case to exceed two dollars ($2)." (1513.5(a), LAW) The same cap is in 1516(d) for securities, and DD says
  "holders may deduct service charges for some property types provided the charge does not exceed the
  administrative cost of mailing the due diligence letter and does not exceed $2.00." **[verified]**
- A bank must also tell a customer at the start: "At the time a new account is opened ... the organization shall
  provide a written notice to the person opening the account informing the person that his or her property may
  be transferred to the appropriate state if no activity occurs". (1513.5(d), LAW) **[verified]**
- What the report must hold: the owner's name and last known address for "property of value of at least
  twenty-five dollars ($25)"; "items of value under twenty-five dollars ($25) each may be reported in aggregate";
  and "the date when the property became payable, demandable, or returnable, and the date of the last transaction
  with the owner". (1530(b), LAW) "There is no minimum value for reporting unclaimed property." (DD) **[verified]**
- How it is filed: "SCO does not accept email report submissions. Visit the online Holder Reporting Portal at
  hrp.sco.ca.gov to upload and submit your report documents." (RFAQ) "Reporting software is free for reports
  containing fewer than 100 properties." (NCHECK) **[verified]**
- Records: "Any person or holder shall retain all records pertaining to property for a period of seven (7) years
  after such property is reported, or would have been reported except for the deduction of charges, to the State
  Controller." (2 CCR 1175, LAW) **[verified]**
- The Controller may look: "The Controller may at reasonable times and upon reasonable notice examine the records
  of any person if the Controller has reason to believe that the person is a holder who has failed to report".
  (1571(a), LAW) **[verified]**
- The Legislature's own site could not be read on 13 Nov 2026 (it answered 403), so sections 1513.5, 1516, 1530,
  1571 and 2 CCR 1175 above are quoted from the Controller's February 2026 printing only.

### H11. The holder's own list: the notice and the periods, read again on 13 Nov 2026

Read on 13 Nov 2026 for the holder's own list (`src/khutlisa/dormancy.py`, `src/khutlisa/notices.py`). Three of the
Controller's files were fetched and read whole on that day: DD, LETTER and DORM. Sections 1513(a)(7) and 1520 were
read in LAW (the Controller's printing, February 2026). The Legislature's site (LEG) and the Controller's web pages
HOW, RPT and ABOUT answered automated requests with a browser check on that day and were **not** read again, so
the calendar in H3 stands as it was verified on 12 Nov 2026.

**The value threshold.**

- "property valued at fifty dollars ($50) or more". (1520(b), LAW) **[verified]**
- "Due diligence is not required if the property is under $50.00 in value; however, it is required for all safe
  deposit boxes and shares regardless of value. There is no minimum value for reporting unclaimed property." (DD)
  **[verified]**
- In code: a notice is required from 50.00 US dollars. A holder may lower the line and may not raise it. A balance
  under the line is still reported and still counted in the queue. Shares and safe deposit boxes are not handled.

**The timing window.**

- "The notice shall be mailed not less than 6 nor more than 12 months before the time when the owner's property
  held by the business becomes reportable to the Controller". (1520(b), LAW) **[verified]**
- "Perform due diligence 6-12 months prior to the Notice Report due date. Notice reports are due before Nov. 1 (or
  May 1 for life insurance) each year." (DD) **[verified]**
- In code: the window for a Notice Report due before 1 November runs from 1 November of the year before to
  30 April. Counting the six months back from "before 1 November" as ending on 30 April and not 1 May is
  **[our reading]**, taken on the careful side.
- A missed window: "the holder is encouraged to send a due diligence letter to the owner as soon as possible,
  then proceed with the reporting process in accordance with reporting deadlines." (DD) **[verified]** In code such
  a notice is still prepared and is labelled as after the window.
- More notices: "the holder may give additional notice as described in subdivision (b) at any time between the
  date of last activity by, or communication with, the owner and the date the holder transfers the property to the
  Controller." (1520(c), LAW) **[verified]** The reminder rests on this.

**What the notice must contain.** Each line is an element that `notices.check` requires before a notice can be
called ready.

| Element | The words read | Mark |
| --- | --- | --- |
| The heading | "The face of the notice shall contain a heading at the top that reads as follows: 'THE STATE OF CALIFORNIA REQUIRES US TO NOTIFY YOU THAT YOUR UNCLAIMED PROPERTY MAY BE TRANSFERRED TO THE STATE IF YOU DO NOT CONTACT US,' or substantially similar language." (1520(b)) | [verified] |
| When, and what follows | "shall specify the time when the property will escheat and the effects of escheat, including the need to file a claim in order for the owner's property to be returned to the owner." (1520(b)) DD: "Include the escheatment date." | [verified] |
| In bold or two points larger: no activity | "(1) specify that since the date of last activity, or for the last two years, there has been no owner activity on the deposit, account, shares, or other interest" | [verified] |
| In bold or two points larger: an identifier | "(2) identify the deposit, account, shares, or other interest by number or identifier, which need not exceed four digits" | [verified] |
| In bold or two points larger: in danger | "(3) indicate that the deposit, account, shares, or other interest is in danger of escheating to the state" | [verified] |
| In bold or two points larger: the law | "(4) specify that the Unclaimed Property Law requires holders to transfer funds of a deposit, account, shares, or other interest if it has been inactive for three years." | [verified] |
| A form to return | "It shall also include a form, as prescribed by the Controller, by which the owner may confirm the owner's current address." LETTER carries it: "PLEASE SIGN BELOW AND RETURN THE ENTIRE NOTICE", signature, date, printed name, current address, and "I wish to maintain this account; by signing and returning this notice, I am satisfying the requirements of the Code of Civil Procedure by indicating an interest in the account". | [verified] |
| A way to answer without the form | "In lieu of returning the form, the holder may provide a telephone number or other electronic means to enable the owner to contact the holder." (1520(b)) DD: "Provide valid contact details for owners to contact with questions or to be reunited with their property." | [verified] |
| Where the emphasis applies | "in boldface type or in a font a minimum of two points larger than the rest of the notice, exclusive of the heading" (1520(b)) The letter sets the four statements both bold and two points larger. | [verified] |

- The sample letter's body, for comparison: "California Unclaimed Property Law requires business entities to
  transfer funds of a deposit, account, shares, or other interest to the State Controller's Office (SCO) if it has
  been inactive for [number] year[s]. According to our records, there has been no activity on your account for more
  than [number] year[s]. Therefore, your property is in danger of escheating to the State unless you contact us or
  respond by completing, signing, and returning this notice prior to the Date of Escheatment listed above." and "If
  your property is transferred to the State, you will be required to file a claim with the SCO to recover it".
  (LETTER) **[verified]**
- The amount is not among the required elements. Khutlisa prints it. **[our reading that this is allowed]**
- The holder may charge at most the cost of sending, "in no case to exceed two dollars ($2)". (1520(b))
  **[verified]** The notice Khutlisa prepares says that the owner is charged nothing; a holder that charges would
  have to change that sentence, and the product does not offer the change.

**What an answer does.**

- "If that form is filled out, signed by the owner, and returned to the holder, it shall be deemed that the
  account, or other device in which the owner's property is being held, remains currently active and recommences
  the escheat period." With contact by telephone or electronic means, "as evidenced by a memorandum or other
  record on file with the holder", the same follows. (1520(b), LAW) **[verified]**
- "Contact with the holder in response to a due diligence notice is considered owner-initiated activity. Depending
  on the property type, such owner contact will restart the dormancy period." and "the holder should make every
  effort to reunite the property to the owner and not remit it." (DD) **[verified]**
- In code: an owner's answer is recorded against the notice with its time. At the handover date a balance whose
  owner has answered and not yet proven the claim is held, if the holder's instructions say so. Holding on that
  basis for every kind of property is **[our reading]**: the guide says it depends on the kind.

**How it is sent.**

- "by mail or, if the owner has consented to electronic notice, electronically". (1520(b)) "Send the due diligence
  letter to the owner's address of record (or electronically with the owner's prior consent)." (DD) **[verified]**
- In code: post is the channel that counts wherever the file has a postal address. Email counts only where the
  file records the owner's consent. An email address with no consent on record is offered as an extra copy under
  1520(c), which is **[our reading]**.

**The periods.** DORM (rev. 07/2023) read whole: cashier's cheques 3, demand deposits 3, dividends 3, employee
benefit plans 3, escrow accounts 3, gift certificates with expiration 3, interest 3, IRAs and retirement plans 3,
life insurance funds 3, liquidating distributions 6 months, matured time deposits 3, money orders 7, ordered
refunds 1, preneed funeral trust funds 3, safe-deposit boxes 3, savings 3, stocks and bonds 3, traveler's
cheques 15, wages or salaries 1, written instruments 3, other tangible and intangible property 3, and
demutualisation proceeds by their own rule. **[verified]** "Any wages or salaries that have remained unclaimed by
the owner for more than one year after the wages or salaries become payable." (1513(a)(7), LAW) **[verified]**
"has remained unclaimed by the owner for more than three years after it became payable or distributable". (1520(a),
LAW) **[verified]** The table cites section 1513 by older letters ("CCP 1513 (g)" for wages); the periods agree.

**Not verified, or our reading, for the holder's own list.**

1. Which date to print as the "Date of Escheatment". The sample leaves it as a blank and the pages read do not
   define it. Khutlisa prints the day the holder hands the property over: the holder's own handover date, or 1 June
   of the year after the Notice Report. **[our reading]**
2. Item (4) of 1520(b) says "three years". Wages have one year. The Controller's sample says "[number] year[s]",
   and Khutlisa prints the period that applies to the kind of property. **[our reading, following the sample]**
3. That 1520(b) is the notice rule for wages, which escheat under 1513(a)(7). The guide speaks of all property of
   50 dollars or more; the section-by-section reading was not checked with the Controller or a lawyer.
   **[our reading]**
4. A translation. The law gives the heading in English and says nothing about other languages. Khutlisa always
   includes the whole notice in English and adds a second page in the owner's likely language. **[our reading
   that this is allowed]** The translations were made by a language model and checked in code for their
   placeholders and numbers; no translator or lawyer has read them. **[unverified]**
5. A personal link with a code as "other electronic means to enable the owner to contact the holder".
   **[our reading]**
6. Which pay counts as "wages or salaries". Words such as wage, salary, payroll, paycheck and commission are read
   as wages (one year; the Controller's FAQ names "payroll, wages, and commissions"). Vacation pay, bonuses,
   expense repayments and anything unnamed are read as other property (three years), and the screen counts them.
   If some of these are wages in law, they are due two years earlier than Khutlisa shows. **[unverified]**
7. Every holder is counted "as of June 30". The law also allows the holder's fiscal year end (1530(d)). Life
   insurance companies, shares, safe deposit boxes and digital assets are not handled.
8. Notices to addresses abroad. No page read says anything about international post or about language. (See H7.)
9. On 13 Nov 2026 the Legislature's site and the Controller's HTML pages could not be read by an automated
   request. Section 1520 was read in the Controller's printing only on that day.

### What this means for Khutlisa

The law gives a holder two points at which it must or may pay the owner itself: before the handover (1532(b), and
the Controller expects it) and after the handover (1560(b), with repayment by the Controller). In both cases the
holder decides that the person is the owner, to its own satisfaction, and keeps the proof. The State remains the
fallback and pays by a cheque in the post. The pages do not say how a holder should pay an owner, so a bank
transfer to an owner abroad is neither named nor ruled out.

### Not verified

1. The Unclaimed Property Holder Handbook. REIMB refers to it, but no current page links to it and the old address
   (https://www.sco.ca.gov/Files-UPD/guide_rptg_holderhandbook.pdf) answers "page not found".
2. Whether a holder may pay the owner by bank transfer, and to a bank outside the United States.
3. Any guidance for notices to owners with foreign addresses, and whether the Controller posts its own letter
   abroad.
4. Whether failing to send the notice is by itself fined under section 1576.
5. How long the Controller takes to repay a holder under section 1560(b).
6. The number of holders, the number of reports, and how much holders return to owners before the handover.
7. The statute text of sections 1510, 1513, 1513.5, 1515, 1516, 1531, 1576 and 1577.5 was read only in the
   Controller's February 2026 printing, not on the Legislature's site.
8. Rules for digital financial assets (section 1516.5) and for safe deposit boxes were not followed up.
9. What the old numeric property type codes mean. No page of the Controller that was read describes them; they are
   grouped by the description the file prints beside each one (H9).
10. What any of the duties in H1 to H11 cost a holder. Nothing was found on the Controller's pages, and no figure
    is given in the product.
