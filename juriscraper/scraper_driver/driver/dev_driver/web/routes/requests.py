"""REST API endpoints for managing requests within a run.

This module provides endpoints for:
- Listing requests with filters
- Getting request details
- Cancelling individual requests
- Batch cancelling requests by continuation
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
)

router = APIRouter(prefix="/api/runs/{run_id}/requests", tags=["requests"])


class RequestResponse(BaseModel):
    """Response model for a single request."""

    id: int
    status: str
    priority: int
    queue_counter: int
    method: str
    url: str
    continuation: str
    current_location: str
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    retry_count: int
    cumulative_backoff: float
    last_error: str | None


class RequestListResponse(BaseModel):
    """Response model for listing requests."""

    items: list[RequestResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


class CancelResponse(BaseModel):
    """Response model for cancel operations."""

    cancelled_count: int
    message: str


class RequeueResponse(BaseModel):
    """Response model for requeue operations."""

    requeued_count: int
    new_request_id: int
    message: str


class CancelByContinuationRequest(BaseModel):
    """Request model for batch cancellation."""

    continuation: str = Field(..., description="Continuation to filter by")


class RequestSummaryItem(BaseModel):
    """Summary counts for a single continuation."""

    continuation: str
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    held: int = 0
    cancelled: int = 0
    total: int = 0


class RequestSummaryResponse(BaseModel):
    """Response model for request summary endpoint."""

    items: list[RequestSummaryItem]
    grand_total: int


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
            detail=f"Run '{run_id}' is not loaded. Load it first with POST /api/runs/{run_id}/load",
        )
    return run_info.driver._db


@router.get("", response_model=RequestListResponse)
async def list_requests(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    status_filter: str | None = Query(
        None, alias="status", description="Filter by status"
    ),
    continuation: str | None = Query(
        None, description="Filter by continuation"
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> RequestListResponse:
    """List requests for a run with optional filters.

    Args:
        run_id: The run identifier.
        status_filter: Optional status filter (pending, in_progress, completed, failed, held).
        continuation: Optional continuation name filter.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of requests.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query
    conditions = []
    params: list = []

    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    if continuation:
        conditions.append("continuation = ?")
        params.append(continuation)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM requests {where_clause}", params
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get paginated results
    query = SQL.SELECT_REQUESTS_LIST_FOR_WEB.format(where_clause=where_clause)
    cursor = await db.execute(query, params + [limit, offset])
    rows = await cursor.fetchall()

    items = [
        RequestResponse(
            id=r[0],
            status=r[1],
            priority=r[2],
            queue_counter=r[3],
            method=r[4],
            url=r[5],
            continuation=r[6],
            current_location=r[7],
            created_at=r[8],
            started_at=r[9],
            completed_at=r[10],
            retry_count=r[11],
            cumulative_backoff=r[12],
            last_error=r[13],
        )
        for r in rows
    ]

    return RequestListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


@router.get("/summary", response_model=RequestSummaryResponse)
async def get_request_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequestSummaryResponse:
    """Get request counts grouped by continuation and status.

    Returns a pivot table with one row per continuation, showing counts
    for each status (pending, in_progress, completed, failed, held, cancelled).

    Args:
        run_id: The run identifier.

    Returns:
        Summary of request counts by continuation and status.
    """
    db = await _get_db_for_run(run_id, manager)

    # Query counts grouped by continuation and status
    query = """
        SELECT continuation, status, COUNT(*) as count
        FROM requests
        GROUP BY continuation, status
        ORDER BY continuation
    """
    cursor = await db.execute(query)
    rows = await cursor.fetchall()

    # Build pivot table
    summaries: dict[str, RequestSummaryItem] = {}
    grand_total = 0

    for continuation, status_val, count in rows:
        if continuation not in summaries:
            summaries[continuation] = RequestSummaryItem(
                continuation=continuation
            )

        item = summaries[continuation]
        grand_total += count
        item.total += count

        # Map status to field
        if status_val == "pending":
            item.pending = count
        elif status_val == "in_progress":
            item.in_progress = count
        elif status_val == "completed":
            item.completed = count
        elif status_val == "failed":
            item.failed = count
        elif status_val == "held":
            item.held = count
        elif status_val == "cancelled":
            item.cancelled = count

    return RequestSummaryResponse(
        items=list(summaries.values()),
        grand_total=grand_total,
    )


