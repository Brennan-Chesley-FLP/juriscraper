"""REST API endpoints for rate limiter monitoring.

This module provides endpoints for:
- Getting current rate limiter state
- Viewing rate limiter statistics
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
)

router = APIRouter(
    prefix="/api/runs/{run_id}/rate-limiter", tags=["rate-limiter"]
)


class RateLimiterStateResponse(BaseModel):
    """Response model for rate limiter state."""

    tokens: float = Field(..., description="Current token count in bucket")
    rate: float = Field(..., description="Current rate in tokens per second")
    bucket_size: float = Field(..., description="Maximum tokens in bucket")
    last_congestion_rate: float = Field(
        ..., description="Rate at last congestion event"
    )
    jitter: float = Field(default=0.0, description="Deprecated: always 0.0")
    approximate_requests_per_minute: float = Field(
        ..., description="Approximate requests per minute (rate * 60)"
    )
    total_requests: int = Field(..., description="Total requests made")
    total_successes: int = Field(..., description="Total successful requests")
    total_rate_limited: int = Field(
        ..., description="Total rate-limited requests"
    )
    success_rate: float = Field(
        ..., description="Success rate percentage (0-100)"
    )
    status: str = Field(
        ..., description="Status: 'healthy', 'throttled', or 'recovering'"
    )
    last_used_at: float = Field(
        ..., description="Unix timestamp of last token acquisition"
    )
    created_at: str | None = Field(
        None, description="When rate limiter was created"
    )
    updated_at: str | None = Field(
        None, description="When state was last updated"
    )


@router.get("", response_model=RateLimiterStateResponse)
async def get_rate_limiter_state(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RateLimiterStateResponse:
    """Get current rate limiter state for a run.

    Returns the current state of the Adaptive Token Bucket rate limiter,
    including token count, rate, statistics, and status.

    Args:
        run_id: The unique identifier of the run.

    Returns:
        Current rate limiter state.

    Raises:
        HTTPException: 404 if run not found or rate limiter not initialized.
    """
    # Get run info
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    # Get SQLManager
    try:
        sql_manager = await get_sql_manager_for_run(run_id, manager)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # Get rate limiter state from database
    state = await sql_manager.get_rate_limiter_state()

    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rate limiter not initialized for run '{run_id}'",
        )

    # Compute derived fields
    total_requests = state["total_requests"]
    total_successes = state["total_successes"]
    total_rate_limited = state["total_rate_limited"]
    rate = state["rate"]

    success_rate = (
        total_successes / total_requests * 100 if total_requests > 0 else 100.0
    )

    # Compute status
    if total_rate_limited == 0:
        status_str = "healthy"
    elif rate < state["last_congestion_rate"]:
        status_str = "recovering"
    else:
        status_str = "throttled"

    return RateLimiterStateResponse(
        tokens=state["tokens"],
        rate=rate,
        bucket_size=state["bucket_size"],
        last_congestion_rate=state["last_congestion_rate"],
        jitter=state["jitter"],
        approximate_requests_per_minute=rate * 60,
        total_requests=total_requests,
        total_successes=total_successes,
        total_rate_limited=total_rate_limited,
        success_rate=round(success_rate, 2),
        status=status_str,
        last_used_at=state["last_used_at"],
        created_at=state.get("created_at"),
        updated_at=state.get("updated_at"),
    )
