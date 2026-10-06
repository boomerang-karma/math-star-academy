# Compliance

> This document describes the engineering controls LeadIntel provides to support
> compliance with data-protection law. It is not legal advice. The organization
> deploying LeadIntel is the **controller**: it must have its counsel and data
> protection officer review the lawful bases, notices, DPIA and vendor contracts
> below before processing personal data in production.

## Position in one paragraph

B2B prospecting data about people is personal data. LeadIntel treats it that
way:

- every record carries its lawful basis and provenance
- contact details are encrypted
- people are visible only within sales territories
- retention is enforced nightly
- data-subject requests are tooled end to end
- suppression prevents re-collection
- scraping of individual LinkedIn profiles is **off by default**

The safest sources of person data are the ones where the person engaged with
us: LinkedIn Lead Gen Forms, website forms, and meetings. Scraped public data
mostly feeds **organization** records and market signals, which are generally
not personal data.

## Regulatory landscape (summary)

| Regime | What matters for LeadIntel |
| --- | --- |
| EU GDPR / UK GDPR | Lawful basis (Art. 6); transparency, including Art. 14 notices when data was not collected from the person; data-subject rights within one month (extendable); right to object to direct marketing (Art. 21), which is absolute; records of processing (Art. 30); security (Art. 32); breach notification within 72 hours (Art. 33); DPIA for high-risk processing (Art. 35) |
| ePrivacy / PECR and national marketing laws | Consent rules for marketing emails differ by country and by corporate versus individual subscriber. The consent ledger records consent by purpose, and reps follow the playbook per country |
| CCPA / CPRA (California) | B2B contact data has been in scope since the B2B exemption expired on 1 January 2023. Rights to know, delete, correct and opt out; respond within 45 days (extendable once); notice at collection |
| CAN-SPAM (US email) | Opt-out honoured through the suppression list |
| Platform terms | LinkedIn's User Agreement prohibits scraping; Google Analytics terms forbid sending personal data to GA |

## Lawful basis by source

