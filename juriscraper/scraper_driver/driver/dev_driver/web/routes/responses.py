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

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
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


class ResponseListResponse(BaseModel):
    """Response model for listing responses."""

    items: list[ResponseResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


async def _get_db_for_run(run_id: str, manager: RunManager):
    """Get database connection for a loaded run.

    Args:
        run_id: The run identifier.
        manager: The run manager.

    Returns:
        Database connection.

    Raises:
        HTTPException: 404 if run not found, 400 if not loaded.
    """
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    if run_info.driver is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' is not loaded. Load it first.",
        )
    return run_info.driver._db


def _calculate_ratio(
    original: int | None, compressed: int | None
) -> float | None:
    """Calculate compression ratio."""
    if original and compressed and compressed > 0:
        return round(original / compressed, 2)
    return None


@router.get("", response_model=ResponseListResponse)
async def list_responses(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    continuation: str | None = Query(
        None, description="Filter by continuation"
    ),
    request_id: int | None = Query(None, description="Filter by request ID"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> ResponseListResponse:
    """List responses for a run with optional filters.

    Args:
        run_id: The run identifier.
        continuation: Optional continuation name filter.
        request_id: Optional request ID filter.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of responses.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query
    conditions = []
    params: list = []

    if continuation:
        conditions.append("continuation = ?")
        params.append(continuation)
    if request_id:
        conditions.append("request_id = ?")
        params.append(request_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count
    cursor = await db.execute(
        SQL.count_table(
            "responses", " AND ".join(conditions) if conditions else ""
        ),
        params,
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get paginated results
    cursor = await db.execute(
        SQL.SELECT_RESPONSES_LIST_FOR_WEB.format(where_clause=where_clause),
        params + [limit, offset],
    )
    rows = await cursor.fetchall()

    items = [
        ResponseResponse(
            id=r[0],
            request_id=r[1],
            status_code=r[2],
            url=r[3],
            content_size_original=r[4],
            content_size_compressed=r[5],
            compression_ratio=_calculate_ratio(r[4], r[5]),
            continuation=r[6],
            created_at=r[7],
            compression_dict_id=r[8],
        )
        for r in rows
    ]

    return ResponseListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
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
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(
        SQL.SELECT_RESPONSE_BY_ID_FOR_WEB, (response_id,)
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} not found in run '{run_id}'",
        )

    return ResponseResponse(
        id=row[0],
        request_id=row[1],
        status_code=row[2],
        url=row[3],
        content_size_original=row[4],
        content_size_compressed=row[5],
        compression_ratio=_calculate_ratio(row[4], row[5]),
        continuation=row[6],
        created_at=row[7],
        compression_dict_id=row[8],
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
    from juriscraper.scraper_driver.driver.dev_driver.compression import (
        decompress_response,
    )

    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(
        SQL.SELECT_RESPONSE_CONTENT_FOR_WEB, (response_id,)
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} not found in run '{run_id}'",
        )

    compressed_content, dict_id, headers_json = row

    if compressed_content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Response {response_id} has no content",
        )

    try:
        content = await decompress_response(db, compressed_content, dict_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decompress content: {e}",
        ) from e

    # Try to get content-type from headers
    content_type = "application/octet-stream"
    if headers_json:
        import json

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
