"""REST API endpoints for compression management within a run.

This module provides endpoints for:
- Training compression dictionaries
- Recompressing responses with new dictionaries
- Viewing compression statistics
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.sql_manager import SQLManager
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
    get_sql_manager_for_run,
)

router = APIRouter(
    prefix="/api/runs/{run_id}/compression", tags=["compression"]
)


class TrainDictRequest(BaseModel):
    """Request model for training a compression dictionary."""

    continuation: str = Field(
        ..., description="Continuation to train dictionary for"
    )
    sample_limit: int = Field(
        default=100, ge=1, description="Maximum samples to use"
    )
    dict_size: int = Field(
        default=112640, ge=1024, description="Dictionary size in bytes"
    )


class TrainDictResponse(BaseModel):
    """Response model for dictionary training."""

    dict_id: int
    continuation: str
    sample_count: int
    dict_size: int
    message: str


class RecompressRequest(BaseModel):
    """Request model for recompressing responses."""

    continuation: str = Field(..., description="Continuation to recompress")
    compression_level: int = Field(
        default=3, ge=1, le=22, description="Zstd compression level"
    )


class RecompressResponse(BaseModel):
    """Response model for recompression."""

    count: int
    total_original_bytes: int
    total_compressed_bytes: int
    compression_ratio: float
    message: str


class CompressionStatsResponse(BaseModel):
    """Response model for compression statistics."""

    total_responses: int
    total_original_bytes: int
    total_compressed_bytes: int
    compression_ratio: float
    with_dict_count: int
    no_dict_count: int


class CompressionStatsByContinuationItem(BaseModel):
    """Compression stats for a single continuation/dictionary combination."""

    continuation: str
    dict_id: int | None = None
    dict_version: int | None = None
    response_count: int = 0
    total_original_bytes: int = 0
    total_compressed_bytes: int = 0
    compression_ratio: float = 0.0
    has_trained_dict: bool = (
        False  # Whether a trained dict exists for this continuation
    )


class CompressionStatsByContinuationResponse(BaseModel):
    """Response model for compression stats grouped by continuation."""

    items: list[CompressionStatsByContinuationItem]
    grand_total_responses: int
    grand_total_original: int
    grand_total_compressed: int
    overall_ratio: float


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


@router.post("/train-dict", response_model=TrainDictResponse)
async def train_dictionary(
    run_id: str,
    request: TrainDictRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> TrainDictResponse:
    """Train a compression dictionary from stored responses.

    Samples responses for the specified continuation and trains a zstd
    dictionary that can significantly improve compression ratios.

    Args:
        run_id: The run identifier.
        request: Training parameters.

    Returns:
        Training result with new dictionary ID.

    Raises:
        HTTPException: 400 if not enough responses to train.
    """
    from juriscraper.scraper_driver.driver.dev_driver.compression import (
        train_compression_dict,
    )

    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    try:
        dict_id = await train_compression_dict(
            db,
            request.continuation,
            sample_limit=request.sample_limit,
            dict_size=request.dict_size,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Get sample count for response
    cursor = await db.execute(SQL.SELECT_DICT_SAMPLE_COUNT, (dict_id,))
    row = await cursor.fetchone()
    sample_count = row[0] if row else 0

    return TrainDictResponse(
        dict_id=dict_id,
        continuation=request.continuation,
        sample_count=sample_count,
        dict_size=request.dict_size,
        message=f"Trained dictionary {dict_id} from {sample_count} samples",
    )


@router.post("/recompress", response_model=RecompressResponse)
async def recompress_responses(
    run_id: str,
    request: RecompressRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> RecompressResponse:
    """Recompress responses using the latest dictionary.

    After training a new dictionary, use this endpoint to recompress
    existing responses for better compression ratios.

    Args:
        run_id: The run identifier.
        request: Recompression parameters.

    Returns:
        Recompression statistics.

    Raises:
        HTTPException: 400 if no dictionary exists for continuation.
    """
    from juriscraper.scraper_driver.driver.dev_driver.compression import (
        recompress_responses as do_recompress,
    )

    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    try:
        count, total_original, total_compressed = await do_recompress(
            db,
            request.continuation,
            level=request.compression_level,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    ratio = total_original / total_compressed if total_compressed > 0 else 0

    return RecompressResponse(
        count=count,
        total_original_bytes=total_original,
        total_compressed_bytes=total_compressed,
        compression_ratio=round(ratio, 2),
        message=f"Recompressed {count} responses for '{request.continuation}'",
    )


@router.get("/stats", response_model=CompressionStatsResponse)
async def get_compression_stats(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> CompressionStatsResponse:
    """Get compression statistics for the run.

    Args:
        run_id: The run identifier.

    Returns:
        Compression statistics.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_COMPRESSION_STATS_FOR_WEB)
    row = await cursor.fetchone()

    total = row[0] or 0
    total_original = row[1] or 0
    total_compressed = row[2] or 0
    with_dict = row[3] or 0
    no_dict = row[4] or 0

    ratio = total_original / total_compressed if total_compressed > 0 else 0

    return CompressionStatsResponse(
        total_responses=total,
        total_original_bytes=total_original,
        total_compressed_bytes=total_compressed,
        compression_ratio=round(ratio, 2),
        with_dict_count=with_dict,
        no_dict_count=no_dict,
    )


