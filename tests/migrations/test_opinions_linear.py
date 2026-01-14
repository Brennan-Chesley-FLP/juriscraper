"""Migration tests comparing OpinionSiteLinear scrapers with BaseScraper implementations.

This module provides a framework for verifying that new BaseScraper implementations
produce equivalent results to their legacy OpinionSiteLinear counterparts.

To add a new scraper pair for testing:
1. Create a ScraperPairConfig subclass (see ConnScraperConfig for example)
2. Implement get_params() - returns (old_kwargs, new_params) for a date range
3. Implement transform_new_to_old() - converts new results to old format
4. Add the config instance to SCRAPER_PAIRS list

Usage:
    # Run all migration tests (skipped by default, requires explicit opt-in)
    RUN_MIGRATION_TESTS=1 pytest tests/migrations/test_opinions_linear.py -v

    # Run a specific scraper pair
    RUN_MIGRATION_TESTS=1 pytest tests/migrations/test_opinions_linear.py -v -k "conn"

Note: These tests hit live court websites and may take significant time to run.
They are skipped by default to avoid network calls during regular test runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    pass


# =============================================================================
# Framework Types
# =============================================================================


@dataclass
class OldScraperResult:
    """Normalized result from an OpinionSiteLinear scraper.

    This represents a single case/opinion from the old scraper format.
    """

    name: str
    url: str
    date_filed: date
    docket: str
    status: str = "Published"
    date_filed_is_approximate: bool = False
    judge: str | None = None
    citation: str | None = None

    def __eq__(self, other: object) -> bool:
        """Compare results, allowing for minor differences.

        Normalizes:
        - Whitespace in text fields
        - Docket to use only primary docket (first in comma-separated list)
        - Opinion types to base category (Concurrence, Dissent, majority)
        """
        if not isinstance(other, OldScraperResult):
            return NotImplemented

        def normalize(s: str) -> str:
            return " ".join(s.split())

        def normalize_docket(s: str) -> str:
            """Get primary docket only (first in comma-separated list)."""
            return normalize(s).split(",")[0].strip()

        def normalize_name(s: str) -> str:
            """Normalize name and simplify opinion type annotations."""
            import re

            name = normalize(s)
            # Replace complex opinion types with base types
            # "First Concurrence" -> "Concurrence", "Concurrence & Dissent" -> "Concurrence"
            name = re.sub(
                r"\((?:First |Second |Third )?Concurrence(?: & Dissent)?\)",
                "(Concurrence)",
                name,
            )
            name = re.sub(
                r"\((?:First |Second |Third )?Dissent\)", "(Dissent)", name
            )
            return name

        return (
            normalize_name(self.name) == normalize_name(other.name)
            and self.url == other.url
            and normalize_docket(self.docket) == normalize_docket(other.docket)
            and self.date_filed == other.date_filed
        )

    def __hash__(self) -> int:
        import re

        def normalize(s: str) -> str:
            return " ".join(s.split())

        def normalize_docket(s: str) -> str:
            return normalize(s).split(",")[0].strip()

        def normalize_name(s: str) -> str:
            name = normalize(s)
            name = re.sub(
                r"\((?:First |Second |Third )?Concurrence(?: & Dissent)?\)",
                "(Concurrence)",
                name,
            )
            name = re.sub(
                r"\((?:First |Second |Third )?Dissent\)", "(Dissent)", name
            )
            return name

        return hash(
            (
                normalize_name(self.name),
                self.url,
                normalize_docket(self.docket),
                self.date_filed,
            )
        )


@dataclass
class ScraperPairConfig(ABC):
    """Configuration for a pair of old/new scrapers to compare.

    Subclass this to add a new scraper pair for migration testing.
    """

    name: str
    """Human-readable name for this scraper pair (e.g., 'conn')."""

    old_scraper_path: str
    """Import path for the old OpinionSiteLinear scraper."""

    new_scraper_path: str
    """Import path for the new BaseScraper implementation."""

    @abstractmethod
    def get_params(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[dict[str, Any], Any]:
        """Get parameters for both scrapers for the given date range.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            Tuple of:
            - kwargs dict for OpinionSiteLinear.__init__()
            - ScraperParams for BaseScraper
        """
        ...

    @abstractmethod
    def transform_new_to_old(
        self,
        new_results: list[Any],
    ) -> list[OldScraperResult]:
        """Transform results from new scraper to old scraper format.

        Args:
            new_results: List of ScrapedData objects from BaseScraper

        Returns:
            List of OldScraperResult objects matching old format
        """
        ...


# =============================================================================
# Connecticut Supreme Court Configuration
# =============================================================================


@dataclass
class ConnScraperConfig(ScraperPairConfig):
    """Configuration for Connecticut Supreme Court scraper pair."""

    name: str = "conn"
    old_scraper_path: str = "juriscraper.opinions.united_states.state.conn"
    new_scraper_path: str = "juriscraper.sd.state.connecticut.jud_ct_gov"

    def get_params(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[dict[str, Any], Any]:
        """Get params for Connecticut scrapers.

        The old scraper uses year-based backscraping, so we need to convert
        the date range to years.
        """
        from juriscraper.sd.state.connecticut.jud_ct_gov import ConnScraper

        # Old scraper uses year-based iteration
        old_kwargs = {
            "backscrape_start": str(start_date.year),
            "backscrape_end": str(end_date.year),
        }

        # New scraper uses date range on ConnOpinionCluster
        new_params = ConnScraper.params()
        # Disable other data types - only test opinions
        new_params.ConnOralArgument = None
        new_params.ConnDocket = None
        # Set date range filter
        new_params.ConnOpinionCluster.date_filed.gte = start_date
        new_params.ConnOpinionCluster.date_filed.lte = end_date
        # Only test Supreme Court (conn) to match old scraper
        new_params.ConnOpinionCluster.court_id.values = {"conn"}

        return old_kwargs, new_params

    def transform_new_to_old(
        self,
        new_results: list[Any],
    ) -> list[OldScraperResult]:
        """Transform ConnOpinionCluster results to old format.

        The old scraper yields one case per PDF, while the new scraper
        yields ConnOpinionCluster objects that may have multiple opinions.
        We need to flatten these to match.

        Format differences handled:
        - Old name: "State v. Doe " (trailing space, no docket)
        - New name: "SC20456 - State v. Doe" (includes docket prefix)
        - Old docket: " SC20456" (leading space)
        - New docket: "SC20456" (no leading space)
        - Old URL: http:// (old protocol)
        - New URL: https:// (new protocol)
        - Old opinion type: "(Concurrence)" capitalized
        - New opinion type: "(concurrence)" lowercase
        """
        import re

        from juriscraper.sd.state.connecticut.jud_ct_gov import (
            ConnOpinionCluster,
        )

        old_results = []

        for cluster in new_results:
            if not isinstance(cluster, ConnOpinionCluster):
                continue

            # Each opinion in the cluster becomes a separate old-style result
            for opinion in cluster.opinions:
                # Old format has leading space in docket
                docket = f" {cluster.docket_id}"

                # Extract case name without docket prefix (new format: "SC20456 - Case Name")
                # Old format is just "Case Name " (with trailing space)
                name = cluster.case_name
                # Remove docket prefix if present, including comma-separated dockets
                # e.g., "SC20456 - " or "SC20635, SC20637, SC20636 - "
                name = re.sub(
                    r"^(?:[A-Z]+\d+(?:,\s*)?)+[\s\r\n\t]*-\s*", "", name
                )
                # Normalize whitespace and add trailing space like old format
                name = " ".join(name.split()) + " "

                # Add opinion type with proper capitalization
                if opinion.type and opinion.type not in ("majority", "Lead"):
                    # Capitalize first letter to match old format
                    op_type = opinion.type.capitalize()
                    # Old format has extra space before paren: " (Concurrence)"
                    name = f"{name} ({op_type})"

                # Convert https:// to http:// to match old format
                url = opinion.download_url or ""
                if url.startswith("https://"):
                    url = "http://" + url[8:]

                old_results.append(
                    OldScraperResult(
                        name=name,
                        url=url,
                        date_filed=cluster.date_filed,
                        docket=docket,
                        status="Published",
                        date_filed_is_approximate=cluster.date_filed_is_approximate
                        or False,
                    )
                )

        return old_results


# =============================================================================
# Registry of Scraper Pairs
# =============================================================================

SCRAPER_PAIRS: list[ScraperPairConfig] = [
    ConnScraperConfig(),
]

# Build pytest parametrize IDs
SCRAPER_PAIR_IDS = [config.name for config in SCRAPER_PAIRS]


# =============================================================================
# Test Fixtures
# =============================================================================


def load_old_scraper(config: ScraperPairConfig, kwargs: dict) -> Any:
    """Load and initialize an OpinionSiteLinear scraper."""
    import importlib

    module = importlib.import_module(config.old_scraper_path)
    scraper_class = module.Site
    return scraper_class(**kwargs)


def load_new_scraper(config: ScraperPairConfig, params: Any) -> Any:
    """Load and initialize a BaseScraper."""
    import importlib

    # Parse module and class from path
    module_path = config.new_scraper_path
    module = importlib.import_module(module_path)

    # Get the scraper class (assumes it's named *Scraper)
    scraper_class = None
    for name in dir(module):
        if name.endswith("Scraper") and not name.startswith("_"):
            scraper_class = getattr(module, name)
            break

    if scraper_class is None:
        raise ValueError(f"No scraper class found in {module_path}")

    return scraper_class(params=params)


def run_old_scraper(scraper: Any) -> list[OldScraperResult]:
    """Run an OpinionSiteLinear scraper and collect results.

    Uses the backscrape mechanism to iterate through years/date ranges.
    """
    results = []

    # Use backscrape iteration if available
    if scraper.back_scrape_iterable:
        for item in scraper.back_scrape_iterable:
            scraper._download_backwards(item)
    else:
        # Fall back to single parse for current page
        scraper.parse()

    # Extract results from the cases list
    for case in scraper.cases:
        # Handle date conversion
        date_filed = case.get("date")
        if isinstance(date_filed, str):
            from juriscraper.lib.string_utils import convert_date_string

            date_filed = convert_date_string(date_filed)

        results.append(
            OldScraperResult(
                name=case.get("name", ""),
                url=case.get("url", ""),
                date_filed=date_filed,
                docket=case.get("docket", ""),
                status=case.get("status", scraper.status or "Published"),
                date_filed_is_approximate=case.get(
                    "date_filed_is_approximate", False
                ),
                judge=case.get("judge"),
                citation=case.get("citation"),
            )
        )

    return results


async def run_new_scraper(scraper: Any) -> list[Any]:
    """Run a BaseScraper and collect results."""
    from juriscraper.scraper_driver.driver.async_driver import AsyncDriver

    results: list[Any] = []

    async def on_data(data: Any) -> None:
        results.append(data)

    driver = AsyncDriver(scraper, on_data=on_data)
    await driver.run()

    return results


# =============================================================================
# Tests
# =============================================================================


def _should_skip_migration_tests() -> bool:
    """Determine if migration tests should be skipped.

    Migration tests are skipped unless the RUN_MIGRATION_TESTS env var is set.
    To run: RUN_MIGRATION_TESTS=1 pytest tests/migrations/ -v
    """
    import os

    return not os.environ.get("RUN_MIGRATION_TESTS")


@pytest.mark.migration
@pytest.mark.skipif(
    _should_skip_migration_tests(),
    reason="Migration test - set RUN_MIGRATION_TESTS=1 to run",
)
@pytest.mark.parametrize("config", SCRAPER_PAIRS, ids=SCRAPER_PAIR_IDS)
class TestOpinionsMigration:
    """Test that new BaseScraper produces equivalent results to old OpinionSiteLinear."""

    # Default test date range - a recent, limited period
    DEFAULT_START = date(2023, 1, 1)
    DEFAULT_END = date(2023, 12, 31)

    @pytest.mark.asyncio
    async def test_results_match(self, config: ScraperPairConfig) -> None:
        """Verify that old and new scrapers produce equivalent results.

        This test:
        1. Gets appropriate params for both scrapers
        2. Runs both scrapers against the same date range
        3. Transforms new results to old format
        4. Compares the results for equivalence
        """
        # Get params for both scrapers
        old_kwargs, new_params = config.get_params(
            self.DEFAULT_START, self.DEFAULT_END
        )

        # Load and run old scraper
        old_scraper = load_old_scraper(config, old_kwargs)
        old_results = run_old_scraper(old_scraper)

        # Load and run new scraper
        new_scraper = load_new_scraper(config, new_params)
        new_raw_results = await run_new_scraper(new_scraper)

        # Transform new results to old format
        new_results = config.transform_new_to_old(new_raw_results)

        # Compare results
        old_set = set(old_results)
        new_set = set(new_results)

        # Find differences
        only_in_old = old_set - new_set
        only_in_new = new_set - old_set

        # Report differences
        if only_in_old:
            print(f"\nResults only in OLD scraper ({len(only_in_old)}):")
            for r in sorted(
                only_in_old, key=lambda x: (x.date_filed, x.docket)
            ):
                print(f"  - {r.docket}: {r.name[:50]}... ({r.date_filed})")

        if only_in_new:
            print(f"\nResults only in NEW scraper ({len(only_in_new)}):")
            for r in sorted(
                only_in_new, key=lambda x: (x.date_filed, x.docket)
            ):
                print(f"  - {r.docket}: {r.name[:50]}... ({r.date_filed})")

        # Assert equivalence
        assert len(only_in_old) == 0, (
            f"Old scraper has {len(only_in_old)} extra results"
        )
        assert len(only_in_new) == 0, (
            f"New scraper has {len(only_in_new)} extra results"
        )

    @pytest.mark.asyncio
    async def test_result_counts_reasonable(
        self, config: ScraperPairConfig
    ) -> None:
        """Verify that both scrapers return a reasonable number of results.

        This is a sanity check to ensure the scrapers are actually working
        and not just returning empty results.
        """
        # Get params for both scrapers
        old_kwargs, new_params = config.get_params(
            self.DEFAULT_START, self.DEFAULT_END
        )

        # Load and run old scraper
        old_scraper = load_old_scraper(config, old_kwargs)
        old_results = run_old_scraper(old_scraper)

        # Load and run new scraper
        new_scraper = load_new_scraper(config, new_params)
        new_raw_results = await run_new_scraper(new_scraper)
        new_results = config.transform_new_to_old(new_raw_results)

        # Both should return at least some results
        assert len(old_results) > 0, "Old scraper returned no results"
        assert len(new_results) > 0, "New scraper returned no results"

        # Results should be within 20% of each other
        ratio = len(new_results) / len(old_results) if old_results else 0
        assert len(new_results) == len(old_results), (
            f"Result counts differ significantly: "
            f"old={len(old_results)}, new={len(new_results)} (ratio={ratio:.2f})"
        )
