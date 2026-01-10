"""Error tracking and storage for LocalDevDriver.

This module provides functionality for capturing, storing, and querying
errors that occur during scraping. It supports all exception types from
the scraper_driver.common.exceptions module with type-specific details.

Error Types:
- structural: HTMLStructuralAssumptionException (selector issues)
- validation: DataFormatAssumptionException (Pydantic validation failures)
- transient: TransientException subclasses (HTTP errors, timeouts)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from juriscraper.scraper_driver.common.exceptions import (
    DataFormatAssumptionException,
    HTMLResponseAssumptionException,
    HTMLStructuralAssumptionException,
    RequestTimeoutException,
    ScraperAssumptionException,
    TransientException,
)
from juriscraper.scraper_driver.driver.dev_driver.sql_queries import SQL

if TYPE_CHECKING:
    import aiosqlite


@dataclass
class ErrorRecord:
    """Error record from database for listing and display.

    Attributes:
        id: Database ID of the error.
        request_id: ID of the request that caused this error (if any).
        error_type: Classification (structural, validation, transient).
        error_class: Full exception class name.
        message: Human-readable error message.
        request_url: URL that triggered the error.
        context_json: JSON-encoded error context.
        selector: For structural errors - the selector that failed.
        selector_type: For structural errors - xpath or css.
        expected_min: For structural errors - minimum expected count.
        expected_max: For structural errors - maximum expected count.
        actual_count: For structural errors - actual count found.
        model_name: For validation errors - the Pydantic model name.
        validation_errors: For validation errors - list of error dicts.
        failed_doc: For validation errors - the document that failed.
        status_code: For transient errors - HTTP status code.
        timeout_seconds: For transient errors - timeout duration.
        is_resolved: Whether this error has been resolved.
        resolved_at: When this error was resolved.
        resolution_notes: Notes about how the error was resolved.
        created_at: When the error was recorded.
    """

    id: int
    request_id: int | None
    error_type: str
    error_class: str
    message: str
    request_url: str
    context_json: str | None
    selector: str | None
    selector_type: str | None
    expected_min: int | None
    expected_max: int | None
    actual_count: int | None
    model_name: str | None
    validation_errors: list[dict[str, Any]] | None
    failed_doc: dict[str, Any] | None
    status_code: int | None
    timeout_seconds: float | None
    is_resolved: bool
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime

    def to_json(self) -> str:
        """Serialize to JSON for web transport."""
        return json.dumps(
            {
                "id": self.id,
                "request_id": self.request_id,
                "error_type": self.error_type,
                "error_class": self.error_class,
                "message": self.message,
                "request_url": self.request_url,
                "selector": self.selector,
                "selector_type": self.selector_type,
                "expected_min": self.expected_min,
                "expected_max": self.expected_max,
                "actual_count": self.actual_count,
                "model_name": self.model_name,
                "validation_errors": self.validation_errors,
                "status_code": self.status_code,
                "timeout_seconds": self.timeout_seconds,
                "is_resolved": self.is_resolved,
                "resolved_at": self.resolved_at.isoformat()
                if self.resolved_at
                else None,
                "resolution_notes": self.resolution_notes,
                "created_at": self.created_at.isoformat()
                if self.created_at
                else None,
            }
        )


def classify_error(exc: Exception) -> str:
    """Classify an exception into an error type.

    Args:
        exc: The exception to classify.

    Returns:
        Error type string: 'structural', 'validation', or 'transient'.
    """
    if isinstance(exc, HTMLStructuralAssumptionException):
        return "structural"
    elif isinstance(exc, DataFormatAssumptionException):
        return "validation"
    elif isinstance(exc, TransientException):
        return "transient"
    else:
        return "unknown"


async def store_error(
    db: aiosqlite.Connection,
    exc: Exception,
    request_id: int | None = None,
    request_url: str | None = None,
) -> int:
    """Store an error in the database.

    Extracts type-specific fields from the exception and stores them
    in the errors table.

    Args:
        db: Database connection.
        exc: The exception to store.
        request_id: ID of the request that caused this error (if known).
        request_url: URL that triggered the error (fallback if not in exception).

    Returns:
        The database ID of the stored error.
    """
    error_type = classify_error(exc)
    error_class = f"{type(exc).__module__}.{type(exc).__name__}"
    message = str(exc)

    # Extract URL from exception if available
    if request_url is None:
        if isinstance(exc, ScraperAssumptionException):
            request_url = exc.request_url
        elif isinstance(
            exc, HTMLResponseAssumptionException | RequestTimeoutException
        ):
            request_url = exc.url
        else:
            request_url = "unknown"

    # Extract context if available
    context_json = None
    if isinstance(exc, ScraperAssumptionException) and exc.context:
        context_json = json.dumps(exc.context)

    # Type-specific fields
    selector = None
    selector_type = None
    expected_min = None
    expected_max = None
    actual_count = None
    model_name = None
    validation_errors_json = None
    failed_doc_json = None
    status_code = None
    timeout_seconds = None

    if isinstance(exc, HTMLStructuralAssumptionException):
        selector = exc.selector
        selector_type = exc.selector_type
        expected_min = exc.expected_min
        expected_max = exc.expected_max
        actual_count = exc.actual_count

    elif isinstance(exc, DataFormatAssumptionException):
        model_name = exc.model_name
        validation_errors_json = json.dumps(exc.errors)
        failed_doc_json = json.dumps(exc.failed_doc)

    elif isinstance(exc, HTMLResponseAssumptionException):
        status_code = exc.status_code

    elif isinstance(exc, RequestTimeoutException):
        timeout_seconds = exc.timeout_seconds

    cursor = await db.execute(
        SQL.INSERT_ERROR,
        (
            request_id,
            error_type,
            error_class,
            message,
            request_url,
            context_json,
            selector,
            selector_type,
            expected_min,
            expected_max,
            actual_count,
            model_name,
            validation_errors_json,
            failed_doc_json,
            status_code,
            timeout_seconds,
        ),
    )
    await db.commit()

    error_id = cursor.lastrowid
    return error_id if error_id else 0


def _row_to_error_record(row: tuple[Any, ...]) -> ErrorRecord:
    """Convert a database row to an ErrorRecord.

    Args:
        row: Database row tuple.

    Returns:
        ErrorRecord instance.
    """
    (
        id_,
        request_id,
        error_type,
        error_class,
        message,
        request_url,
        context_json,
        selector,
        selector_type,
        expected_min,
        expected_max,
        actual_count,
        model_name,
        validation_errors_json,
        failed_doc_json,
        status_code,
        timeout_seconds,
        is_resolved,
        resolved_at,
        resolution_notes,
        created_at,
    ) = row

    # Parse JSON fields
    validation_errors = (
        json.loads(validation_errors_json) if validation_errors_json else None
    )
    failed_doc = json.loads(failed_doc_json) if failed_doc_json else None

    # Parse timestamps
    resolved_at_dt = None
    if resolved_at:
        resolved_at_dt = (
            datetime.fromisoformat(resolved_at)
            if isinstance(resolved_at, str)
            else resolved_at
        )

    created_at_dt = (
        datetime.fromisoformat(created_at)
        if isinstance(created_at, str)
        else created_at
    )

    return ErrorRecord(
        id=id_,
        request_id=request_id,
        error_type=error_type,
        error_class=error_class,
        message=message,
        request_url=request_url,
        context_json=context_json,
        selector=selector,
        selector_type=selector_type,
        expected_min=expected_min,
        expected_max=expected_max,
        actual_count=actual_count,
        model_name=model_name,
        validation_errors=validation_errors,
        failed_doc=failed_doc,
        status_code=status_code,
        timeout_seconds=timeout_seconds,
        is_resolved=bool(is_resolved),
        resolved_at=resolved_at_dt,
        resolution_notes=resolution_notes,
        created_at=created_at_dt,
    )


async def get_error(
    db: aiosqlite.Connection, error_id: int
) -> ErrorRecord | None:
    """Get a single error by ID.

    Args:
        db: Database connection.
        error_id: The error ID to retrieve.

    Returns:
        ErrorRecord if found, None otherwise.
    """
    cursor = await db.execute(SQL.SELECT_ERROR_FULL, (error_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_error_record(row)


async def list_errors(
    db: aiosqlite.Connection,
    error_type: str | None = None,
    continuation: str | None = None,
    unresolved_only: bool = True,
    offset: int = 0,
    limit: int = 50,
) -> list[ErrorRecord]:
    """List errors with optional filters.

    Args:
        db: Database connection.
        error_type: Filter by error type (structural, validation, transient).
        continuation: Filter by continuation method name (requires join with requests).
        unresolved_only: If True, only return unresolved errors.
        offset: Number of records to skip.
        limit: Maximum records to return.

    Returns:
        List of ErrorRecord objects.
    """
    conditions = []
    params: list[Any] = []

    if error_type:
        conditions.append("e.error_type = ?")
        params.append(error_type)

    if unresolved_only:
        conditions.append("e.is_resolved = 0")

    if continuation:
        conditions.append("r.continuation = ?")
        params.append(continuation)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Join with requests if filtering by continuation
    if continuation:
        query = SQL.SELECT_ERRORS_LIST_WITH_JOIN.format(
            where_clause=where_clause
        )
    else:
        query = SQL.SELECT_ERRORS_LIST.format(where_clause=where_clause)

    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    return [_row_to_error_record(row) for row in rows]


async def count_errors(
    db: aiosqlite.Connection,
    error_type: str | None = None,
    unresolved_only: bool = True,
) -> int:
    """Count errors with optional filters.

    Args:
        db: Database connection.
        error_type: Filter by error type.
        unresolved_only: If True, only count unresolved errors.

    Returns:
        Count of matching errors.
    """
    conditions = []
    params: list[Any] = []

    if error_type:
        conditions.append("error_type = ?")
        params.append(error_type)

    if unresolved_only:
        conditions.append("is_resolved = 0")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM errors {where_clause}",
        params,
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


async def resolve_error(
    db: aiosqlite.Connection,
    error_id: int,
    notes: str | None = None,
) -> bool:
    """Mark an error as resolved.

    Args:
        db: Database connection.
        error_id: The error ID to resolve.
        notes: Optional notes about how the error was resolved.

    Returns:
        True if error was found and updated, False if not found.
    """
    cursor = await db.execute(SQL.UPDATE_RESOLVE_ERROR, (notes, error_id))
    await db.commit()
    return cursor.rowcount > 0
