#!/usr/bin/env python3
"""Search for regex patterns in responses of a LocalDevDriver run.

This script searches through all responses in a run's SQLite database
and outputs matching results as JSONL.

Usage:
    python scripts/search_run.py --run runs/my-run.db --search "pattern"
    python scripts/search_run.py --run runs/my-run.db --search "(?i)error.*found"

Output format (JSONL):
    {"request_id": 123, "url": "https://example.com/page"}
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sqlite3
import sys
from pathlib import Path

import zstandard as zstd

# Handle broken pipe gracefully (e.g., when piping to head)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def decompress(data: bytes, dictionary: bytes | None = None) -> bytes:
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


def search_responses(
    db_path: Path,
    pattern: str,
    *,
    case_insensitive: bool = False,
) -> None:
    """Search responses for a regex pattern and output matching results as JSONL.

    Args:
        db_path: Path to the SQLite database file.
        pattern: Regex pattern to search for.
        case_insensitive: Whether to use case-insensitive matching.
    """
    flags = re.IGNORECASE if case_insensitive else 0
    regex = re.compile(pattern, flags)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Cache dictionaries by ID
    dict_cache: dict[int, bytes] = {}

    try:
        # Get all responses with their compressed content
        cursor = conn.execute("""
            SELECT r.id, r.request_id, r.url, r.content_compressed, r.compression_dict_id
            FROM responses r
            WHERE r.content_compressed IS NOT NULL
            ORDER BY r.id
        """)

        for row in cursor:
            response_id = row["id"]
            request_id = row["request_id"]
            url = row["url"]
            compressed = row["content_compressed"]
            dict_id = row["compression_dict_id"]

            # Get dictionary if needed
            dictionary = None
            if dict_id is not None:
                if dict_id not in dict_cache:
                    dict_cursor = conn.execute(
                        "SELECT dictionary_data FROM compression_dicts WHERE id = ?",
                        (dict_id,),
                    )
                    dict_row = dict_cursor.fetchone()
                    if dict_row:
                        dict_cache[dict_id] = dict_row["dictionary_data"]
                dictionary = dict_cache.get(dict_id)

            # Decompress and search
            try:
                content = decompress(compressed, dictionary)
                text = content.decode("utf-8", errors="replace")

                if regex.search(text):
                    result = {"request_id": request_id, "url": url}
                    print(json.dumps(result))

            except Exception as e:
                # Log errors to stderr but continue
                print(
                    f"Error processing response {response_id}: {e}",
                    file=sys.stderr,
                )
                continue

    finally:
        conn.close()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Search for regex patterns in responses of a LocalDevDriver run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/search_run.py --run runs/my-run.db --search "error"
    python scripts/search_run.py --run runs/my-run.db --search "(?i)not found"
    python scripts/search_run.py --run runs/my-run.db -s "class=.main." -i

Output is JSONL format:
    {"request_id": 123, "url": "https://example.com/page"}
""",
    )
    parser.add_argument(
        "--run",
        "-r",
        required=True,
        type=Path,
        help="Path to the run's SQLite database file",
    )
    parser.add_argument(
        "--search",
        "-s",
        required=True,
        help="Regex pattern to search for in response content",
    )
    parser.add_argument(
        "--ignore-case",
        "-i",
        action="store_true",
        help="Case-insensitive search",
    )

    args = parser.parse_args()

    # Validate database path
    db_path = args.run
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}", file=sys.stderr)
        return 1

    # Validate regex
    try:
        re.compile(args.search)
    except re.error as e:
        print(f"Error: Invalid regex pattern: {e}", file=sys.stderr)
        return 1

    search_responses(db_path, args.search, case_insensitive=args.ignore_case)
    return 0


if __name__ == "__main__":
    sys.exit(main())
