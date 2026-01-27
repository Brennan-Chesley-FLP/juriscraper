"""Command-line interface for LocalDevDriverDebugger.

This module provides a Click-based CLI for inspecting and manipulating
LocalDevDriver run databases.

Usage:
    ldd-debug info <db-path>                    # Show run metadata and stats
    ldd-debug requests list <db-path>           # List requests
    ldd-debug requests show <db-path> <id>      # Show request details
    ldd-debug responses list <db-path>          # List responses
    ldd-debug responses search <db-path>        # Search response content
    ldd-debug errors list <db-path>             # List errors
    ldd-debug results list <db-path>            # List results
    ldd-debug requeue request <db-path> <id>    # Requeue a request
    ldd-debug cancel request <db-path> <id>     # Cancel a request
    ldd-debug compression stats <db-path>       # Show compression stats
    ldd-debug diagnose <db-path> <error-id>     # Diagnose an error
    ldd-debug export jsonl <db-path> <output>   # Export results to JSONL
    ldd-debug export warc <db-path> <output>    # Export responses to WARC

All commands support:
    --format table|json|jsonl    Output format (default: table)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click

from juriscraper.scraper_driver.driver.dev_driver.debugger import (
    LocalDevDriverDebugger,
)

# =========================================================================
# Output Formatting
# =========================================================================


def format_output(
    data: Any, format_type: str = "table", headers: list[str] | None = None
) -> None:
    """Format and print output based on format type.

    Args:
        data: Data to format (dict, list of dicts, or list of objects)
        format_type: Output format ('table', 'json', 'jsonl')
        headers: Column headers for table format
    """
    if format_type == "json":
        click.echo(json.dumps(data, indent=2))
    elif format_type == "jsonl":
        if isinstance(data, list):
            for item in data:
                click.echo(json.dumps(item))
        else:
            click.echo(json.dumps(data))
    elif format_type == "table":
        if isinstance(data, dict):
            # Single record - display as key-value pairs
            for key, value in data.items():
                click.echo(f"{key}: {value}")
        elif isinstance(data, list) and data:
            # Multiple records - display as table
            if headers is None:
                # Auto-detect headers from first item
                first = data[0]
                if hasattr(first, "__dict__"):
                    headers = list(vars(first).keys())
                elif isinstance(first, dict):
                    headers = list(first.keys())
                else:
                    headers = []

            if headers:
                # Print header
                click.echo("  ".join(str(h).ljust(15) for h in headers))
                click.echo("-" * (len(headers) * 17))

                # Print rows
                for item in data:
                    if hasattr(item, "__dict__"):
                        row = [str(getattr(item, h, ""))[:15] for h in headers]
                    elif isinstance(item, dict):
                        row = [str(item.get(h, ""))[:15] for h in headers]
                    else:
                        row = [str(item)[:15]]
                    click.echo("  ".join(v.ljust(15) for v in row))
            else:
                # Just print items
                for item in data:
                    click.echo(item)
        elif not data:
            click.echo("No results")
        else:
            click.echo(str(data))
    else:
        raise ValueError(f"Unknown format: {format_type}")


# =========================================================================
# CLI Groups
# =========================================================================


@click.group()
@click.version_option()
def cli() -> None:
    """LocalDevDriver Debugger - Inspect and manipulate scraper run databases."""
    pass


# =========================================================================
# Info Command
# =========================================================================


@cli.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def info(db_path: str, format_type: str) -> None:
    """Show run metadata and statistics.

    \b
    Examples:
        ldd-debug info run.db
        ldd-debug info run.db --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            metadata = await debugger.get_run_metadata()
            stats = await debugger.get_stats()

            if format_type == "table":
                click.echo("=== Run Metadata ===")
                if metadata:
                    for key, value in metadata.items():
                        click.echo(f"{key}: {value}")
                else:
                    click.echo("No metadata found")

                click.echo("\n=== Statistics ===")
                click.echo(f"Queue Total: {stats['queue']['total']}")
                click.echo(f"Queue Pending: {stats['queue']['pending']}")
                click.echo(f"Queue Completed: {stats['queue']['completed']}")
                click.echo(f"Queue Failed: {stats['queue']['failed']}")
                click.echo(f"Results Total: {stats['results']['total']}")
                click.echo(f"Errors Total: {stats['errors']['total']}")
                click.echo(
                    f"Errors Unresolved: {stats['errors']['unresolved']}"
                )
            else:
                output = {"metadata": metadata, "stats": stats}
                format_output(output, format_type)

    asyncio.run(run())


