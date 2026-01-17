"""FastAPI application for LocalDevDriver web interface.

This module provides the main FastAPI application with:
- Lifespan context manager for startup/shutdown
- RunManager for tracking active scraper runs
- Graceful shutdown support for hot reload
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
        LocalDevDriver,
    )
    from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
        SQLManager,
    )

logger = logging.getLogger(__name__)


@dataclass
class RunInfo:
    """Information about a scraper run.

    Attributes:
        run_id: Unique identifier for the run (database filename without .db).
        db_path: Path to the SQLite database file.
        driver: The LocalDevDriver instance (if loaded).
        task: The asyncio task running the driver (if running).
        status: Current status (unloaded, loaded, running, stopping, stopped).
        created_at: When this run info was created.
        started_at: When the run was started (if running).
    """

    run_id: str
    db_path: Path
    driver: LocalDevDriver[Any] | None = None
    task: asyncio.Task[None] | None = None
    status: str = "unloaded"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "db_path": str(self.db_path),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat()
            if self.started_at
            else None,
        }


class RunManager:
    """Manager for tracking and controlling scraper runs.

    Watches a runs directory for database files and tracks active
    driver instances. Supports graceful shutdown for hot reload.

    Attributes:
        runs_dir: Directory containing run database files.
        runs: Dictionary mapping run_id to RunInfo.
    """

    def __init__(self, runs_dir: Path) -> None:
        """Initialize the run manager.

        Args:
            runs_dir: Directory to watch for run database files.
        """
        self.runs_dir = runs_dir
        self.runs: dict[str, RunInfo] = {}
        self._lock = asyncio.Lock()

    async def scan_runs(self) -> list[str]:
        """Scan runs directory for database files.

        Returns:
            List of discovered run_ids.
        """
        async with self._lock:
            discovered: list[str] = []

            if not self.runs_dir.exists():
                self.runs_dir.mkdir(parents=True, exist_ok=True)
                return discovered

            for db_file in self.runs_dir.glob("*.db"):
                run_id = db_file.stem
                if run_id not in self.runs:
                    self.runs[run_id] = RunInfo(
                        run_id=run_id,
                        db_path=db_file,
                        status="unloaded",
                    )
                discovered.append(run_id)

            return discovered

    async def list_runs(self) -> list[RunInfo]:
        """List all known runs.

        Returns:
            List of RunInfo objects.
        """
        async with self._lock:
            return list(self.runs.values())

    async def get_run(self, run_id: str) -> RunInfo | None:
        """Get info for a specific run.

        Args:
            run_id: The run identifier.

        Returns:
            RunInfo or None if not found.
        """
        async with self._lock:
            return self.runs.get(run_id)

    async def create_run(
        self,
        run_id: str,
        scraper: Any,
        **driver_kwargs: Any,
    ) -> RunInfo:
        """Create a new run with a fresh database.

        Args:
            run_id: Unique identifier for the run.
            scraper: The scraper instance to run.
            **driver_kwargs: Additional arguments for LocalDevDriver.

        Returns:
            RunInfo for the new run.

        Raises:
            ValueError: If run_id already exists.
        """
        from juriscraper.scraper_driver.common.request_manager import (
            AsyncRequestManager,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            JitterRateLimitInterceptor,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )
        from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
            SQLManager,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.archive import (
            get_storage_dir_for_run,
            uuid_archive_callback,
        )

        async with self._lock:
            if run_id in self.runs:
                raise ValueError(f"Run '{run_id}' already exists")

            db_path = self.runs_dir / f"{run_id}.db"

            # Set up storage directory for archived files
            storage_dir = get_storage_dir_for_run(self.runs_dir, run_id)

            # Extract config from driver_kwargs
            base_delay = driver_kwargs.get("base_delay", 10.0)
            jitter = driver_kwargs.get("jitter", 2.0)
            num_workers = driver_kwargs.get("num_workers", 1)
            max_backoff_time = driver_kwargs.get("max_backoff_time", 3600.0)

            # Initialize database and SQLManager
            aiosqlite_db = await init_database(db_path)
            sql_manager = SQLManager(aiosqlite_db)

            # Initialize run metadata
            scraper_name = scraper.__class__.__name__
            scraper_version = getattr(scraper, "__version__", None)
            await sql_manager.init_run_metadata(
                scraper_name=scraper_name,
                scraper_version=scraper_version,
                base_delay=base_delay,
                jitter=jitter,
                num_workers=num_workers,
                max_backoff_time=max_backoff_time,
            )

            # Set up rate limiter interceptor and request manager
            rate_limiter = JitterRateLimitInterceptor(
                base_delay_seconds=base_delay,
                jitter_seconds=jitter,
            )
            request_manager = AsyncRequestManager(
                interceptors=[rate_limiter],
                ssl_context=scraper.get_ssl_context(),
            )

            # Create driver with SQLManager and request manager
            driver = LocalDevDriver(
                scraper=scraper,
                db=sql_manager,
                storage_dir=storage_dir,
                request_manager=request_manager,
                **driver_kwargs,
            )

            # Set the custom archive callback
            driver.on_archive = uuid_archive_callback

            run_info = RunInfo(
                run_id=run_id,
                db_path=db_path,
                driver=driver,
                status="loaded",
            )
            self.runs[run_id] = run_info

            logger.info(f"Created run '{run_id}' at {db_path}")
            return run_info

    async def load_run(
        self, run_id: str, scraper: Any, **driver_kwargs: Any
    ) -> RunInfo:
        """Load an existing run from database.

        Args:
            run_id: The run identifier.
            scraper: The scraper instance to use.
            **driver_kwargs: Additional arguments for LocalDevDriver.

        Returns:
            Updated RunInfo.

        Raises:
            ValueError: If run_id not found or already loaded.
        """
        from juriscraper.scraper_driver.common.request_manager import (
            AsyncRequestManager,
        )
        from juriscraper.scraper_driver.driver.dev_driver.dev_driver import (
            LocalDevDriver,
        )
        from juriscraper.scraper_driver.driver.dev_driver.rate_limiter import (
            JitterRateLimitInterceptor,
        )
        from juriscraper.scraper_driver.driver.dev_driver.schema import (
            init_database,
        )
        from juriscraper.scraper_driver.driver.dev_driver.sql_manager import (
            SQLManager,
        )
        from juriscraper.scraper_driver.driver.dev_driver.web.archive import (
            get_storage_dir_for_run,
            uuid_archive_callback,
        )

        async with self._lock:
            if run_id not in self.runs:
                raise ValueError(f"Run '{run_id}' not found")

            run_info = self.runs[run_id]
            if run_info.driver is not None:
                raise ValueError(f"Run '{run_id}' is already loaded")

            # Set up storage directory for archived files
            storage_dir = get_storage_dir_for_run(self.runs_dir, run_id)

            # Extract config from driver_kwargs
            base_delay = driver_kwargs.get("base_delay", 10.0)
            jitter = driver_kwargs.get("jitter", 2.0)
            num_workers = driver_kwargs.get("num_workers", 1)
            max_backoff_time = driver_kwargs.get("max_backoff_time", 3600.0)

            # Initialize database and SQLManager
            aiosqlite_db = await init_database(run_info.db_path)
            sql_manager = SQLManager(aiosqlite_db)

            # Initialize run metadata (for existing runs, this updates status)
            scraper_name = scraper.__class__.__name__
            scraper_version = getattr(scraper, "__version__", None)
            await sql_manager.init_run_metadata(
                scraper_name=scraper_name,
                scraper_version=scraper_version,
                base_delay=base_delay,
                jitter=jitter,
                num_workers=num_workers,
                max_backoff_time=max_backoff_time,
            )

            # Restore queue since we're resuming
            pending_count = await sql_manager.restore_queue()
            if pending_count > 0:
                logger.info(
                    f"Restored {pending_count} pending requests from database"
                )

            # Set up rate limiter interceptor and request manager
            rate_limiter = JitterRateLimitInterceptor(
                base_delay_seconds=base_delay,
                jitter_seconds=jitter,
            )
            request_manager = AsyncRequestManager(
                interceptors=[rate_limiter],
                ssl_context=scraper.get_ssl_context(),
            )

            # Load driver with resume=True and custom archive handler
            driver = LocalDevDriver(
                scraper=scraper,
                db=sql_manager,
                storage_dir=storage_dir,
                resume=True,
                request_manager=request_manager,
                **driver_kwargs,
            )

            # Set the custom archive callback
            driver.on_archive = uuid_archive_callback

            run_info.driver = driver
            run_info.status = "loaded"

            logger.info(f"Loaded run '{run_id}'")
            return run_info

    async def start_run(self, run_id: str) -> RunInfo:
        """Start running a loaded driver.

        Args:
            run_id: The run identifier.

        Returns:
            Updated RunInfo.

        Raises:
            ValueError: If run not loaded or already running.
        """
        async with self._lock:
            if run_id not in self.runs:
                raise ValueError(f"Run '{run_id}' not found")

            run_info = self.runs[run_id]
            if run_info.driver is None:
                raise ValueError(f"Run '{run_id}' is not loaded")
            if run_info.task is not None and not run_info.task.done():
                raise ValueError(f"Run '{run_id}' is already running")

            # Create task to run the driver
            async def run_driver() -> None:
                assert run_info.driver is not None
                try:
                    # Don't set up signal handlers - FastAPI manages those
                    await run_info.driver.run(setup_signal_handlers=False)
                except asyncio.CancelledError:
                    logger.info(f"Run '{run_id}' was cancelled")
                except Exception as e:
                    logger.exception(f"Run '{run_id}' failed: {e}")
                finally:
                    async with self._lock:
                        run_info.status = "stopped"

            run_info.task = asyncio.create_task(run_driver())
            run_info.status = "running"
            run_info.started_at = datetime.now(timezone.utc)

            logger.info(f"Started run '{run_id}'")
            return run_info

    async def stop_run(self, run_id: str, timeout: float = 30.0) -> RunInfo:
        """Stop a running driver gracefully.

        Args:
            run_id: The run identifier.
            timeout: Timeout in seconds to wait for graceful stop.

        Returns:
            Updated RunInfo.

        Raises:
            ValueError: If run not found or not running.
        """
        async with self._lock:
            if run_id not in self.runs:
                raise ValueError(f"Run '{run_id}' not found")

            run_info = self.runs[run_id]
            if run_info.task is None or run_info.task.done():
                raise ValueError(f"Run '{run_id}' is not running")

            run_info.status = "stopping"

        # Signal stop and wait (outside lock)
        assert run_info.driver is not None
        run_info.driver.stop()

        try:
            await asyncio.wait_for(run_info.task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Run '{run_id}' did not stop gracefully, cancelling"
            )
            run_info.task.cancel()
            try:
                await run_info.task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            run_info.status = "stopped"

        logger.info(f"Stopped run '{run_id}'")
        return run_info

    async def unload_run(self, run_id: str) -> None:
        """Unload a run, closing its driver connection.

        Args:
            run_id: The run identifier.

        Raises:
            ValueError: If run not found or still running.
        """
        async with self._lock:
            if run_id not in self.runs:
                raise ValueError(f"Run '{run_id}' not found")

            run_info = self.runs[run_id]
            if run_info.task is not None and not run_info.task.done():
                raise ValueError(f"Run '{run_id}' is still running")

            if run_info.driver is not None:
                await run_info.driver.close()
                run_info.driver = None

            run_info.status = "unloaded"

        logger.info(f"Unloaded run '{run_id}'")

    async def delete_run(self, run_id: str) -> None:
        """Delete a run and its database file.

        Args:
            run_id: The run identifier.

        Raises:
            ValueError: If run not found or still running.
        """
        async with self._lock:
            if run_id not in self.runs:
                raise ValueError(f"Run '{run_id}' not found")

            run_info = self.runs[run_id]
            if run_info.task is not None and not run_info.task.done():
                raise ValueError(f"Run '{run_id}' is still running")

            if run_info.driver is not None:
                await run_info.driver.close()

            # Delete database file
            if run_info.db_path.exists():
                run_info.db_path.unlink()
                # Also delete WAL and SHM files if they exist
                for suffix in ["-wal", "-shm"]:
                    wal_path = run_info.db_path.with_suffix(f".db{suffix}")
                    if wal_path.exists():
                        wal_path.unlink()

            del self.runs[run_id]

        logger.info(f"Deleted run '{run_id}'")

    async def shutdown_all(self, timeout: float = 30.0) -> None:
        """Stop all running drivers and close connections.

        Used for graceful shutdown during hot reload.

        Args:
            timeout: Timeout in seconds to wait for each driver.
        """
        logger.info("Shutting down all runs...")

        # Get list of running runs
        async with self._lock:
            running_runs = [
                run_id
                for run_id, run_info in self.runs.items()
                if run_info.task is not None and not run_info.task.done()
            ]

        # Stop running runs
        for run_id in running_runs:
            try:
                await self.stop_run(run_id, timeout=timeout)
            except Exception as e:
                logger.warning(f"Error stopping run '{run_id}': {e}")

        # Unload all runs
        async with self._lock:
            for run_id, run_info in self.runs.items():
                if run_info.driver is not None:
                    try:
                        await run_info.driver.close()
                        run_info.driver = None
                        run_info.status = "unloaded"
                    except Exception as e:
                        logger.warning(f"Error closing run '{run_id}': {e}")

        logger.info("All runs shut down")


# Global run manager instance (set during lifespan)
_run_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    """Get the global run manager instance.

    Returns:
        The RunManager instance.

    Raises:
        RuntimeError: If run manager not initialized.
    """
    if _run_manager is None:
        raise RuntimeError("Run manager not initialized")
    return _run_manager


async def get_sql_manager_for_run(
    run_id: str, manager: RunManager
) -> SQLManager:
    """Get SQLManager for a run, opening DB if not already loaded.

    This function provides database access for runs without requiring
    the full driver to be loaded. For loaded runs, it wraps the driver's
    existing database connection. For unloaded runs, it opens the database
    directly.

    Args:
        run_id: The run identifier.
        manager: The run manager.

    Returns:
        SQLManager instance for the run.

    Raises:
        ValueError: If run not found.
    """
    run_info = await manager.get_run(run_id)
    if run_info is None:
        raise ValueError(f"Run '{run_id}' not found")

    # If driver is loaded, use its SQLManager
    if run_info.driver is not None:
        return run_info.driver.db

    # Otherwise, open the database directly
    # Note: For now, we require the driver to be loaded
    # to avoid managing multiple connections to the same database
    raise ValueError(
        f"Run '{run_id}' is not loaded. Load it first with POST /api/runs/{run_id}/load"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI app.

    Handles startup (scan runs directory, scan scrapers) and shutdown (stop all runs).
    """
    global _run_manager

    # Get runs directory from app state or use default
    runs_dir = getattr(app.state, "runs_dir", Path("runs"))

    # Initialize run manager
    _run_manager = RunManager(runs_dir)

    # Scan for existing runs
    discovered = await _run_manager.scan_runs()
    logger.info(f"Discovered {len(discovered)} existing runs")

    # Initialize scraper registry
    from juriscraper.scraper_driver.driver.dev_driver.web.scraper_registry import (
        init_registry,
    )

    sd_dir = getattr(app.state, "sd_dir", None)
    registry = init_registry(sd_dir)
    logger.info(f"Discovered {len(registry.list_scrapers())} scrapers")

    yield

    # Shutdown all runs
    await _run_manager.shutdown_all()
    _run_manager = None


