# Connecticut Appellate Inquiry — CC Notes

> Conforms to [`SCRAPER_STANDARDS.md`](../../../sd/state/SCRAPER_STANDARDS.md).
> One speculative entry, `dockets_by_internal_id(internal_id: SpeculativeRange)`,
> probes `CaseDetail.aspx?CRN={n}` on `appellateinquiry.jud.ct.gov`. The CRN is
> an opaque internal id forming a **single space shared by both appellate
> courts**; the court is read from the docket number on the page (`SC` →
> `conn`, `AC` → `connappct`), so — unlike California — the speculative param
> carries no court and no `CourtRange` is needed. HTML extraction lives in the
> `parsers/` package (§9); steps keep navigation, URL resolution, archive
> requests, and unavailable-page detection.

This is one of three scrapers the legacy combined `connecticut/jud_ct_gov`
scraper was split into (the others: opinions on `www.jud.ct.gov`, oral
arguments on `jud.ct.gov`). The split was forced by `driver_requirements` being
scraper-wide/binary — opinions are plain HTTP while oral arguments need
ViewState/serial handling — and follows the one-host-per-dir precedent.

## Site Overview
- **Appellate**: `https://appellateinquiry.jud.ct.gov` — Supreme & Appellate
  Court case look-up. Server-rendered ASP.NET (`CaseDetail.aspx`), **no JS
  required**; plain HTTP works.
- **Trial court**: `https://civilinquiry.jud.ct.gov` — Superior Court civil
  case detail (`CaseDetail/PublicCaseDetail.aspx`). Reached only by following
  the trial-court link off a *civil* appellate case (folded into this scraper;
  court id `connsuperct`).
- **Driver**: `driver_requirements = []` (plain HTTP). No browser, no captcha.

### TLS gotcha
Both CT Judicial hosts reject OpenSSL 3.0's **default** `SECLEVEL=2`
handshake — every request fails with `SSLV3_ALERT_HANDSHAKE_FAILURE` (this is
what killed the first full run). The scraper overrides `get_ssl_context` to
set `DEFAULT@SECLEVEL=1`, which both hosts accept. Verified live against the
erroring `CaseDetail.aspx?CRN=…` page and a `civilinquiry` page:

| SSL config | appellateinquiry | civilinquiry |
|---|---|---|
| default (`SECLEVEL=2`) | ❌ handshake failure | ❌ handshake failure |
| legacy `AES256-SHA256` | ✅ 200 | ❌ handshake failure |
| `DEFAULT@SECLEVEL=1` | ✅ 200 | ✅ 200 |

The legacy scraper pinned `AES256-SHA256`, which only fixed `appellateinquiry`
— `civilinquiry` rejects it. Do **not** pin a single cipher; lower the
security level instead.

## Addressing: CRN speculation
- `CaseDetail.aspx?CRN={n}` where CRN is a monotonic-ish internal id.
- A missing CRN **302-redirects to `ErrorPage.aspx?errmsg=Case Not Found`**
  (the unencoded space in the Location header may stop httpx from following, so
  the step also treats non-200 as a miss). Misses yield nothing, so the driver
  advances/terminates the speculation.
- **Gaps are large and irregular**: e.g. as of 2026-06, CRN 1 exists, 104500
  and 105000+ exist, but the entire 102000–104000 band is empty. Seed a
  **generous `gap`** (hundreds), not the tiny gap the legacy seed used.
- A case that exists but is withheld shows `<docket> - This case is not
  available at this time.` in `lblNotAvailable`; that yields
  `ConnAppDocketUnavailable` (only the docket number is recoverable).

Example seed:
```json
[{"dockets_by_internal_id": {"internal_id": {"min": 1, "soft_max": 105336, "gap": 500}}}]
```

## Flow (priorities descend by depth; downloads at 1)
```
dockets_by_internal_id (entry, speculative)
  → parse_case_detail        (3)  AppealCaseParser + ActivitiesParser
      ├ ParsedData(ConnAppDocket)
      ├ ParsedData(ConnAppDocketEntry) per Case Activity row
      ├ archive document → handle_appellate_document (1) → ConnAppFile
      └ civil trial link → parse_trial_court_detail
  → parse_trial_court_detail  (2)  TrialCourtCaseParser + TrialActivitiesParser
      ├ ParsedData(ConnTrialCourtDocket) | ConnTrialCaseUnavailable
      ├ ParsedData(ConnTrialCourtDocketEntry) per document row
      └ archive document → handle_trial_document (1) → ConnTrialFile
```