# =========================================================================
# Requests Commands
# =========================================================================


@cli.group()
def requests() -> None:
    """Inspect and manipulate requests."""
    pass


@requests.command("list")
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--status", help="Filter by status (pending, completed, failed, held)"
)
@click.option("--continuation", help="Filter by continuation (step name)")
@click.option("--limit", default=100, help="Maximum number of results")
@click.option("--offset", default=0, help="Number of results to skip")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def requests_list(
    db_path: str,
    status: str | None,
    continuation: str | None,
    limit: int,
    offset: int,
    format_type: str,
) -> None:
    """List requests with optional filtering.

    \b
    Examples:
        ldd-debug requests list run.db
        ldd-debug requests list run.db --status failed
        ldd-debug requests list run.db --continuation step1 --limit 50
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_requests(
                status=status,  # type: ignore
                continuation=continuation,
                limit=limit,
                offset=offset,
            )

            if format_type == "table":
                click.echo(
                    f"Total: {page.total}, Showing: {len(page.items)}, "
                    f"Offset: {offset}, Limit: {limit}"
                )
                if page.items:
                    headers = [
                        "id",
                        "status",
                        "url",
                        "continuation",
                        "retry_count",
                    ]
                    items = [
                        {
                            "id": r.id,
                            "status": r.status,
                            "url": r.url[:50] if r.url else "",
                            "continuation": r.continuation,
                            "retry_count": r.retry_count,
                        }
                        for r in page.items
                    ]
                    format_output(items, format_type, headers)
                else:
                    click.echo("No requests found")
            else:
                output = {
                    "total": page.total,
                    "items": [
                        {
                            "id": r.id,
                            "status": r.status,
                            "url": r.url,
                            "continuation": r.continuation,
                            "retry_count": r.retry_count,
                            "method": r.method,
                            "priority": r.priority,
                        }
                        for r in page.items
                    ],
                    "limit": limit,
                    "offset": offset,
                    "has_more": page.has_more,
                }
                format_output(output, format_type)

    asyncio.run(run())


@requests.command("show")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("request_id", type=int)
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def requests_show(db_path: str, request_id: int, format_type: str) -> None:
    """Show detailed request information.

    \b
    Examples:
        ldd-debug requests show run.db 123
        ldd-debug requests show run.db 123 --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            request = await debugger.get_request(request_id)

            if request is None:
                click.echo(f"Request {request_id} not found", err=True)
                sys.exit(1)

            if format_type == "table":
                click.echo(f"ID: {request.id}")
                click.echo(f"Status: {request.status}")
                click.echo(f"URL: {request.url}")
                click.echo(f"Method: {request.method}")
                click.echo(f"Continuation: {request.continuation}")
                click.echo(f"Priority: {request.priority}")
                click.echo(f"Retry Count: {request.retry_count}")
                click.echo(f"Created At: {request.created_at}")
                if request.completed_at:
                    click.echo(f"Completed At: {request.completed_at}")
            else:
                output = {
                    "id": request.id,
                    "status": request.status,
                    "url": request.url,
                    "method": request.method,
                    "continuation": request.continuation,
                    "priority": request.priority,
                    "retry_count": request.retry_count,
                    "created_at": request.created_at,
                    "completed_at": request.completed_at,
                }
                format_output(output, format_type)

    asyncio.run(run())


