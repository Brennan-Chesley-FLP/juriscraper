"""Sphinx extension for court site research reports.

This extension generates documentation from TOML site reports in
docs/data/site_reports/. It creates:

1. An index page showing all completed reports with progress tracking
2. Individual report pages rendered from the TOML data

Reports are named by domain (e.g., judicial.alabama.gov.toml) and
document the technical characteristics and available content for
court websites.
"""

from __future__ import annotations

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

# Cache for reports and domain counts
_reports_cache: dict | None = None
_domain_count_cache: int | None = None


def get_total_domains(app: Sphinx) -> int:
    """Count unique domains from courts.toml."""
    global _domain_count_cache
    if _domain_count_cache is not None:
        return _domain_count_cache

    courts_toml = Path(app.srcdir).parent / "data" / "courts.toml"
    if not courts_toml.exists():
        _logger.warning(f"courts.toml not found at {courts_toml}")
        _domain_count_cache = 0
        return 0

    with open(courts_toml, "rb") as f:
        data = tomllib.load(f)

    domains = set()
    for court_data in data.get("courts", {}).values():
        if url := court_data.get("court_url"):
            parsed = urlparse(url)
            if parsed.netloc:
                domains.add(parsed.netloc)

    _domain_count_cache = len(domains)
    return _domain_count_cache


def get_reports(app: Sphinx) -> dict[str, dict]:
    """Load and cache all site reports."""
    global _reports_cache
    if _reports_cache is not None:
        return _reports_cache

    reports_dir = Path(app.srcdir).parent / "data" / "site_reports"
    _reports_cache = {}

    if not reports_dir.exists():
        _logger.warning(f"Site reports directory not found at {reports_dir}")
        return _reports_cache

    for report_file in reports_dir.glob("*.toml"):
        if report_file.name.startswith("_"):
            continue  # Skip template

        try:
            with open(report_file, "rb") as f:
                report_data = tomllib.load(f)
                domain = report_data.get("meta", {}).get(
                    "domain", report_file.stem
                )
                _reports_cache[domain] = report_data
        except Exception as e:
            _logger.warning(f"Failed to load {report_file}: {e}")

    return _reports_cache


class SiteReportStatsDirective(SphinxDirective):
    """Directive to display site report progress statistics.

    Usage::

        .. site-report-stats::
    """

    has_content = False
    required_arguments = 0
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        """Generate statistics block."""
        reports = get_reports(self.env.app)
        total_domains = get_total_domains(self.env.app)
        completed = len(reports)
        remaining = total_domains - completed
        pct = (completed / total_domains * 100) if total_domains > 0 else 0

        # Count by priority
        priority_counts: dict[str, int] = {}
        for report in reports.values():
            priority = report.get("research_notes", {}).get(
                "priority", "unknown"
            )
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        # Create container
        container = nodes.container()

        # Progress summary
        para = nodes.paragraph()
        para += nodes.strong(text="Progress: ")
        para += nodes.Text(
            f"{completed} of {total_domains} domains researched ({pct:.1f}%)"
        )
        container += para

        # Remaining count
        para2 = nodes.paragraph()
        para2 += nodes.strong(text="Remaining: ")
        para2 += nodes.Text(f"{remaining} domains")
        container += para2

        # Priority breakdown if we have reports
        if priority_counts:
            para3 = nodes.paragraph()
            para3 += nodes.strong(text="By Priority: ")
            priority_parts = []
            for pri in ["high", "medium", "low", "skip"]:
                if pri in priority_counts:
                    priority_parts.append(f"{pri}: {priority_counts[pri]}")
            para3 += nodes.Text(", ".join(priority_parts))
            container += para3

        return [container]