def create_app(
    runs_dir: Path | None = None, sd_dir: Path | None = None
) -> FastAPI:
    """Create a new FastAPI application.

    Args:
        runs_dir: Directory for run database files. Defaults to "runs".
        sd_dir: Directory containing scrapers. Defaults to juriscraper/sd.

    Returns:
        Configured FastAPI application.
    """
    from fastapi.staticfiles import StaticFiles

    from juriscraper.scraper_driver.driver.dev_driver.web.routes import (
        archived_files_router,
        compression_router,
        debug_router,
        errors_router,
        export_router,
        requests_router,
        responses_router,
        results_router,
        runs_router,
        scrapers_router,
        views_router,
        websocket_router,
    )

    app = FastAPI(
        title="LocalDevDriver Web Interface",
        description="Web interface for managing scraper runs",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config in app state for lifespan access
    app.state.runs_dir = runs_dir or Path("runs")
    app.state.sd_dir = sd_dir

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount(
            "/static", StaticFiles(directory=str(static_dir)), name="static"
        )

    # Include API routers
    app.include_router(scrapers_router)
    app.include_router(runs_router)
    app.include_router(requests_router)
    app.include_router(responses_router)
    app.include_router(results_router)
    app.include_router(errors_router)
    app.include_router(compression_router)
    app.include_router(export_router)
    app.include_router(debug_router)
    app.include_router(archived_files_router)
    app.include_router(websocket_router)

    # Include view routers (HTML pages) - must be last to avoid route conflicts
    app.include_router(views_router)

    return app


# Default app instance
app = create_app()