@requests.command("summary")
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def requests_summary(db_path: str, format_type: str) -> None:
    """Show request counts by status and continuation.

    \b
    Examples:
        ldd-debug requests summary run.db
        ldd-debug requests summary run.db --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_request_summary()

            if format_type == "table":
                for continuation, status_counts in summary.items():
                    click.echo(f"\n=== {continuation} ===")
                    for status, count in status_counts.items():
                        click.echo(f"  {status}: {count}")
            else:
                format_output(summary, format_type)

    asyncio.run(run())


# =========================================================================
# Responses Commands
# =========================================================================


@cli.group()
def responses() -> None:
    """Inspect responses."""
    pass


@responses.command("list")
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--continuation", help="Filter by continuation (step name)")
@click.option("--limit", default=100, help="Maximum number of results")
@click.option("--offset", default=0, help="Number of results to skip")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def responses_list(
    db_path: str,
    continuation: str | None,
    limit: int,
    offset: int,
    format_type: str,
) -> None:
    """List responses with optional filtering.

    \b
    Examples:
        ldd-debug responses list run.db
        ldd-debug responses list run.db --continuation step1
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_responses(
                continuation=continuation, limit=limit, offset=offset
            )

            if format_type == "table":
                click.echo(
                    f"Total: {page.total}, Showing: {len(page.items)}, "
                    f"Offset: {offset}, Limit: {limit}"
                )
                if page.items:
                    headers = [
                        "id",
                        "status_code",
                        "url",
                        "continuation",
                        "size",
                    ]
                    items = [
                        {
                            "id": r.id,
                            "status_code": r.status_code,
                            "url": r.url[:50] if r.url else "",
                            "continuation": r.continuation,
                            "size": r.content_size_original,
                        }
                        for r in page.items
                    ]
                    format_output(items, format_type, headers)
                else:
                    click.echo("No responses found")
            else:
                output = {
                    "total": page.total,
                    "items": [
                        {
                            "id": r.id,
                            "status_code": r.status_code,
                            "url": r.url,
                            "continuation": r.continuation,
                            "content_size_original": r.content_size_original,
                            "content_size_compressed": r.content_size_compressed,
                            "compression_ratio": r.compression_ratio,
                        }
                        for r in page.items
                    ],
                    "limit": limit,
                    "offset": offset,
                    "has_more": page.has_more,
                }
                format_output(output, format_type)

    asyncio.run(run())


@responses.command("show")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("response_id", type=int)
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def responses_show(db_path: str, response_id: int, format_type: str) -> None:
    """Show detailed response information.

    \b
    Examples:
        ldd-debug responses show run.db 123
        ldd-debug responses show run.db 123 --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            response = await debugger.get_response(response_id)

            if response is None:
                click.echo(f"Response {response_id} not found", err=True)
                sys.exit(1)

            if format_type == "table":
                click.echo(f"ID: {response.id}")
                click.echo(f"Request ID: {response.request_id}")
                click.echo(f"Status Code: {response.status_code}")
                click.echo(f"URL: {response.url}")
                click.echo(f"Continuation: {response.continuation}")
                click.echo(f"Original Size: {response.content_size_original}")
                click.echo(
                    f"Compressed Size: {response.content_size_compressed}"
                )
                click.echo(
                    f"Compression Ratio: {response.compression_ratio:.2f}x"
                )
                click.echo(f"Created At: {response.created_at}")
            else:
                output = {
                    "id": response.id,
                    "request_id": response.request_id,
                    "status_code": response.status_code,
                    "url": response.url,
                    "continuation": response.continuation,
                    "content_size_original": response.content_size_original,
                    "content_size_compressed": response.content_size_compressed,
                    "compression_ratio": response.compression_ratio,
                    "created_at": response.created_at,
                }
                format_output(output, format_type)

    asyncio.run(run())


@responses.command("content")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("response_id", type=int)
@click.option("--output", "-o", help="Output file path (default: stdout)")
def responses_content(
    db_path: str, response_id: int, output: str | None
) -> None:
    """Get decompressed response content.

    \b
    Examples:
        ldd-debug responses content run.db 123
        ldd-debug responses content run.db 123 -o response.html
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            content = await debugger.get_response_content(response_id)

            if content is None:
                click.echo(f"Response {response_id} not found", err=True)
                sys.exit(1)

            if output:
                Path(output).write_bytes(content)
                click.echo(f"Content saved to {output}")
            else:
                # Try to decode as UTF-8, fall back to binary output
                try:
                    click.echo(content.decode("utf-8"))
                except UnicodeDecodeError:
                    click.echo(content, nl=False)

    asyncio.run(run())


