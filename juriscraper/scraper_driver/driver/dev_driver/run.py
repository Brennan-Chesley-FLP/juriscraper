#!/usr/bin/env python3
"""CLI runner for LocalDevDriver.

This script provides a command-line interface for running scrapers with
the LocalDevDriver, checking status, viewing statistics, managing errors,
and exporting data.

Usage:
    # Start the web interface
    python -m juriscraper.scraper_driver.driver.dev_driver.run --serve

    # Start with custom options
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --serve --runs-dir ./my_runs --port 9000

    # Run a scraper
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --scraper myproject.scrapers:MyScraper \\
        --db scraper.db

    # Check status
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --db scraper.db --status

    # View statistics
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --db scraper.db --stats

    # Export to WARC
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --db scraper.db --export-warc export.warc.gz

    # List errors
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --db scraper.db --errors

    # Requeue a specific error
    python -m juriscraper.scraper_driver.driver.dev_driver.run \\
        --db scraper.db --requeue-error 123
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    from juriscraper.scraper_driver.data_types import BaseScraper

logger = logging.getLogger(__name__)


def import_scraper(scraper_path: str) -> type:
    """Import a scraper class from a module path.

    Args:
        scraper_path: Path in format "module.path:ClassName".

    Returns:
        The scraper class.

    Raises:
        ValueError: If the path format is invalid.
        ImportError: If the module or class cannot be imported.
    """
    if ":" not in scraper_path:
        raise ValueError(
            f"Invalid scraper path '{scraper_path}'. "
            "Expected format: 'module.path:ClassName'"
        )

    module_path, class_name = scraper_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    scraper_class = getattr(module, class_name)
    return scraper_class


async def cmd_run(args: argparse.Namespace) -> int:
    """Run the scraper."""
    from juriscraper.scraper_driver.driver.dev_driver import LocalDevDriver

    # Import and instantiate scraper
    scraper_class = import_scraper(args.scraper)
    scraper: BaseScraper[Any] = scraper_class()

    # Create storage directory if specified
    storage_dir = Path(args.storage) if args.storage else None
    if storage_dir:
        storage_dir.mkdir(parents=True, exist_ok=True)

    async with LocalDevDriver.open(
        scraper=scraper,
        db_path=Path(args.db),
        storage_dir=storage_dir,
        base_delay=args.delay,
        jitter=args.jitter,
        num_workers=args.workers,
        resume=not args.no_resume,
        max_backoff_time=args.max_backoff,
    ) as driver:
        print(f"Running scraper: {scraper_class.__name__}")
        print(f"Database: {args.db}")
        print(f"Workers: {args.workers}")
        print(f"Delay: {args.delay}s ± {args.jitter}s")

        await driver.run()

        # Print final status
        status = await driver.status()
        print(f"\nFinal status: {status}")

    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    """Check the status of a scraper run."""
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )

    db = await init_database(Path(args.db))

    cursor = await db.execute(SQL.SELECT_RUN_STATUS_AND_NAME)
    row = await cursor.fetchone()

    if row:
        status, scraper_name = row
        print(f"Scraper: {scraper_name}")
        print(f"Status: {status}")
    else:
        print("No run metadata found")

    # Count requests by status
    cursor = await db.execute(SQL.SELECT_REQUEST_COUNTS_BY_STATUS)
    rows = await cursor.fetchall()

    print("\nRequests:")
    for status, count in rows:
        print(f"  {status}: {count}")

    await db.close()
    return 0


async def cmd_stats(args: argparse.Namespace) -> int:
    """Show detailed statistics."""
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )
    from juriscraper.scraper_driver.driver.dev_driver.stats import get_stats

    db = await init_database(Path(args.db))
    stats = await get_stats(db)

    if args.json:
        print(stats.to_json())
    else:
        print(f"=== {stats.scraper_name} ({stats.run_status}) ===\n")

        print("Queue:")
        print(f"  Pending:     {stats.queue.pending}")
        print(f"  In Progress: {stats.queue.in_progress}")
        print(f"  Completed:   {stats.queue.completed}")
        print(f"  Failed:      {stats.queue.failed}")
        print(f"  Held:        {stats.queue.held}")
        print(f"  Total:       {stats.queue.total}")

        print("\nThroughput:")
        print(f"  Completed:    {stats.throughput.total_completed}")
        print(
            f"  Duration:     {stats.throughput.total_duration_seconds:.1f}s"
        )
        print(
            f"  Rate:         {stats.throughput.requests_per_minute:.2f}/min"
        )
        print(
            f"  Avg Response: {stats.throughput.average_response_time_seconds:.2f}s"
        )

        print("\nCompression:")
        print(f"  Responses:  {stats.compression.total_responses}")
        print(
            f"  Original:   {stats.compression.total_original_bytes:,} bytes"
        )
        print(
            f"  Compressed: {stats.compression.total_compressed_bytes:,} bytes"
        )
        print(f"  Ratio:      {stats.compression.compression_ratio:.2f}x")

        print("\nResults:")
        print(f"  Total:   {stats.results.total}")
        print(f"  Valid:   {stats.results.valid}")
        print(f"  Invalid: {stats.results.invalid}")

        print("\nErrors:")
        print(f"  Total:      {stats.errors.total}")
        print(f"  Unresolved: {stats.errors.unresolved}")
        print(f"  Resolved:   {stats.errors.resolved}")

    await db.close()
    return 0


async def cmd_export_warc(args: argparse.Namespace) -> int:
    """Export responses to WARC file."""
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )
    from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
        export_warc,
    )

    db = await init_database(Path(args.db))
    output_path = Path(args.export_warc)

    count = await export_warc(db, output_path, compress=True)
    print(f"Exported {count} responses to {output_path}")

    await db.close()
    return 0


async def cmd_errors(args: argparse.Namespace) -> int:
    """List errors."""
    from juriscraper.scraper_driver.driver.dev_driver.errors import list_errors
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )

    db = await init_database(Path(args.db))

    errors = await list_errors(
        db,
        error_type=args.error_type,
        unresolved_only=not args.all_errors,
        limit=args.limit or 50,
    )

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": e.id,
                        "type": e.error_type,
                        "class": e.error_class,
                        "message": e.message,
                        "url": e.request_url,
                        "is_resolved": e.is_resolved,
                    }
                    for e in errors
                ],
                indent=2,
            )
        )
    else:
        if not errors:
            print("No errors found")
        else:
            print(f"Found {len(errors)} errors:\n")
            for e in errors:
                resolved = "[RESOLVED] " if e.is_resolved else ""
                print(f"{resolved}#{e.id} [{e.error_type}] {e.error_class}")
                print(f"  URL: {e.request_url}")
                print(f"  Message: {e.message[:100]}...")
                print()

    await db.close()
    return 0


async def cmd_requeue_error(args: argparse.Namespace) -> int:
    """Requeue a specific error."""
    from juriscraper.scraper_driver.driver.dev_driver.errors import (
        resolve_error,
    )
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        get_next_queue_counter,
        init_database,
    )

    db = await init_database(Path(args.db))

    # Get error with request info
    cursor = await db.execute(
        SQL.SELECT_ERROR_FOR_CLI_REQUEUE, (args.requeue_error,)
    )
    row = await cursor.fetchone()

    if row is None:
        print(f"Error {args.requeue_error} not found")
        await db.close()
        return 1

    if row[2]:  # is_resolved
        print(f"Error {args.requeue_error} is already resolved")
        await db.close()
        return 1

    if row[1] is None:  # request_id
        print(f"Error {args.requeue_error} has no associated request")
        await db.close()
        return 1

    # Create new pending request
    queue_counter = await get_next_queue_counter(db)
    cursor = await db.execute(
        SQL.INSERT_REQUEUE_REQUEST,
        (
            row[13] or 9,  # priority
            queue_counter,
            row[3],  # method
            row[4],  # url
            row[5],  # headers_json
            row[6],  # cookies_json
            row[7],  # body
            row[8],  # continuation
            row[9],  # current_location
            row[10],  # accumulated_data_json
            row[11],  # aux_data_json
            row[12],  # permanent_json
            row[1],  # parent_request_id
        ),
    )
    new_request_id = cursor.lastrowid

    # Resolve the error
    await resolve_error(
        db, args.requeue_error, notes=f"Requeued as request {new_request_id}"
    )

    print(f"Requeued error {args.requeue_error} as request {new_request_id}")

    await db.close()
    return 0


async def cmd_requeue_errors(args: argparse.Namespace) -> int:
    """Requeue all errors of a type."""
    from juriscraper.scraper_driver.driver.dev_driver.errors import (
        resolve_error,
    )
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        get_next_queue_counter,
        init_database,
    )

    db = await init_database(Path(args.db))

    # Get matching errors
    cursor = await db.execute(
        SQL.SELECT_ERRORS_BY_TYPE_FOR_CLI_REQUEUE,
        (args.requeue_errors,),
    )
    rows = await cursor.fetchall()

    if not rows:
        print(f"No unresolved errors of type '{args.requeue_errors}'")
        await db.close()
        return 0

    count = 0
    for row in rows:
        error_id, request_id = row[0], row[1]

        queue_counter = await get_next_queue_counter(db)
        cursor = await db.execute(
            SQL.INSERT_REQUEUE_REQUEST,
            (
                row[12] or 9,  # priority
                queue_counter,
                row[2],  # method
                row[3],  # url
                row[4],  # headers_json
                row[5],  # cookies_json
                row[6],  # body
                row[7],  # continuation
                row[8],  # current_location
                row[9],  # accumulated_data_json
                row[10],  # aux_data_json
                row[11],  # permanent_json
                request_id,
            ),
        )
        new_request_id = cursor.lastrowid
        await resolve_error(
            db, error_id, notes=f"Batch requeued as request {new_request_id}"
        )
        count += 1

    await db.commit()
    print(f"Requeued {count} errors of type '{args.requeue_errors}'")

    await db.close()
    return 0


async def cmd_resolve_error(args: argparse.Namespace) -> int:
    """Resolve an error without requeuing."""
    from juriscraper.scraper_driver.driver.dev_driver.errors import (
        get_error,
        resolve_error,
    )
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        init_database,
    )

    db = await init_database(Path(args.db))

    error = await get_error(db, args.resolve_error)
    if error is None:
        print(f"Error {args.resolve_error} not found")
        await db.close()
        return 1

    if error.is_resolved:
        print(f"Error {args.resolve_error} is already resolved")
        await db.close()
        return 0

    notes = args.notes or "Resolved via CLI"
    await resolve_error(db, args.resolve_error, notes=notes)
    print(f"Resolved error {args.resolve_error}")

    await db.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the web interface server."""
    import uvicorn

    from juriscraper.scraper_driver.driver.dev_driver.web.app import create_app

    runs_dir = Path(args.runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(runs_dir=runs_dir)

    print(f"Starting web server at http://{args.host}:{args.port}")
    print(f"Runs directory: {runs_dir.absolute()}")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info" if args.verbose else "warning",
    )
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="LocalDevDriver CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--db",
        help="Path to SQLite database file (required for most commands)",
    )

    # Web server options
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the web interface server",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory containing run databases (default: runs)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind server to (default: 8000)",
    )

    # Run options
    parser.add_argument(
        "--scraper",
        help="Scraper class path (module.path:ClassName)",
    )
    parser.add_argument(
        "--storage",
        help="Directory for downloaded files",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Base delay between requests (default: 10.0)",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=2.0,
        help="Jitter for request delay (default: 2.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent workers (default: 1)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh instead of resuming",
    )
    parser.add_argument(
        "--max-backoff",
        type=float,
        default=3600.0,
        help="Maximum backoff time for retries (default: 3600.0)",
    )

    # Commands
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show run status",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show detailed statistics",
    )
    parser.add_argument(
        "--export-warc",
        metavar="PATH",
        help="Export responses to WARC file",
    )
    parser.add_argument(
        "--errors",
        action="store_true",
        help="List errors",
    )
    parser.add_argument(
        "--error-type",
        help="Filter errors by type (structural, validation, transient)",
    )
    parser.add_argument(
        "--all-errors",
        action="store_true",
        help="Include resolved errors",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of results",
    )
    parser.add_argument(
        "--requeue-error",
        type=int,
        metavar="ID",
        help="Requeue a specific error",
    )
    parser.add_argument(
        "--requeue-errors",
        metavar="TYPE",
        help="Requeue all errors of a type",
    )
    parser.add_argument(
        "--resolve-error",
        type=int,
        metavar="ID",
        help="Resolve an error without requeuing",
    )
    parser.add_argument(
        "--notes",
        help="Notes for error resolution",
    )

    # Output format
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


async def main_async(args: argparse.Namespace) -> int:
    """Main async entry point."""
    # Determine which command to run
    if args.status:
        return await cmd_status(args)
    elif args.stats:
        return await cmd_stats(args)
    elif args.export_warc:
        return await cmd_export_warc(args)
    elif args.errors:
        return await cmd_errors(args)
    elif args.requeue_error:
        return await cmd_requeue_error(args)
    elif args.requeue_errors:
        return await cmd_requeue_errors(args)
    elif args.resolve_error:
        return await cmd_resolve_error(args)
    elif args.scraper:
        return await cmd_run(args)
    else:
        print("No command specified. Use --help for usage.")
        return 1


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Handle serve command specially (synchronous)
    if args.serve:
        try:
            return cmd_serve(args)
        except KeyboardInterrupt:
            print("\nServer stopped")
            return 0

    # All other commands require --db
    if not args.db:
        parser.error("--db is required for this command")

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
