"""SQLite schema for LocalDevDriver and PlaywrightDriver.

This module defines the database schema for the LocalDevDriver and PlaywrightDriver,
which provides persistent storage for request queuing, response archival, compression
dictionaries, results, and error tracking.

The schema consists of 14 tables:
- requests: HTTP request queue with status tracking and retry logic
- responses: Compressed HTTP responses with dictionary references
- compression_dicts: Versioned zstd dictionaries per-continuation
- results: Validated scraped data
- archived_files: Downloaded file metadata
- run_metadata: Single-row configuration and state (including browser config for Playwright)
- errors: Detailed error tracking with type-specific fields
- rate_bucket: Token bucket state for pyrate_limiter (legacy)
- rate_items: Rate limiting items for pyrate_limiter
- rate_limiter_state: Rate limiter state for adaptive rate limiting
- speculative_progress: Tracks latest speculative_id per step for recovery (legacy)
- speculative_start_ids: Starting IDs for speculative steps
- speculation_tracking: Tracks @speculate function state for the new pattern
- incidental_requests: Browser-initiated network requests (Playwright driver)
"""

from pathlib import Path

import aiosqlite

# Schema version for migrations
SCHEMA_VERSION = 11

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
    cache_key TEXT,                          -- Hash of (method, url, body, headers) for response caching

    -- ArchiveRequest-specific fields
    expected_type TEXT,                      -- For ArchiveRequest: expected file type

    -- Timestamps (human-readable)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- High-precision monotonic timestamps (nanoseconds from time.monotonic_ns())
    created_at_ns INTEGER,
    started_at_ns INTEGER,
    completed_at_ns INTEGER,

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
    "CREATE INDEX IF NOT EXISTS idx_requests_cache_key ON requests(cache_key)",
    "CREATE INDEX IF NOT EXISTS idx_requests_parent ON requests(parent_request_id)",
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
    warc_record_id TEXT,                     -- UUID for WARC record linking

    -- Speculative request outcome tracking
    speculation_outcome TEXT                 -- NULL=not speculative, 'success', 'stopped', 'skipped'
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
    max_backoff_time REAL NOT NULL,          -- Max cumulative backoff before marking failed

    -- Speculation configuration
    speculation_config_json TEXT,            -- JSON: {continuation: {threshold: int, speculation: int}}

    -- Browser configuration (Playwright driver)
    browser_config_json TEXT                 -- JSON: {browser_type, headless, viewport, user_agent, etc.}
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

    -- Stack trace
    traceback TEXT,                          -- Full Python traceback

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

_CREATE_SPECULATIVE_PROGRESS = """
CREATE TABLE IF NOT EXISTS speculative_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_name TEXT NOT NULL UNIQUE,          -- Name of the speculative step method
    latest_speculative_id INTEGER NOT NULL,  -- Last speculative_id processed
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_SPECULATIVE_PROGRESS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_speculative_progress_step ON speculative_progress(step_name)",
]

_CREATE_SPECULATIVE_START_IDS = """
CREATE TABLE IF NOT EXISTS speculative_start_ids (
    step_name TEXT PRIMARY KEY,
    starting_id INTEGER NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_RATE_LIMITER_STATE = """
CREATE TABLE IF NOT EXISTS rate_limiter_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),   -- Single row for this driver
    tokens REAL NOT NULL DEFAULT 1.0,        -- Current token count
    rate REAL NOT NULL DEFAULT 0.1,          -- Tokens per second (current rate)
    bucket_size REAL NOT NULL DEFAULT 4.0,   -- Maximum tokens
    last_congestion_rate REAL NOT NULL DEFAULT 1.0,  -- Rate at last congestion event
    jitter REAL NOT NULL DEFAULT 2.0,        -- Uniform jitter ±seconds
    last_used_at REAL NOT NULL,              -- Unix timestamp of last token acquisition
    total_requests INTEGER NOT NULL DEFAULT 0,
    total_successes INTEGER NOT NULL DEFAULT 0,
    total_rate_limited INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# Table for tracking @speculate function state
_CREATE_SPECULATION_TRACKING = """
CREATE TABLE IF NOT EXISTS speculation_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    func_name TEXT NOT NULL UNIQUE,          -- Name of the @speculate decorated function
    highest_successful_id INTEGER NOT NULL DEFAULT 0,  -- Highest ID that returned 2xx
    consecutive_failures INTEGER NOT NULL DEFAULT 0,   -- Failures beyond highest_successful_id
    current_ceiling INTEGER NOT NULL DEFAULT 0,        -- Current upper bound of seeded IDs
    stopped BOOLEAN NOT NULL DEFAULT FALSE,  -- Whether speculation has stopped for this function
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_SPECULATION_TRACKING_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_speculation_tracking_func ON speculation_tracking(func_name)",
]

