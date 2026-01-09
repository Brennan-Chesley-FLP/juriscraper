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
_domain_counts_cache: dict | None = None
_domain_alias_map: dict | None = None


def is_pacer_domain(domain: str) -> bool:
    """Check if a domain is a PACER/uscourts.gov domain."""
    return domain.endswith("uscourts.gov") or ".uscourts.gov" in domain


def get_domain_counts(app: Sphinx) -> dict[str, int]:
    """Count unique domains from courts.toml, split by PACER vs non-PACER.

    Returns dict with keys: 'total', 'pacer', 'non_pacer'
    """
    global _domain_counts_cache
    if _domain_counts_cache is not None:
        return _domain_counts_cache

    courts_toml = Path(app.srcdir).parent / "data" / "courts.toml"
    if not courts_toml.exists():
        _logger.warning(f"courts.toml not found at {courts_toml}")
        _domain_counts_cache = {"total": 0, "pacer": 0, "non_pacer": 0}
        return _domain_counts_cache

    with open(courts_toml, "rb") as f:
        data = tomllib.load(f)

    pacer_domains = set()
    non_pacer_domains = set()

    for court_data in data.get("courts", {}).values():
        if url := court_data.get("court_url"):
            parsed = urlparse(url)
            if parsed.netloc:
                domain = parsed.netloc
                if is_pacer_domain(domain):
                    pacer_domains.add(domain)
                else:
                    non_pacer_domains.add(domain)

    _domain_counts_cache = {
        "total": len(pacer_domains) + len(non_pacer_domains),
        "pacer": len(pacer_domains),
        "non_pacer": len(non_pacer_domains),
    }
    return _domain_counts_cache


def get_total_domains(app: Sphinx) -> int:
    """Count unique domains from courts.toml (for backward compatibility)."""
    return get_domain_counts(app)["total"]


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


def get_domain_alias_map(app: Sphinx) -> dict[str, str]:
    """Build a mapping from domain aliases to canonical domains.

    Returns dict mapping alias domain -> canonical domain from reports.
    """
    global _domain_alias_map
    if _domain_alias_map is not None:
        return _domain_alias_map

    reports = get_reports(app)
    _domain_alias_map = {}

    for domain, report in reports.items():
        meta = report.get("meta", {})
        aliases = meta.get("domain_aliases", [])
        for alias in aliases:
            _domain_alias_map[alias] = domain

    return _domain_alias_map


def resolve_domain(app: Sphinx, domain: str) -> str | None:
    """Resolve a domain to its canonical form if an alias exists.

    Returns the canonical domain if found in reports or aliases, else None.
    """
    reports = get_reports(app)
    if domain in reports:
        return domain

    alias_map = get_domain_alias_map(app)
    return alias_map.get(domain)


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
        domain_counts = get_domain_counts(self.env.app)
        total_domains = domain_counts["total"]
        pacer_total = domain_counts["pacer"]
        non_pacer_total = domain_counts["non_pacer"]

        # Split completed reports by PACER vs non-PACER
        pacer_completed = 0
        non_pacer_completed = 0
        priority_counts: dict[str, int] = {}

        for domain, report in reports.items():
            if is_pacer_domain(domain):
                pacer_completed += 1
            else:
                non_pacer_completed += 1

            priority = report.get("research_notes", {}).get(
                "priority", "unknown"
            )
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        completed = len(reports)
        pct = (completed / total_domains * 100) if total_domains > 0 else 0

        # Calculate percentages for each category
        pacer_pct = (
            (pacer_completed / pacer_total * 100) if pacer_total > 0 else 0
        )
        non_pacer_pct = (
            (non_pacer_completed / non_pacer_total * 100)
            if non_pacer_total > 0
            else 0
        )

        # Create container
        container = nodes.container()

        # Overall progress summary
        para = nodes.paragraph()
        para += nodes.strong(text="Overall Progress: ")
        para += nodes.Text(
            f"{completed} of {total_domains} domains researched ({pct:.1f}%)"
        )
        container += para

        # Non-PACER (State Courts) progress
        para_state = nodes.paragraph()
        para_state += nodes.strong(text="State Courts: ")
        para_state += nodes.Text(
            f"{non_pacer_completed} of {non_pacer_total} "
            f"({non_pacer_pct:.1f}%) - "
            f"{non_pacer_total - non_pacer_completed} remaining"
        )
        container += para_state

        # PACER (Federal Courts) progress
        para_pacer = nodes.paragraph()
        para_pacer += nodes.strong(text="Federal (PACER): ")
        para_pacer += nodes.Text(
            f"{pacer_completed} of {pacer_total} "
            f"({pacer_pct:.1f}%) - "
            f"{pacer_total - pacer_completed} remaining"
        )
        container += para_pacer

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


