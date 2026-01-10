"""REST API endpoints for managing scraper runs.

This module provides endpoints for:
- Listing all runs
- Getting run details
- Creating new runs
- Starting/stopping runs
- Deleting runs
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunInfo,
    RunManager,
    get_run_manager,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunResponse(BaseModel):
    """Response model for a single run."""

    run_id: str
    db_path: str
    status: str
    created_at: str
    started_at: str | None


class RunListResponse(BaseModel):
    """Response model for listing runs."""

    runs: list[RunResponse]
    total: int


class CreateRunRequest(BaseModel):
    """Request model for creating a new run."""

    run_id: str = Field(..., description="Unique identifier for the run")
    scraper_name: str = Field(
        ..., description="Name of the scraper class to use"
    )
    base_delay: float = Field(
        default=10.0, description="Base rate limit delay in seconds"
    )
    jitter: float = Field(
        default=2.0, description="Rate limit jitter in seconds"
    )
    num_workers: int = Field(
        default=1, description="Number of concurrent workers"
    )
    max_backoff_time: float = Field(
        default=3600.0,
        description="Maximum total backoff time before marking failed",
    )


class StopRunRequest(BaseModel):
    """Request model for stopping a run."""

    timeout: float = Field(
        default=30.0, description="Timeout for graceful stop in seconds"
    )


def _run_info_to_response(run_info: RunInfo) -> RunResponse:
    """Convert RunInfo to API response model."""
    d = run_info.to_dict()
    return RunResponse(
        run_id=d["run_id"],
        db_path=d["db_path"],
        status=d["status"],
        created_at=d["created_at"],
        started_at=d["started_at"],
    )


@router.get("", response_model=RunListResponse)
async def list_runs(
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunListResponse:
    """List all known runs.

    Returns runs discovered from the runs directory, including
    their current status (unloaded, loaded, running, etc.).
    """
    runs = await manager.list_runs()
    return RunListResponse(
        runs=[_run_info_to_response(r) for r in runs],
        total=len(runs),
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunResponse:
    """Get details for a specific run.

    Args:
        run_id: The unique identifier of the run.

    Returns:
        Run details including status and timestamps.

    Raises:
        HTTPException: 404 if run not found.
    """
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return _run_info_to_response(run_info)


@router.post(
    "", response_model=RunResponse, status_code=status.HTTP_201_CREATED
)
async def create_run(
    request: CreateRunRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunResponse:
    """Create a new scraper run.

    Creates a new database and initializes the driver with the
    specified configuration. The run is created in 'loaded' state
    and must be explicitly started.

    Note: This endpoint requires the scraper to be registered or
    dynamically loaded. Currently returns a placeholder response
    as scraper registry is not yet implemented.

    Args:
        request: Run configuration including scraper name and parameters.

    Returns:
        The created run details.

    Raises:
        HTTPException: 400 if run_id already exists.
        HTTPException: 400 if scraper not found.
    """
    # TODO: Implement scraper registry to look up scraper by name
    # For now, return an error explaining this limitation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Scraper registry not yet implemented. "
            "Use the Python API to create runs with a scraper instance."
        ),
    )


@router.post("/{run_id}/start", response_model=RunResponse)
async def start_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunResponse:
    """Start or resume a run.

    The run must be in 'loaded' state. If the run completed previously,
    it will resume from where it left off.

    Args:
        run_id: The unique identifier of the run.

    Returns:
        Updated run details with status 'running'.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run not in valid state to start.
    """
    try:
        run_info = await manager.start_run(run_id)
        return _run_info_to_response(run_info)
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


@router.post("/{run_id}/stop", response_model=RunResponse)
async def stop_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    request: StopRunRequest | None = None,
) -> RunResponse:
    """Stop a running run gracefully.

    Signals the driver to stop and waits for in-progress requests
    to complete. If the timeout is exceeded, forces cancellation.

    Args:
        run_id: The unique identifier of the run.
        request: Optional configuration for stop behavior.

    Returns:
        Updated run details with status 'stopped'.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run not currently running.
    """
    timeout = request.timeout if request else 30.0

    try:
        run_info = await manager.stop_run(run_id, timeout=timeout)
        return _run_info_to_response(run_info)
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


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> None:
    """Delete a run and its database.

    The run must be stopped before deletion. This permanently
    removes all data associated with the run.

    Args:
        run_id: The unique identifier of the run.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run is still running.
    """
    try:
        await manager.delete_run(run_id)
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


@router.post("/{run_id}/unload", response_model=RunResponse)
async def unload_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunResponse:
    """Unload a run, closing its database connection.

    Frees memory by closing the driver connection while keeping
    the run available for future loading.

    Args:
        run_id: The unique identifier of the run.

    Returns:
        Updated run details with status 'unloaded'.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run is still running.
    """
    try:
        await manager.unload_run(run_id)
        run_info = await manager.get_run(run_id)
        if run_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found after unload",
            )
        return _run_info_to_response(run_info)
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


@router.post("/scan", response_model=RunListResponse)
async def scan_runs(
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunListResponse:
    """Rescan the runs directory for new databases.

    Discovers any new .db files that have been added to the
    runs directory since the last scan.

    Returns:
        Updated list of all runs after scanning.
    """
    await manager.scan_runs()
    runs = await manager.list_runs()
    return RunListResponse(
        runs=[_run_info_to_response(r) for r in runs],
        total=len(runs),
    )