@responses.command("search")
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--text", "text_pattern", help="Plain text to search for")
@click.option("--regex", "regex_pattern", help="Regular expression pattern")
@click.option("--xpath", "xpath_expr", help="XPath expression to evaluate")
@click.option("--continuation", help="Filter by continuation (step name)")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def responses_search(
    db_path: str,
    text_pattern: str | None,
    regex_pattern: str | None,
    xpath_expr: str | None,
    continuation: str | None,
    format_type: str,
) -> None:
    """Search response content for matching patterns.

    Searches through all response content (decompressed) for matches.
    Exactly one of --text, --regex, or --xpath must be provided.

    \b
    Examples:
        ldd-debug responses search run.db --text "error"
        ldd-debug responses search run.db --regex "case.*\\d{4}"
        ldd-debug responses search run.db --xpath "//div[@class='opinion']"
        ldd-debug responses search run.db --text "verdict" --format json
        ldd-debug responses search run.db --text "verdict" --format jsonl
    """
    # Validate exactly one search type is provided
    search_types = [text_pattern, regex_pattern, xpath_expr]
    provided = sum(1 for s in search_types if s is not None)
    if provided != 1:
        click.echo(
            "Error: Exactly one of --text, --regex, or --xpath must be provided",
            err=True,
        )
        sys.exit(1)

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            try:
                matches = await debugger.search_responses(
                    text=text_pattern,
                    regex=regex_pattern,
                    xpath=xpath_expr,
                    continuation=continuation,
                )

                if format_type == "table":
                    if matches:
                        click.echo(f"Found {len(matches)} matching responses:")
                        for match in matches:
                            click.echo(
                                f"  response_id={match['response_id']}, "
                                f"request_id={match['request_id']}"
                            )
                    else:
                        click.echo("No matching responses found")
                elif format_type == "json":
                    click.echo(json.dumps(matches, indent=2))
                elif format_type == "jsonl":
                    for match in matches:
                        click.echo(json.dumps(match))

            except ValueError as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)
            except Exception as e:
                click.echo(f"Search error: {e}", err=True)
                sys.exit(1)

    asyncio.run(run())


# =========================================================================
# Errors Commands
# =========================================================================


@cli.group()
def errors() -> None:
    """Inspect and manipulate errors."""
    pass


@errors.command("list")
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--type", "error_type", help="Filter by error type")
@click.option(
    "--resolved/--unresolved",
    default=None,
    help="Filter by resolution status",
)
@click.option("--continuation", help="Filter by continuation (step name)")
@click.option("--limit", default=100, help="Maximum number of results")
@click.option("--offset", default=0, help="Number of results to skip")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def errors_list(
    db_path: str,
    error_type: str | None,
    resolved: bool | None,
    continuation: str | None,
    limit: int,
    offset: int,
    format_type: str,
) -> None:
    """List errors with optional filtering.

    \b
    Examples:
        ldd-debug errors list run.db
        ldd-debug errors list run.db --type xpath --unresolved
        ldd-debug errors list run.db --continuation step1
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_errors(
                error_type=error_type,
                is_resolved=resolved,
                continuation=continuation,
                limit=limit,
                offset=offset,
            )

            if format_type == "table":
                click.echo(
                    f"Total: {page.total}, Showing: {len(page.items)}, "
                    f"Offset: {offset}, Limit: {limit}"
                )
                if page.items:
                    headers = ["id", "type", "message", "resolved"]
                    items = [
                        {
                            "id": e["id"],
                            "type": e["error_type"],
                            "message": e["message"][:50]
                            if e.get("message")
                            else "",
                            "resolved": "✓" if e["is_resolved"] else "✗",
                        }
                        for e in page.items
                    ]
                    format_output(items, format_type, headers)
                else:
                    click.echo("No errors found")
            else:
                output = {
                    "total": page.total,
                    "items": page.items,
                    "limit": limit,
                    "offset": offset,
                    "has_more": page.has_more,
                }
                format_output(output, format_type)

    asyncio.run(run())


@errors.command("show")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("error_id", type=int)
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def errors_show(db_path: str, error_id: int, format_type: str) -> None:
    """Show detailed error information.

    \b
    Examples:
        ldd-debug errors show run.db 123
        ldd-debug errors show run.db 123 --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            error = await debugger.get_error(error_id)

            if error is None:
                click.echo(f"Error {error_id} not found", err=True)
                sys.exit(1)

            if format_type == "table":
                click.echo(f"ID: {error['id']}")
                click.echo(f"Type: {error['error_type']}")
                click.echo(f"Message: {error['message']}")
                click.echo(f"Request ID: {error['request_id']}")
                click.echo(
                    f"Resolved: {'Yes' if error['is_resolved'] else 'No'}"
                )
                if error.get("selector"):
                    click.echo(f"Selector: {error['selector']}")
                if error.get("resolution_notes"):
                    click.echo(
                        f"Resolution Notes: {error['resolution_notes']}"
                    )
                click.echo(f"Created At: {error['created_at']}")
            else:
                format_output(error, format_type)

    asyncio.run(run())