## Appellate page (`CaseDetail.aspx`) fields
Flat `lbl*` spans (exact ids): `lblAppealNo` (docket no, `SC`/`AC` + digits),
`lblCaseName`, `lblCaseStatus`, `lblDateFiled`, `lblArgSub` (argued),
`lblDispDt` (terminated), `lblDispMethod`, `lblAppealBy`, `lblSubmitDt`,
`lblResponse2Docket`, `lblRecordFiled`, `lblExhbitsRecByCourt`, `lblRescript`
(citation), `lblPanel`. Subscription link `hlnkSubscribe`.

- **Trial-court block** (`ConnAppOriginatingCourt` → CL
  `OriginatingCourtInformation`): `lblCourt`, `lblTrialJudge`,
  `lblJudgementdate`, `lblJudgementFor`, `lblCaseType`, and the trial docket
  number in `dlTCDockets … lblDocketNumber`. For **civil** cases the docket
  number is a link to `civilinquiry`; criminal/family numbers are plain text
  (no follow).
- **Parties** (`gvPartyCounsel`): one row per party with `lblPartyName`,
  `lblAppealPartyClass` (role → `PartyType`), `lblTrialCourtPartyClass`, and
  nested `tblJurisInfo` tables giving each attorney's `tdJurisName` +
  `tdJurisNumber` ("Juris: NNNNNN").
- **Case Activity** (`gvActivities`, 8 columns → `ConnAppDocketEntry`):
  Activity (`lblActivity` + document links), Number, Date filed, Initiated By,
  Description (`lblDescription`), Action, Action Date, Notice Date. Documents
  are `DocumentDisplayer.aspx?AppId=2&DocId=…` links; each is archived as a
  `ConnAppFile`.
- **Preliminary papers** (`gvPrelimPapers`) and **transcripts**
  (`gvTranscripts`) are parsed best-effort (absent on most cases).

## Trial-court page (`PublicCaseDetail.aspx`) fields
Element ids are prefixed `ctl00_ContentPlaceHolder1_…`, and each value span
(`…lblBasicCaseType`) is paired with a label span (`…lblBasicCaseTypeTitle`),
so the parser matches values by **id ends-with** (a `contains` match grabs the
label). Fields: `lblDocketNo`, `lblCaseCaption`, `lblBasicCaseType`,
`lblBasicLocation`, `lblBasicListType`, `lblFileDate`, `lblReturnDate`,
`lblBasicDispositionDate`, `lblBasicDisposition`, `lblBasicDispJudge`,
`lblBasicLastAction`. Parties: `gvParties` (`lblPlaintDefPartyNo`,
`lblPtyPartyName`, `lblNonAppearing`, appearance `lblAppearanceInfo1/2`).
Documents: `gvDocuments` (Entry No, File Date, Filed By `lblFiledBy`,
Description with `hlnkDocument` link + `lblAddDesc` + `lblResult`, Arguable).

### Known gap: civilinquiry session
Direct `PublicCaseDetail.aspx?DocketNo=…` access **without a warm session**
redirects to an error page (`ErrorPage.aspx?emLID=…`); a browser that has
visited the site first loads it fine. The step detects the missing case
content / error redirect and yields `ConnTrialCaseUnavailable`. Whether the
jkent HTTP driver's cookie jar warms the session naturally across the
appellate→trial hop needs confirming on a real run; if not, a civilinquiry
home-page warmup request may be required.

## Models (aligned to [`CL_MODELS.md`](../../../sd/state/CL_MODELS.md))
- `ConnAppDocket` → `Docket` (`court`, `docket_number`/`_raw`, `case_name`,
  `date_filed`, `date_argued`, `date_terminated`, `panel_str`, …); CT extras:
  `crn`, `case_status`, `appeal_by`, `disposition_method`, prelim papers,
  transcripts. Trial block → embedded `ConnAppOriginatingCourt`.
- `ConnAppDocketEntry` → `DocketEntry`; `ConnAppFile` → `RECAPDocument`.
- `ConnAppParty`/`ConnAppAttorney` → `Party`/`PartyType` + `Attorney`.
- `ConnAppDocketUnavailable` — withheld appellate case.
- `ConnTrialCourtDocket` → `Docket` (`connsuperct`);
  `ConnTrialCourtDocketEntry` → `DocketEntry`; `ConnTrialFile` →
  `RECAPDocument`; `ConnTrialCourtParty`/`ConnTrialCourtAttorney`;
  `ConnTrialCaseUnavailable`.

## Tests
`test.py` exercises every parser offline with `JKentParser.from_file` against
the saved fixtures in `test_assets/` (criminal + civil appellate pages and a
civil trial-court page). Run: `uv run python -m pytest <this dir>/test.py`.
