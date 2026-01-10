"""REST API endpoints for viewing results within a run.

This module provides endpoints for:
- Listing results with filters
- Getting result details including full data
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
