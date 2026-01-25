"""REST API endpoints for error management within a run.

This module provides endpoints for:
- Listing errors with filters
- Getting error details
- Requeuing individual errors
- Batch requeuing by type or continuation
- Resolving errors
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
)

router = APIRouter(prefix="/api/runs/{run_id}/errors", tags=["errors"])


class ErrorResponse(BaseModel):
    """Response model for a single error."""

    id: int
    request_id: int | None
    error_type: str
    error_class: str
    message: str
    request_url: str
    is_resolved: bool
    resolved_at: str | None
    resolution_notes: str | None
    created_at: str | None
    # Type-specific fields
    selector: str | None = None
    selector_type: str | None = None
    expected_min: int | None = None
    expected_max: int | None = None
    actual_count: int | None = None
    model_name: str | None = None
    status_code: int | None = None
    timeout_seconds: float | None = None
    # Full details
    traceback: str | None = None
    context: dict[str, Any] | None = None
    validation_errors: list[dict[str, Any]] | None = None
    failed_doc: dict[str, Any] | None = None


class ErrorListResponse(BaseModel):
    """Response model for listing errors."""

    items: list[ErrorResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


class ResolveRequest(BaseModel):
    """Request model for resolving an error."""

    notes: str = Field(default="", description="Resolution notes")


class RequeueResponse(BaseModel):
    """Response model for requeue operations."""

    requeued_request_ids: list[int]
    cleared_response_ids: list[int] = []
    cleared_downstream_request_ids: list[int] = []
    cleared_result_ids: list[int] = []
    cleared_error_ids: list[int] = []
    resolved_error_ids: list[int] = []
    dry_run: bool = False
    message: str


class BatchRequeueRequest(BaseModel):
    """Request model for batch requeue."""

    continuation: str = Field(..., description="Continuation to filter by")
    error_type: str | None = Field(None, description="Filter by error type")
    traceback_contains: str | None = Field(
        None, description="Filter by traceback substring"
    )


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


def _row_to_error(row) -> ErrorResponse:
    """Convert a database row to ErrorResponse.

    Row format from SELECT_ERRORS_PAGE_FOR_WEB / SELECT_ERROR_BY_ID_FOR_WEB:
    0: id, 1: request_id, 2: error_type, 3: error_class, 4: message,
    5: request_url, 6: is_resolved, 7: resolved_at, 8: resolution_notes,
    9: created_at, 10: selector, 11: selector_type, 12: expected_min,
    13: expected_max, 14: actual_count, 15: model_name, 16: status_code,
    17: timeout_seconds, 18: traceback, 19: context_json,
    20: validation_errors_json, 21: failed_doc_json
    """
    import json

    # Parse JSON fields
    context = None
    if row[19]:
        try:
            context = json.loads(row[19])
        except (json.JSONDecodeError, TypeError):
            pass

    validation_errors = None
    if row[20]:
        try:
            validation_errors = json.loads(row[20])
        except (json.JSONDecodeError, TypeError):
            pass

    failed_doc = None
    if row[21]:
        try:
            failed_doc = json.loads(row[21])
        except (json.JSONDecodeError, TypeError):
            pass

    return ErrorResponse(
        id=row[0],
        request_id=row[1],
        error_type=row[2],
        error_class=row[3],
        message=row[4],
        request_url=row[5],
        is_resolved=bool(row[6]),
        resolved_at=row[7],
        resolution_notes=row[8],
        created_at=row[9],
        selector=row[10],
        selector_type=row[11],
        expected_min=row[12],
        expected_max=row[13],
        actual_count=row[14],
        model_name=row[15],
        status_code=row[16],
        timeout_seconds=row[17],
        traceback=row[18],
        context=context,
        validation_errors=validation_errors,
        failed_doc=failed_doc,
    )


@router.get("/summary")
async def get_error_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> dict[str, Any]:
    """Get a summary of error counts by type and resolution status.

    Args:
        run_id: The run identifier.

    Returns:
        Summary with counts by type and resolution status.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Get counts by type
    cursor = await db.execute(SQL.SELECT_ERROR_SUMMARY_FOR_WEB)
    rows = await cursor.fetchall()

    by_type: dict[str, dict[str, int]] = {}
    total_resolved = 0
    total_unresolved = 0

    for error_type, is_resolved, count in rows:
        if error_type not in by_type:
            by_type[error_type] = {"resolved": 0, "unresolved": 0}
        key = "resolved" if is_resolved else "unresolved"
        by_type[error_type][key] = count
        if is_resolved:
            total_resolved += count
        else:
            total_unresolved += count

    return {
        "total": total_resolved + total_unresolved,
        "resolved": total_resolved,
        "unresolved": total_unresolved,
        "by_type": by_type,
    }