@errors.command("summary")
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def errors_summary(db_path: str, format_type: str) -> None:
    """Show error counts by type and resolution status.

    \b
    Examples:
        ldd-debug errors summary run.db
        ldd-debug errors summary run.db --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_error_summary()

            if format_type == "table":
                click.echo("=== Totals ===")
                for key, value in summary["totals"].items():
                    click.echo(f"  {key}: {value}")

                click.echo("\n=== By Type ===")
                for error_type, counts in summary["by_type"].items():
                    click.echo(f"\n{error_type}:")
                    for status, count in counts.items():
                        click.echo(f"  {status}: {count}")

                if summary["by_continuation"]:
                    click.echo("\n=== By Continuation ===")
                    for continuation, count in summary[
                        "by_continuation"
                    ].items():
                        click.echo(f"  {continuation}: {count}")
            else:
                format_output(summary, format_type)

    asyncio.run(run())


@errors.command("resolve")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("error_id", type=int)
@click.option("--notes", help="Resolution notes")
def errors_resolve(db_path: str, error_id: int, notes: str | None) -> None:
    """Mark an error as resolved.

    \b
    Examples:
        ldd-debug errors resolve run.db 123
        ldd-debug errors resolve run.db 123 --notes "Fixed XPath selector"
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            resolved = await debugger.resolve_error(error_id, notes)

            if resolved:
                click.echo(f"Error {error_id} marked as resolved")
            else:
                click.echo(
                    f"Error {error_id} not found or already resolved", err=True
                )
                sys.exit(1)

    asyncio.run(run())


@errors.command("requeue")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("error_id", type=int)
@click.option("--notes", help="Resolution notes")
def errors_requeue(db_path: str, error_id: int, notes: str | None) -> None:
    """Requeue the request that caused an error.

    \b
    Examples:
        ldd-debug errors requeue run.db 123
        ldd-debug errors requeue run.db 123 --notes "Fixed server issue"
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            try:
                new_id = await debugger.requeue_error(error_id, notes)
                click.echo(f"Error {error_id} requeued as request {new_id}")
            except ValueError as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


# =========================================================================
# Results Commands
# =========================================================================


@cli.group()
def results() -> None:
    """Inspect and export results."""
    pass


@results.command("list")
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--type", "result_type", help="Filter by result type")
@click.option(
    "--valid/--invalid", default=None, help="Filter by validation status"
)
@click.option("--limit", default=100, help="Maximum number of results")
@click.option("--offset", default=0, help="Number of results to skip")
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def results_list(
    db_path: str,
    result_type: str | None,
    valid: bool | None,
    limit: int,
    offset: int,
    format_type: str,
) -> None:
    """List results with optional filtering.

    \b
    Examples:
        ldd-debug results list run.db
        ldd-debug results list run.db --type CourtOpinion --valid
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            page = await debugger.list_results(
                result_type=result_type,
                is_valid=valid,
                limit=limit,
                offset=offset,
            )

            if format_type == "table":
                click.echo(
                    f"Total: {page.total}, Showing: {len(page.items)}, "
                    f"Offset: {offset}, Limit: {limit}"
                )
                if page.items:
                    headers = ["id", "type", "valid", "request_id"]
                    items = [
                        {
                            "id": r.id,
                            "type": r.result_type,
                            "valid": "✓" if r.is_valid else "✗",
                            "request_id": r.request_id,
                        }
                        for r in page.items
                    ]
                    format_output(items, format_type, headers)
                else:
                    click.echo("No results found")
            else:
                output = {
                    "total": page.total,
                    "items": [
                        {
                            "id": r.id,
                            "request_id": r.request_id,
                            "result_type": r.result_type,
                            "is_valid": r.is_valid,
                            "data": r.data,
                            "validation_errors": r.validation_errors,
                        }
                        for r in page.items
                    ],
                    "limit": limit,
                    "offset": offset,
                    "has_more": page.has_more,
                }
                format_output(output, format_type)

    asyncio.run(run())


