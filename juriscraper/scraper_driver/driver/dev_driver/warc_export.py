"""WARC export functionality for LocalDevDriver.

This module provides functionality to export stored responses from the
database to WARC (Web ARChive) format, enabling archival and replay
of HTTP traffic.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


async def export_warc(
    db: aiosqlite.Connection,
    output_path: Path,
    compress: bool = True,
    continuation: str | None = None,
) -> int:
    """Export all responses from database to WARC file.

    Iterates through all stored responses, decompresses them, and
    writes them to a WARC file with request/response record pairs.

    Args:
        db: Database connection.
        output_path: Path for output WARC file. If compress=True and
            path doesn't end with .gz, it will be appended.
        compress: Whether to gzip-compress the WARC file.
        continuation: If specified, only export responses for requests
            with this continuation method.

    Returns:
        Number of responses exported.
    """
    from juriscraper.scraper_driver.driver.dev_driver.compression import (
        decompress_response,
    )

    # Ensure output path has correct extension
    if compress and not str(output_path).endswith(".gz"):
        output_path = Path(str(output_path) + ".gz")

    # Create parent directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build query with optional continuation filter - need request_id for incidental requests
    params: list = []
    if continuation:
        where_clause = "WHERE req.continuation = ?"
        params.append(continuation)
    else:
        where_clause = ""
    # Modified query to include request_id
    query = f"""
        SELECT
            resp.id,
            resp.status_code,
            resp.headers_json,
            resp.url,
            resp.content_compressed,
            resp.compression_dict_id,
            resp.warc_record_id,
            req.method,
            req.url as request_url,
            req.headers_json as request_headers_json,
            req.body,
            req.id as request_id
        FROM responses resp
        JOIN requests req ON resp.request_id = req.id
        {where_clause}
        ORDER BY resp.id
    """

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    if not rows:
        logger.info("No responses to export")
        return 0

    count = 0
    with output_path.open("wb") as f:
        writer = WARCWriter(f, gzip=compress)

        for row in rows:
            (
                response_id,
                status_code,
                headers_json,
                response_url,
                content_compressed,
                compression_dict_id,
                warc_record_id,
                method,
                request_url,
                request_headers_json,
                request_body,
                request_id,
            ) = row

            # Decompress content
            if content_compressed:
                try:
                    content = await decompress_response(
                        db, content_compressed, compression_dict_id
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to decompress response {response_id}: {e}"
                    )
                    continue
            else:
                content = b""

            # Parse response headers
            response_headers = []
            if headers_json:
                headers_dict = json.loads(headers_json)
                response_headers = list(headers_dict.items())

            # Build HTTP response headers
            http_headers = StatusAndHeaders(
                statusline=f"{status_code} OK",
                headers=response_headers,
                protocol="HTTP/1.1",
            )

            # Create response record
            payload_stream = BytesIO(content)
            response_record = writer.create_warc_record(
                uri=response_url,
                record_type="response",
                payload=payload_stream,
                http_headers=http_headers,
                warc_headers_dict={
                    "WARC-Record-ID": f"<urn:uuid:{warc_record_id}>",
                    "X-HTTP-Method": method,
                },
            )
            writer.write_record(response_record)

            # Optionally create request record
            # Parse request headers
            request_headers = []
            if request_headers_json:
                req_headers_dict = json.loads(request_headers_json)
                request_headers = list(req_headers_dict.items())

            # Build HTTP request headers
            request_http_headers = StatusAndHeaders(
                statusline=f"{method} {request_url} HTTP/1.1",
                headers=request_headers,
                protocol="HTTP/1.1",
                is_http_request=True,
            )

            # Create request record
            request_payload = BytesIO(request_body or b"")
            request_record = writer.create_warc_record(
                uri=request_url,
                record_type="request",
                payload=request_payload,
                http_headers=request_http_headers,
                warc_headers_dict={
                    "WARC-Concurrent-To": f"<urn:uuid:{warc_record_id}>",
                },
            )
            writer.write_record(request_record)

            count += 1
            logger.debug(f"Exported response {response_id} ({response_url})")

            # Export incidental requests associated with this parent request
            # Get incidental requests for this parent
            inc_cursor = await db.execute(
                SQL.SELECT_INCIDENTAL_REQUESTS_BY_PARENT, (request_id,)
            )
            inc_rows = await inc_cursor.fetchall()

            for inc_row in inc_rows:
                (
                    inc_id,
                    parent_request_id,
                    resource_type,
                    inc_method,
                    inc_url,
                    inc_headers_json,
                    inc_body,
                    inc_status_code,
                    inc_response_headers_json,
                    inc_content_compressed,
                    inc_content_size_original,
                    inc_content_size_compressed,
                    inc_compression_dict_id,
                    started_at_ns,
                    completed_at_ns,
                    from_cache,
                    failure_reason,
                    created_at,
                ) = inc_row

                # Skip failed incidental requests (no response)
                if not inc_status_code:
                    logger.debug(
                        f"Skipping failed incidental request {inc_id} ({inc_url})"
                    )
                    continue

                # Decompress incidental content if present
                inc_content = b""
                if inc_content_compressed:
                    try:
                        inc_content = await decompress_response(
                            db,
                            inc_content_compressed,
                            inc_compression_dict_id,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to decompress incidental request {inc_id}: {e}"
                        )
                        continue

                # Parse incidental response headers
                inc_response_headers = []
                if inc_response_headers_json:
                    inc_headers_dict = json.loads(inc_response_headers_json)
                    inc_response_headers = list(inc_headers_dict.items())

                # Build HTTP response headers for incidental request
                inc_http_headers = StatusAndHeaders(
                    statusline=f"{inc_status_code} OK",
                    headers=inc_response_headers,
                    protocol="HTTP/1.1",
                )

                # Create response record for incidental request
                inc_payload_stream = BytesIO(inc_content)
                inc_response_record = writer.create_warc_record(
                    uri=inc_url,
                    record_type="response",
                    payload=inc_payload_stream,
                    http_headers=inc_http_headers,
                    warc_headers_dict={
                        "X-HTTP-Method": inc_method,
                        "X-Resource-Type": resource_type,
                        "X-From-Cache": str(from_cache),
                        "X-Parent-WARC-Record-ID": f"<urn:uuid:{warc_record_id}>",
                    },
                )
                writer.write_record(inc_response_record)

                # Create request record for incidental request
                inc_request_headers = []
                if inc_headers_json:
                    inc_req_headers_dict = json.loads(inc_headers_json)
                    inc_request_headers = list(inc_req_headers_dict.items())

                inc_request_http_headers = StatusAndHeaders(
                    statusline=f"{inc_method} {inc_url} HTTP/1.1",
                    headers=inc_request_headers,
                    protocol="HTTP/1.1",
                    is_http_request=True,
                )

                inc_request_payload = BytesIO(inc_body or b"")
                inc_request_record = writer.create_warc_record(
                    uri=inc_url,
                    record_type="request",
                    payload=inc_request_payload,
                    http_headers=inc_request_http_headers,
                    warc_headers_dict={
                        "X-Resource-Type": resource_type,
                        "X-Parent-WARC-Record-ID": f"<urn:uuid:{warc_record_id}>",
                    },
                )
                writer.write_record(inc_request_record)

                logger.debug(
                    f"Exported incidental {resource_type} {inc_id} ({inc_url})"
                )

    logger.info(f"Exported {count} responses to {output_path}")
    return count


async def export_warc_for_continuation(
    db: aiosqlite.Connection,
    continuation: str,
    output_path: Path,
    compress: bool = True,
) -> int:
    """Export responses for a specific continuation to WARC file.

    Args:
        db: Database connection.
        continuation: The continuation method name to filter by.
        output_path: Path for output WARC file.
        compress: Whether to gzip-compress the WARC file.

    Returns:
        Number of responses exported.
    """
    from juriscraper.scraper_driver.driver.dev_driver.compression import (
        decompress_response,
    )

    # Ensure output path has correct extension
    if compress and not str(output_path).endswith(".gz"):
        output_path = Path(str(output_path) + ".gz")

    # Create parent directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Query responses for specific continuation
    cursor = await db.execute(
        SQL.SELECT_RESPONSES_FOR_WARC_BY_CONTINUATION,
        (continuation,),
    )
    rows = await cursor.fetchall()

    if not rows:
        logger.info(f"No responses for continuation '{continuation}'")
        return 0

    count = 0
    with output_path.open("wb") as f:
        writer = WARCWriter(f, gzip=compress)

        for row in rows:
            (
                response_id,
                status_code,
                headers_json,
                response_url,
                content_compressed,
                compression_dict_id,
                warc_record_id,
                method,
                request_url,
                request_headers_json,
                request_body,
            ) = row

            # Decompress content
            if content_compressed:
                try:
                    content = await decompress_response(
                        db, content_compressed, compression_dict_id
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to decompress response {response_id}: {e}"
                    )
                    continue
            else:
                content = b""

            # Parse response headers
            response_headers = []
            if headers_json:
                headers_dict = json.loads(headers_json)
                response_headers = list(headers_dict.items())

            # Build HTTP response headers
            http_headers = StatusAndHeaders(
                statusline=f"{status_code} OK",
                headers=response_headers,
                protocol="HTTP/1.1",
            )

            # Create response record
            payload_stream = BytesIO(content)
            response_record = writer.create_warc_record(
                uri=response_url,
                record_type="response",
                payload=payload_stream,
                http_headers=http_headers,
                warc_headers_dict={
                    "WARC-Record-ID": f"<urn:uuid:{warc_record_id}>",
                    "X-HTTP-Method": method,
                },
            )
            writer.write_record(response_record)
            count += 1

    logger.info(f"Exported {count} responses to {output_path}")
    return count