| Source | Data subjects | Lawful basis recorded | Notes |
| --- | --- | --- | --- |
| LinkedIn Lead Gen Forms (Lead Sync) | People who submitted our form | `consent` for the purposes ticked; otherwise `legitimate_interest` for responding | The form's privacy notice must name the purposes. A member's lead deletion is honoured automatically |
| Website forms (beacon) | People who submitted our form | `consent` / `legitimate_interest` per form | The form's privacy notice applies |
| Website and GA4 behaviour | Visitors, pseudonymous until they identify themselves | `consent` (analytics) where required | The tracking snippet loads only after consent where required. GA receives no personal data |
| ScrapeBadger: company pages, jobs, maps, news, websites | Mostly organizations; incidental names (e.g. a CEO named in news) | `legitimate_interest` | Organization data is generally not personal data, but sole traders and named individuals in news can be |
| ScrapeBadger: person profiles | Individuals | `legitimate_interest`, **only after the steps under [Scraping policy](#scraping-policy)** | Disabled by default |

### Legitimate interests assessment (outline)

Complete one LIA per purpose before relying on legitimate interest:

1. **Purpose test.** Identifying organizations likely to benefit from our
   product, and the roles that buy it. Recital 47 recognises direct marketing as
   a possible legitimate interest.
2. **Necessity test.** Only role-relevant professional data is used: name,
   title, seniority, employer, and business contact details. No sensitive data,
   no personal social activity, and no private contact data.
3. **Balancing test.**
   - The context is professional.
   - Collection is limited to people in buyer roles (ICP personas).
   - Retention is short for unengaged people (180 days).
   - Every outreach offers an opt-out, honoured by suppression.
   - Notices are provided (see Art. 14 below).
   - Contacts who limited their visibility on a platform are excluded.

## Transparency: Article 14 notices

When personal data is not obtained from the person, GDPR Art. 14 requires
telling them within a reasonable period: at the latest one month after
collection, or at the first communication if the data is used to contact them.
Two enforcement cases show regulators take this seriously for B2B data:

- Poland's UODO fined Bisnode about €220,000 in 2019 for not notifying
  business owners whose data came from public registers. It rejected the
  "disproportionate effort" defence
  ([summary](https://www.blakemorgan.co.uk/digital-marketing-agency-bisnode-fined-by-the-polish-dpa-for-failing-to-be-transparent-with-data-subjects/)).
- France's CNIL fined KASPR €240,000 in December 2024 for collecting LinkedIn
  users' contact details, including those of users who had restricted their
  visibility. KASPR kept the data for years and informed people late
  ([CNIL](https://www.cnil.fr/en/data-scraping-kaspr-fined-eu240000)).

Operational rule: the first outreach to any person whose record came from a
scraped source must carry the Art. 14 information (or a link to it). If person
scraping is enabled for a population that will not be contacted within a
month, a notice process must exist first.

## Scraping policy

1. **Public pages only, as a logged-out visitor.** No logins, no fake
   accounts, no circumvention of access controls. LeadIntel uses ScrapeBadger as
   a processor and must also comply with ScrapeBadger's terms.
2. **Organization data first.** Company pages, job postings, maps listings,
   news and company websites are the default playbooks.
3. **Person profiles are gated.** `person_profile` refuses to run unless
   `LEADINTEL_ALLOW_PERSON_PROFILE_SCRAPING=true`. Before setting it:
   - complete a **DPIA** and an LIA for the purpose
   - restrict the target population to ICP personas
   - set up the Art. 14 notice process
   - get documented legal sign-off on the platform-terms risk
4. **Respect people's choices.** Do not collect people who restricted their
   visibility. Honour objections globally through the suppression list.
5. **Know the platform-terms risk.** In the US, *hiQ Labs v. LinkedIn* found
   that scraping public pages likely does not violate the CFAA, but the court
   held hiQ liable for breaching LinkedIn's User Agreement. The case ended in
   2022 with a consent judgment: a permanent injunction, deletion of scraped
   data, and $500,000 in damages
   ([summary](https://www.morganlewis.com/blogs/sourcingatmorganlewis/2022/12/linkedin-v-hiq-landmark-data-scraping-suit-provides-guidance-to-data-scrapers-and-web-operators)).
   The compliant route to LinkedIn people data is the member's own action
   (Lead Gen Forms / Lead Sync), which is why it is the default.

## Data protection impact assessment

LeadIntel evaluates and scores people (profiling) and combines datasets from
several sources. These are two of the criteria European regulators use to flag
likely high-risk processing, so expect a DPIA before production use with
person data. Inputs for the DPIA live in this repository:

| DPIA input | Where it lives |
| --- | --- |
| Data inventory | [ONTOLOGY.md](ONTOLOGY.md) |
| Security measures | [SECURITY.md](SECURITY.md) |
| Retention | The retention schedule below |
| Rights handling | The DSAR section below |

## Record of processing activities

Keep this table in sync with `database/seeds/0002_retention_policies.sql`.

| Activity | Purpose | Data subjects | Personal data | Sources | Lawful basis | Recipients / processors | Retention | Safeguards |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Account discovery and enrichment | Find and qualify target organizations | Incidental (named individuals in public sources) | Names in news/job posts | ScrapeBadger | Legitimate interest | AWS (hosting), ScrapeBadger (collection) | Raw payloads 30 days; organization records 730 days | Organization-first playbooks; credit budgets; bronze-zone expiry |
| Inbound lead capture | Respond to people who asked to be contacted | Form submitters | Name, email, phone, title, company, consent choices | LinkedIn Lead Gen Forms, website forms | Consent / legitimate interest | AWS, LinkedIn | While engaged; disqualified leads anonymized after 365 days | Envelope encryption; consent ledger; deletion on withdrawal |
| Website engagement analytics | Understand interest of known and unknown visitors | Website visitors | Pseudonymous visitor id, pages, timestamps | Beacon, GA4 | Consent (where required) | AWS, Google (GA4) | Web events 395 days; signals 365 days | No IPs stored; GA gets no personal data; consent gating |
| Lead scoring and prioritization | Prioritize sales effort | Leads | Derived scores, explanations | All of the above | Legitimate interest | AWS | With the lead | Explainable scores; human decides on outreach |
| Prospect research (optional) | Identify buyer-role people at target accounts | Professionals in ICP roles | Name, title, seniority, employer, public profile URL | ScrapeBadger person profiles | Legitimate interest (after DPIA/LIA) | AWS, ScrapeBadger | Unengaged people 180 days | Disabled by default; Art. 14 process; suppression |
| AI account briefs | Summarize public business context for reps | (Indirect) | Person title and seniority only; no names or contact data | Derived | Legitimate interest | AWS (Amazon Bedrock) | Cached with the lead | Data minimization; prompt fencing; AI label in UI |
| Rights and suppression management | Comply with data-subject rights | Requesters | Email blind index, request metadata | Requests | Legal obligation | AWS | DSAR exports 30 days; request log retained | Identity verification; approval step; audit trail |

**Vendors.** Sign data-processing terms with every processor:

- **AWS**: DPA via AWS Artifact.
- **ScrapeBadger**: request their DPA and their sub-processor list.
- **Google**: data processing terms for GA4.
- **LinkedIn**: Marketing API terms for Lead Sync.

On Amazon Bedrock, AWS states that prompts and outputs are not shared with
model providers. Confirm this against the current AWS terms during vendor
review. Choose an AWS region that matches your data-residency commitments
(`region` in `infra/config/<env>.json`).

## Retention schedule

Enforced nightly by the `retention` Lambda from `privacy.retention_policy`, and
by S3 lifecycle rules:

| Data class | Retain | Action |
| --- | --- | --- |
| Raw upstream payloads (bronze) | 30 days (dev: 14) | Delete (DB job and S3 lifecycle) |
| First-party web events | 395 days (13 months) | Delete |
| Signals | 365 days | Delete |
| Scraped people never linked to an engaged lead | 180 days | Delete |
| Organization source records | 730 days | Delete |
| Disqualified leads | 365 days | Anonymize (keep firmographics, drop the person link) |
| DSAR exports | 30 days | S3 lifecycle delete |
| Audit anchors | 7 years in production (Object Lock) | Expire |
| Application logs | 14 / 30 / 365 days (dev / staging / prod) | Expire |
| Database backups | 1 / 7 / 30 days (dev / staging / prod) | Expire |

Erased data can survive in backups until they expire. This is a standard,
documented limitation. Restores must re-apply erasures (see
[RUNBOOK.md](RUNBOOK.md#restore)).

## Data-subject rights

The workflow covers `access`, `portability`, `erasure`, `rectification`,
`restriction` and `objection` (UI or `POST /api/v1/privacy/dsar`, permission
`compliance:dsar`):

1. **Receive.** The compliance officer records the request: type,
   jurisdiction, email. The email is stored only as a blind index. Due dates
   are set automatically: 30 days for GDPR and UK GDPR, 45 days for CCPA.
2. **Verify identity** out of band (reply from the address, or the CRM
   account), then **approve** (`POST /api/v1/privacy/dsar/{id}/approve`).
3. **Execute.** The `dsar-worker` (every 15 minutes) handles approved
   requests. Every step is audited.
   - **Access / portability**: exports every record, signal and consent held
     about the person, decrypted, as JSON to the encrypted DSAR export bucket.
     The request is completed only after the export is stored. The database
     keeps counts and the export location, never the data. The compliance
     officer sends the file securely ([runbook](RUNBOOK.md#data-subject-requests)).
   - **Erasure**:
     - deletes the person's source records, signals, relationships, identity
       links, leads, review items and consent records, plus their raw payloads
       in S3
     - tombstones the entity (no personal data left in the row)
     - adds an email **suppression**, so no source can re-collect the person
   - **Objection / restriction**: add a suppression (`POST
     /api/v1/privacy/suppressions`, reason `objection`). This stops
     re-collection, and the Lead 360 page flags the person as do-not-contact.
     If the person also wants their data deleted, process an erasure request.
     Otherwise the retention schedule removes unengaged people after 180 days.
   - **Rectification**: correct the source (CRM or form) or add a `manual`
     source record, which has the highest survivorship trust.

Audit entries reference request and record ids, never personal data, so they
survive erasure.

## Consent ledger

`privacy.consent` stores consent by purpose (`marketing_email`,
`sales_outreach`, `analytics`, `profiling`) with status (`granted`, `denied`,
`withdrawn`), source, lawful basis, evidence and timestamp, keyed by email
blind index. LinkedIn Lead Sync writes it from each form's consent responses.
Website forms record marketing consent as the source record's lawful basis
(`marketing_consent` → `consent`); writing them to the ledger too is on the
roadmap. The Lead 360 page shows the ledger next to the contact, so reps can see
what the person agreed to.

## Breach response

1. Contain: rotate credentials and revoke sessions (see
   [SECURITY.md](SECURITY.md#detection-and-response)).
2. Assess scope using the audit log, CloudTrail and access logs. Encrypted
   contact fields reduce the impact of a database-only exposure, provided the
   KMS key was not also misused.
3. Notify the supervisory authority within 72 hours where required, and the
   affected people where the risk is high.
4. Record the incident and the remediation in the breach register.