@results.command("show")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("result_id", type=int)
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def results_show(db_path: str, result_id: int, format_type: str) -> None:
    """Show detailed result information.

    \b
    Examples:
        ldd-debug results show run.db 123
        ldd-debug results show run.db 123 --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            result = await debugger.get_result(result_id)

            if result is None:
                click.echo(f"Result {result_id} not found", err=True)
                sys.exit(1)

            if format_type == "table":
                click.echo(f"ID: {result.id}")
                click.echo(f"Request ID: {result.request_id}")
                click.echo(f"Type: {result.result_type}")
                click.echo(f"Valid: {'Yes' if result.is_valid else 'No'}")
                click.echo(f"Data: {json.dumps(result.data, indent=2)}")
                if result.validation_errors:
                    click.echo(
                        f"Validation Errors: {json.dumps(result.validation_errors, indent=2)}"
                    )
                click.echo(f"Created At: {result.created_at}")
            else:
                output = {
                    "id": result.id,
                    "request_id": result.request_id,
                    "result_type": result.result_type,
                    "is_valid": result.is_valid,
                    "data": result.data,
                    "validation_errors": result.validation_errors,
                    "created_at": result.created_at,
                }
                format_output(output, format_type)

    asyncio.run(run())


@results.command("summary")
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def results_summary(db_path: str, format_type: str) -> None:
    """Show result counts by type and validity.

    \b
    Examples:
        ldd-debug results summary run.db
        ldd-debug results summary run.db --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            summary = await debugger.get_result_summary()

            if format_type == "table":
                for result_type, counts in summary.items():
                    click.echo(f"\n{result_type}:")
                    for status, count in counts.items():
                        click.echo(f"  {status}: {count}")
            else:
                format_output(summary, format_type)

    asyncio.run(run())


# =========================================================================
# Requeue Commands
# =========================================================================


@cli.group()
def requeue() -> None:
    """Requeue requests or errors."""
    pass


@requeue.command("request")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("request_id", type=int)
@click.option(
    "--clear-downstream/--no-clear-downstream",
    default=True,
    help="Clear downstream data (responses, results, errors)",
)
def requeue_request(
    db_path: str, request_id: int, clear_downstream: bool
) -> None:
    """Requeue a completed or failed request.

    \b
    Examples:
        ldd-debug requeue request run.db 123
        ldd-debug requeue request run.db 123 --no-clear-downstream
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            try:
                new_id = await debugger.requeue_request(
                    request_id, clear_downstream=clear_downstream
                )
                click.echo(
                    f"Request {request_id} requeued as request {new_id}"
                )
            except ValueError as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


@requeue.command("continuation")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("continuation")
@click.option(
    "--status",
    type=click.Choice(["completed", "failed"]),
    default="completed",
    help="Which requests to requeue",
)
def requeue_continuation(db_path: str, continuation: str, status: str) -> None:
    """Requeue all requests for a continuation with a given status.

    \b
    Examples:
        ldd-debug requeue continuation run.db step1
        ldd-debug requeue continuation run.db step1 --status failed
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            count = await debugger.requeue_continuation(
                continuation,
                status=status,  # type: ignore
            )
            click.echo(
                f"Requeued {count} {status} requests for {continuation}"
            )

    asyncio.run(run())


