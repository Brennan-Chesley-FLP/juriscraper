#!/usr/bin/env python3
"""CLI for running scrapers with AsyncDriver.

A streamlined interface for running scrapers and exporting results.

Usage:
    # List available scrapers
    uv run python scripts/async_cli.py --list-scrapers

    # Run a scraper with default params
    uv run python scripts/async_cli.py --scraper NYSCEFScraper

    # Run with date range filter
    uv run python scripts/async_cli.py \\
        --scraper NYSCEFScraper \\
        --param "NYSCEFDocket.date_filed.gte=2025-01-01" \\
        --param "NYSCEFDocket.date_filed.lte=2025-01-07"

    # Run Connecticut Supreme Court opinions for 2023 only
    uv run python scripts/async_cli.py \\
        --scraper ConnScraper \\
        --disable ConnOralArgument \\
        --disable ConnDocket \\
        --param "ConnOpinionCluster.court_id.values=conn" \\
        --param "ConnOpinionCluster.date_filed.gte=2023-01-01" \\
        --param "ConnOpinionCluster.date_filed.lte=2023-12-31"

    # Run with max results and output file
    uv run python scripts/async_cli.py \\
        --scraper NYSCEFScraper \\
        --max-results 100 \\
        --results output.jsonl

    # Run with full module path
    uv run python scripts/async_cli.py \\
        --scraper juriscraper.sd.state.new_york.nyscef.scraper:NYSCEFScraper

    # Run with speculation control (limit pagination probing)
    # Auto-approve IDs < 10, then approve only 3 more requests at/above threshold
    uv run python scripts/async_cli.py \\
        --scraper ConnScraper \\
        --speculation-threshold 10 \\
        --speculation-limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from juriscraper.scraper_driver.data_types import BaseScraper

logger = logging.getLogger(__name__)


def parse_param(param_str: str) -> tuple[str, str, str, str]:
    """Parse a parameter string into components.

    Format: Model.field.operator=value
    Examples:
        NYSCEFDocket.date_filed.gte=2025-01-01
        NYSCEFDocket.court_id.values=nysupctbrnx,nysupctkings
        NYSCEFDocket.docket_number.value=2024-001

    Args:
        param_str: Parameter string in Model.field.operator=value format.

    Returns:
        Tuple of (model_name, field_name, operator, value).

    Raises:
        ValueError: If the format is invalid.
    """
    if "=" not in param_str:
        raise ValueError(
            f"Invalid param format: {param_str}. Expected Model.field.operator=value"
        )

    path, value = param_str.split("=", 1)
    parts = path.split(".")

    if len(parts) != 3:
        raise ValueError(
            f"Invalid param path: {path}. Expected Model.field.operator"
        )

    return parts[0], parts[1], parts[2], value


def build_params_data(
    param_strings: list[str],
    disabled_models: list[str] | None = None,
) -> dict[str, Any]:
    """Build params_data dict from parameter strings.

    Args:
        param_strings: List of parameter strings.
        disabled_models: List of model names to disable.

    Returns:
        Dictionary suitable for ScraperRegistry._build_params().
    """
    models: dict[str, Any] = {}

    # Mark disabled models
    for model_name in disabled_models or []:
        models[model_name] = {"enabled": False, "fields": {}}

    for param_str in param_strings:
        model_name, field_name, operator, value = parse_param(param_str)

        if model_name not in models:
            models[model_name] = {"enabled": True, "fields": {}}

        if field_name not in models[model_name]["fields"]:
            models[model_name]["fields"][field_name] = {}

        # Handle different operators
        if operator == "values":
            # Comma-separated values for SetFilter
            models[model_name]["fields"][field_name]["values"] = [
                v.strip() for v in value.split(",")
            ]
        else:
            # gte, lte, value
            models[model_name]["fields"][field_name][operator] = value

    return {"models": models}


def find_scraper(
    scraper_name: str,
) -> tuple[type[BaseScraper[Any]], str] | None:
    """Find a scraper by name or full path.

    Args:
        scraper_name: Either a class name (e.g., "NYSCEFScraper") or
            full path (e.g., "juriscraper.sd.state.new_york.nyscef.scraper:NYSCEFScraper").

    Returns:
        Tuple of (scraper_class, full_path) or None if not found.
    """
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        init_registry,
    )

    registry = init_registry()

    # If it's a full path, try direct lookup
    if ":" in scraper_name:
        scraper_class = registry.get_scraper_class(scraper_name)
        if scraper_class:
            return scraper_class, scraper_name

    # Otherwise, search by class name
    for info in registry.list_scrapers():
        if info.class_name == scraper_name:
            scraper_class = registry.get_scraper_class(info.full_path)
            if scraper_class:
                return scraper_class, info.full_path

    return None


def list_scrapers() -> None:
    """List all available scrapers."""
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        init_registry,
    )

    registry = init_registry()
    scrapers = registry.list_scrapers()

    if not scrapers:
        print("No scrapers found.")
        return

    print(f"Found {len(scrapers)} scrapers:\n")

    # Group by status
    by_status: dict[str, list] = {}
    for s in scrapers:
        status = s.status or "unknown"
        by_status.setdefault(status, []).append(s)

    for status in sorted(by_status.keys()):
        print(f"=== {status.upper()} ===")
        for s in sorted(by_status[status], key=lambda x: x.class_name):
            courts = ", ".join(sorted(s.court_ids)) if s.court_ids else "N/A"
            print(f"  {s.class_name}")
            print(f"    Courts: {courts}")
            if s.models:
                for model in s.models:
                    fields = [f.name for f in model.fields]
                    print(f"    Params ({model.name}): {', '.join(fields)}")
            print()


def create_speculation_callback(
    threshold: int,
    limit: int,
    verbose: bool,
) -> tuple[Any, dict[int, int]]:
    """Create an on_speculation_response callback with threshold and limit logic.

    Args:
        threshold: Speculative IDs below this are auto-approved.
        limit: Number of speculative requests at/above threshold to approve.
        verbose: Enable verbose output.

    Returns:
        Tuple of (callback, counter_dict) where counter_dict tracks approvals
        per speculative_id.
    """
    from juriscraper.scraper_driver.data_types import Response

    # Track how many times we've approved each speculative_id >= threshold
    approval_counts: dict[int, int] = {}

    async def on_speculation_response(
        response: Response, _continuation: str
    ) -> bool:
        """Decide whether to continue speculation based on threshold and limit.

        - If speculative_id < threshold: always approve (return True)
        - If speculative_id >= threshold: approve first `limit` times, then reject
        """
        # Extract speculative_id from accumulated_data
        # Format: {'speculative_id': {'ModelName': {'field': value}}}
        accumulated = response.request.accumulated_data or {}
        speculative_id_data = accumulated.get("speculative_id", {})

        # Get the speculative ID (typically a page number or similar)
        # The structure is nested, so we need to extract the innermost value
        spec_id = None
        for model_data in speculative_id_data.values():
            if isinstance(model_data, dict):
                for value in model_data.values():
                    if isinstance(value, int):
                        spec_id = value
                        break
            if spec_id is not None:
                break

        if spec_id is None:
            # No speculative_id found, default to rejecting
            if verbose:
                print("  [speculation] No speculative_id found, rejecting")
            return False

        # Check if below threshold - always approve
        if spec_id < threshold:
            if verbose:
                print(
                    f"  [speculation] ID {spec_id} < threshold {threshold}, approving"
                )
            return True

        # At or above threshold - check limit
        current_count = approval_counts.get(spec_id, 0)
        if current_count < limit:
            approval_counts[spec_id] = current_count + 1
            if verbose:
                print(
                    f"  [speculation] ID {spec_id} >= threshold, "
                    f"approved {current_count + 1}/{limit}"
                )
            return True

        # Exceeded limit
        if verbose:
            print(
                f"  [speculation] ID {spec_id} >= threshold, "
                f"limit {limit} reached, rejecting"
            )
        return False

    return on_speculation_response, approval_counts


async def run_scraper(
    scraper_name: str,
    params: list[str],
    disabled_models: list[str],
    max_results: int | None,
    results_path: Path | None,
    verbose: bool,
    speculation_threshold: int | None = None,
    speculation_limit: int | None = None,
) -> int:
    """Run a scraper and optionally export results.

    Args:
        scraper_name: Scraper name or full path.
        params: List of parameter strings.
        disabled_models: List of model names to disable.
        max_results: Maximum number of results to collect before stopping.
        results_path: Path to write results JSONL file.
        verbose: Enable verbose output.
        speculation_threshold: Speculative IDs below this are auto-approved.
        speculation_limit: Number of speculative requests at/above threshold to approve.

    Returns:
        Exit code.
    """
    from juriscraper.scraper_driver.driver.async_driver import AsyncDriver
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        init_registry,
    )

    # Find the scraper
    result = find_scraper(scraper_name)
    if result is None:
        print(f"Error: Scraper '{scraper_name}' not found.")
        print("Use --list-scrapers to see available scrapers.")
        return 1

    scraper_class, full_path = result
    print(f"Using scraper: {full_path}")

    # Build params if provided
    scraper_params = None
    if params or disabled_models:
        registry = init_registry()
        params_data = build_params_data(params, disabled_models)
        if verbose:
            print(f"Parameters: {json.dumps(params_data, indent=2)}")
        scraper_params = registry._build_params(scraper_class, params_data)

    # Instantiate scraper
    scraper = scraper_class(params=scraper_params)

    if max_results:
        print(f"Max results: {max_results}")

    # Track results
    results: list[Any] = []
    results_count = 0
    stop_event = asyncio.Event()

    # Open results file if specified
    results_file = None
    if results_path:
        results_file = open(results_path, "w")  # noqa: SIM115
        print(f"Results will be written to: {results_path}")

    async def on_data(data: Any) -> None:
        """Handle each data item emitted by the scraper."""
        nonlocal results_count

        results_count += 1
        results.append(data)

        # Serialize and write to file
        if results_file:
            if hasattr(data, "model_dump"):
                data_dict = data.model_dump()
            elif hasattr(data, "dict"):
                data_dict = data.dict()
            else:
                data_dict = data

            results_file.write(json.dumps(data_dict) + "\n")
            results_file.flush()

        if verbose:
            data_type = type(data).__name__
            print(f"  [{results_count}] {data_type}")

        # Check max results and signal stop
        if max_results and results_count >= max_results:
            print(f"\nReached max results limit ({max_results}), stopping...")
            stop_event.set()

    # Create speculation callback if both threshold and limit are provided
    on_speculation_response = None
    if speculation_threshold is not None and speculation_limit is not None:
        on_speculation_response, _ = create_speculation_callback(
            threshold=speculation_threshold,
            limit=speculation_limit,
            verbose=verbose,
        )
        print(
            f"Speculation control: threshold={speculation_threshold}, "
            f"limit={speculation_limit}"
        )

    try:
        print(f"\nRunning {scraper_class.__name__}...")
        print("Press Ctrl+C to stop.\n")

        driver = AsyncDriver(
            scraper=scraper,
            on_data=on_data,
            stop_event=stop_event,
            num_workers=1,
            on_speculation_response=on_speculation_response,
        )

        await driver.run()

        print("\n=== Complete ===")
        print(f"Results collected: {results_count}")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        print(f"Results collected: {results_count}")

    finally:
        if results_file:
            results_file.close()
            print(f"Results written to: {results_path}")

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="Run scrapers and export results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List available scrapers
    %(prog)s --list-scrapers

    # Run a scraper
    %(prog)s --scraper NYSCEFScraper

    # Run with date range
    %(prog)s --scraper NYSCEFScraper \\
        --param "NYSCEFDocket.date_filed.gte=2025-01-01" \\
        --param "NYSCEFDocket.date_filed.lte=2025-01-07"

    # Run with max results and output
    %(prog)s --scraper NYSCEFScraper \\
        --max-results 100 \\
        --results output.jsonl
""",
    )

    # Scraper selection
    parser.add_argument(
        "--scraper",
        "-s",
        metavar="NAME",
        help="Scraper name (e.g., NYSCEFScraper) or full path (module:Class)",
    )

    parser.add_argument(
        "--list-scrapers",
        action="store_true",
        help="List all available scrapers",
    )

    # Parameters
    parser.add_argument(
        "--param",
        "-p",
        action="append",
        default=[],
        metavar="PARAM",
        help="Parameter in Model.field.operator=value format (can be repeated)",
    )

    parser.add_argument(
        "--disable",
        "-d",
        action="append",
        default=[],
        metavar="MODEL",
        help="Disable a data model (e.g., ConnOralArgument). Can be repeated.",
    )

    # Output options
    parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        metavar="N",
        help="Stop after collecting N results",
    )

    parser.add_argument(
        "--results",
        "-r",
        type=Path,
        metavar="PATH",
        help="Path to write results as JSONL",
    )

    # Output control
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output (show each result)",
    )

    # Speculation control
    parser.add_argument(
        "--speculation-threshold",
        type=int,
        metavar="N",
        help="Speculative IDs below this threshold are auto-approved",
    )

    parser.add_argument(
        "--speculation-limit",
        type=int,
        metavar="N",
        help="Number of speculative requests at/above threshold to approve",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Handle --list-scrapers
    if args.list_scrapers:
        list_scrapers()
        return 0

    # Require scraper for running
    if not args.scraper:
        parser.error("--scraper is required (or use --list-scrapers)")

    try:
        return asyncio.run(
            run_scraper(
                scraper_name=args.scraper,
                params=args.param,
                disabled_models=args.disable,
                max_results=args.max_results,
                results_path=args.results,
                verbose=args.verbose,
                speculation_threshold=args.speculation_threshold,
                speculation_limit=args.speculation_limit,
            )
        )
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