# Table for tracking incidental requests (Playwright driver)
_CREATE_INCIDENTAL_REQUESTS = """
CREATE TABLE IF NOT EXISTS incidental_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_request_id INTEGER NOT NULL REFERENCES requests(id),

    -- Request info
    resource_type TEXT NOT NULL,        -- document, stylesheet, image, script, font, xhr, fetch, etc.
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    headers_json TEXT,
    body BLOB,

    -- Response info (NULL if request failed/blocked)
    status_code INTEGER,
    response_headers_json TEXT,
    content_compressed BLOB,            -- Zstd-compressed response body
    content_size_original INTEGER,
    content_size_compressed INTEGER,
    compression_dict_id INTEGER REFERENCES compression_dicts(id),

    -- Timing
    started_at_ns INTEGER,
    completed_at_ns INTEGER,

    -- Metadata
    from_cache BOOLEAN,                 -- Whether browser served from cache
    failure_reason TEXT,                -- If request failed: 'timeout', 'aborted', etc.

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_INCIDENTAL_REQUESTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_incidental_requests_parent ON incidental_requests(parent_request_id)",
    "CREATE INDEX IF NOT EXISTS idx_incidental_requests_resource_type ON incidental_requests(resource_type)",
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
    await db.execute(_CREATE_SPECULATIVE_PROGRESS)
    await db.execute(_CREATE_SPECULATIVE_START_IDS)
    await db.execute(_CREATE_RATE_LIMITER_STATE)
    await db.execute(_CREATE_SPECULATION_TRACKING)
    await db.execute(_CREATE_INCIDENTAL_REQUESTS)

    # Run migrations BEFORE creating indexes
    # This ensures columns added by migrations exist when their indexes are created
    await _run_migrations(db)

    # Create all indexes (after migrations so new columns exist)
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
    for index_sql in _CREATE_SPECULATIVE_PROGRESS_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_SPECULATION_TRACKING_INDEXES:
        await db.execute(index_sql)
    for index_sql in _CREATE_INCIDENTAL_REQUESTS_INDEXES:
        await db.execute(index_sql)

    await db.commit()
    return db


async def _run_migrations(db: aiosqlite.Connection) -> None:
    """Run any pending database migrations.

    Args:
        db: An open aiosqlite connection.
    """
    current_version = await get_schema_version(db)

    # Migration 1 -> 2: Add traceback column to errors table
    if current_version < 2:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(errors)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "traceback" not in columns:
            await db.execute("ALTER TABLE errors ADD COLUMN traceback TEXT")

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (2,),
        )
        current_version = 2

    # Migration 2 -> 3: Add speculation_outcome column to responses table
    if current_version < 3:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(responses)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "speculation_outcome" not in columns:
            await db.execute(
                "ALTER TABLE responses ADD COLUMN speculation_outcome TEXT"
            )

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (3,),
        )
        current_version = 3

    # Migration 3 -> 4: Add speculation_config_json column to run_metadata table
    if current_version < 4:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(run_metadata)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "speculation_config_json" not in columns:
            await db.execute(
                "ALTER TABLE run_metadata ADD COLUMN speculation_config_json TEXT"
            )

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (4,),
        )
        current_version = 4

    # Migration 4 -> 5: Add speculative_start_ids table
    if current_version < 5:
        # Create the table if it doesn't exist
        await db.execute(_CREATE_SPECULATIVE_START_IDS)

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (5,),
        )
        current_version = 5

    # Migration 5 -> 6: Add nanosecond timing columns to requests table
    if current_version < 6:
        # Check if columns exist
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = [row[1] for row in await cursor.fetchall()]

        if "created_at_ns" not in columns:
            await db.execute(
                "ALTER TABLE requests ADD COLUMN created_at_ns INTEGER"
            )
        if "started_at_ns" not in columns:
            await db.execute(
                "ALTER TABLE requests ADD COLUMN started_at_ns INTEGER"
            )
        if "completed_at_ns" not in columns:
            await db.execute(
                "ALTER TABLE requests ADD COLUMN completed_at_ns INTEGER"
            )

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (6,),
        )
        current_version = 6

    # Migration 6 -> 7: Add rate_limiter_state table
    if current_version < 7:
        # Create the table if it doesn't exist
        await db.execute(_CREATE_RATE_LIMITER_STATE)

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (7,),
        )

    # Migration 7 -> 8: Add cache_key column to requests for response caching
    if current_version < 8:
        # Check if cache_key column already exists (new databases have it in schema)
        cursor = await db.execute("PRAGMA table_info(requests)")
        columns = await cursor.fetchall()
        column_names = {col[1] for col in columns}

        if "cache_key" not in column_names:
            # Add the cache_key column only if it doesn't exist
            await db.execute("ALTER TABLE requests ADD COLUMN cache_key TEXT")
            # Add index for cache lookups
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_cache_key ON requests(cache_key)"
            )

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (8,),
        )
        current_version = 8

    # Migration 8 -> 9: Add speculation_tracking table for @speculate pattern
    if current_version < 9:
        # Create the table if it doesn't exist
        await db.execute(_CREATE_SPECULATION_TRACKING)

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (9,),
        )
        current_version = 9

    # Migration 9 -> 10: Add browser_config_json column to run_metadata
    if current_version < 10:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(run_metadata)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "browser_config_json" not in columns:
            await db.execute(
                "ALTER TABLE run_metadata ADD COLUMN browser_config_json TEXT"
            )

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (10,),
        )
        current_version = 10

    # Migration 10 -> 11: Add incidental_requests table
    if current_version < 11:
        # Create the table if it doesn't exist
        await db.execute(_CREATE_INCIDENTAL_REQUESTS)
        # Create indexes
        for index_sql in _CREATE_INCIDENTAL_REQUESTS_INDEXES:
            await db.execute(index_sql)

        # Update schema version
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (11,),
        )

    # Record initial schema version if not present
    if current_version == 0:
        await db.execute(
            "INSERT INTO schema_info (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )


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
