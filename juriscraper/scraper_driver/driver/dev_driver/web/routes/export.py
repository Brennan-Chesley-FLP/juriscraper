"""REST API endpoints for data export within a run.

This module provides endpoints for:
- Exporting responses to WARC format
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
)

router = APIRouter(prefix="/api/runs/{run_id}/export", tags=["export"])


class WarcExportRequest(BaseModel):
    """Request model for WARC export."""

    compress: bool = Field(
        default=True, description="Compress the WARC file with gzip"
    )
    continuation: str | None = Field(
        None, description="Filter by continuation"
    )


class WarcExportResponse(BaseModel):
    """Response model for WARC export metadata."""

    record_count: int
    file_size: int
    filename: str
    message: str


async def _get_db_for_run(run_id: str, manager: RunManager):
    """Get database connection for a loaded run."""
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


@router.post("/warc", response_class=FileResponse)
async def export_warc(
    run_id: str,
    request: WarcExportRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> FileResponse:
    """Export responses to a WARC file.

    Creates a WARC file containing all request/response pairs for the run,
    suitable for archival or replay with tools like Wayback Machine.

    Args:
        run_id: The run identifier.
        request: Export options.

    Returns:
        WARC file as downloadable attachment.

    Raises:
        HTTPException: 400 if no responses to export.
    """
    from juriscraper.scraper_driver.driver.dev_driver.warc_export import (
        export_warc as do_export,
    )

    db = await _get_db_for_run(run_id, manager)

    # Create temp file for WARC
    suffix = ".warc.gz" if request.compress else ".warc"
    fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix=f"{run_id}_")
    # Close the file descriptor since we'll pass the path to export function
    import os

    os.close(fd)
    warc_path = Path(temp_path)

    try:
        count = await do_export(
            db,
            warc_path,
            compress=request.compress,
            continuation=request.continuation,
        )
    except Exception as e:
        warc_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export WARC: {e}",
        ) from e

    if count == 0:
        warc_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No responses to export",
        )

    filename = f"{run_id}{suffix}"
    media_type = (
        "application/warc+gzip" if request.compress else "application/warc"
    )

    return FileResponse(
        path=warc_path,
        filename=filename,
        media_type=media_type,
        background=None,  # Don't delete file in background, let client download complete
    )


@router.get("/warc/preview", response_model=WarcExportResponse)
async def preview_warc_export(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    continuation: str | None = Query(
        None, description="Filter by continuation"
    ),
) -> WarcExportResponse:
    """Preview WARC export without creating the file.

    Returns metadata about what would be exported.

    Args:
        run_id: The run identifier.
        continuation: Optional continuation filter.

    Returns:
        Export preview with record count.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query
    conditions = []
    params: list = []

    if continuation:
        conditions.append("continuation = ?")
        params.append(continuation)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor = await db.execute(
        SQL.SELECT_WARC_PREVIEW_STATS.format(where_clause=where_clause),
        params,
    )
    row = await cursor.fetchone()
    count = row[0] if row else 0
    estimated_size = row[1] if row else 0

    return WarcExportResponse(
        record_count=count,
        file_size=estimated_size,
        filename=f"{run_id}.warc.gz",
        message=f"Would export {count} records (~{estimated_size} bytes uncompressed)",
    )