class SiteReportListDirective(SphinxDirective):
    """Directive to list all completed site reports.

    Usage::

        .. site-report-list::
    """

    has_content = False
    required_arguments = 0
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        """Generate report list."""
        reports = get_reports(self.env.app)

        if not reports:
            return [nodes.paragraph(text="No site reports completed yet.")]

        # Create table
        table = nodes.table()
        tgroup = nodes.tgroup(cols=5)
        table += tgroup

        # Column specs
        for width in [40, 15, 15, 15, 15]:
            tgroup += nodes.colspec(colwidth=width)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Domain", "Courts", "Priority", "Complexity", "Date"]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        for domain in sorted(reports.keys()):
            report = reports[domain]
            meta = report.get("meta", {})
            notes = report.get("research_notes", {})

            row = nodes.row()
            tbody += row

            # Domain with link
            cell = nodes.entry()
            para = nodes.paragraph()
            ref = nodes.reference(
                "",
                domain,
                internal=True,
                refuri=f"{domain.replace('.', '_')}.html",
            )
            para += ref
            cell += para
            row += cell

            # Court count
            court_ids = meta.get("court_ids", [])
            row += nodes.entry("", nodes.paragraph(text=str(len(court_ids))))

            # Priority
            priority = notes.get("priority", "unknown")
            priority_cell = nodes.entry()
            priority_para = nodes.paragraph()
            # Add styling based on priority
            if priority == "high":
                priority_para += nodes.strong(text=priority)
            elif priority == "skip":
                priority_para += nodes.emphasis(text=priority)
            else:
                priority_para += nodes.Text(priority)
            priority_cell += priority_para
            row += priority_cell

            # Complexity
            complexity = notes.get("complexity", "unknown")
            row += nodes.entry("", nodes.paragraph(text=complexity))

            # Research date
            research_date = meta.get("research_date", "unknown")
            row += nodes.entry("", nodes.paragraph(text=research_date))

        return [table]