@router.get(
    "/stats-by-continuation",
    response_model=CompressionStatsByContinuationResponse,
)
async def get_compression_stats_by_continuation(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> CompressionStatsByContinuationResponse:
    """Get compression statistics grouped by continuation and dictionary version.

    Returns a breakdown of compression stats for each continuation, showing
    which dictionary is being used and the compression ratios achieved.

    Args:
        run_id: The run identifier.

    Returns:
        Compression statistics grouped by continuation.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    # First, get set of continuations that have trained dictionaries
    dict_cursor = await db.execute(
        "SELECT DISTINCT continuation FROM compression_dicts"
    )
    continuations_with_dicts = {row[0] for row in await dict_cursor.fetchall()}

    # Query stats grouped by continuation and dictionary
    query = """
        SELECT
            r.continuation,
            r.compression_dict_id,
            d.version,
            COUNT(*) as response_count,
            COALESCE(SUM(r.content_size_original), 0) as total_original,
            COALESCE(SUM(r.content_size_compressed), 0) as total_compressed
        FROM responses r
        LEFT JOIN compression_dicts d ON r.compression_dict_id = d.id
        GROUP BY r.continuation, r.compression_dict_id
        ORDER BY r.continuation, d.version DESC NULLS LAST
    """
    cursor = await db.execute(query)
    rows = await cursor.fetchall()

    items: list[CompressionStatsByContinuationItem] = []
    grand_total_responses = 0
    grand_total_original = 0
    grand_total_compressed = 0

    for continuation, dict_id, version, count, total_orig, total_comp in rows:
        ratio = total_orig / total_comp if total_comp > 0 else 0.0
        items.append(
            CompressionStatsByContinuationItem(
                continuation=continuation,
                dict_id=dict_id,
                dict_version=version,
                response_count=count,
                total_original_bytes=total_orig,
                total_compressed_bytes=total_comp,
                compression_ratio=round(ratio, 2),
                has_trained_dict=continuation in continuations_with_dicts,
            )
        )
        grand_total_responses += count
        grand_total_original += total_orig
        grand_total_compressed += total_comp

    overall_ratio = (
        grand_total_original / grand_total_compressed
        if grand_total_compressed > 0
        else 0.0
    )

    return CompressionStatsByContinuationResponse(
        items=items,
        grand_total_responses=grand_total_responses,
        grand_total_original=grand_total_original,
        grand_total_compressed=grand_total_compressed,
        overall_ratio=round(overall_ratio, 2),
    )


@router.get("/dicts")
async def list_dictionaries(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> list[dict]:
    """List all compression dictionaries for the run.

    Args:
        run_id: The run identifier.

    Returns:
        List of dictionary metadata.
    """
    sql_manager = await _get_sql_manager(run_id, manager)
    db = sql_manager.db

    cursor = await db.execute(SQL.SELECT_COMPRESSION_DICTS_FOR_WEB)
    rows = await cursor.fetchall()

    return [
        {
            "id": r[0],
            "continuation": r[1],
            "version": r[2],
            "sample_count": r[3],
            "size": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]
