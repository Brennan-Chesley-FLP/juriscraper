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


class ParamsFieldData(BaseModel):
    """Filter data for a single field."""

    gte: str | None = None  # For DateRange
    lte: str | None = None  # For DateRange
    values: list[str] | None = None  # For SetFilter
    value: str | None = None  # For UniqueMatch


class ParamsModelData(BaseModel):
    """Configuration for a single data model."""

    enabled: bool = True
    fields: dict[str, ParamsFieldData] = Field(default_factory=dict)


class ParamsData(BaseModel):
    """Full parameter configuration."""

    models: dict[str, ParamsModelData] = Field(default_factory=dict)


class SpeculationStepConfig(BaseModel):
    """Configuration for a single speculative step.

    For speculative_id <= threshold: always continue.
    For speculative_id > threshold: continue for up to `speculation` non-2xx responses.
    """

    threshold: int = Field(
        default=0, description="IDs at or below this always continue"
    )
    speculation: int = Field(
        default=5, description="Number of non-2xx attempts above threshold"
    )


class CreateRunRequest(BaseModel):
    """Request model for creating a new run."""

    run_id: str = Field(..., description="Unique identifier for the run")
    scraper_path: str = Field(
        ..., description="Full scraper path (module.path:ClassName)"
    )
    params: ParamsData | None = Field(
        default=None, description="Optional scraper parameters"
    )
    # ATB Rate Limiter config
    initial_rate: float = Field(
        default=0.1,
        description="Initial request rate in requests/second (0.1 = 6/min)",
    )
    bucket_size: float = Field(
        default=4.0, description="Maximum tokens in the rate limiter bucket"
    )
    jitter: float = Field(
        default=2.0,
        description="Uniform jitter ±seconds after token acquisition",
    )
    first_step: float = Field(
        default=1.5,
        description="Aggressive rate increase multiplier (below congestion)",
    )
    second_step: float = Field(
        default=1.2,
        description="Conservative rate increase multiplier (above congestion)",
    )
    min_rate: float = Field(
        default=0.01, description="Minimum allowed rate in requests/second"
    )
    # Legacy parameter (kept for metadata compatibility)
    base_delay: float = Field(
        default=10.0, description="Legacy: Base rate limit delay in seconds"
    )
    num_workers: int = Field(
        default=1, description="Number of concurrent workers"
    )
    max_backoff_time: float = Field(
        default=3600.0,
        description="Maximum total backoff time before marking failed",
    )
    speculation_config: dict[str, SpeculationStepConfig] | None = Field(
        default=None,
        description="Optional speculation config per step: {step_name: {threshold, speculation}}",
    )


class StopRunRequest(BaseModel):
    """Request model for stopping a run."""

    timeout: float = Field(
        default=30.0, description="Timeout for graceful stop in seconds"
    )


class LoadRunRequest(BaseModel):
    """Request model for loading an existing run.

    DEPRECATED: Use POST /api/runs/{run_id}/resume instead.
    """

    scraper_path: str | None = Field(
        default=None,
        description="Full scraper path (module.path:ClassName). If not provided, uses scraper_name from database.",
    )
    # ATB Rate Limiter config
    initial_rate: float = Field(
        default=0.1,
        description="Initial request rate in requests/second (0.1 = 6/min)",
    )
    bucket_size: float = Field(
        default=4.0, description="Maximum tokens in the rate limiter bucket"
    )
    jitter: float = Field(
        default=2.0,
        description="Uniform jitter ±seconds after token acquisition",
    )
    first_step: float = Field(
        default=1.5,
        description="Aggressive rate increase multiplier (below congestion)",
    )
    second_step: float = Field(
        default=1.2,
        description="Conservative rate increase multiplier (above congestion)",
    )
    min_rate: float = Field(
        default=0.01, description="Minimum allowed rate in requests/second"
    )
    # Legacy parameter (kept for metadata compatibility)
    base_delay: float = Field(
        default=10.0, description="Legacy: Base rate limit delay in seconds"
    )
    num_workers: int = Field(
        default=1, description="Number of concurrent workers"
    )
    max_backoff_time: float = Field(
        default=3600.0,
        description="Maximum total backoff time before marking failed",
    )
    speculation_config: dict[str, SpeculationStepConfig] | None = Field(
        default=None,
        description="Optional speculation config per step: {step_name: {threshold, speculation}}. If not provided, uses config from database.",
    )


