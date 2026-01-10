"""SQLite schema for LocalDevDriver.

This module defines the database schema for the LocalDevDriver, which provides
persistent storage for request queuing, response archival, compression
dictionaries, results, and error tracking.

The schema consists of 8 tables:
- requests: HTTP request queue with status tracking and retry logic
- responses: Compressed HTTP responses with dictionary references
- compression_dicts: Versioned zstd dictionaries per-continuation
- results: Validated scraped data
- archived_files: Downloaded file metadata
- run_metadata: Single-row configuration and state
- errors: Detailed error tracking with type-specific fields
- rate_bucket: Token bucket state for pyrate_limiter
"""

from pathlib import Path

import aiosqlite

# Schema version for migrations
SCHEMA_VERSION = 1

# SQL statements for creating tables
_CREATE_REQUESTS = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Queue management
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, failed, held
    priority INTEGER NOT NULL DEFAULT 9,
    queue_counter INTEGER NOT NULL,          -- For FIFO within same priority

    -- Request type
    request_type TEXT NOT NULL DEFAULT 'navigating',  -- navigating, non_navigating, archive

    -- HTTP Request
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    headers_json TEXT,                       -- JSON-encoded headers
    cookies_json TEXT,                       -- JSON-encoded cookies
    body BLOB,                               -- Request body (if any)

    -- Scraper context
    continuation TEXT NOT NULL,              -- Method name to call with response
    current_location TEXT NOT NULL DEFAULT '',
    accumulated_data_json TEXT,              -- JSON-encoded accumulated data
    aux_data_json TEXT,                      -- JSON-encoded aux data
    permanent_json TEXT,                     -- JSON-encoded permanent data
    deduplication_key TEXT,                  -- For duplicate detection

    -- ArchiveRequest-specific fields
    expected_type TEXT,                      -- For ArchiveRequest: expected file type

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Retry tracking (exponential backoff)
    retry_count INTEGER NOT NULL DEFAULT 0,
    cumulative_backoff REAL NOT NULL DEFAULT 0.0,  -- Total backoff time accumulated
    next_retry_delay REAL,                   -- Next backoff delay (base_delay * 2^retry_count)
    last_error TEXT,                         -- Last error message if failed

    -- Parent tracking
    parent_request_id INTEGER REFERENCES requests(id),

    -- Indexing
    UNIQUE(deduplication_key) ON CONFLICT IGNORE
)
"""

_CREATE_REQUESTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_requests_status_priority ON requests(status, priority, queue_counter)",
    "CREATE INDEX IF NOT EXISTS idx_requests_continuation ON requests(continuation)",
    "CREATE INDEX IF NOT EXISTS idx_requests_deduplication ON requests(deduplication_key)",
]

_CREATE_RESPONSES = """
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),

    -- HTTP Response
    status_code INTEGER NOT NULL,
    headers_json TEXT,                       -- JSON-encoded headers
    url TEXT NOT NULL,                       -- Final URL after redirects

    -- Content (compressed)
    content_compressed BLOB,                 -- Zstd-compressed content
    content_size_original INTEGER,           -- Original size for stats
    content_size_compressed INTEGER,         -- Compressed size

    -- Compression metadata
    compression_dict_id INTEGER REFERENCES compression_dicts(id),
    continuation TEXT NOT NULL,              -- For dictionary training grouping

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- WARC export metadata
    warc_record_id TEXT                      -- UUID for WARC record linking
)
"""

_CREATE_RESPONSES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_responses_request ON responses(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_responses_continuation ON responses(continuation)",
    "CREATE INDEX IF NOT EXISTS idx_responses_dict ON responses(compression_dict_id)",
]

_CREATE_COMPRESSION_DICTS = """
CREATE TABLE IF NOT EXISTS compression_dicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    continuation TEXT NOT NULL,              -- Which continuation this dict is for
    version INTEGER NOT NULL,                -- Version number (incrementing)
    dictionary_data BLOB NOT NULL,           -- The zstd dictionary bytes
    sample_count INTEGER NOT NULL,           -- How many samples trained on
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(continuation, version)
)
"""

_CREATE_COMPRESSION_DICTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_compression_dicts_continuation ON compression_dicts(continuation)",
]

_CREATE_RESULTS = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER REFERENCES requests(id),

    -- Result data
    result_type TEXT NOT NULL,               -- Pydantic model class name
    data_json TEXT NOT NULL,                 -- JSON-encoded result data

    -- Validation status
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    validation_errors_json TEXT,             -- JSON-encoded validation errors if invalid

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_RESULTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_results_type ON results(result_type)",
    "CREATE INDEX IF NOT EXISTS idx_results_request ON results(request_id)",
]

_CREATE_ARCHIVED_FILES = """
CREATE TABLE IF NOT EXISTS archived_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),

    -- File info
    file_path TEXT NOT NULL,                 -- Path relative to storage_dir
    original_url TEXT NOT NULL,              -- URL the file was downloaded from
    expected_type TEXT,                      -- "pdf", "audio", etc.
    file_size INTEGER,                       -- Size in bytes
    content_hash TEXT,                       -- SHA256 of file content for dedup

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_ARCHIVED_FILES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_archived_files_request ON archived_files(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_archived_files_hash ON archived_files(content_hash)",
]

