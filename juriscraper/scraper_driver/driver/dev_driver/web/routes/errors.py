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

    requeued_count: int
    new_request_ids: list[int]
    message: str


class BatchRequeueRequest(BaseModel):
    """Request model for batch requeue."""

    error_type: str | None = Field(None, description="Filter by error type")
    continuation: str | None = Field(
        None, description="Filter by continuation"
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
) -> RequeueResponse:
    """Requeue the request that caused this error.

    Creates a new pending request with the same parameters as the
    original request, and marks the error as resolved.

    Args:
        run_id: The run identifier.
        error_id: The error ID.

    Returns:
        Requeue result with new request ID.

    Raises:
        HTTPException: 404 if error not found or has no linked request.
    """
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        get_next_queue_counter,
    )

    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Get error and linked request
    cursor = await db.execute(SQL.SELECT_ERROR_FOR_WEB_REQUEUE, (error_id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error {error_id} not found",
        )

    if row[1] is None or row[2] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error {error_id} has no linked request to requeue",
        )

    # Create new request
    queue_counter = await get_next_queue_counter(db)

    await db.execute(
        SQL.INSERT_REQUEUE_REQUEST,
        (
            row[5],  # priority
            queue_counter,
            row[2],  # method
            row[3],  # url
            row[6],  # headers_json
            row[7],  # cookies_json
            row[8],  # body
            row[4],  # continuation
            row[9],  # current_location
            row[10],  # accumulated_data_json
            row[11],  # aux_data_json
            row[12],  # permanent_json
            row[1],  # parent_request_id (original request)
        ),
    )

    cursor = await db.execute(SQL.SELECT_LAST_INSERT_ROWID)
    new_id_row = await cursor.fetchone()
    new_request_id = new_id_row[0]

    # Mark error as resolved
    await db.execute(
        SQL.UPDATE_RESOLVE_ERROR_FOR_WEB,
        (f"Requeued as request {new_request_id}", error_id),
    )

    await db.commit()

    return RequeueResponse(
        requeued_count=1,
        new_request_ids=[new_request_id],
        message=f"Requeued error {error_id} as request {new_request_id}",
    )


@router.post("/batch-requeue", response_model=RequeueResponse)
async def batch_requeue(
    run_id: str,
    request: BatchRequeueRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequeueResponse:
    """Batch requeue errors by type or continuation.

    Args:
        run_id: The run identifier.
        request: Filter criteria for errors to requeue.

    Returns:
        Requeue result with all new request IDs.

    Raises:
        HTTPException: 400 if no filter criteria provided.
    """
    if not request.error_type and not request.continuation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify error_type or continuation filter",
        )

    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        get_next_queue_counter,
    )

    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Build conditions for finding errors
    conditions = ["is_resolved = FALSE", "request_id IS NOT NULL"]
    params: list = []

    if request.error_type:
        conditions.append("e.error_type = ?")
        params.append(request.error_type)

    # For continuation filter, need to join with requests
    join_clause = "LEFT JOIN requests r ON e.request_id = r.id"
    if request.continuation:
        conditions.append("r.continuation = ?")
        params.append(request.continuation)

    where_clause = f"WHERE {' AND '.join(conditions)}"

    # Get all matching errors with their request data
    cursor = await db.execute(
        f"""
        SELECT e.id, e.request_id, r.method, r.url, r.continuation,
               r.priority, r.headers_json, r.cookies_json, r.body,
               r.current_location, r.accumulated_data_json, r.aux_data_json,
               r.permanent_json
        FROM errors e
        {join_clause}
        {where_clause}
        """,
        params,
    )
    rows = await cursor.fetchall()

    if not rows:
        return RequeueResponse(
            requeued_count=0,
            new_request_ids=[],
            message="No matching errors to requeue",
        )

    new_request_ids = []
    error_ids = []

    for row in rows:
        queue_counter = await get_next_queue_counter(db)

        await db.execute(
            SQL.INSERT_REQUEUE_REQUEST,
            (
                row[5],  # priority
                queue_counter,
                row[2],  # method
                row[3],  # url
                row[6],  # headers_json
                row[7],  # cookies_json
                row[8],  # body
                row[4],  # continuation
                row[9],  # current_location
                row[10],  # accumulated_data_json
                row[11],  # aux_data_json
                row[12],  # permanent_json
                row[1],  # parent_request_id
            ),
        )

        cursor = await db.execute(SQL.SELECT_LAST_INSERT_ROWID)
        new_id_row = await cursor.fetchone()
        new_request_ids.append(new_id_row[0])
        error_ids.append(row[0])

    # Mark all errors as resolved
    placeholders = ",".join("?" * len(error_ids))
    await db.execute(
        f"""
        UPDATE errors
        SET is_resolved = TRUE,
            resolved_at = CURRENT_TIMESTAMP,
            resolution_notes = 'Batch requeued'
        WHERE id IN ({placeholders})
        """,
        error_ids,
    )

    await db.commit()

    return RequeueResponse(
        requeued_count=len(new_request_ids),
        new_request_ids=new_request_ids,
        message=f"Batch requeued {len(new_request_ids)} errors",
    )