@router.get("", response_model=ErrorListResponse)
async def list_errors(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    error_type: str | None = Query(None, description="Filter by error type"),
    unresolved_only: bool = Query(
        True, description="Only show unresolved errors"
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> ErrorListResponse:
    """List errors for a run with optional filters.

    Args:
        run_id: The run identifier.
        error_type: Optional error type filter (structural, validation, transient).
        unresolved_only: If True, only show unresolved errors.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of errors.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Build query
    conditions = []
    params: list = []

    if error_type:
        conditions.append("error_type = ?")
        params.append(error_type)
    if unresolved_only:
        conditions.append("is_resolved = FALSE")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM errors {where_clause}", params
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get paginated results
    query = SQL.SELECT_ERRORS_PAGE_FOR_WEB.format(where_clause=where_clause)
    cursor = await db.execute(query, params + [limit, offset])
    rows = await cursor.fetchall()

    items = [_row_to_error(r) for r in rows]

    return ErrorListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


@router.get("/{error_id}", response_model=ErrorResponse)
async def get_error(
    run_id: str,
    error_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ErrorResponse:
    """Get details for a specific error.

    Args:
        run_id: The run identifier.
        error_id: The error ID.

    Returns:
        Error details.

    Raises:
        HTTPException: 404 if error not found.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_ERROR_BY_ID_FOR_WEB, (error_id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error {error_id} not found in run '{run_id}'",
        )

    return _row_to_error(row)


@router.post("/{error_id}/resolve", response_model=ErrorResponse)
async def resolve_error(
    run_id: str,
    error_id: int,
    request: ResolveRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ErrorResponse:
    """Mark an error as resolved.

    Args:
        run_id: The run identifier.
        error_id: The error ID.
        request: Resolution details.

    Returns:
        Updated error details.

    Raises:
        HTTPException: 404 if error not found.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(
        SQL.UPDATE_RESOLVE_ERROR_FOR_WEB, (request.notes, error_id)
    )
    await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error {error_id} not found",
        )

    # Return updated error
    return await get_error(run_id, error_id, manager)


@router.post("/{error_id}/requeue", response_model=RequeueResponse)
async def requeue_error(
    run_id: str,
    error_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    mark_resolved: bool = Query(True, description="Mark error as resolved"),
    clear_responses: bool = Query(
        False, description="Clear responses to force re-fetch"
    ),
    clear_downstream: bool = Query(
        False, description="Clear all downstream artifacts"
    ),
    dry_run: bool = Query(
        False, description="Preview changes without executing"
    ),
) -> RequeueResponse:
    """Requeue the request that caused this error.

    Creates a new pending request with the same parameters as the
    original request. By default, marks the error as resolved.

    Args:
        run_id: The run identifier.
        error_id: The error ID.
        mark_resolved: If True, mark error as resolved after requeuing.
        clear_responses: If True, delete responses to force re-fetch.
        clear_downstream: If True, recursively delete downstream artifacts.
        dry_run: If True, report what would happen without making changes.

    Returns:
        Requeue result with affected IDs.

    Raises:
        HTTPException: 404 if error not found or has no linked request.
    """
    sql_manager = await _get_sql_manager(run_id, manager)

    # Use new requeue_error method
    result = await sql_manager.requeue_error(
        error_id,
        mark_resolved=mark_resolved,
        clear_responses=clear_responses,
        clear_downstream=clear_downstream,
        dry_run=dry_run,
    )

    if not result.requeued_request_ids:
        # Error not found or has no linked request
        db = sql_manager.db
        cursor = await db.execute(
            "SELECT id, request_id FROM errors WHERE id = ?", (error_id,)
        )
        row = await cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Error {error_id} not found",
            )
        if row[1] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error {error_id} has no linked request to requeue",
            )

    new_request_id = (
        result.requeued_request_ids[0] if result.requeued_request_ids else None
    )
    message = f"Requeued error {error_id}"
    if new_request_id:
        message += f" as request {new_request_id}"
    if dry_run:
        message = f"[DRY RUN] {message}"

    return RequeueResponse(
        requeued_request_ids=result.requeued_request_ids,
        cleared_response_ids=result.cleared_response_ids,
        cleared_downstream_request_ids=result.cleared_downstream_request_ids,
        cleared_result_ids=result.cleared_result_ids,
        cleared_error_ids=result.cleared_error_ids,
        resolved_error_ids=result.resolved_error_ids,
        dry_run=result.dry_run,
        message=message,
    )


@router.post("/batch-requeue", response_model=RequeueResponse)
async def batch_requeue(
    run_id: str,
    request: BatchRequeueRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    clear_responses: bool = Query(
        False, description="Clear responses to force re-fetch"
    ),
    clear_downstream: bool = Query(
        False, description="Clear all downstream artifacts"
    ),
    dry_run: bool = Query(
        False, description="Preview changes without executing"
    ),
) -> RequeueResponse:
    """Batch requeue errors by continuation with optional filtering.

    Requeues all completed requests for a continuation, optionally filtering
    to only those with specific types of errors or traceback content.

    Args:
        run_id: The run identifier.
        request: Filter criteria (continuation required, error_type and traceback_contains optional).
        clear_responses: If True, delete responses to force re-fetch.
        clear_downstream: If True, recursively delete downstream artifacts.
        dry_run: If True, report what would happen without making changes.

    Returns:
        Requeue result with affected IDs.
    """
    sql_manager = await _get_sql_manager(run_id, manager)

    # Use new requeue_continuation method with optional error filtering
    result = await sql_manager.requeue_continuation(
        request.continuation,
        error_type=request.error_type,
        traceback_contains=request.traceback_contains,
        clear_responses=clear_responses,
        clear_downstream=clear_downstream,
        dry_run=dry_run,
    )

    filters = []
    if request.error_type:
        filters.append(f"error_type={request.error_type}")
    if request.traceback_contains:
        filters.append(f"traceback contains '{request.traceback_contains}'")

    message = f"Batch requeued {len(result.requeued_request_ids)} requests"
    message += f" with continuation '{request.continuation}'"
    if filters:
        message += f" (filters: {', '.join(filters)})"
    if dry_run:
        message = f"[DRY RUN] {message}"

    return RequeueResponse(
        requeued_request_ids=result.requeued_request_ids,
        cleared_response_ids=result.cleared_response_ids,
        cleared_downstream_request_ids=result.cleared_downstream_request_ids,
        cleared_result_ids=result.cleared_result_ids,
        cleared_error_ids=result.cleared_error_ids,
        resolved_error_ids=result.resolved_error_ids,
        dry_run=result.dry_run,
        message=message,
    )