class ResumeRunRequest(BaseModel):
    """Request model for resuming an existing run (load + start combined).

    This is the preferred way to start an existing run. It combines
    loading and starting into a single atomic operation.
    """

    scraper_path: str | None = Field(
        default=None,
        description="Full scraper path (module.path:ClassName). If not provided, uses scraper_name from database.",
    )
    # ATB Rate Limiter config
    initial_rate: float = Field(
        default=0.1,
        description="Initial request rate in requests/second (0.1 = 6/min)",
    )
    bucket_size: float = Field(
        default=4.0, description="Maximum tokens in the rate limiter bucket"
    )
    jitter: float = Field(
        default=2.0,
        description="Uniform jitter ±seconds after token acquisition",
    )
    first_step: float = Field(
        default=1.5,
        description="Aggressive rate increase multiplier (below congestion)",
    )
    second_step: float = Field(
        default=1.2,
        description="Conservative rate increase multiplier (above congestion)",
    )
    min_rate: float = Field(
        default=0.01, description="Minimum allowed rate in requests/second"
    )
    # Legacy parameter (kept for metadata compatibility)
    base_delay: float = Field(
        default=10.0, description="Legacy: Base rate limit delay in seconds"
    )
    num_workers: int = Field(
        default=1, description="Number of concurrent workers"
    )
    max_backoff_time: float = Field(
        default=3600.0,
        description="Maximum total backoff time before marking failed",
    )
    speculation_config: dict[str, SpeculationStepConfig] | None = Field(
        default=None,
        description="Optional speculation config per step: {step_name: {threshold, speculation}}. If not provided, uses config from database.",
    )
    speculative_restart: dict[str, int] | None = Field(
        default=None,
        description="Optional speculative starting IDs per step: {step_name: starting_id}. Use to restart speculative scraping from a specific ID.",
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
    """Create a new scraper run and start it immediately.

    Creates a new database, initializes the driver with the specified
    configuration, and starts running automatically.

    Args:
        request: Run configuration including scraper path and parameters.

    Returns:
        The created run details with status 'running'.

    Raises:
        HTTPException: 400 if run_id already exists.
        HTTPException: 404 if scraper not found.
    """
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        get_registry,
    )

    # Get registry and look up scraper
    try:
        registry = get_registry()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scraper registry not initialized",
        ) from e

    # Check if scraper exists
    scraper_info = registry.get_scraper(request.scraper_path)
    if scraper_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scraper '{request.scraper_path}' not found",
        )

    # Convert params to dict format for registry
    params_data = None
    if request.params:
        params_data = {
            "models": {
                model_name: {
                    "enabled": model_data.enabled,
                    "fields": {
                        field_name: {
                            "gte": field_data.gte,
                            "lte": field_data.lte,
                            "values": field_data.values,
                            "value": field_data.value,
                        }
                        for field_name, field_data in model_data.fields.items()
                    },
                }
                for model_name, model_data in request.params.models.items()
            }
        }

    # Instantiate scraper with parameters
    scraper = registry.instantiate_scraper(request.scraper_path, params_data)
    if scraper is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to instantiate scraper '{request.scraper_path}'",
        )

    # Convert speculation_config to dict format
    speculation_config_dict = None
    if request.speculation_config:
        speculation_config_dict = {
            step_name: {
                "threshold": step_config.threshold,
                "speculation": step_config.speculation,
            }
            for step_name, step_config in request.speculation_config.items()
        }

    # Create run
    try:
        run_info = await manager.create_run(
            run_id=request.run_id,
            scraper=scraper,
            # ATB config
            initial_rate=request.initial_rate,
            bucket_size=request.bucket_size,
            jitter=request.jitter,
            first_step=request.first_step,
            second_step=request.second_step,
            min_rate=request.min_rate,
            # Legacy/other config
            base_delay=request.base_delay,
            num_workers=request.num_workers,
            max_backoff_time=request.max_backoff_time,
            speculation_config=speculation_config_dict,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Auto-start the run
    try:
        run_info = await manager.start_run(request.run_id)
        return _run_info_to_response(run_info)
    except ValueError:
        # If start fails, still return the created run info
        return _run_info_to_response(run_info)


@router.post("/{run_id}/load", response_model=RunResponse, deprecated=True)
async def load_run(
    run_id: str,
    request: LoadRunRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RunResponse:
    """Load an existing run from its database.

    DEPRECATED: Use POST /api/runs/{run_id}/resume instead, which combines
    loading and starting into a single atomic operation.

    Opens the database and prepares the driver for running. The scraper
    can be specified explicitly or inferred from the database metadata.

    Args:
        run_id: The unique identifier of the run.
        request: Load configuration including optional scraper path.

    Returns:
        Updated run details with status 'loaded'.

    Raises:
        HTTPException: 404 if run not found or scraper not found.
        HTTPException: 400 if run already loaded.
    """
    import warnings

    warnings.warn(
        "POST /api/runs/{run_id}/load is deprecated. Use POST /api/runs/{run_id}/resume instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    import aiosqlite

    from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        get_registry,
    )

    # Get run info
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    if run_info.driver is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' is already loaded",
        )

    # Determine scraper path
    scraper_path = request.scraper_path

    if scraper_path is None:
        # Query the database for the scraper_name
        try:
            async with aiosqlite.connect(run_info.db_path) as db:
                cursor = await db.execute(SQL.SELECT_RUN_STATUS_AND_NAME)
                row = await cursor.fetchone()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Run '{run_id}' has no metadata. Cannot determine scraper.",
                    )
                scraper_name = row[1]
        except aiosqlite.Error as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read database: {e}",
            ) from e

        # Find a scraper with this name in the registry
        try:
            registry = get_registry()
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scraper registry not initialized",
            ) from e

        # Search for scraper by name (class name matches)
        matching_scrapers = [
            s for s in registry.list_scrapers() if s.class_name == scraper_name
        ]
        if not matching_scrapers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scraper '{scraper_name}' not found in registry. "
                f"Specify scraper_path explicitly.",
            )
        if len(matching_scrapers) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Multiple scrapers named '{scraper_name}' found. "
                f"Specify scraper_path explicitly: "
                f"{[s.full_path for s in matching_scrapers]}",
            )
        scraper_path = matching_scrapers[0].full_path

    # Get registry and instantiate scraper
    try:
        registry = get_registry()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scraper registry not initialized",
        ) from e

    scraper_info = registry.get_scraper(scraper_path)
    if scraper_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scraper '{scraper_path}' not found",
        )

    # Instantiate scraper (without params for resume - they're in the DB)
    scraper = registry.instantiate_scraper(scraper_path)
    if scraper is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to instantiate scraper '{scraper_path}'",
        )

    # Convert speculation_config to dict format if provided
    speculation_config_dict = None
    if request.speculation_config:
        speculation_config_dict = {
            step_name: {
                "threshold": step_config.threshold,
                "speculation": step_config.speculation,
            }
            for step_name, step_config in request.speculation_config.items()
        }

    # Load run
    try:
        run_info = await manager.load_run(
            run_id=run_id,
            scraper=scraper,
            # ATB config
            initial_rate=request.initial_rate,
            bucket_size=request.bucket_size,
            jitter=request.jitter,
            first_step=request.first_step,
            second_step=request.second_step,
            min_rate=request.min_rate,
            # Legacy/other config
            base_delay=request.base_delay,
            num_workers=request.num_workers,
            max_backoff_time=request.max_backoff_time,
            speculation_config=speculation_config_dict,
        )
        return _run_info_to_response(run_info)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


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


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    request: ResumeRunRequest | None = None,
) -> RunResponse:
    """Resume a run (load + start in one step).

    This is the preferred way to start an existing run. It combines
    loading and starting into a single atomic operation. If the run
    is already running, returns its current status.

    Args:
        run_id: The unique identifier of the run.
        request: Optional configuration for the run.

    Returns:
        Run details with status 'running'.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run cannot be started.
        HTTPException: 500 if scraper cannot be instantiated.
    """
    from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
        SQLManager,
    )
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        get_registry,
    )

    request = request or ResumeRunRequest()

    # Get run info
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    # If already running, return current state
    if run_info.task is not None and not run_info.task.done():
        return _run_info_to_response(run_info)

    # If already loaded but not running, just start it
    if run_info.driver is not None:
        try:
            run_info = await manager.start_run(run_id)
            return _run_info_to_response(run_info)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    # Need to load first - determine scraper path
    scraper_path = request.scraper_path
    if scraper_path is None:
        # Get scraper name from database
        try:
            async with SQLManager.open(run_info.db_path) as sql_manager:
                metadata = await sql_manager.get_run_metadata()
                if metadata is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Run has no metadata. Specify scraper_path explicitly.",
                    )
                scraper_name = metadata.get("scraper_name")
                if not scraper_name:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Run has no scraper_name in metadata. Specify scraper_path explicitly.",
                    )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read database: {e}",
            ) from e

        # Find scraper by name in registry
        try:
            registry = get_registry()
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scraper registry not initialized",
            ) from e

        matching_scrapers = [
            s for s in registry.list_scrapers() if s.class_name == scraper_name
        ]
        if not matching_scrapers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scraper '{scraper_name}' not found in registry. Specify scraper_path explicitly.",
            )
        if len(matching_scrapers) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Multiple scrapers named '{scraper_name}' found. Specify scraper_path explicitly: {[s.full_path for s in matching_scrapers]}",
            )
        scraper_path = matching_scrapers[0].full_path

    # Get registry and instantiate scraper
    try:
        registry = get_registry()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scraper registry not initialized",
        ) from e

    scraper = registry.instantiate_scraper(scraper_path)
    if scraper is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to instantiate scraper '{scraper_path}'",
        )

    # Initialize params if speculative_restart is provided
    if request.speculative_restart and scraper._params is None:
        scraper._params = scraper.__class__.params()

    # Set speculative starting IDs if provided
    if request.speculative_restart:
        # _params is guaranteed non-None from the check above
        assert scraper._params is not None
        for step_name, starting_id in request.speculative_restart.items():
            try:
                setattr(scraper._params.speculative, step_name, starting_id)
            except AttributeError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown speculative step '{step_name}': {e}",
                ) from e

    # Convert speculation_config to dict format if provided
    speculation_config_dict = None
    if request.speculation_config:
        speculation_config_dict = {
            step_name: {
                "threshold": step_config.threshold,
                "speculation": step_config.speculation,
            }
            for step_name, step_config in request.speculation_config.items()
        }

    # Resume (load + start)
    try:
        run_info = await manager.resume_run(
            run_id=run_id,
            scraper=scraper,
            # ATB config
            initial_rate=request.initial_rate,
            bucket_size=request.bucket_size,
            jitter=request.jitter,
            first_step=request.first_step,
            second_step=request.second_step,
            min_rate=request.min_rate,
            # Legacy/other config
            base_delay=request.base_delay,
            num_workers=request.num_workers,
            max_backoff_time=request.max_backoff_time,
            speculation_config=speculation_config_dict,
        )
        return _run_info_to_response(run_info)
    except ValueError as e:
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


