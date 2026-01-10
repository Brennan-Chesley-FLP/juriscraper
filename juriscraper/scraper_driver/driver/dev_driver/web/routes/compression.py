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

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL
from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
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

    db = await _get_db_for_run(run_id, manager)

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

    db = await _get_db_for_run(run_id, manager)

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
    db = await _get_db_for_run(run_id, manager)

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
    db = await _get_db_for_run(run_id, manager)

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