def get_courts_by_domain(app: Sphinx) -> dict[str, list[dict]]:
    """Get all courts grouped by domain from courts.toml.

    Returns dict mapping domain -> list of court data dicts
    """
    courts_toml = Path(app.srcdir).parent / "data" / "courts.toml"
    if not courts_toml.exists():
        return {}

    with open(courts_toml, "rb") as f:
        data = tomllib.load(f)

    domain_courts: dict[str, list[dict]] = {}

    for court_id, court_data in data.get("courts", {}).items():
        if url := court_data.get("court_url"):
            parsed = urlparse(url)
            if parsed.netloc:
                domain = parsed.netloc
                if domain not in domain_courts:
                    domain_courts[domain] = []
                court_info = dict(court_data)
                court_info["court_id"] = court_id
                domain_courts[domain].append(court_info)

    return domain_courts


def get_court_counts(app: Sphinx) -> dict[str, int]:
    """Count total courts from courts.toml, split by PACER vs non-PACER.

    Returns dict with keys: 'total', 'pacer', 'non_pacer', 'no_url'
    """
    courts_toml = Path(app.srcdir).parent / "data" / "courts.toml"
    if not courts_toml.exists():
        return {"total": 0, "pacer": 0, "non_pacer": 0, "no_url": 0}

    with open(courts_toml, "rb") as f:
        data = tomllib.load(f)

    pacer_courts = 0
    non_pacer_courts = 0
    no_url_courts = 0

    for court_data in data.get("courts", {}).values():
        if url := court_data.get("court_url"):
            parsed = urlparse(url)
            if parsed.netloc:
                if is_pacer_domain(parsed.netloc):
                    pacer_courts += 1
                else:
                    non_pacer_courts += 1
            else:
                no_url_courts += 1
        else:
            no_url_courts += 1

    return {
        "total": pacer_courts + non_pacer_courts + no_url_courts,
        "pacer": pacer_courts,
        "non_pacer": non_pacer_courts,
        "no_url": no_url_courts,
    }