# Speculative progress models and endpoints


class SpeculativeStepProgress(BaseModel):
    """Progress information for a single speculative step."""

    step_name: str = Field(..., description="Name of the speculative step")
    latest_id: int = Field(
        ..., description="Latest speculative_id that was processed"
    )
    suggested_restart_id: int = Field(
        ..., description="Suggested ID to restart from (latest + 1)"
    )
    updated_at: str | None = Field(
        None, description="When the progress was last updated"
    )


class SpeculativeProgressResponse(BaseModel):
    """Response model for speculative progress."""

    run_id: str
    steps: list[SpeculativeStepProgress]
    speculation_config: dict[str, dict[str, int]] | None = Field(
        None, description="Current speculation config from database"
    )


class RestartSpeculativeRequest(BaseModel):
    """Request model for restarting speculative scraping."""

    step_name: str = Field(
        ..., description="Name of the speculative step to restart"
    )
    speculative_id: int = Field(
        ...,
        ge=1,
        description="Speculative ID to start from",
    )
    speculation_config: SpeculationStepConfig | None = Field(
        default=None,
        description="Optional new speculation config for this step",
    )


class RestartSpeculativeResponse(BaseModel):
    """Response model for restart speculative action."""

    run_id: str
    step_name: str
    starting_id: int
    speculation_config: dict[str, int] | None
    message: str


