# CourtListener target models

The CourtListener (CL) database models a scraper's output eventually lands in.
Use this to decide **what to name a field and what it means** when you design a
scraper's `ScrapedData` models — match CL's field names and semantics so the
downstream merge is mechanical.

Source: `courtlistener/cl/search/models.py`, `cl/people_db/models.py`,
`cl/lib/models.py`. Only the **scrape-relevant** fields are reproduced here —
indexing, Internet-Archive, S3 storage, history, and other infrastructure
fields are omitted. See the source for the complete definitions.

Referenced from [`SCRAPER_STANDARDS.md`](SCRAPER_STANDARDS.md) §8 (Models).

---

## The object graph

```
Docket ─1:1─ OriginatingCourtInformation   (lower court, one step down)
  │   ─1:1─ ScotusDocketMetadata | NYCoADocketMetadata   (court-specific extras)
  │   ─1:1─ TrialCourtData        (the very first trial court, ≥2 hops down)
  │   ─*──  CaseTransfer          (transfers in/out of this docket)
  │
  ├─*─ DocketEntry ─*─ RECAPDocument          (general / RECAP path)
  │                                            (+ Attachment, same model)
  ├─*─ SCOTUSDocketEntry ─*─ SCOTUSDocument   (SCOTUS-specific path)
  │
  └─*─ Party  (through PartyType: party↔docket + role-on-this-docket)
         └─*─ Attorney (through Role: attorney↔party↔docket)
                └─*─ AttorneyOrganization (through association, per docket)
```

- A scraper that produces dockets maps its records onto **Docket** (+ its
  per-court metadata side-table), **DocketEntry**, the document model, and the
  **Party/Attorney** graph.
- **SCOTUS** has its own entry/document tables (`SCOTUSDocketEntry` /
  `SCOTUSDocument`); everything else uses `DocketEntry` / `RECAPDocument`.

### How the example scrapers map

