"""REST API endpoints for viewing archived files within a run.

This module provides endpoints for:
- Listing archived files with filters
- Getting archived file details
- Getting archived file content
- Archived files statistics
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
)

router = APIRouter(
    prefix="/api/runs/{run_id}/archived-files", tags=["archived-files"]
)


class ArchivedFileResponse(BaseModel):
    """Response model for a single archived file record."""

    id: int
    request_id: int
    file_path: str
    original_url: str
    expected_type: str | None
    file_size: int | None
    content_hash: str | None
    created_at: str | None
    continuation: str | None


class ArchivedFileListResponse(BaseModel):
    """Response model for listing archived files."""

    items: list[ArchivedFileResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


class ArchivedFilesStatsResponse(BaseModel):
    """Response model for archived files statistics."""

    total_files: int
    total_size: int
    total_size_human: str


async def _get_sql_manager(run_id: str, manager: RunManager) -> SQLManager:
    """Get SQLManager for a loaded run."""
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


def _format_size(size: int) -> str:
    """Format bytes to human-readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


@router.get("", response_model=ArchivedFileListResponse)
async def list_archived_files(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
    expected_type: str | None = Query(None, description="Filter by file type"),
    continuation: str | None = Query(
        None, description="Filter by continuation"
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> ArchivedFileListResponse:
    """List archived files for a run with optional filters.

    Args:
        run_id: The run identifier.
        expected_type: Optional file type filter (pdf, audio, etc.).
        continuation: Optional continuation name filter.
        offset: Pagination offset.
        limit: Maximum number of results.

    Returns:
        Paginated list of archived files.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # Build query
    conditions = []
    params: list = []

    if expected_type:
        conditions.append("af.expected_type = ?")
        params.append(expected_type)
    if continuation:
        conditions.append("r.continuation = ?")
        params.append(continuation)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count - need to join for continuation filter
    count_query = """
        SELECT COUNT(*)
        FROM archived_files af
        LEFT JOIN requests r ON af.request_id = r.id
    """
    if conditions:
        count_query += f" WHERE {' AND '.join(conditions)}"
    cursor = await db.execute(count_query, params)
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get paginated results
    cursor = await db.execute(
        SQL.SELECT_ARCHIVED_FILES_LIST.format(where_clause=where_clause),
        params + [limit, offset],
    )
    rows = await cursor.fetchall()

    items = [
        ArchivedFileResponse(
            id=r[0],
            request_id=r[1],
            file_path=r[2],
            original_url=r[3],
            expected_type=r[4],
            file_size=r[5],
            content_hash=r[6],
            created_at=r[7],
            continuation=r[8],
        )
        for r in rows
    ]

    return ArchivedFileListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


@router.get("/stats", response_model=ArchivedFilesStatsResponse)
async def get_archived_files_stats(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ArchivedFilesStatsResponse:
    """Get statistics for archived files.

    Args:
        run_id: The run identifier.

    Returns:
        Archived files statistics.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_ARCHIVED_FILES_STATS)
    row = await cursor.fetchone()

    total_files = row[0] if row else 0
    total_size = row[1] if row else 0

    return ArchivedFilesStatsResponse(
        total_files=total_files,
        total_size=total_size,
        total_size_human=_format_size(total_size),
    )


@router.get("/{file_id}", response_model=ArchivedFileResponse)
async def get_archived_file(
    run_id: str,
    file_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ArchivedFileResponse:
    """Get details for a specific archived file.

    Args:
        run_id: The run identifier.
        file_id: The archived file ID.

    Returns:
        Archived file details.

    Raises:
        HTTPException: 404 if file not found.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_ARCHIVED_FILE_BY_ID, (file_id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archived file {file_id} not found in run '{run_id}'",
        )

    return ArchivedFileResponse(
        id=row[0],
        request_id=row[1],
        file_path=row[2],
        original_url=row[3],
        expected_type=row[4],
        file_size=row[5],
        content_hash=row[6],
        created_at=row[7],
        continuation=row[8],
    )


@router.get("/{file_id}/content")
async def get_archived_file_content(
    run_id: str,
    file_id: int,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> Response:
    """Get content of an archived file from disk.

    Args:
        run_id: The run identifier.
        file_id: The archived file ID.

    Returns:
        File content as raw bytes.

    Raises:
        HTTPException: 404 if file not found or file doesn't exist on disk.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_ARCHIVED_FILE_BY_ID, (file_id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Archived file {file_id} not found in run '{run_id}'",
        )

    file_path = row[2]
    expected_type = row[4]

    # Read file from disk
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found on disk: {file_path}",
        )

    content = path.read_bytes()

    # Determine content type
    content_type_map = {
        "pdf": "application/pdf",
        "audio": "audio/mpeg",
        "image": "image/jpeg",
        "html": "text/html",
    }
    content_type = content_type_map.get(
        expected_type or "", "application/octet-stream"
    )

    return Response(content=content, media_type=content_type)