@router.get("/{request_id}", response_model=RequestResponse)
async def get_request(
    run_id: str,
    request_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequestResponse:
    """Get details for a specific request.

    Args:
        run_id: The run identifier.
        request_id: The request ID.

    Returns:
        Request details.

    Raises:
        HTTPException: 404 if request not found.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(SQL.SELECT_REQUEST_BY_ID_FOR_WEB, (request_id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found in run '{run_id}'",
        )

    return RequestResponse(
        id=row[0],
        status=row[1],
        priority=row[2],
        queue_counter=row[3],
        method=row[4],
        url=row[5],
        continuation=row[6],
        current_location=row[7],
        created_at=row[8],
        started_at=row[9],
        completed_at=row[10],
        retry_count=row[11],
        cumulative_backoff=row[12],
        last_error=row[13],
    )


@router.post("/{request_id}/cancel", response_model=CancelResponse)
async def cancel_request(
    run_id: str,
    request_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> CancelResponse:
    """Cancel a pending or held request.

    Args:
        run_id: The run identifier.
        request_id: The request ID to cancel.

    Returns:
        Cancellation result.

    Raises:
        HTTPException: 404 if request not found.
        HTTPException: 400 if request cannot be cancelled.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(SQL.UPDATE_CANCEL_REQUEST_FOR_WEB, (request_id,))
    await db.commit()

    if cursor.rowcount == 0:
        # Check if request exists
        cursor = await db.execute(SQL.SELECT_REQUEST_STATUS, (request_id,))
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request {request_id} not found",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request {request_id} cannot be cancelled (status: {row[0]})",
        )

    return CancelResponse(
        cancelled_count=1,
        message=f"Request {request_id} cancelled",
    )


@router.post("/{request_id}/requeue", response_model=RequeueResponse)
async def requeue_request(
    run_id: str,
    request_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequeueResponse:
    """Requeue a failed or completed request.

    Creates a new pending request with the same parameters as the
    original request.

    Args:
        run_id: The run identifier.
        request_id: The request ID to requeue.

    Returns:
        Requeue result with new request ID.

    Raises:
        HTTPException: 404 if request not found.
    """
    from juriscraper.scraper_driver.driver.dev_driver.schema import (
        get_next_queue_counter,
    )

    db = await _get_db_for_run(run_id, manager)

    # Get request data
    cursor = await db.execute(
        SQL.SELECT_REQUEST_FOR_WEB_REQUEUE, (request_id,)
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found",
        )

    # Create new request
    queue_counter = await get_next_queue_counter(db)

    await db.execute(
        SQL.INSERT_REQUEUE_REQUEST,
        (
            row[4],  # priority
            queue_counter,
            row[1],  # method
            row[2],  # url
            row[5],  # headers_json
            row[6],  # cookies_json
            row[7],  # body
            row[3],  # continuation
            row[8],  # current_location
            row[9],  # accumulated_data_json
            row[10],  # aux_data_json
            row[11],  # permanent_json
            row[0],  # parent_request_id (original request)
        ),
    )

    cursor = await db.execute(SQL.SELECT_LAST_INSERT_ROWID)
    new_id_row = await cursor.fetchone()
    new_request_id = new_id_row[0]

    await db.commit()

    return RequeueResponse(
        requeued_count=1,
        new_request_id=new_request_id,
        message=f"Requeued request {request_id} as request {new_request_id}",
    )


@router.post("/cancel-by-continuation", response_model=CancelResponse)
async def cancel_by_continuation(
    run_id: str,
    request: CancelByContinuationRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> CancelResponse:
    """Cancel all pending/held requests for a specific continuation.

    Args:
        run_id: The run identifier.
        request: Contains the continuation name.

    Returns:
        Number of requests cancelled.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute(
        SQL.UPDATE_CANCEL_BY_CONTINUATION_FOR_WEB, (request.continuation,)
    )
    await db.commit()

    return CancelResponse(
        cancelled_count=cursor.rowcount,
        message=f"Cancelled {cursor.rowcount} requests with continuation '{request.continuation}'",
    )
