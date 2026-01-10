"""Zstd compression for LocalDevDriver responses.

This module provides zstd compression and decompression for HTTP responses,
with support for per-continuation trained dictionaries for better compression
ratios on similar content.

Compression is done with zstd (Zstandard) which offers excellent compression
ratios and fast decompression speeds. Dictionary-based compression can
significantly improve compression of similar content (like HTML from the
same website).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import zstandard as zstd

from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    import aiosqlite

# Default compression level (3 is a good balance of speed/ratio)
DEFAULT_COMPRESSION_LEVEL = 3


def compress(
    data: bytes,
    level: int = DEFAULT_COMPRESSION_LEVEL,
    dictionary: bytes | None = None,
) -> bytes:
    """Compress data using zstd.

    Args:
        data: The data to compress.
        level: Compression level (1-22, default 3).
        dictionary: Optional pre-trained dictionary for better compression.

    Returns:
        Compressed data bytes.
    """
    if dictionary:
        dict_obj = zstd.ZstdCompressionDict(dictionary)
        compressor = zstd.ZstdCompressor(level=level, dict_data=dict_obj)
    else:
        compressor = zstd.ZstdCompressor(level=level)

    return compressor.compress(data)


def decompress(
    data: bytes,
    dictionary: bytes | None = None,
) -> bytes:
    """Decompress zstd-compressed data.

    Args:
        data: The compressed data to decompress.
        dictionary: Dictionary used for compression (must match).

    Returns:
        Decompressed data bytes.
    """
    if dictionary:
        dict_obj = zstd.ZstdCompressionDict(dictionary)
        decompressor = zstd.ZstdDecompressor(dict_data=dict_obj)
    else:
        decompressor = zstd.ZstdDecompressor()

    return decompressor.decompress(data)


async def get_compression_dict(
    db: aiosqlite.Connection,
    continuation: str,
) -> tuple[int, bytes] | None:
    """Get the latest compression dictionary for a continuation.

    Args:
        db: Database connection.
        continuation: The continuation method name.

    Returns:
        Tuple of (dict_id, dictionary_data) or None if no dictionary exists.
    """
    cursor = await db.execute(
        SQL.SELECT_COMPRESSION_DICT_LATEST, (continuation,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return (row[0], row[1])


async def get_dict_by_id(
    db: aiosqlite.Connection,
    dict_id: int,
) -> bytes | None:
    """Get a compression dictionary by its ID.

    Args:
        db: Database connection.
        dict_id: The dictionary ID.

    Returns:
        Dictionary data bytes or None if not found.
    """
    cursor = await db.execute(
        SQL.SELECT_COMPRESSION_DICT_DATA_BY_ID, (dict_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def compress_response(
    db: aiosqlite.Connection,
    content: bytes,
    continuation: str,
    level: int = DEFAULT_COMPRESSION_LEVEL,
) -> tuple[bytes, int | None]:
    """Compress response content, using dictionary if available.

    Attempts to use a trained dictionary for the continuation if one exists.
    Falls back to standard compression if no dictionary is available.

    Args:
        db: Database connection.
        content: The response content to compress.
        continuation: The continuation method name (for dictionary lookup).
        level: Compression level (1-22, default 3).

    Returns:
        Tuple of (compressed_data, dict_id) where dict_id is None if no
        dictionary was used.
    """
    # Try to get a dictionary for this continuation
    dict_result = await get_compression_dict(db, continuation)

    if dict_result:
        dict_id, dictionary = dict_result
        compressed = compress(content, level=level, dictionary=dictionary)
        return (compressed, dict_id)
    else:
        compressed = compress(content, level=level)
        return (compressed, None)


async def decompress_response(
    db: aiosqlite.Connection,
    compressed: bytes,
    dict_id: int | None,
) -> bytes:
    """Decompress response content, using dictionary if one was used.

    Args:
        db: Database connection.
        compressed: The compressed data.
        dict_id: The dictionary ID used for compression (or None).

    Returns:
        Decompressed data bytes.
    """
    dictionary = None
    if dict_id is not None:
        dictionary = await get_dict_by_id(db, dict_id)
        if dictionary is None:
            raise ValueError(f"Dictionary {dict_id} not found in database")

    return decompress(compressed, dictionary=dictionary)


# Default dictionary size (112640 bytes = 110KB, zstd's default)
DEFAULT_DICT_SIZE = 112640


async def train_compression_dict(
    db: aiosqlite.Connection,
    continuation: str,
    sample_limit: int = 100,
    dict_size: int = DEFAULT_DICT_SIZE,
) -> int:
    """Train a zstd compression dictionary from stored responses.

    Samples responses for the given continuation, trains a zstd dictionary,
    and stores it as a new version in the compression_dicts table.

    Args:
        db: Database connection.
        continuation: The continuation method name to train dictionary for.
        sample_limit: Maximum number of responses to sample (default 100).
        dict_size: Size of dictionary to train (default 112640 bytes).

    Returns:
        The ID of the newly created dictionary.

    Raises:
        ValueError: If no responses found for continuation or training fails.
    """
    # Sample responses for this continuation (decompress first if needed)
    cursor = await db.execute(
        SQL.SELECT_RESPONSES_FOR_DICT_TRAINING,
        (continuation, sample_limit),
    )
    rows = await cursor.fetchall()

    if not rows:
        raise ValueError(
            f"No responses found for continuation '{continuation}'"
        )

    # Decompress all samples to get raw content for training
    samples = []
    for compressed, dict_id in rows:
        try:
            content = await decompress_response(db, compressed, dict_id)
            samples.append(content)
        except Exception:
            # Skip samples that fail to decompress
            continue

    if not samples:
        raise ValueError(
            f"Could not decompress any samples for continuation '{continuation}'"
        )

    # Train the dictionary
    dictionary_data = zstd.train_dictionary(dict_size, samples)

    # Get next version number for this continuation
    cursor = await db.execute(SQL.SELECT_NEXT_DICT_VERSION, (continuation,))
    row = await cursor.fetchone()
    next_version = row[0]

    # Store the new dictionary
    cursor = await db.execute(
        SQL.INSERT_COMPRESSION_DICT,
        (continuation, next_version, dictionary_data.as_bytes(), len(samples)),
    )
    await db.commit()

    return cursor.lastrowid  # type: ignore[return-value]


async def recompress_responses(
    db: aiosqlite.Connection,
    continuation: str,
    level: int = DEFAULT_COMPRESSION_LEVEL,
) -> tuple[int, int, int]:
    """Re-compress responses using the latest dictionary for a continuation.

    Decompresses all responses for the continuation and re-compresses them
    using the latest trained dictionary. This can significantly improve
    compression ratios after training a new dictionary.

    Args:
        db: Database connection.
        continuation: The continuation method name.
        level: Compression level for re-compression (default 3).

    Returns:
        Tuple of (recompressed_count, total_original_bytes, total_compressed_bytes).

    Raises:
        ValueError: If no dictionary exists for this continuation.
    """
    # Get the latest dictionary for this continuation
    dict_result = await get_compression_dict(db, continuation)
    if dict_result is None:
        raise ValueError(
            f"No dictionary found for continuation '{continuation}'. "
            "Train a dictionary first using train_compression_dict()."
        )

    dict_id, dictionary = dict_result

    # Get all responses for this continuation
    cursor = await db.execute(
        SQL.SELECT_RESPONSES_FOR_RECOMPRESSION,
        (continuation,),
    )
    rows = await cursor.fetchall()

    recompressed_count = 0
    total_original = 0
    total_compressed = 0

    for response_id, compressed, old_dict_id in rows:
        try:
            # Decompress using the old dictionary (or none)
            content = await decompress_response(db, compressed, old_dict_id)
            original_size = len(content)

            # Re-compress with new dictionary
            new_compressed = compress(
                content, level=level, dictionary=dictionary
            )
            new_size = len(new_compressed)

            # Update the response
            await db.execute(
                SQL.UPDATE_RESPONSE_RECOMPRESSED,
                (
                    new_compressed,
                    original_size,
                    new_size,
                    dict_id,
                    response_id,
                ),
            )

            recompressed_count += 1
            total_original += original_size
            total_compressed += new_size

        except Exception:
            # Skip responses that fail to process
            continue

    await db.commit()
    return (recompressed_count, total_original, total_compressed)