_CREATE_RUN_METADATA = """
CREATE TABLE IF NOT EXISTS run_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),   -- Enforce single row

    -- Scraper identity
    scraper_name TEXT NOT NULL,
    scraper_version TEXT,

    -- Run state
    status TEXT NOT NULL DEFAULT 'created',  -- created, running, completed, error, interrupted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    error_message TEXT,

    -- Invocation parameters (immutable after creation)
    params_json TEXT,                        -- JSON-encoded ScraperParams filters
    base_delay REAL NOT NULL,
    jitter REAL NOT NULL,
    num_workers INTEGER NOT NULL,
    max_backoff_time REAL NOT NULL           -- Max cumulative backoff before marking failed
)
"""

_CREATE_ERRORS = """
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER REFERENCES requests(id),

    -- Error classification
    error_type TEXT NOT NULL,                -- 'structural', 'validation', 'transient'
    error_class TEXT NOT NULL,               -- Full exception class name
    message TEXT NOT NULL,
    request_url TEXT NOT NULL,

    -- Structured error data (type-specific)
    context_json TEXT,                       -- JSON-encoded error context

    -- For structural errors (HTMLStructuralAssumptionException)
    selector TEXT,
    selector_type TEXT,                      -- 'xpath' or 'css'
    expected_min INTEGER,
    expected_max INTEGER,
    actual_count INTEGER,

    -- For validation errors (DataFormatAssumptionException)
    model_name TEXT,
    validation_errors_json TEXT,             -- JSON-encoded Pydantic errors
    failed_doc_json TEXT,                    -- JSON-encoded failed document

    -- For transient errors
    status_code INTEGER,                     -- For HTMLResponseAssumptionException
    timeout_seconds REAL,                    -- For RequestTimeoutException

    -- Resolution tracking
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolution_notes TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_ERRORS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_errors_request ON errors(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_errors_type ON errors(error_type)",
    "CREATE INDEX IF NOT EXISTS idx_errors_unresolved ON errors(is_resolved) WHERE is_resolved = FALSE",
]

_CREATE_RATE_BUCKET = """
CREATE TABLE IF NOT EXISTS rate_bucket (
    id INTEGER PRIMARY KEY CHECK (id = 1),   -- Single bucket for this driver
    tokens REAL NOT NULL DEFAULT 0,          -- Current token count
    last_leak_at REAL NOT NULL               -- Unix timestamp of last leak
)
"""

_CREATE_RATE_ITEMS = """
CREATE TABLE IF NOT EXISTS rate_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                      -- Item name (e.g., URL or request key)
    timestamp INTEGER NOT NULL,              -- Timestamp in milliseconds
    weight INTEGER NOT NULL DEFAULT 1        -- Item weight for rate limiting
)
"""

_CREATE_RATE_ITEMS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rate_items_timestamp ON rate_items(timestamp)",
]

# Schema metadata table for versioning
_CREATE_SCHEMA_INFO = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


async def init_database(db_path: Path) -> aiosqlite.Connection:
    """Initialize the database with schema and return connection.

    Creates all tables if they don't exist and sets up WAL mode for
    better concurrent access performance.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open aiosqlite connection configured with WAL mode.
    """
    db = await aiosqlite.connect(db_path)

    # Enable WAL mode for better concurrent access
    await db.execute("PRAGMA journal_mode=WAL")

    # Enable foreign keys
    await db.execute("PRAGMA foreign_keys=ON")

    # Create all tables
    await db.execute(_CREATE_SCHEMA_INFO)
    await db.execute(_CREATE_REQUESTS)
    await db.execute(_CREATE_RESPONSES)
    await db.execute(_CREATE_COMPRESSION_DICTS)
    await db.execute(_CREATE_RESULTS)
    await db.execute(_CREATE_ARCHIVED_FILES)
    await db.execute(_CREATE_RUN_METADATA)
    await db.execute(_CREATE_ERRORS)
    await db.execute(_CREATE_RATE_BUCKET)
    await db.execute(_CREATE_RATE_ITEMS)

    # Create all indexes
    for index_sql in _CREATE_REQUESTS_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_RESPONSES_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_COMPRESSION_DICTS_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_RESULTS_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_ARCHIVED_FILES_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_ERRORS_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_RATE_ITEMS_INDEXES:
        await db.execute(index_sql)

    # Record schema version if not present
    cursor = await db.execute(
        "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if row is None:
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )

    await db.commit()
    return db


async def get_schema_version(db: aiosqlite.Connection) -> int:
    """Get the current schema version from the database.

    Args:
        db: An open aiosqlite connection.

    Returns:
        The current schema version number, or 0 if not initialized.
    """
    try:
        cursor = await db.execute(
            "SELECT version FROM schema_info ORDER BY version DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    except aiosqlite.OperationalError:
        return 0


async def get_next_queue_counter(db: aiosqlite.Connection) -> int:
    """Get the next queue counter value for FIFO ordering.

    Args:
        db: An open aiosqlite connection.

    Returns:
        The next queue_counter value (max + 1, or 1 if empty).
    """
    cursor = await db.execute("SELECT MAX(queue_counter) FROM requests")
    row = await cursor.fetchone()
    return (row[0] or 0) + 1