@requeue.command("errors")
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--type", "error_type", help="Filter by error type")
@click.option("--continuation", help="Filter by continuation (step name)")
def requeue_errors(
    db_path: str, error_type: str | None, continuation: str | None
) -> None:
    """Batch requeue errors matching filter criteria.

    \b
    Examples:
        ldd-debug requeue errors run.db --type xpath
        ldd-debug requeue errors run.db --continuation step1
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            count = await debugger.batch_requeue_errors(
                error_type=error_type, continuation=continuation
            )
            click.echo(f"Requeued {count} errors")

    asyncio.run(run())


# =========================================================================
# Cancel Commands
# =========================================================================


@cli.group()
def cancel() -> None:
    """Cancel pending or held requests."""
    pass


@cancel.command("request")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("request_id", type=int)
def cancel_request(db_path: str, request_id: int) -> None:
    """Cancel a pending or held request.

    \b
    Examples:
        ldd-debug cancel request run.db 123
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            cancelled = await debugger.cancel_request(request_id)

            if cancelled:
                click.echo(f"Request {request_id} cancelled")
            else:
                click.echo(
                    f"Request {request_id} not found or not pending/held",
                    err=True,
                )
                sys.exit(1)

    asyncio.run(run())


@cancel.command("continuation")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("continuation")
def cancel_continuation(db_path: str, continuation: str) -> None:
    """Cancel all pending/held requests for a continuation.

    \b
    Examples:
        ldd-debug cancel continuation run.db step1
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            count = await debugger.cancel_requests_by_continuation(
                continuation
            )
            click.echo(f"Cancelled {count} requests for {continuation}")

    asyncio.run(run())


# =========================================================================
# Compression Commands
# =========================================================================


@cli.group()
def compression() -> None:
    """Inspect and manipulate compression."""
    pass


@compression.command("stats")
@click.argument("db_path", type=click.Path(exists=True))
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def compression_stats(db_path: str, format_type: str) -> None:
    """Show compression statistics.

    \b
    Examples:
        ldd-debug compression stats run.db
        ldd-debug compression stats run.db --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            stats = await debugger.get_compression_stats()

            if format_type == "table":
                click.echo("=== Compression Statistics ===")
                click.echo(f"Total Responses: {stats['total']}")
                click.echo(
                    f"Total Original Size: {stats['total_original']} bytes"
                )
                click.echo(
                    f"Total Compressed Size: {stats['total_compressed']} bytes"
                )
                click.echo(f"With Dict: {stats['with_dict']}")
                click.echo(f"No Dict: {stats['no_dict']}")
                click.echo(
                    f"Compression Ratio: {stats['compression_ratio']:.2f}x"
                )
            else:
                format_output(stats, format_type)

    asyncio.run(run())


@compression.command("train")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("continuation")
@click.option(
    "--samples", default=1000, help="Number of samples to use for training"
)
def compression_train(db_path: str, continuation: str, samples: int) -> None:
    """Train a new compression dictionary for a continuation.

    \b
    Examples:
        ldd-debug compression train run.db step1
        ldd-debug compression train run.db step1 --samples 500
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            try:
                dict_id = await debugger.train_compression_dict(
                    continuation, sample_count=samples
                )
                click.echo(
                    f"Trained compression dictionary {dict_id} for {continuation}"
                )
            except ValueError as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


@compression.command("recompress")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("continuation")
@click.option(
    "--dict-id", type=int, help="Compression dictionary ID (default: latest)"
)
def compression_recompress(
    db_path: str, continuation: str, dict_id: int | None
) -> None:
    """Recompress responses with a compression dictionary.

    \b
    Examples:
        ldd-debug compression recompress run.db step1
        ldd-debug compression recompress run.db step1 --dict-id 5
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(
            db_path, read_only=False
        ) as debugger:
            try:
                stats = await debugger.recompress_responses(
                    continuation, dict_id
                )
                click.echo(f"Recompressed {stats['total']} responses")
                click.echo(f"Size before: {stats['size_before']} bytes")
                click.echo(f"Size after: {stats['size_after']} bytes")
                click.echo(f"Savings: {stats['savings']} bytes")
            except ValueError as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