@router.get(
    "/{run_id}/speculative-progress",
    response_model=SpeculativeProgressResponse,
)
async def get_speculative_progress(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> SpeculativeProgressResponse:
    """Get speculative progress for a run.

    Returns the latest speculative_id for each speculative step,
    along with suggested restart IDs. Works with both loaded and
    unloaded runs.

    Args:
        run_id: The unique identifier of the run.

    Returns:
        Speculative progress for all steps.

    Raises:
        HTTPException: 404 if run not found.
    """
    from juriscraper.scraper_driver.driver.dev_driver.web.app import (
        get_sql_manager_for_run,
    )

    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    # Get SQLManager - works for both loaded and unloaded runs
    try:
        sql_manager = await get_sql_manager_for_run(run_id, manager)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # Get all speculative progress
    progress_dict = await sql_manager.get_all_speculative_progress()

    # Get speculation config from database
    speculation_config = await sql_manager.get_speculation_config()

    # Build step progress list
    steps: list[SpeculativeStepProgress] = []
    for step_name, latest_id in progress_dict.items():
        steps.append(
            SpeculativeStepProgress(
                step_name=step_name,
                latest_id=latest_id,
                suggested_restart_id=latest_id + 1,
                updated_at=None,  # Could add timestamp lookup if needed
            )
        )

    return SpeculativeProgressResponse(
        run_id=run_id,
        steps=steps,
        speculation_config=speculation_config,
    )


@router.post(
    "/{run_id}/restart-speculative", response_model=RestartSpeculativeResponse
)
async def restart_speculative(
    run_id: str,
    request: RestartSpeculativeRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RestartSpeculativeResponse:
    """Restart speculative scraping from a specific ID.

    Stores the speculative starting ID in the database. When the run is
    resumed, the driver will apply this starting ID to the scraper params.

    This works with both loaded and unloaded runs by:
    1. Storing the starting ID in the speculative_start_ids table
    2. Optionally updating speculation_config in the database
    3. The driver applies these IDs when it starts via _apply_speculative_start_ids()

    Args:
        run_id: The unique identifier of the run.
        request: Restart configuration including step name and starting ID.

    Returns:
        Confirmation of the restart configuration.

    Raises:
        HTTPException: 404 if run not found.
        HTTPException: 400 if run is currently running.
    """
    from juriscraper.scraper_driver.driver.dev_driver.web.app import (
        get_sql_manager_for_run,
    )

    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )

    if run_info.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{run_id}' is currently running. Stop it first.",
        )

    # Get SQLManager - works for both loaded and unloaded runs
    try:
        sql_manager = await get_sql_manager_for_run(run_id, manager)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # Store the speculative starting ID in the database
    # The driver will apply this when it starts
    await sql_manager.set_speculative_start_id(
        request.step_name, request.speculative_id
    )

    # Update speculative progress to start from one before the requested ID
    # This ensures the next ID processed will be speculative_id
    await sql_manager.update_speculative_progress(
        request.step_name, request.speculative_id - 1
    )

    # Update speculation config if provided
    new_config_dict: dict[str, int] | None = None
    if request.speculation_config:
        new_config_dict = {
            "threshold": request.speculation_config.threshold,
            "speculation": request.speculation_config.speculation,
        }
        # Get current config and update it
        current_config = await sql_manager.get_speculation_config() or {}
        current_config[request.step_name] = new_config_dict
        await sql_manager.update_speculation_config(current_config)

    # If driver is loaded, also update the scraper params directly
    # (for immediate effect if they start without reloading)
    if run_info.driver is not None:
        scraper = run_info.driver.scraper
        # Initialize params if not set
        if not hasattr(scraper, "_params") or scraper._params is None:
            try:
                scraper._params = scraper.__class__.params()
            except Exception:
                pass  # Will be applied from DB when driver starts

        if hasattr(scraper, "_params") and scraper._params is not None:
            try:
                if hasattr(scraper._params, "speculative"):
                    setattr(
                        scraper._params.speculative,
                        request.step_name,
                        request.speculative_id,
                    )
            except AttributeError:
                pass  # Will be applied from DB when driver starts

    return RestartSpeculativeResponse(
        run_id=run_id,
        step_name=request.step_name,
        starting_id=request.speculative_id,
        speculation_config=new_config_dict,
        message=f"Speculative step '{request.step_name}' configured to restart from ID {request.speculative_id}. Resume the run to begin scraping.",
    )
