"""Data models for NYSCEF (iapps.courts.state.ny.us) scraper.

These models capture appellate case data from the New York State
Courts Electronic Filing system (NYSCEF).

Data source:
- https://iapps.courts.state.ny.us/nyscef/

Courts covered:
- Appellate Division - 1st Dept
- Appellate Division - 2nd Dept
- Appellate Division - 3rd Dept
- Appellate Division - 4th Dept

Case number format: YYYY-NNNNN (e.g., 2024-00003)
"""

from __future__ import annotations

from datetime import date

from jkent.common.data_models import ScrapedData


class NYSCEFAttorneyRep(ScrapedData):
    """An attorney representation record from the Case Detail page."""

    attorney_name: str
    """Attorney name (e.g., 'FLYNN, ERIN K')"""

    firm: str | None = None
    """Law firm name"""

    consent_date: date | None = None
    """Date attorney entered appearance (from 'on MM/DD/YYYY')"""


class NYSCEFParty(ScrapedData):
    """A party from the Case Detail page."""

    name: str
    """Party name (e.g., 'Melissa Fawer')"""

    role: str
    """Party's role in the case (e.g., 'Appellant', 'Respondent', 'Mailing Party')"""

    party_group: str
    """Group heading (e.g., 'Petitioners', 'Respondents')"""

    attorneys: list[NYSCEFAttorneyRep] = []
    """Attorneys representing this party"""


class NYSCEFDocketEntry(ScrapedData):
    """A document from the Document List page."""

    doc_number: int
    """Document sequence number"""

    document_type: str
    """Document type (e.g., 'APPELLANT'S BRIEF', 'DECISION AND ORDER')"""

    description: str | None = None
    """Extra description text (e.g., 'Volume 1 of 2', 'Stipulation Adjourning...')"""

    filed_by: str | None = None
    """Person who filed the document"""

    filed_date: date | None = None
    """Date filed"""

    received_date: date | None = None
    """Date received by the court"""

    status: str | None = None
    """Processing status (e.g., 'Processed')"""

    download_url: str | None = None
    """URL to view/download the document (ViewDocument?docIndex=...)"""

    confirmation_notice_url: str | None = None
    """URL to the confirmation notice PDF (ConfirmationNotice?docId=...)"""


class NYSCEFDownloadedDocument(ScrapedData):
    """A downloaded document file from the NYSCEF Document List page.

    Yielded separately from NYSCEFCase so that archive downloads can
    proceed independently.  Use ``iapps_internal_docket_id`` to join
    back to the parent case in post-processing.
    """

    iapps_internal_docket_id: str
    """NYSCEF internal docket ID (base64-encoded) — join key to NYSCEFCase"""

    doc_number: int
    """Document sequence number within the case"""

    document_type: str
    """Document type (e.g., 'APPELLANT\\'S BRIEF', 'DECISION AND ORDER')"""

    download_url: str
    """Source URL (ViewDocument?docIndex=...)"""

    local_path: str | None = None
    """Local filesystem path where the file was saved (set by driver)"""


class NYSCEFCase(ScrapedData):
    """A case from the NYSCEF system.

    This is the main output type yielded by the NYSCEF scraper.
    Combines data from three pages:
    - Search Results (basic info)
    - Case Detail (parties, originating court, full caption)
    - Document List (filed documents)
    """

    # === Identifiers ===
    case_number: str
    """NYSCEF case number (e.g., '2024-00003')"""

    court: str
    """Court name (e.g., 'Appellate Division - 1st Dept')"""

    iapps_internal_docket_id: str | None = None
    """NYSCEF internal docket ID (base64-encoded, from URL docketId param)"""

    # === Case info ===
    short_caption: str | None = None
    """Short caption (e.g., 'AC 31, LLC v. Melissa Fawer et al')"""

    full_caption: str | None = None
    """Full caption with all parties"""

    case_type: str | None = None
    """Case type (e.g., 'Civil Action - General')"""

    efiling_status: str | None = None
    """eFiling status (e.g., 'Partial Participation Recorded')"""

    case_status: str | None = None
    """Case status from search results"""

    received_date: date | None = None
    """Date case was received/filed in NYSCEF"""

    # === Originating court info (appellate cases) ===
    originating_court_index: str | None = None
    """Index number from court of original instance (e.g., '850250/2017')"""

    originating_court_name: str | None = None
    """Court of original instance (e.g., 'New York Supreme Civil')"""

    originating_court_judge: str | None = None
    """Judge from court of original instance"""

    order_appealing_from_date: date | None = None
    """Date of order being appealed"""

    notice_of_appeal_date: date | None = None
    """Date of notice of appeal"""

    order_entered_date: date | None = None
    """Date order was entered"""

    notice_of_appeal_filed_date: date | None = None
    """Date notice of appeal was filed"""

    requested_argument_time: str | None = None
    """Requested argument time (e.g., 'Appellant :15 / Respondent :15')"""

    # === Parties ===
    parties: list[NYSCEFParty] = []
    """All parties in the case with their attorneys"""

    # === Documents ===
    documents: list[NYSCEFDocketEntry] = []
    """All documents filed in the case"""

    # === Metadata ===
    source_url: str | None = None
    """URL of the case detail page"""
