"""REST API endpoints for viewing results within a run.

This module provides endpoints for:
- Listing results with filters
- Getting result details including full data
- Summary statistics by result type with valid/invalid counts
- JSONL export for bulk data download
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
)

router = APIRouter(prefix="/api/runs/{run_id}/results", tags=["results"])


class ResultResponse(BaseModel):
    """Response model for a single result."""

    id: int
    request_id: int | None
    result_type: str
    is_valid: bool
    created_at: str | None


class ResultWithDataResponse(ResultResponse):
    """Response model for a result with full data."""

    data: dict[str, Any]
    validation_errors: list[dict[str, Any]] | None


class ResultListResponse(BaseModel):
    """Response model for listing results."""

    items: list[ResultResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


class ResultTypeSummaryItem(BaseModel):
    """Summary stats for a single result type."""

    result_type: str
    valid_count: int
    invalid_count: int
    total_count: int


class ResultsSummaryResponse(BaseModel):
    """Response model for results summary statistics."""

    total_valid: int
    total_invalid: int
    total: int
    by_type: list[ResultTypeSummaryItem]


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


@router.get("", response_model=ResultListResponse)
async def list_results(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    result_type: str | None = Query(None, description="Filter by result type"),
    is_valid: bool | None = Query(
        None, description="Filter by validation status"
    ),
    request_id: int | None = Query(None, description="Filter by request ID"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> ResultListResponse:
    """List results for a run with optional filters.

    Args:
        run_id: The run identifier.
        result_type: Optional result type filter.
        is_valid: Optional validation status filter.
        request_id: Optional request ID filter.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of results.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query
    conditions = []
    params: list = []

    if result_type:
        conditions.append("result_type = ?")
        params.append(result_type)
    if is_valid is not None:
        conditions.append("is_valid = ?")
        params.append(is_valid)
    if request_id:
        conditions.append("request_id = ?")
        params.append(request_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count
    cursor = await db.execute(
        SQL.count_table(
            "results", " AND ".join(conditions) if conditions else ""
        ),
        params,
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get paginated results (without full data for list view)
    cursor = await db.execute(
        SQL.SELECT_RESULTS_LIST_FOR_WEB.format(where_clause=where_clause),
        params + [limit, offset],
    )
    rows = await cursor.fetchall()

    items = [
        ResultResponse(
            id=r[0],
            request_id=r[1],
            result_type=r[2],
            is_valid=bool(r[3]),
            created_at=r[4],
        )
        for r in rows
    ]

    return ResultListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


# NOTE: Literal path routes must be defined BEFORE parameterized routes
# to ensure FastAPI matches them correctly (e.g., /summary before /{result_id})


@router.get("/types/summary")
async def get_result_type_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> dict[str, int]:
    """Get a summary of result counts by type.

    Args:
        run_id: The run identifier.

    Returns:
        Dictionary mapping result types to their counts.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(SQL.SELECT_RESULT_TYPE_SUMMARY)
    rows = await cursor.fetchall()

    return {r[0]: r[1] for r in rows}


@router.get("/summary", response_model=ResultsSummaryResponse)
async def get_results_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ResultsSummaryResponse:
    """Get summary statistics for results including valid/invalid counts by type.

    Args:
        run_id: The run identifier.

    Returns:
        Summary with total counts and breakdown by result type.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(SQL.SELECT_RESULTS_SUMMARY_FOR_WEB)
    rows = await cursor.fetchall()

    by_type: list[ResultTypeSummaryItem] = []
    total_valid = 0
    total_invalid = 0

    for result_type, valid_count, invalid_count, total_count in rows:
        by_type.append(
            ResultTypeSummaryItem(
                result_type=result_type,
                valid_count=valid_count,
                invalid_count=invalid_count,
                total_count=total_count,
            )
        )
        total_valid += valid_count
        total_invalid += invalid_count

    return ResultsSummaryResponse(
        total_valid=total_valid,
        total_invalid=total_invalid,
        total=total_valid + total_invalid,
        by_type=by_type,
    )


@router.get("/export.jsonl")
async def export_results_jsonl(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    result_type: str | None = Query(None, description="Filter by result type"),
    is_valid: bool | None = Query(
        None, description="Filter by validation status"
    ),
) -> StreamingResponse:
    """Export results as JSONL (newline-delimited JSON) for bulk download.

    Each line is a valid JSON object containing result data. This format
    is efficient for large datasets and can be processed line-by-line.

    Args:
        run_id: The run identifier.
        result_type: Optional filter by result type.
        is_valid: Optional filter by validation status.

    Returns:
        Streaming JSONL response with Content-Disposition for download.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build where clause
    conditions = []
    params: list = []

    if result_type:
        conditions.append("result_type = ?")
        params.append(result_type)
    if is_valid is not None:
        conditions.append("is_valid = ?")
        params.append(is_valid)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def generate_jsonl() -> AsyncGenerator[bytes, None]:
        """Stream results as JSONL."""
        cursor = await db.execute(
            SQL.SELECT_RESULTS_FOR_EXPORT.format(where_clause=where_clause),
            params,
        )

        async for row in cursor:
            (
                result_id,
                request_id,
                rtype,
                data_json,
                valid,
                errors_json,
                created_at,
            ) = row

            # Parse JSON fields
            try:
                data = json.loads(data_json) if data_json else {}
            except json.JSONDecodeError:
                data = {}

            validation_errors = None
            if errors_json:
                try:
                    validation_errors = json.loads(errors_json)
                except json.JSONDecodeError:
                    pass

            record = {
                "id": result_id,
                "request_id": request_id,
                "result_type": rtype,
                "is_valid": bool(valid),
                "data": data,
                "validation_errors": validation_errors,
                "created_at": created_at,
            }
            yield (json.dumps(record) + "\n").encode("utf-8")

    # Build filename with optional filters
    filename_parts = [run_id, "results"]
    if result_type:
        filename_parts.append(result_type)
    if is_valid is not None:
        filename_parts.append("valid" if is_valid else "invalid")
    filename = "-".join(filename_parts) + ".jsonl"

    return StreamingResponse(
        generate_jsonl(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# Parameterized route must come LAST to avoid matching literal paths like /summary
@router.get("/{result_id}", response_model=ResultWithDataResponse)
async def get_result(
    run_id: str,
    result_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ResultWithDataResponse:
    """Get full details for a specific result including data.

    Args:
        run_id: The run identifier.
        result_id: The result ID.

    Returns:
        Full result details including data and validation errors.

    Raises:
        HTTPException: 404 if result not found.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(
        SQL.SELECT_RESULT_WITH_DATA_FOR_WEB, (result_id,)
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result {result_id} not found in run '{run_id}'",
        )

    # Parse JSON data
    try:
        data = json.loads(row[3]) if row[3] else {}
    except json.JSONDecodeError:
        data = {}

    # Parse validation errors
    validation_errors = None
    if row[5]:
        try:
            validation_errors = json.loads(row[5])
        except json.JSONDecodeError:
            validation_errors = None

    return ResultWithDataResponse(
        id=row[0],
        request_id=row[1],
        result_type=row[2],
        is_valid=bool(row[4]),
        created_at=row[6],
        data=data,
        validation_errors=validation_errors,
    )