# =========================================================================
# Diagnose Command
# =========================================================================


@cli.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("error_id", type=int)
@click.option(
    "--format",
    "format_type",
    type=click.Choice(["table", "json", "jsonl"]),
    default="table",
    help="Output format",
)
def diagnose(db_path: str, error_id: int, format_type: str) -> None:
    """Diagnose an error by re-running XPath observation.

    \b
    Examples:
        ldd-debug diagnose run.db 123
        ldd-debug diagnose run.db 123 --format json
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            try:
                result = await debugger.diagnose(error_id)

                if format_type == "table":
                    click.echo("=== Error ===")
                    click.echo(f"ID: {result['error']['id']}")
                    click.echo(f"Type: {result['error']['error_type']}")
                    click.echo(f"Message: {result['error']['message']}")

                    click.echo("\n=== Response ===")
                    click.echo(f"ID: {result['response']['id']}")
                    click.echo(f"Status: {result['response']['status_code']}")
                    click.echo(f"URL: {result['response']['url']}")
                    click.echo(f"Size: {result['response']['size']} bytes")

                    click.echo("\n=== Scraper ===")
                    if result["scraper_info"]["class"]:
                        click.echo(f"Class: {result['scraper_info']['class']}")
                        click.echo(
                            f"Module: {result['scraper_info']['module']}"
                        )

                    click.echo("\n=== Observations ===")
                    for key, value in result["observations"].items():
                        click.echo(f"{key}: {value}")
                else:
                    format_output(result, format_type)
            except (ValueError, ImportError) as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


# =========================================================================
# Export Commands
# =========================================================================


@cli.group()
def export() -> None:
    """Export results and responses."""
    pass


@export.command("jsonl")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
@click.option("--type", "result_type", help="Filter by result type")
@click.option(
    "--valid/--invalid", default=None, help="Filter by validation status"
)
def export_jsonl(
    db_path: str,
    output_path: str,
    result_type: str | None,
    valid: bool | None,
) -> None:
    """Export results to JSONL (newline-delimited JSON) file.

    \b
    Examples:
        ldd-debug export jsonl run.db results.jsonl
        ldd-debug export jsonl run.db opinions.jsonl --type CourtOpinion --valid
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            count = await debugger.export_results_jsonl(
                output_path, result_type=result_type, is_valid=valid
            )
            click.echo(f"Exported {count} results to {output_path}")

    asyncio.run(run())


@export.command("warc")
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
@click.option(
    "--compress/--no-compress",
    default=True,
    help="Gzip-compress the WARC file",
)
@click.option("--continuation", help="Filter by continuation (step name)")
def export_warc(
    db_path: str, output_path: str, compress: bool, continuation: str | None
) -> None:
    """Export responses to WARC (Web ARChive) format.

    \b
    Examples:
        ldd-debug export warc run.db archive.warc.gz
        ldd-debug export warc run.db step1.warc --no-compress --continuation step1
    """

    async def run() -> None:
        async with LocalDevDriverDebugger.open(db_path) as debugger:
            try:
                count = await debugger.export_warc(
                    output_path, compress=compress, continuation=continuation
                )
                click.echo(f"Exported {count} responses to {output_path}")
            except ValueError as e:
                click.echo(str(e), err=True)
                sys.exit(1)

    asyncio.run(run())


# =========================================================================
# Main Entry Point
# =========================================================================


def main() -> None:
    """Main CLI entry point."""
    # Add shell completion support
    cli.add_command(requests)
    cli.add_command(responses)
    cli.add_command(errors)
    cli.add_command(results)
    cli.add_command(requeue)
    cli.add_command(cancel)
    cli.add_command(compression)
    cli.add_command(export)

    cli()


if __name__ == "__main__":
    main()