class SiteReportDetailDirective(SphinxDirective):
    """Directive to display a single site report in detail.

    Usage::

        .. site-report-detail:: judicial.alabama.gov
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        """Generate detailed report view."""
        domain = self.arguments[0]
        reports = get_reports(self.env.app)

        if domain not in reports:
            return [nodes.paragraph(text=f"Report for '{domain}' not found.")]

        report = reports[domain]
        result: list[nodes.Node] = []

        # Meta section
        meta = report.get("meta", {})
        result.append(self._section("Overview", self._meta_content(meta)))

        # Access section
        access = report.get("access", {})
        result.append(
            self._section(
                "Access & Authentication", self._access_content(access)
            )
        )

        # Technical section
        technical = report.get("technical", {})
        result.append(
            self._section(
                "Technical Details", self._technical_content(technical)
            )
        )

        # Robots section
        robots = report.get("robots", {})
        result.append(
            self._section(
                "Robots & Rate Limiting", self._robots_content(robots)
            )
        )

        # Content availability section
        content = report.get("content", {})
        result.append(
            self._section("Content Availability", self._content_table(content))
        )

        # Coverage section
        coverage = report.get("coverage", {})
        result.append(
            self._section(
                "Coverage & Freshness", self._coverage_content(coverage)
            )
        )

        # Existing scraper section
        existing = report.get("existing_scraper", {})
        result.append(
            self._section(
                "Existing Scrapers", self._existing_content(existing)
            )
        )

        # Research notes section
        notes = report.get("research_notes", {})
        result.append(
            self._section("Research Notes", self._notes_content(notes))
        )

        return result

    def _section(
        self, title: str, content: list[nodes.Node]
    ) -> nodes.container:
        """Create a section with title and content.

        Uses container instead of section to avoid Sphinx toctree issues
        with sections that don't have proper IDs.
        """
        container = nodes.container()
        container += nodes.rubric(text=title)
        container.extend(content)
        return container

    def _field_list(self, fields: list[tuple[str, Any]]) -> nodes.field_list:
        """Create a field list from name-value pairs."""
        field_list = nodes.field_list()
        for name, value in fields:
            if value in (None, "", [], {}):
                continue
            field = nodes.field()
            field += nodes.field_name(text=name)
            field_body = nodes.field_body()

            if isinstance(value, bool):
                text = "Yes" if value else "No"
                field_body += nodes.paragraph(text=text)
            elif isinstance(value, list):
                if value:
                    field_body += nodes.paragraph(
                        text=", ".join(str(v) for v in value)
                    )
            elif str(value).startswith("http"):
                para = nodes.paragraph()
                para += nodes.reference("", str(value), refuri=str(value))
                field_body += para
            else:
                field_body += nodes.paragraph(text=str(value))

            field += field_body
            field_list += field
        return field_list

    def _meta_content(self, meta: dict) -> list[nodes.Node]:
        """Generate meta section content."""
        fields = [
            ("Domain", meta.get("domain")),
            ("Court IDs", meta.get("court_ids")),
            ("Court Name", meta.get("court_name")),
            ("URL", meta.get("court_url")),
            ("Research Date", meta.get("research_date")),
            ("Researcher", meta.get("researcher")),
        ]
        return [self._field_list(fields)]

    def _access_content(self, access: dict) -> list[nodes.Node]:
        """Generate access section content."""
        fields = [
            ("Public Access", access.get("public_access")),
            ("Requires Signup", access.get("requires_signup")),
            ("Signup Method", access.get("signup_method")),
            ("Requires Payment", access.get("requires_payment")),
            ("Payment Details", access.get("payment_details")),
            ("Has Captcha", access.get("has_captcha")),
            ("Captcha Type", access.get("captcha_type")),
        ]
        return [self._field_list(fields)]

    def _technical_content(self, technical: dict) -> list[nodes.Node]:
        """Generate technical section content."""
        fields = [
            ("Requires JavaScript", technical.get("requires_javascript")),
            ("JavaScript Framework", technical.get("javascript_framework")),
            ("Platform", technical.get("platform")),
            ("Scope", technical.get("scope")),
            ("Has API", technical.get("has_api")),
            ("API Documented", technical.get("api_documented")),
            ("API URL", technical.get("api_url")),
            ("Bulk Download", technical.get("bulk_download_available")),
            ("Document Formats", technical.get("document_formats")),
            ("Auth Mechanism", technical.get("auth_mechanism")),
        ]
        return [self._field_list(fields)]

    def _robots_content(self, robots: dict) -> list[nodes.Node]:
        """Generate robots section content."""
        fields = [
            ("Has robots.txt", robots.get("has_robots_txt")),
            ("Allows Scraping", robots.get("allows_scraping")),
            ("Disallowed Paths", robots.get("disallowed_paths")),
            ("Crawl Delay (sec)", robots.get("crawl_delay_seconds")),
            ("Rate Limit Notice", robots.get("rate_limit_notice")),
            ("TOS Restrictions", robots.get("tos_restrictions")),
        ]
        return [self._field_list(fields)]

    def _content_table(self, content: dict) -> list[nodes.Node]:
        """Generate content availability table."""
        # Create table
        table = nodes.table()
        tgroup = nodes.tgroup(cols=3)
        table += tgroup

        tgroup += nodes.colspec(colwidth=30)
        tgroup += nodes.colspec(colwidth=15)
        tgroup += nodes.colspec(colwidth=55)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Content Type", "Status", "Notes"]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        # Priority content types to show first
        priority_types = [
            "opinions",
            "oral_arguments",
            "dockets",
            "docket_entries",
        ]

        # Show priority types first, then others
        shown = set()
        for content_type in priority_types:
            if content_type in content:
                self._add_content_row(
                    tbody, content_type, content[content_type]
                )
                shown.add(content_type)

        # Show remaining types that aren't "unknown" or "unavailable"
        for content_type, content_data in sorted(content.items()):
            if content_type in shown:
                continue
            status = content_data.get("status", "unknown")
            if status in ("available", "partial"):
                self._add_content_row(tbody, content_type, content_data)

        return [table]

    def _add_content_row(
        self, tbody: nodes.tbody, content_type: str, content_data: dict
    ) -> None:
        """Add a row to the content table."""
        row = nodes.row()
        tbody += row

        # Content type (formatted)
        name = content_type.replace("_", " ").title()
        row += nodes.entry("", nodes.paragraph(text=name))

        # Status with indicator
        status = content_data.get("status", "unknown")
        status_cell = nodes.entry()
        status_para = nodes.paragraph()
        if status == "available":
            status_para += nodes.Text("\u2714 ")  # Check mark
            status_para += nodes.Text(status)
        elif status == "partial":
            status_para += nodes.Text("\u25d0 ")  # Half circle
            status_para += nodes.Text(status)
        elif status == "unavailable":
            status_para += nodes.Text("\u2718 ")  # X mark
            status_para += nodes.Text(status)
        else:
            status_para += nodes.Text("? ")
            status_para += nodes.Text(status)
        status_cell += status_para
        row += status_cell

        # Notes (truncated if long)
        notes = content_data.get("notes", "")
        if len(notes) > 100:
            notes = notes[:97] + "..."
        row += nodes.entry("", nodes.paragraph(text=notes))

    def _coverage_content(self, coverage: dict) -> list[nodes.Node]:
        """Generate coverage section content."""
        fields = [
            ("Earliest Date", coverage.get("earliest_date")),
            ("Latest Date", coverage.get("latest_date")),
            ("Has Historical", coverage.get("has_historical")),
            ("Historical Notes", coverage.get("historical_notes")),
            ("Update Frequency", coverage.get("update_frequency")),
            ("Has Subscription", coverage.get("has_subscription")),
            ("Subscription Type", coverage.get("subscription_type")),
            ("Has Search", coverage.get("has_search")),
            ("Search Capabilities", coverage.get("search_capabilities")),
        ]
        return [self._field_list(fields)]

    def _existing_content(self, existing: dict) -> list[nodes.Node]:
        """Generate existing scraper section content."""
        fields = [
            ("Has Scraper", existing.get("has_scraper")),
            ("Modules", existing.get("scraper_modules")),
            ("Covers Opinions", existing.get("covers_opinions")),
            ("Covers Oral Args", existing.get("covers_oral_arguments")),
            ("Covers Dockets", existing.get("covers_dockets")),
            ("Known Issues", existing.get("known_issues")),
        ]
        return [self._field_list(fields)]

    def _notes_content(self, notes: dict) -> list[nodes.Node]:
        """Generate research notes section content."""
        result: list[nodes.Node] = []

        # Summary as block quote
        summary = notes.get("summary", "")
        if summary:
            block = nodes.block_quote()
            block += nodes.paragraph(text=summary.strip())
            result.append(block)

        fields = [
            ("Priority", notes.get("priority")),
            ("Priority Reasoning", notes.get("priority_reasoning")),
            ("Complexity", notes.get("complexity")),
            ("Complexity Reasoning", notes.get("complexity_reasoning")),
            ("Blockers", notes.get("blockers")),
        ]
        result.append(self._field_list(fields))

        return result


def generate_site_report_pages(app: Sphinx) -> None:
    """Generate site report RST pages.

    This runs during builder-inited to create the index and
    individual report pages.
    """
    reports = get_reports(app)
    total_domains = get_total_domains(app)

    # Create site_reports directory in source
    reports_dir = Path(app.srcdir) / "site_reports"
    reports_dir.mkdir(exist_ok=True)

    # Build toctree entries
    toctree_entries = []
    for domain in sorted(reports.keys()):
        safe_name = domain.replace(".", "_")
        toctree_entries.append(safe_name)

    toctree_str = "\n   ".join(toctree_entries) if toctree_entries else ""

    # Generate index page
    completed = len(reports)
    remaining = total_domains - completed
    pct = (completed / total_domains * 100) if total_domains > 0 else 0

    index_content = f""".. _site-reports:

Court Site Research Reports
===========================

This section documents research findings for court websites. Each report
covers the technical characteristics, available content, and scraping
considerations for a court domain.

Progress
--------

.. site-report-stats::

**{completed}** of **{total_domains}** domains researched ({pct:.1f}%)

{remaining} domains remaining.

Completed Reports
-----------------

.. site-report-list::

"""

    if toctree_str:
        index_content += f"""
.. toctree::
   :maxdepth: 1
   :hidden:

   {toctree_str}
"""

    (reports_dir / "index.rst").write_text(index_content)

    # Generate individual report pages
    for domain, report in reports.items():
        meta = report.get("meta", {})
        court_name = meta.get("court_name", domain)
        safe_name = domain.replace(".", "_")

        # Build title
        title = f"{domain}"
        underline = "=" * len(title)

        page_content = f""".. _site-report-{safe_name}:

{title}
{underline}

{court_name}

`Back to Reports Index <index.html>`_

.. site-report-detail:: {domain}
"""
        (reports_dir / f"{safe_name}.rst").write_text(page_content)


def setup(app: Sphinx) -> dict[str, Any]:
    """Set up the Sphinx extension."""
    # Register directives
    app.add_directive("site-report-stats", SiteReportStatsDirective)
    app.add_directive("site-report-list", SiteReportListDirective)
    app.add_directive("site-report-detail", SiteReportDetailDirective)

    # Register event handler to generate pages
    app.connect("builder-inited", generate_site_report_pages)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
