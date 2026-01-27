"""REST API endpoints for managing requests within a run.

This module provides endpoints for:
- Listing requests with filters
- Getting request details
- Cancelling individual requests
- Batch cancelling requests by continuation
- Batch requeuing requests by continuation
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.debugger import (
    LocalDevDriverDebugger,
)
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_debugger_for_run,
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

    requeued_request_ids: list[int]
    cleared_response_ids: list[int] = []
    cleared_downstream_request_ids: list[int] = []
    cleared_result_ids: list[int] = []
    cleared_error_ids: list[int] = []
    resolved_error_ids: list[int] = []
    dry_run: bool = False
    message: str


class CancelByContinuationRequest(BaseModel):
    """Request model for batch cancellation."""

    continuation: str = Field(..., description="Continuation to filter by")


class RequeueByContinuationRequest(BaseModel):
    """Request model for batch requeue."""

    continuation: str = Field(..., description="Continuation to filter by")
    status: str = Field(
        default="failed",
        description="Status of requests to requeue (deprecated, ignored)",
    )


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


async def _get_debugger(
    run_id: str, manager: RunManager, read_only: bool = True
) -> LocalDevDriverDebugger:
    """Get LocalDevDriverDebugger for a run.

    Args:
        run_id: The run identifier.
        manager: The run manager.
        read_only: If True, open in read-only mode (prevents writes).

    Returns:
        LocalDevDriverDebugger instance.

    Raises:
        HTTPException: 404 if run not found, 400 if error.
    """
    try:
        return await get_debugger_for_run(run_id, manager, read_only=read_only)
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
    status_filter: Literal[
        "pending", "in_progress", "completed", "failed", "held"
    ]
    | None = Query(None, alias="status", description="Filter by status"),
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
    debugger = await _get_debugger(run_id, manager, read_only=True)

    # Use LDDD's list_requests method
    page = await debugger.list_requests(
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
    debugger = await _get_debugger(run_id, manager, read_only=True)

    # Use LDDD's get_request_summary method
    summary = await debugger.get_request_summary()

    # Convert to response model format
    summaries: dict[str, RequestSummaryItem] = {}
    grand_total = 0

    for continuation, status_counts in summary.items():
        if continuation == "all":
            # Skip the "all" key as we calculate grand_total separately
            continue

        summaries[continuation] = RequestSummaryItem(
            continuation=continuation,
            pending=status_counts.get("pending", 0),
            in_progress=status_counts.get("in_progress", 0),
            completed=status_counts.get("completed", 0),
            failed=status_counts.get("failed", 0),
            held=status_counts.get("held", 0),
            cancelled=status_counts.get("cancelled", 0),
            total=sum(status_counts.values()),
        )
        grand_total += summaries[continuation].total

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
    debugger = await _get_debugger(run_id, manager, read_only=True)

    record = await debugger.get_request(request_id)

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
    debugger = await _get_debugger(run_id, manager, read_only=False)

    cancelled = await debugger.cancel_request(request_id)

    if not cancelled:
        # Check if request exists
        record = await debugger.get_request(request_id)
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
    """Requeue a failed or completed request.

    Creates a new pending request with the same parameters as the
    original request. Optionally clears responses and/or downstream artifacts.

    Args:
        run_id: The run identifier.
        request_id: The request ID to requeue.
        clear_responses: If True, delete responses to force re-fetch.
        clear_downstream: If True, recursively delete downstream artifacts.
        dry_run: If True, report what would happen without making changes.

    Returns:
        Requeue result with affected IDs.

    Raises:
        HTTPException: 404 if request not found.
    """
    debugger = await _get_debugger(run_id, manager, read_only=False)

    # Verify request exists
    record = await debugger.get_request(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found",
        )

    # Use SQLManager's requeue_requests method (via debugger.sql)
    # TODO: LDDD's requeue_request doesn't support clear_responses/dry_run yet
    result = await debugger.sql.requeue_requests(
        [request_id],
        clear_responses=clear_responses,
        clear_downstream=clear_downstream,
        dry_run=dry_run,
    )

    new_request_id = (
        result.requeued_request_ids[0] if result.requeued_request_ids else None
    )
    message = f"Requeued request {request_id}"
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
    debugger = await _get_debugger(run_id, manager, read_only=False)

    cancelled_count = await debugger.cancel_requests_by_continuation(
        request.continuation
    )

    return CancelResponse(
        cancelled_count=cancelled_count,
        message=f"Cancelled {cancelled_count} requests with continuation '{request.continuation}'",
    )


@router.post("/requeue-by-continuation", response_model=RequeueResponse)
async def requeue_by_continuation(
    run_id: str,
    request: RequeueByContinuationRequest,
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
    """Requeue all requests matching continuation and status.

    Creates new pending requests with the same parameters as the
    original requests. Optionally clears responses and/or downstream artifacts.

    Note: The status filter from the request body is ignored. This endpoint now
    requeues all completed requests for the continuation (the most common use case).
    For error-based filtering, use the batch-requeue endpoint on /errors.

    Args:
        run_id: The run identifier.
        request: Contains continuation name (status field is deprecated).
        clear_responses: If True, delete responses to force re-fetch.
        clear_downstream: If True, recursively delete downstream artifacts.
        dry_run: If True, report what would happen without making changes.

    Returns:
        Requeue result with affected IDs.
    """
    debugger = await _get_debugger(run_id, manager, read_only=False)

    # Use SQLManager's requeue_continuation method (via debugger.sql)
    # TODO: LDDD's requeue_continuation doesn't support clear_responses/dry_run yet
    result = await debugger.sql.requeue_continuation(
        request.continuation,
        clear_responses=clear_responses,
        clear_downstream=clear_downstream,
        dry_run=dry_run,
    )

    message = f"Requeued {len(result.requeued_request_ids)} requests with continuation '{request.continuation}'"
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