class SiteReportAnalyticsDirective(SphinxDirective):
    """Directive to display comprehensive analytics for site reports.

    Generates statistics about:
    - URL validity (url_is_current field)
    - Scraper coverage
    - Subscription availability
    - Technical characteristics (JS required, has API, etc.)
    - Content availability
    - Courts without site reports

    Usage::

        .. site-report-analytics::
    """

    has_content = False
    required_arguments = 0
    optional_arguments = 0

    def run(self) -> list[nodes.Node]:
        """Generate comprehensive analytics."""
        reports = get_reports(self.env.app)
        domain_counts = get_domain_counts(self.env.app)
        court_counts = get_court_counts(self.env.app)
        courts_by_domain = get_courts_by_domain(self.env.app)

        # Filter to non-PACER reports only
        non_pacer_reports = {
            d: r for d, r in reports.items() if not is_pacer_domain(d)
        }

        # Filter courts_by_domain to non-PACER only
        non_pacer_courts_by_domain = {
            d: courts
            for d, courts in courts_by_domain.items()
            if not is_pacer_domain(d)
        }

        result: list[nodes.Node] = []

        # Summary section (domains and courts)
        result.extend(
            self._summary_section(
                non_pacer_reports,
                domain_counts,
                court_counts,
                non_pacer_courts_by_domain,
            )
        )

        # URL validity section
        result.extend(self._url_validity_section(non_pacer_reports))

        # Scraper coverage section (now includes court counts)
        result.extend(
            self._scraper_section(
                non_pacer_reports, non_pacer_courts_by_domain
            )
        )

        # Subscription availability section
        result.extend(self._subscription_section(non_pacer_reports))

        # Technical characteristics section
        result.extend(self._technical_section(non_pacer_reports))

        # Content availability section
        result.extend(self._content_section(non_pacer_reports))

        # Missing reports section
        result.extend(
            self._missing_reports_section(
                non_pacer_reports, courts_by_domain, domain_counts
            )
        )

        return result

    def _create_section(
        self, title: str, content: list[nodes.Node]
    ) -> list[nodes.Node]:
        """Create a section with title and content."""
        result: list[nodes.Node] = []
        result.append(nodes.rubric(text=title))
        result.extend(content)
        return result

    def _summary_section(
        self,
        reports: dict[str, dict],
        domain_counts: dict[str, int],
        court_counts: dict[str, int],
        courts_by_domain: dict[str, list[dict]],
    ) -> list[nodes.Node]:
        """Generate summary statistics for both domains and courts."""
        # Get alias map for resolving old domains
        alias_map = get_domain_alias_map(self.env.app)

        # Domain stats - count domains covered (directly or via alias)
        non_pacer_domains = domain_counts["non_pacer"]
        reported_domains = set(reports.keys())
        # Count how many courts.toml domains are covered
        covered_domain_count = 0
        for domain in courts_by_domain:
            if is_pacer_domain(domain):
                continue
            if domain in reported_domains or domain in alias_map:
                covered_domain_count += 1

        domain_pct = (
            (covered_domain_count / non_pacer_domains * 100)
            if non_pacer_domains > 0
            else 0
        )

        # Court stats - count courts covered by completed reports
        total_non_pacer_courts = court_counts["non_pacer"]
        courts_with_no_url = court_counts["no_url"]

        # Count courts covered by completed domain reports (including aliases)
        courts_covered = 0
        for domain, courts in courts_by_domain.items():
            if is_pacer_domain(domain):
                continue
            if domain in reported_domains or domain in alias_map:
                courts_covered += len(courts)

        court_pct = (
            (courts_covered / total_non_pacer_courts * 100)
            if total_non_pacer_courts > 0
            else 0
        )

        content: list[nodes.Node] = []

        # Create summary table
        table = nodes.table()
        tgroup = nodes.tgroup(cols=4)
        table += tgroup

        tgroup += nodes.colspec(colwidth=25)
        tgroup += nodes.colspec(colwidth=20)
        tgroup += nodes.colspec(colwidth=20)
        tgroup += nodes.colspec(colwidth=15)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Metric", "Researched", "Total", "Coverage"]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        # Domains row
        row1 = nodes.row()
        tbody += row1
        row1 += nodes.entry("", nodes.paragraph(text="Domains"))
        row1 += nodes.entry(
            "", nodes.paragraph(text=str(covered_domain_count))
        )
        row1 += nodes.entry("", nodes.paragraph(text=str(non_pacer_domains)))
        row1 += nodes.entry("", nodes.paragraph(text=f"{domain_pct:.1f}%"))

        # Courts row
        row2 = nodes.row()
        tbody += row2
        row2 += nodes.entry("", nodes.paragraph(text="Courts"))
        row2 += nodes.entry("", nodes.paragraph(text=str(courts_covered)))
        row2 += nodes.entry(
            "", nodes.paragraph(text=str(total_non_pacer_courts))
        )
        row2 += nodes.entry("", nodes.paragraph(text=f"{court_pct:.1f}%"))

        content.append(table)

        # Note about courts without URLs
        if courts_with_no_url > 0:
            note = nodes.paragraph()
            note += nodes.emphasis(
                text=f"Note: {courts_with_no_url} courts in courts.toml "
                f"have no court_url defined."
            )
            content.append(note)

        return content

    def _url_validity_section(
        self, reports: dict[str, dict]
    ) -> list[nodes.Node]:
        """Generate URL validity statistics."""
        current = 0
        outdated = 0
        unknown = 0
        has_alternates = 0

        for report in reports.values():
            coverage = report.get("coverage", {})
            url_current = coverage.get("url_is_current")
            if url_current is True:
                current += 1
            elif url_current is False:
                outdated += 1
            else:
                unknown += 1

            alternate_urls = coverage.get("alternate_urls", [])
            if alternate_urls:
                has_alternates += 1

        content: list[nodes.Node] = []

        # Create a bullet list
        bullet_list = nodes.bullet_list()

        item1 = nodes.list_item()
        item1 += nodes.paragraph(text=f"URLs confirmed current: {current}")
        bullet_list += item1

        item2 = nodes.list_item()
        item2 += nodes.paragraph(text=f"URLs outdated/redirecting: {outdated}")
        bullet_list += item2

        item3 = nodes.list_item()
        item3 += nodes.paragraph(text=f"URL status unknown: {unknown}")
        bullet_list += item3

        item4 = nodes.list_item()
        item4 += nodes.paragraph(
            text=f"Sites with alternate URLs documented: {has_alternates}"
        )
        bullet_list += item4

        content.append(bullet_list)

        return self._create_section("URL Validity", content)

    def _scraper_section(
        self,
        reports: dict[str, dict],
        courts_by_domain: dict[str, list[dict]],
    ) -> list[nodes.Node]:
        """Generate scraper coverage statistics for both domains and courts."""
        # Domain-level stats
        domains_with_scraper = 0
        domains_covers_opinions = 0
        domains_covers_oral_args = 0
        domains_covers_dockets = 0
        domains_no_scraper = 0

        # Court-level stats
        courts_with_scraper = 0
        courts_covers_opinions = 0
        courts_covers_oral_args = 0
        courts_covers_dockets = 0
        courts_no_scraper = 0

        for domain, report in reports.items():
            existing = report.get("existing_scraper", {})
            court_count = len(courts_by_domain.get(domain, []))

            if existing.get("has_scraper"):
                domains_with_scraper += 1
                courts_with_scraper += court_count
                if existing.get("covers_opinions"):
                    domains_covers_opinions += 1
                    courts_covers_opinions += court_count
                if existing.get("covers_oral_arguments"):
                    domains_covers_oral_args += 1
                    courts_covers_oral_args += court_count
                if existing.get("covers_dockets"):
                    domains_covers_dockets += 1
                    courts_covers_dockets += court_count
            else:
                domains_no_scraper += 1
                courts_no_scraper += court_count

        content: list[nodes.Node] = []

        # Create table comparing domains vs courts
        table = nodes.table()
        tgroup = nodes.tgroup(cols=3)
        table += tgroup

        tgroup += nodes.colspec(colwidth=40)
        tgroup += nodes.colspec(colwidth=20)
        tgroup += nodes.colspec(colwidth=20)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Metric", "Domains", "Courts"]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        stats = [
            (
                "With existing scrapers",
                domains_with_scraper,
                courts_with_scraper,
            ),
            ("Without scrapers", domains_no_scraper, courts_no_scraper),
            (
                "Opinions coverage",
                domains_covers_opinions,
                courts_covers_opinions,
            ),
            (
                "Oral arguments coverage",
                domains_covers_oral_args,
                courts_covers_oral_args,
            ),
            (
                "Dockets coverage",
                domains_covers_dockets,
                courts_covers_dockets,
            ),
        ]

        for label, domain_count, court_count in stats:
            row = nodes.row()
            tbody += row
            row += nodes.entry("", nodes.paragraph(text=label))
            row += nodes.entry("", nodes.paragraph(text=str(domain_count)))
            row += nodes.entry("", nodes.paragraph(text=str(court_count)))

        content.append(table)

        return self._create_section("Scraper Coverage", content)

    def _subscription_section(
        self, reports: dict[str, dict]
    ) -> list[nodes.Node]:
        """Generate subscription availability statistics."""
        has_subscription = 0
        subscription_types: dict[str, int] = {}

        for report in reports.values():
            coverage = report.get("coverage", {})
            if coverage.get("has_subscription"):
                has_subscription += 1
                sub_type = coverage.get("subscription_type", "unknown")
                if sub_type:
                    subscription_types[sub_type] = (
                        subscription_types.get(sub_type, 0) + 1
                    )

        content: list[nodes.Node] = []
        bullet_list = nodes.bullet_list()

        item1 = nodes.list_item()
        item1 += nodes.paragraph(
            text=f"Sites offering update subscriptions: {has_subscription}"
        )
        bullet_list += item1

        if subscription_types:
            item2 = nodes.list_item()
            item2 += nodes.paragraph(text="Subscription types:")
            sub_list = nodes.bullet_list()
            for sub_type, count in sorted(subscription_types.items()):
                sub_item = nodes.list_item()
                sub_item += nodes.paragraph(text=f"{sub_type}: {count}")
                sub_list += sub_item
            item2 += sub_list
            bullet_list += item2

        content.append(bullet_list)

        return self._create_section("Update Subscriptions", content)

    def _technical_section(self, reports: dict[str, dict]) -> list[nodes.Node]:
        """Generate technical characteristics statistics."""
        requires_js = 0
        has_api = 0
        has_captcha = 0
        requires_signup = 0
        requires_payment = 0
        bulk_download = 0
        platforms: dict[str, int] = {}

        for report in reports.values():
            tech = report.get("technical", {})
            access = report.get("access", {})

            if tech.get("requires_javascript"):
                requires_js += 1
            if tech.get("has_api"):
                has_api += 1
            if tech.get("bulk_download_available"):
                bulk_download += 1
            if access.get("has_captcha"):
                has_captcha += 1
            if access.get("requires_signup"):
                requires_signup += 1
            if access.get("requires_payment"):
                requires_payment += 1

            platform = tech.get("platform", "")
            if platform:
                platforms[platform] = platforms.get(platform, 0) + 1

        total = len(reports)
        content: list[nodes.Node] = []

        # Create table for technical stats
        table = nodes.table()
        tgroup = nodes.tgroup(cols=3)
        table += tgroup

        tgroup += nodes.colspec(colwidth=40)
        tgroup += nodes.colspec(colwidth=15)
        tgroup += nodes.colspec(colwidth=15)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Characteristic", "Count", "Percentage"]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        stats = [
            ("Requires JavaScript", requires_js),
            ("Has documented API", has_api),
            ("Offers bulk downloads", bulk_download),
            ("Has CAPTCHA", has_captcha),
            ("Requires signup/login", requires_signup),
            ("Requires payment", requires_payment),
        ]

        for label, count in stats:
            row = nodes.row()
            tbody += row
            row += nodes.entry("", nodes.paragraph(text=label))
            row += nodes.entry("", nodes.paragraph(text=str(count)))
            pct = (count / total * 100) if total > 0 else 0
            row += nodes.entry("", nodes.paragraph(text=f"{pct:.1f}%"))

        content.append(table)

        # Platform breakdown if we have data
        if platforms:
            para = nodes.paragraph()
            para += nodes.strong(text="Platforms detected: ")
            platform_parts = [
                f"{p} ({c})"
                for p, c in sorted(platforms.items(), key=lambda x: -x[1])[:5]
            ]
            para += nodes.Text(", ".join(platform_parts))
            content.append(para)

        return self._create_section("Technical Characteristics", content)

    def _content_section(self, reports: dict[str, dict]) -> list[nodes.Node]:
        """Generate content availability statistics."""
        # Track availability of key content types
        content_stats: dict[str, dict[str, int]] = {}
        key_types = [
            "opinions",
            "oral_arguments",
            "dockets",
            "docket_entries",
            "parties",
            "attorneys",
        ]

        for content_type in key_types:
            content_stats[content_type] = {
                "available": 0,
                "partial": 0,
                "unavailable": 0,
                "unknown": 0,
            }

        for report in reports.values():
            c = report.get("content", {})
            for content_type in key_types:
                type_data = c.get(content_type, {})
                status = type_data.get("status", "unknown")
                if status in content_stats[content_type]:
                    content_stats[content_type][status] += 1

        content: list[nodes.Node] = []

        # Create table
        table = nodes.table()
        tgroup = nodes.tgroup(cols=5)
        table += tgroup

        for _ in range(5):
            tgroup += nodes.colspec(colwidth=20)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in [
            "Content Type",
            "Available",
            "Partial",
            "Unavailable",
            "Unknown",
        ]:
            header_row += nodes.entry("", nodes.paragraph(text=header))

        # Body
        tbody = nodes.tbody()
        tgroup += tbody

        for content_type in key_types:
            stats = content_stats[content_type]
            row = nodes.row()
            tbody += row

            name = content_type.replace("_", " ").title()
            row += nodes.entry("", nodes.paragraph(text=name))
            row += nodes.entry(
                "", nodes.paragraph(text=str(stats["available"]))
            )
            row += nodes.entry("", nodes.paragraph(text=str(stats["partial"])))
            row += nodes.entry(
                "", nodes.paragraph(text=str(stats["unavailable"]))
            )
            row += nodes.entry("", nodes.paragraph(text=str(stats["unknown"])))

        content.append(table)

        return self._create_section("Content Availability", content)

    def _missing_reports_section(
        self,
        reports: dict[str, dict],
        courts_by_domain: dict[str, list[dict]],
        domain_counts: dict[str, int],
    ) -> list[nodes.Node]:
        """Generate list of state court domains without reports."""
        # Find non-PACER domains that don't have reports (including aliases)
        reported_domains = set(reports.keys())
        alias_map = get_domain_alias_map(self.env.app)
        missing_domains: list[tuple[str, int, str]] = []

        for domain, courts in courts_by_domain.items():
            if is_pacer_domain(domain):
                continue
            # Check if domain is covered directly or via alias
            if domain in reported_domains or domain in alias_map:
                continue
            # Get jurisdiction(s) for this domain
            jurisdictions = {c.get("jurisdiction", "?") for c in courts}
            jurisdiction_str = ", ".join(sorted(jurisdictions))
            missing_domains.append((domain, len(courts), jurisdiction_str))

        # Sort by number of courts (most courts first)
        missing_domains.sort(key=lambda x: (-x[1], x[0]))

        content: list[nodes.Node] = []

        missing_count = len(missing_domains)
        missing_courts = sum(
            court_count for _, court_count, _ in missing_domains
        )

        para = nodes.paragraph()
        para += nodes.Text(
            f"{missing_count} state court domains without research reports "
            f"(representing {missing_courts} courts):"
        )
        content.append(para)

        if missing_domains:
            # Show top 20 by court count
            table = nodes.table()
            tgroup = nodes.tgroup(cols=3)
            table += tgroup

            tgroup += nodes.colspec(colwidth=50)
            tgroup += nodes.colspec(colwidth=15)
            tgroup += nodes.colspec(colwidth=20)

            # Header
            thead = nodes.thead()
            tgroup += thead
            header_row = nodes.row()
            thead += header_row
            for header in ["Domain", "Courts", "Jurisdiction"]:
                header_row += nodes.entry("", nodes.paragraph(text=header))

            # Body (limit to 20)
            tbody = nodes.tbody()
            tgroup += tbody

            for domain, court_count, jurisdiction in missing_domains[:20]:
                row = nodes.row()
                tbody += row
                row += nodes.entry("", nodes.paragraph(text=domain))
                row += nodes.entry("", nodes.paragraph(text=str(court_count)))
                row += nodes.entry("", nodes.paragraph(text=jurisdiction))

            content.append(table)

            if len(missing_domains) > 20:
                note = nodes.paragraph()
                note += nodes.emphasis(
                    text=f"... and {len(missing_domains) - 20} more domains"
                )
                content.append(note)

        return self._create_section(
            "State Court Domains Without Reports", content
        )


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
        tgroup = nodes.tgroup(cols=4)
        table += tgroup

        tgroup += nodes.colspec(colwidth=25)
        tgroup += nodes.colspec(colwidth=12)
        tgroup += nodes.colspec(colwidth=40)
        tgroup += nodes.colspec(colwidth=23)

        # Header
        thead = nodes.thead()
        tgroup += thead
        header_row = nodes.row()
        thead += header_row
        for header in ["Content Type", "Status", "Notes", "Examples"]:
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

        # Example URLs
        example_urls = content_data.get("example_urls", [])
        urls_cell = nodes.entry()
        if example_urls:
            url_list = nodes.bullet_list()
            for url in example_urls[:3]:  # Limit to 3
                item = nodes.list_item()
                para = nodes.paragraph()
                # Truncate display text but keep full URL in link
                display = url if len(url) <= 40 else url[:37] + "..."
                para += nodes.reference("", display, refuri=url)
                item += para
                url_list += item
            urls_cell += url_list
        else:
            urls_cell += nodes.paragraph(text="-")
        row += urls_cell

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
    domain_counts = get_domain_counts(app)
    total_domains = domain_counts["total"]
    pacer_total = domain_counts["pacer"]
    non_pacer_total = domain_counts["non_pacer"]

    # Split completed reports by PACER vs non-PACER
    pacer_completed = sum(1 for d in reports if is_pacer_domain(d))
    non_pacer_completed = len(reports) - pacer_completed

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

**{completed}** of **{total_domains}** total domains researched ({pct:.1f}%)

- **State Courts:** {non_pacer_completed} of {non_pacer_total} ({non_pacer_total - non_pacer_completed} remaining)
- **Federal (PACER):** {pacer_completed} of {pacer_total} ({pacer_total - pacer_completed} remaining)

For detailed statistics about state court sites, see the :doc:`statistics` page.

Completed Reports
-----------------

.. site-report-list::

"""

    # Always include statistics page in toctree
    toctree_content = "statistics"
    if toctree_str:
        toctree_content += f"\n   {toctree_str}"

    index_content += f"""
.. toctree::
   :maxdepth: 1
   :hidden:

   {toctree_content}
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
    app.add_directive("site-report-analytics", SiteReportAnalyticsDirective)

    # Register event handler to generate pages
    app.connect("builder-inited", generate_site_report_pages)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
