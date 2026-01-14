#!/usr/bin/env python
"""CLI script to run OpinionSiteLinear scrapers with backscraping support.

Usage:
    # List all available OpinionSiteLinear scrapers
    python scripts/run_opinion_linear.py --list

    # Run a scraper with backscrape
    python scripts/run_opinion_linear.py \
        --scraper juriscraper.opinions.united_states.state.conn \
        --start 2023 \
        --end 2023 \
        --results output.jsonl

    # Run without backscrape (current data only)
    python scripts/run_opinion_linear.py \
        --scraper juriscraper.opinions.united_states.state.cal \
        --results output.jsonl
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def find_opinion_linear_scrapers() -> list[str]:
    """Find all OpinionSiteLinear scrapers in the opinions directory.

    Returns:
        List of module paths for scrapers that extend OpinionSiteLinear.
    """
    from juriscraper.OpinionSiteLinear import OpinionSiteLinear

    scrapers = []
    opinions_dir = Path(__file__).parent.parent / "juriscraper" / "opinions"

    for py_file in opinions_dir.rglob("*.py"):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue
        if "template" in py_file.name:
            continue

        # Build module path
        relative = py_file.relative_to(opinions_dir.parent.parent)
        module_path = str(relative.with_suffix("")).replace("/", ".")

        try:
            module = importlib.import_module(module_path)
            if hasattr(module, "Site"):
                site_class = module.Site
                if (
                    isinstance(site_class, type)
                    and issubclass(site_class, OpinionSiteLinear)
                    and site_class is not OpinionSiteLinear
                ):
                    scrapers.append(module_path)
        except Exception:
            # Skip modules that fail to import
            continue

    return sorted(scrapers)


def json_serializer(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (date | datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def run_scraper(
    module_path: str,
    backscrape_start: str | None,
    backscrape_end: str | None,
    results_path: str | None,
    limit: int | None,
) -> int:
    """Run a scraper and optionally save results.

    Args:
        module_path: Full module path to the scraper.
        backscrape_start: Start value for backscraping (format depends on scraper).
        backscrape_end: End value for backscraping (format depends on scraper).
        results_path: Path to save JSONL results.
        limit: Maximum number of items to scrape.

    Returns:
        Number of items scraped.
    """
    # Import the module
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        print(f"Error: Could not import {module_path}: {e}", file=sys.stderr)
        return 0

    if not hasattr(module, "Site"):
        print(
            f"Error: {module_path} does not have a Site class", file=sys.stderr
        )
        return 0

    results_file = None
    if results_path:
        results_file = open(results_path, "w")  # noqa: SIM115

    total_count = 0

    try:
        # Determine if we're backscraping or doing a regular scrape
        if backscrape_start or backscrape_end:
            # Backscrape mode
            site_for_iterable = module.Site(
                backscrape_start=backscrape_start,
                backscrape_end=backscrape_end,
            )

            if site_for_iterable.back_scrape_iterable is None:
                print(
                    f"Warning: {module_path} does not support backscraping",
                    file=sys.stderr,
                )
                # Fall back to regular scrape
                sites = [module.Site()]
            else:
                # Create sites from the backscrape iterable
                sites = []
                for item in site_for_iterable.back_scrape_iterable:
                    site = module.Site()
                    site._download_backwards(item)
                    sites.append(site)
        else:
            # Regular scrape (current data)
            sites = [module.Site()]

        for site in sites:
            site.parse()
            print(f"\n{site.court_id}: Found {len(site)} items")

            for _, item in enumerate(site):
                if limit and total_count >= limit:
                    print(f"\nReached limit of {limit} items")
                    break

                total_count += 1

                # Print summary
                case_name = item.get("case_names", "Unknown")
                docket = item.get("docket_numbers", "")
                print(f"  [{total_count}] {case_name[:60]}... ({docket})")

                # Write to results file
                if results_file:
                    results_file.write(
                        json.dumps(item, default=json_serializer) + "\n"
                    )

            if limit and total_count >= limit:
                break

    finally:
        if results_file:
            results_file.close()
            print(f"\nResults saved to {results_path}")

    return total_count


def main():
    parser = argparse.ArgumentParser(
        description="Run OpinionSiteLinear scrapers with backscraping support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all available scrapers
  python scripts/run_opinion_linear.py --list

  # Run Connecticut scraper for year 2023
  python scripts/run_opinion_linear.py \\
      --scraper juriscraper.opinions.united_states.state.conn \\
      --start 2023 --end 2023

  # Run California scraper (no backscrape, current data only)
  python scripts/run_opinion_linear.py \\
      --scraper juriscraper.opinions.united_states.state.cal \\
      --results cal_opinions.jsonl

  # Run with a limit on results
  python scripts/run_opinion_linear.py \\
      --scraper juriscraper.opinions.united_states.state.conn \\
      --start 2023 --end 2023 \\
      --results conn_2023.jsonl \\
      --limit 50

Note: The format of --start and --end depends on the scraper:
  - Some use years (e.g., 2023)
  - Some use dates (e.g., 2023-01-01)
  Check the scraper's make_backscrape_iterable() method for details.
        """,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available OpinionSiteLinear scrapers",
    )
    parser.add_argument(
        "--scraper",
        type=str,
        help="Full module path to the scraper (e.g., juriscraper.opinions.united_states.state.conn)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Backscrape start value (format depends on scraper)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="Backscrape end value (format depends on scraper)",
    )
    parser.add_argument(
        "--results",
        type=str,
        help="Path to save results as JSONL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of items to scrape",
    )

    args = parser.parse_args()

    if args.list:
        print("Discovering OpinionSiteLinear scrapers...\n")
        scrapers = find_opinion_linear_scrapers()
        print(f"Found {len(scrapers)} scrapers:\n")
        for scraper in scrapers:
            print(f"  {scraper}")
        return

    if not args.scraper:
        parser.error("--scraper is required unless using --list")

    print(f"Running scraper: {args.scraper}")
    if args.start or args.end:
        print(
            f"Backscrape range: {args.start or 'default'} to {args.end or 'default'}"
        )

    count = run_scraper(
        module_path=args.scraper,
        backscrape_start=args.start,
        backscrape_end=args.end,
        results_path=args.results,
        limit=args.limit,
    )

    print(f"\nTotal items scraped: {count}")


if __name__ == "__main__":
    main()