| Scraper model | CL model |
| --- | --- |
| `TexasDocket` / SCOTUS metadata dict | `Docket` (+ `ScotusDocketMetadata`) |
| `TexasDocketEntry` / SCOTUS `docket_entries[]` | `DocketEntry` (or `SCOTUSDocketEntry`) |
| `TexasDocument` / SCOTUS `attachments[]` | `RECAPDocument` (or `SCOTUSDocument`) |
| `TexasParty` / SCOTUS `parties[]` | `Party` + `PartyType` |
| (party's) `representatives` / `attorneys[]` | `Attorney` + `Role` |
| `TexasOriginatingCourt` | `OriginatingCourtInformation` |
| `TexasTransfer` / `TexasAppealsCourtRef` | `CaseTransfer` |

### Capture everything relevant — even fields CL doesn't have yet

These tables are the **target**, not a ceiling. Capture all of the information
that seems relevant on a page, even when it doesn't correspond to an existing
CL field. When that happens, **add a field to the most relevant model** (the
scraper's `ScrapedData` model, and ultimately the CL model it maps to) rather
than dropping the data. The mapping is easiest when names and semantics match
CL, but a faithful scrape of a useful field beats discarding it because there's
no column for it today.

### Conventions

- **`docket_number` vs `docket_number_raw`:** scrape the verbatim site value into
  `*_raw`; CL derives the cleaned/`_core` forms. Provide `docket_number` (cleaned
  enough to be usable) and `docket_number_raw` when they differ.
- **`court` is a CourtListener court ID string** (`tex`, `texapp`, `scotus`,
  `ny`, …) — the same IDs in the scraper's `court_ids` ClassVar.
- **`*_str` fallback fields** (`assigned_to_str`, `appeal_from_str`, …) hold the
  raw name when we can't resolve it to a `Person`/`Court` FK. Scrapers populate
  the `_str` form; resolution happens downstream.
- **Dates** are `date` objects; **`date_*`** naming throughout.

---

## Docket

The case. Top-level record nearly every scraper produces.

| Field | Type | Description |
| --- | --- | --- |
| `court` | court-id str | The court where the docket was filed. |
| `docket_number` | str | The docket number(s); may be consolidated and long. |
| `docket_number_raw` | str | Raw docket number as found on the source, no cleaning. |
| `case_name` | str | Standard name of the case (e.g. `Foo v. Bar`). |
| `case_name_short` | str | Abridged name, often one word (e.g. `Marsh`). |
| `case_name_full` | str | Full, unshortened case name. |
| `date_filed` | date | The date the case was filed. |
| `date_terminated` | date | The date the case was terminated. |
| `date_last_filing` | date | Date of the most recent docket activity. |
| `date_argued` | date | The date the case was argued. |
| `date_reargued` | date | The date the case was reargued. |
| `date_reargument_denied` | date | The date reargument was denied. |
| `date_cert_granted` | date | Date cert was granted, if applicable. |
| `date_cert_denied` | date | Date cert was denied, if applicable. |
| `appeal_from` | court-id str | Lower court/body where originally heard (FK; often blank). |
| `appeal_from_str` | str | Same as above, as a raw string when unresolved. |
| `assigned_to_str` | str | The judge the case was assigned to, as a string. |
| `referred_to_str` | str | The judge the case was referred to, as a string. |
| `panel_str` | str | Initials of the judges on the panel. |
| `cause` | str | The cause for the case. |
| `nature_of_suit` | str | The nature-of-suit code. |
| `jury_demand` | str | The compensation demand. |
| `jurisdiction_type` | str | E.g. `Diversity`, `U.S. Government Defendant`. |
| `appellate_fee_status` | str | Status of the fee in the appellate court. |
| `appellate_case_type_information` | str | E.g. `civil, private, bankruptcy`. |
| `mdl_status` | str | MDL status before the JPML. |
| `pacer_case_id` | str | Case ID provided by PACER (federal only). |

> Federal/PACER-only plumbing fields (`docket_number_core`, `federal_dn_*`,
> `federal_defendant_number`, `parent_docket`, IDB data) exist on the model but
> are derived or PACER-specific — state scrapers normally leave them unset.

---

## OriginatingCourtInformation

Lower-court metadata for an appellate case — **one step down** the chain. 1:1
with `Docket` via `Docket.originating_court_information`.

| Field | Type | Description |
| --- | --- | --- |
| `docket_number` | str | The docket number in the lower court. |
| `docket_number_raw` | str | Raw lower-court docket number, no cleaning. |
| `assigned_to_str` | str | The judge the case was assigned to (string). |
| `ordering_judge_str` | str | Judge who issued the final order (string). |
| `court_reporter` | str | The court reporter responsible for the case. |
| `date_filed` | date | Date filed in the lower court. |
| `date_disposed` | date | Date the case was disposed at the lower court. |
| `date_judgment` | date | Date of the order/judgment in the lower court. |
| `date_judgment_eod` | date | Date judgment was entered on the docket. |
| `date_filed_noa` | date | Date the notice of appeal was filed. |
| `date_received_coa` | date | Date the case was received at the court of appeals. |
| `date_rehearing_denied` | date | Date the petition for rehearing was denied. |

---

## DocketEntry

A row on the docket. `Docket ──*── DocketEntry`.

| Field | Type | Description |
| --- | --- | --- |
| `date_filed` | date | Created date of the entry (court timezone). |
| `time_filed` | time | Created time of the entry, if available. |
| `entry_number` | int | The number on the docket page (`#` column). |
| `description` | str | Text content of the docket entry. |
| `recap_sequence_number` | str | CL-generated ordering key (date + sequence); for ordering unnumbered entries. |
| `pacer_sequence_number` | int | `de_seqno` from PACER (federal; collected, mostly unused). |

---

## RECAPDocument

A document or attachment hung off a `DocketEntry`. `DocketEntry ──*──
RECAPDocument`. Inherits `AbstractPacerDocument` + `AbstractPDF`.

| Field | Type | Description |
| --- | --- | --- |
| `document_type` | int | `1` = PACER Document, `2` = Attachment. |
| `document_number` | str | Document number within the docket entry. |
| `attachment_number` | int | Attachment number, when this is an attachment. |
| `description` | str | Short description (esp. on the attachments page). |
| `pacer_doc_id` | str | The document's PACER ID (federal). |
| `acms_document_guid` | str | The document's GUID in ACMS (federal appellate). |
| `is_available` | bool | True if the file is available/downloaded. |
| `is_sealed` | bool | True if sealed/unavailable. |
| `is_free_on_pacer` | bool | Freely available as an opinion on PACER. |
| `date_upload` | datetime | When the file was uploaded to RECAP. |
| **from `AbstractPDF`:** | | |
| `sha1` | str | SHA1 of the document file. |
| `page_count` | int | Number of pages, if known. |
| `file_size` | int | File size in bytes, if known. |
| `filepath_local` | file/path | Stored file location (set by the driver/pipeline). |
| `plain_text` | str | Extracted text (set downstream after extraction). |
| `ocr_status` | int | OCR processing status (1 complete / 2 unnecessary / 3 failed / 4 needed). |

---

## Parties & attorneys

A party↔docket↔attorney graph. Scrapers usually produce a party with a role and
a list of representing attorneys (see `TexasParty`, SCOTUS `parties[]`).

### Party

| Field | Type | Description |
| --- | --- | --- |
| `name` | str | The name of the party. |

### PartyType — links a `Party` to a `Docket` (the party's role on this case)

| Field | Type | Description |
| --- | --- | --- |
| `docket` | FK | The docket. |
| `party` | FK | The party. |
| `name` | str | The role/type on this docket: `Defendant`, `Plaintiff`, `Appellant`, `Respondent`, `Amicus`, … |
| `date_terminated` | date | Date the party was terminated from the case, if applicable. |
| `extra_info` | str | Additional info from the source. |

### Attorney

| Field | Type | Description |
| --- | --- | --- |
| `name` | str | The name of the attorney. |
| `contact_raw` | str | Raw contents of the contact field. |
| `phone` | str | Phone number. |
| `fax` | str | Fax number. |
| `email` | str | Email address. |

### Role — links an `Attorney` to a `Party` on a `Docket`

| Field | Type | Description |
| --- | --- | --- |
| `party` / `attorney` / `docket` | FK | The (party, attorney, docket) triple. |
| `role` | int | Coded role: lead, to-be-noticed, pro hac vice, terminated, suspended, inactive, disbarred, unknown. |
| `role_raw` | str | Raw role string as found on the source. |
| `date_action` | date | Date the attorney was disbarred/suspended/terminated. |

### AttorneyOrganization — a firm (linked per-docket via an association table)

| Field | Type | Description |
| --- | --- | --- |
| `name` | str | The name of the organization. |
| `address1` / `address2` | str | Street address lines. |
| `city` | str | City. |
| `state` | str | Two-letter USPS state code. |
| `zip_code` | str | ZIP (`XXXXX` or `XXXXX-XXXX`). |

---

## Court-specific docket metadata

1:1 side-tables off `Docket`, for fields that only apply to one court.

### ScotusDocketMetadata

| Field | Type | Description |
| --- | --- | --- |
| `capital_case` | bool | Whether this SCOTUS case is a capital case. |
| `date_discretionary_court_decision` | date | Date of the Court's discretionary decision. |
| `linked_with` | str | Other docket(s) this case is linked with. |
| `questions_presented_url` | str | URL to the Questions Presented page/document. |

### NYCoADocketMetadata

| Field | Type | Description |
| --- | --- | --- |
| `issue` | str | Issue categories the Court of Appeals associated with the case. |
| `summary` | str | Detailed issue descriptions. |
| `decision_date` | date | Date the case was decided, if decided. |
| `opinion_by` | str | Author of the opinion, for decided cases. |
| `official_citation` | str | Official citation, for decided cases. |

---

## SCOTUS entry & document tables

SCOTUS uses these instead of `DocketEntry` / `RECAPDocument`.

### SCOTUSDocketEntry (`Docket ──*──`)

| Field | Type | Description |
| --- | --- | --- |
| `entry_number` | int | Entry number on the SCOTUS docket page. |
| `description` | str | Short description (e.g. for an appellate brief event). |
| `date_filed` | date | Date SCOTUS indicates the entry was filed. |
| `sequence_number` | str | CL ordering key: ISO filing date + index in the SCOTUS table. |

### SCOTUSDocument (`SCOTUSDocketEntry ──*──`; inherits `AbstractPDF`)

| Field | Type | Description |
| --- | --- | --- |
| `description` | str | Description of the file in SCOTUS. |
| `document_number` | int | Document number on the SCOTUS docket page. |
| `attachment_number` | int | Attachment number on the page. |
| `url` | str | Download URL SCOTUS provided for the document. |
| (+ `AbstractPDF`: `sha1`, `page_count`, `file_size`, `filepath_local`, `plain_text`, `ocr_status`) | | See RECAPDocument. |

---

## Transfers & trial court

### CaseTransfer

A transfer of a docket between two courts — appeal, workload balancing, merge,
or jurisdiction change. `x_court` + `x_docket_number` are always set; at least
one of `origin_docket` / `destination_docket` must resolve.

| Field | Type | Description |
| --- | --- | --- |
| `origin_court` | court-id str | Court the transfer originates from. |
| `origin_docket_number` | str | Docket number on the origin side. |
| `destination_court` | court-id str | Court the docket is transferred to. |
| `destination_docket_number` | str | Docket number on the destination side. |
| `transfer_date` | date | Date the transfer occurred. |
| `transfer_type` | int | `0` Appeal · `1` Workload · `2` Merge · `3` Jurisdiction. |

### TrialCourtData

The **first** trial court, for cases ≥2 hops up (where
`OriginatingCourtInformation` and `CaseTransfer` only reach one step). 1:1 with
`Docket`.

| Field | Type | Description |
| --- | --- | --- |
| `docket_number_trial` | str | Trial-court docket number (some cleanup applied). |
| `docket_number_raw_trial` | str | Raw trial-court docket number, no cleaning. |
| `judge_str` | str | Name of the presiding judge. |
| `reporter` | str | Court reporter listed for the case. |
| `date_filed` | date | Date the case was originally filed. |
| `court_name` | str | Name of the court as it appears on the source. |
| `court` | court-id str | Resolved `Court` FK, if in the DB. |
| `punishment` | str | Punishment assigned, in criminal cases. |
| `county` | str | County the trial court is located in. |
