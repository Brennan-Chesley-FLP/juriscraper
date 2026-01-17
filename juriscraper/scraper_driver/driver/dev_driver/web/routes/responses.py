"""REST API endpoints for viewing responses within a run.

This module provides endpoints for:
- Listing responses with filters
- Getting response details
- Getting decompressed response content
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
)

router = APIRouter(prefix="/api/runs/{run_id}/responses", tags=["responses"])


class ResponseResponse(BaseModel):
    """Response model for a single HTTP response record."""

    id: int
    request_id: int
    status_code: int
    url: str
    content_size_original: int | None
    content_size_compressed: int | None
    compression_ratio: float | None
    continuation: str
    created_at: str | None
    compression_dict_id: int | None
    speculation_outcome: str | None = (
        None  # 'success', 'stopped', 'skipped', or None
    )


class ResponseListResponse(BaseModel):
    """Response model for listing responses."""

    items: list[ResponseResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


async def _get_sql_manager(run_id: str, manager: RunManager) -> SQLManager:
    """Get SQLManager for a loaded run.

    Args:
        run_id: The run identifier.
        manager: The run manager.

    Returns:
        SQLManager instance.

    Raises:
        HTTPException: 404 if run not found, 400 if not loaded.
    """
    try:
        return await get_sql_manager_for_run(run_id, manager)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


class SpeculationSummaryResponse(BaseModel):
    """Response model for speculation outcome summary."""

    success: int = 0
    stopped: int = 0
    skipped: int = 0
    non_speculative: int = 0
    total: int = 0


@router.get("/speculation-summary", response_model=SpeculationSummaryResponse)
async def get_speculation_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> SpeculationSummaryResponse:
    """Get summary of speculation outcomes for a run.

    Returns counts of:
    - success: Speculative requests that continued (2xx or callback approved)
    - stopped: Speculative requests that stopped (non-2xx, not approved)
    - skipped: Deduplicated speculative requests
    - non_speculative: Regular (non-speculative) requests
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_SPECULATION_SUMMARY_FOR_WEB)
    rows = await cursor.fetchall()

    summary = SpeculationSummaryResponse()
    for outcome, count in rows:
        if outcome == "success":
            summary.success = count
        elif outcome == "stopped":
            summary.stopped = count
        elif outcome == "skipped":
            summary.skipped = count
        elif outcome is None:
            summary.non_speculative = count
        summary.total += count

    return summary


@router.get("", response_model=ResponseListResponse)
async def list_responses(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    continuation: str | None = Query(
        None, description="Filter by continuation"
    ),
    request_id: int | None = Query(None, description="Filter by request ID"),
    speculation_outcome: str | None = Query(
        None,
        description="Filter by speculation outcome: 'success', 'stopped', 'skipped'",
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> ResponseListResponse:
    """List responses for a run with optional filters.

    Args:
        run_id: The run identifier.
        continuation: Optional continuation name filter.
        request_id: Optional request ID filter.
        speculation_outcome: Optional speculation outcome filter.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of responses.
    """
    sql_manager = await _get_sql_manager(run_id, manager)

    page = await sql_manager.list_responses(
        continuation=continuation,
        request_id=request_id,
        speculation_outcome=speculation_outcome,
        offset=offset,
        limit=limit,
    )

    items = [
        ResponseResponse(
            id=r.id,
            request_id=r.request_id,
            status_code=r.status_code,
            url=r.url,
            content_size_original=r.content_size_original,
            content_size_compressed=r.content_size_compressed,
            compression_ratio=r.compression_ratio,
            continuation=r.continuation,
            created_at=r.created_at,
            compression_dict_id=r.compression_dict_id,
            speculation_outcome=r.speculation_outcome,
        )
        for r in page.items
    ]

    return ResponseListResponse(
        items=items,
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        has_more=page.has_more,
    )


@router.get("/{response_id}", response_model=ResponseResponse)
async def get_response(
    run_id: str,
    response_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ResponseResponse:
    """Get details for a specific response.

    Args:
        run_id: The run identifier.
        response_id: The response ID.

    Returns:
        Response details (excluding content).

    Raises:
        HTTPException: 404 if response not found.
    """
    sql_manager = await _get_sql_manager(run_id, manager)

    record = await sql_manager.get_response(response_id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} not found in run '{run_id}'",
        )

    return ResponseResponse(
        id=record.id,
        request_id=record.request_id,
        status_code=record.status_code,
        url=record.url,
        content_size_original=record.content_size_original,
        content_size_compressed=record.content_size_compressed,
        compression_ratio=record.compression_ratio,
        continuation=record.continuation,
        created_at=record.created_at,
        compression_dict_id=record.compression_dict_id,
        speculation_outcome=record.speculation_outcome,
    )


@router.get("/{response_id}/content")
async def get_response_content(
    run_id: str,
    response_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> Response:
    """Get decompressed content for a response.

    Args:
        run_id: The run identifier.
        response_id: The response ID.

    Returns:
        Decompressed content as raw bytes.

    Raises:
        HTTPException: 404 if response not found.
        HTTPException: 500 if decompression fails.
    """
    import json

    sql_manager = await _get_sql_manager(run_id, manager)

    try:
        result = await sql_manager.get_response_content_with_headers(
            response_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decompress content: {e}",
        ) from e

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} not found in run '{run_id}'",
        )

    content, headers_json = result

    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} has no content",
        )

    # Try to get content-type from headers
    content_type = "application/octet-stream"
    if headers_json:
        try:
            headers = json.loads(headers_json)
            if isinstance(headers, dict):
                for key, value in headers.items():
                    if key.lower() == "content-type":
                        content_type = value
                        break
        except json.JSONDecodeError:
            pass

    return Response(content=content, media_type=content_type)
