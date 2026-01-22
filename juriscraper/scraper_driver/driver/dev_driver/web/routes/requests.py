"""REST API endpoints for managing requests within a run.

This module provides endpoints for:
- Listing requests with filters
- Getting request details
- Cancelling individual requests
- Batch cancelling requests by continuation
- Batch requeuing requests by continuation
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
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


class RequeueByContinuationRequest(BaseModel):
    """Request model for batch requeue."""

    continuation: str = Field(..., description="Continuation to filter by")
    status: str = Field(
        default="failed",
        description="Status of requests to requeue (e.g., 'failed', 'completed')",
    )


class RequeueByContinuationResponse(BaseModel):
    """Response model for batch requeue operations."""

    requeued_count: int
    message: str


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
    sql_manager = await _get_sql_manager(run_id, manager)

    # Use SQLManager's list_requests method
    page = await sql_manager.list_requests(
        status=status_filter,
        continuation=continuation,
        offset=offset,
        limit=limit,
    )

    items = [
        RequestResponse(
            id=r.id,
            status=r.status,
            priority=r.priority,
            queue_counter=r.queue_counter,
            method=r.method,
            url=r.url,
            continuation=r.continuation,
            current_location=r.current_location,
            created_at=r.created_at,
            started_at=r.started_at,
            completed_at=r.completed_at,
            retry_count=r.retry_count,
            cumulative_backoff=r.cumulative_backoff or 0.0,
            last_error=r.last_error,
        )
        for r in page.items
    ]

    return RequestListResponse(
        items=items,
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        has_more=page.has_more,
    )


@router.get("/summary", response_model=RequestSummaryResponse)
async def get_request_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequestSummaryResponse:
    """Get request counts grouped by continuation and status.

    Returns a pivot table with one row per continuation, showing counts
    for each status (pending, in_progress, completed, failed, held, cancelled).

    Bookkeeping requests (those without URLs) are excluded from the summary.

    Args:
        run_id: The run identifier.

    Returns:
        Summary of request counts by continuation and status.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Query counts grouped by continuation and status
    # Exclude bookkeeping requests (those without URLs)
    query = """
        SELECT continuation, status, COUNT(*) as count
        FROM requests
        WHERE url IS NOT NULL AND url != ''
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
    sql_manager = await _get_sql_manager(run_id, manager)

    record = await sql_manager.get_request(request_id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found in run '{run_id}'",
        )

    return RequestResponse(
        id=record.id,
        status=record.status,
        priority=record.priority,
        queue_counter=record.queue_counter,
        method=record.method,
        url=record.url,
        continuation=record.continuation,
        current_location=record.current_location,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        retry_count=record.retry_count,
        cumulative_backoff=record.cumulative_backoff or 0.0,
        last_error=record.last_error,
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
    sql_manager = await _get_sql_manager(run_id, manager)

    cancelled = await sql_manager.cancel_request(request_id)

    if not cancelled:
        # Check if request exists
        record = await sql_manager.get_request(request_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request {request_id} not found",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request {request_id} cannot be cancelled (status: {record.status})",
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
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

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

    # Create new request using SQLManager
    new_request_id = await sql_manager.insert_requeue_request(
        priority=row[4],
        method=row[1],
        url=row[2],
        headers_json=row[5],
        cookies_json=row[6],
        body=row[7],
        continuation=row[3],
        current_location=row[8],
        accumulated_data_json=row[9],
        aux_data_json=row[10],
        permanent_json=row[11],
        original_request_id=row[0],
    )

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
    sql_manager = await _get_sql_manager(run_id, manager)

    cancelled_count = await sql_manager.cancel_requests_by_continuation(
        request.continuation
    )

    return CancelResponse(
        cancelled_count=cancelled_count,
        message=f"Cancelled {cancelled_count} requests with continuation '{request.continuation}'",
    )


@router.post(
    "/requeue-by-continuation", response_model=RequeueByContinuationResponse
)
async def requeue_by_continuation(
    run_id: str,
    request: RequeueByContinuationRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RequeueByContinuationResponse:
    """Requeue all requests matching continuation and status.

    Creates new pending requests with the same parameters as the
    original requests.

    Args:
        run_id: The run identifier.
        request: Contains continuation name and status filter.

    Returns:
        Number of requests requeued.
    """
    sql_manager = await _get_sql_manager(run_id, manager)

    requeued_count = await sql_manager.requeue_requests_by_continuation(
        request.continuation, request.status
    )

    return RequeueByContinuationResponse(
        requeued_count=requeued_count,
        message=f"Requeued {requeued_count} '{request.status}' requests with continuation '{request.continuation}'",
    )
