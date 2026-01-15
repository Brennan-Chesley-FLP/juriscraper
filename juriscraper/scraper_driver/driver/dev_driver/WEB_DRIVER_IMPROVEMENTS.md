# Web Driver Debugging Improvements

This document specifies improvements to the LocalDevDriver web interface for accelerated debugging of scraper issues. These features address the pain points documented in `DEBUG_WANTS.md`.

## Overview

Three main feature areas:

1. **XPath/CSS Observer** - Instrument selector queries to capture what was queried, match counts, and element samples
2. **Diagnose Endpoint** - Re-run a continuation against a stored response with observation enabled
3. **Web UI Enhancements** - Improved request queue view, compression stats, and XSD validation

---

## 1. XPath/CSS Debugging Improvements

### 1.1 XPathObserver Context Manager

Add a context manager that instruments `CheckedHtmlElement` to collect XPath/CSS query data.

**Location**: `juriscraper/scraper_driver/common/xpath_observer.py`

```python
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lxml.html import HtmlElement

# Context variable for the active observer
_active_observer: contextvars.ContextVar[XPathObserver | None] = contextvars.ContextVar(
    "xpath_observer", default=None
)


@dataclass
class SelectorQuery:
    """A single XPath or CSS selector query."""

    selector: str
    selector_type: str  # "xpath" or "css"
    description: str
    match_count: int
    expected_min: int
    expected_max: int | None
    sample_elements: list[str] = field(default_factory=list)
    children: list[SelectorQuery] = field(default_factory=list)
    element_id: str | None = None  # Unique ID for highlighting in UI

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "selector": self.selector,
            "selector_type": self.selector_type,
            "description": self.description,
            "match_count": self.match_count,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "sample_elements": self.sample_elements,
            "children": [c.to_dict() for c in self.children],
            "element_id": self.element_id,
        }


class XPathObserver:
    """Observer that collects XPath/CSS query information.

    Usage:
        with XPathObserver() as observer:
            tree = CheckedHtmlElement(lxml_html.fromstring(content), url)
            rows = tree.checked_xpath("//tr", "table rows", min_count=1)
            for row in rows:
                cells = row.checked_xpath(".//td", "cells")

            print(observer.simple_tree())  # Human-readable tree
            print(observer.json())  # JSON for UI highlighting
    """

    def __init__(self, max_sample_length: int = 100, max_samples: int = 3):
        """Initialize the observer.

        Args:
            max_sample_length: Maximum characters per sample element.
            max_samples: Maximum number of sample elements to capture.
        """
        self.max_sample_length = max_sample_length
        self.max_samples = max_samples
        self.queries: list[SelectorQuery] = []
        self._query_stack: list[SelectorQuery] = []
        self._element_counter: int = 0
        self._token: contextvars.Token | None = None

    def __enter__(self) -> XPathObserver:
        """Enter the observer context."""
        self._token = _active_observer.set(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the observer context."""
        if self._token is not None:
            _active_observer.reset(self._token)
            self._token = None

    def record_query(
        self,
        selector: str,
        selector_type: str,
        description: str,
        results: list[Any],
        expected_min: int,
        expected_max: int | None,
        parent_element: HtmlElement | None = None,
    ) -> None:
        """Record a selector query and its results.

        Args:
            selector: The XPath or CSS selector string.
            selector_type: "xpath" or "css".
            description: Human-readable description from checked_xpath/css.
            results: The elements/values returned by the query.
            expected_min: Minimum expected count.
            expected_max: Maximum expected count (None = unlimited).
            parent_element: The element the query was executed on.
        """
        # Generate sample content from results
        samples = []
        for i, result in enumerate(results[:self.max_samples]):
            if hasattr(result, "text_content"):
                # HtmlElement - get text content
                text = result.text_content()
            elif hasattr(result, "_element") and hasattr(result._element, "text_content"):
                # CheckedHtmlElement wrapper
                text = result._element.text_content()
            elif isinstance(result, str):
                text = result
            else:
                text = str(result)

            # Normalize whitespace and truncate
            text = " ".join(text.split())
            if len(text) > self.max_sample_length:
                text = text[:self.max_sample_length] + "..."
            samples.append(text)

        # Generate unique element ID for highlighting
        self._element_counter += 1
        element_id = f"xpath_match_{self._element_counter}"

        query = SelectorQuery(
            selector=selector,
            selector_type=selector_type,
            description=description,
            match_count=len(results),
            expected_min=expected_min,
            expected_max=expected_max,
            sample_elements=samples,
            element_id=element_id,
        )

        # Add to current context (nested or top-level)
        if self._query_stack:
            self._query_stack[-1].children.append(query)
        else:
            self.queries.append(query)

    def push_context(self, query: SelectorQuery) -> None:
        """Push a query onto the stack for nested queries."""
        self._query_stack.append(query)

    def pop_context(self) -> SelectorQuery | None:
        """Pop a query from the stack."""
        if self._query_stack:
            return self._query_stack.pop()
        return None

    def simple_tree(self, indent: int = 0) -> str:
        """Generate a human-readable tree representation.

        Returns:
            Formatted string showing query hierarchy with match counts.

        Example output:
            - //div[@id='mainContent']/table "Main Table" ✓ (1 match)
              - //tr "Main Table Rows" ✓ (5 matches)
                - (//td)[2] "Important Column" ✗ (0 matches, expected 1+)
        """
        lines = []
        for query in self.queries:
            lines.extend(self._format_query(query, indent))
        return "\n".join(lines)

    def _format_query(self, query: SelectorQuery, indent: int) -> list[str]:
        """Format a single query and its children."""
        prefix = "  " * indent + "- "

        # Status indicator
        if query.match_count >= query.expected_min:
            if query.expected_max is None or query.match_count <= query.expected_max:
                status = "✓"
            else:
                status = "✗"
        else:
            status = "✗"

        # Match count display
        match_text = f"{query.match_count} match" + ("es" if query.match_count != 1 else "")
        if status == "✗":
            if query.match_count < query.expected_min:
                match_text += f", expected {query.expected_min}+"
            elif query.expected_max and query.match_count > query.expected_max:
                match_text += f", expected max {query.expected_max}"

        line = f'{prefix}{query.selector} "{query.description}" {status} ({match_text})'
        lines = [line]

        # Add sample content preview if available
        if query.sample_elements and query.match_count > 0:
            sample_preview = query.sample_elements[0]
            if sample_preview:
                sample_line = "  " * (indent + 1) + f'→ "{sample_preview}"'
                lines.append(sample_line)

        # Recurse for children
        for child in query.children:
            lines.extend(self._format_query(child, indent + 1))

        return lines

    def json(self) -> list[dict[str, Any]]:
        """Generate JSON representation for UI highlighting.

        Returns:
            List of query dictionaries suitable for JavaScript processing.
        """
        return [q.to_dict() for q in self.queries]


def get_active_observer() -> XPathObserver | None:
    """Get the currently active XPathObserver, if any."""
    return _active_observer.get()
```

### 1.2 CheckedHtmlElement Integration

Modify `CheckedHtmlElement` to report queries to the active observer.

**Changes to**: `juriscraper/scraper_driver/common/checked_html.py`

```python
# Add import at top
from juriscraper.scraper_driver.common.xpath_observer import get_active_observer

# Modify checked_xpath method (add observer reporting before return)
def checked_xpath(self, ...):
    results = self._element.xpath(xpath)

    # ... existing filtering and validation ...

    # Report to active observer if present
    observer = get_active_observer()
    if observer is not None:
        observer.record_query(
            selector=xpath,
            selector_type="xpath",
            description=description,
            results=results,  # raw results before wrapping
            expected_min=min_count,
            expected_max=max_count,
            parent_element=self._element,
        )

    # ... rest of existing logic ...

# Similarly modify checked_css
```

The key insight is that the observer uses a `contextvars.ContextVar` to be thread-safe and to automatically propagate through nested calls. When `checked_xpath` or `checked_css` is called on a result element, the observer captures the query in context.

---

## 2. Diagnose Endpoint

### 2.1 Driver Method

Add a `diagnose()` method to `LocalDevDriver` that re-runs a continuation with observation.

**Location**: Add to `juriscraper/scraper_driver/driver/dev_driver/dev_driver.py`

```python
@dataclass
class DiagnoseResult:
    """Result of running diagnose() on a response."""

    response_id: int
    continuation: str
    yields: list[dict[str, Any]]  # List of yielded items (type, key attributes)
    simple_tree: str  # Human-readable XPath observation tree
    observer_json: list[dict[str, Any]]  # JSON for UI highlighting
    error: str | None = None  # Error message if continuation raised

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "continuation": self.continuation,
            "yields": self.yields,
            "simple_tree": self.simple_tree,
            "observer_json": self.observer_json,
            "error": self.error,
        }


async def diagnose(
    self,
    response_id: int,
    speculation_cap: int = 3,
) -> DiagnoseResult:
    """Re-run a continuation against a stored response with XPath observation.

    This method retrieves a stored response, decompresses it, reconstructs
    the Response object, and re-runs the continuation method with an
    XPathObserver active to capture all XPath/CSS queries.

    Args:
        response_id: The database ID of the response to diagnose.
        speculation_cap: Maximum number of SpeculativeRequests to follow
            (prevents infinite loops). Default 3.

    Returns:
        DiagnoseResult with yields, observation tree, and any errors.

    Raises:
        ValueError: If response_id not found.
    """
    assert self._db is not None

    from juriscraper.scraper_driver.common.xpath_observer import XPathObserver
    from juriscraper.scraper_driver.data_types import (
        ArchiveRequest,
        NavigatingRequest,
        NonNavigatingRequest,
        ParsedData,
        SpeculativeRequest,
    )

    # Get response and request data
    cursor = await self._db.execute(
        """
        SELECT
            r.content_compressed,
            r.compression_dict_id,
            r.status_code,
            r.url,
            r.headers_json,
            r.continuation,
            req.method,
            req.url as request_url,
            req.accumulated_data_json,
            req.aux_data_json,
            req.permanent_json
        FROM responses r
        JOIN requests req ON r.request_id = req.id
        WHERE r.id = ?
        """,
        (response_id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise ValueError(f"Response {response_id} not found")

    (
        compressed,
        dict_id,
        status_code,
        url,
        headers_json,
        continuation_name,
        method,
        request_url,
        accumulated_data_json,
        aux_data_json,
        permanent_json,
    ) = row

    # Decompress content
    content = await self.get_response_content(response_id)
    if content is None:
        content = b""

    # Reconstruct Response object
    import json
    from juriscraper.scraper_driver.data_types import (
        HTTPRequestParams,
        HttpMethod,
        Response,
        ResolvedRequest,
    )

    headers = json.loads(headers_json) if headers_json else {}
    accumulated_data = json.loads(accumulated_data_json) if accumulated_data_json else {}
    aux_data = json.loads(aux_data_json) if aux_data_json else {}
    permanent = json.loads(permanent_json) if permanent_json else {}

    http_params = HTTPRequestParams(
        method=HttpMethod(method),
        url=request_url,
    )
    resolved_request = ResolvedRequest(
        request=http_params,
        accumulated_data=accumulated_data,
        aux_data=aux_data,
        permanent=permanent,
    )

    response = Response(
        status_code=status_code,
        url=url,
        content=content,
        headers=headers,
        request=resolved_request,
    )

    # Run continuation with observer
    yields: list[dict[str, Any]] = []
    error: str | None = None

    with XPathObserver() as observer:
        try:
            continuation_method = self.scraper.get_continuation(continuation_name)
            gen = continuation_method(response)

            speculation_count = 0
            for item in gen:
                yield_info = self._describe_yield(item)
                yields.append(yield_info)

                # Track speculation count
                if isinstance(item, SpeculativeRequest):
                    speculation_count += 1
                    if speculation_count >= speculation_cap:
                        yields.append({
                            "type": "_speculation_cap_reached",
                            "message": f"Stopped after {speculation_cap} SpeculativeRequests",
                        })
                        break

        except Exception as e:
            import traceback
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    return DiagnoseResult(
        response_id=response_id,
        continuation=continuation_name,
        yields=yields,
        simple_tree=observer.simple_tree(),
        observer_json=observer.json(),
        error=error,
    )


def _describe_yield(self, item: Any) -> dict[str, Any]:
    """Create a description of a yielded item."""
    from juriscraper.scraper_driver.data_types import (
        ArchiveRequest,
        NavigatingRequest,
        NonNavigatingRequest,
        ParsedData,
        SpeculativeRequest,
    )

    if isinstance(item, ParsedData):
        data = item.unwrap()
        return {
            "type": "ParsedData",
            "data_type": type(data).__name__,
            "preview": str(data)[:200] + "..." if len(str(data)) > 200 else str(data),
        }
    elif isinstance(item, NavigatingRequest):
        return {
            "type": "NavigatingRequest",
            "url": item.request.url,
            "method": item.request.method.value,
            "continuation": item.continuation if isinstance(item.continuation, str) else item.continuation.__name__,
        }
    elif isinstance(item, SpeculativeRequest):
        return {
            "type": "SpeculativeRequest",
            "url": item.request.url,
            "method": item.request.method.value,
            "continuation": item.continuation if isinstance(item.continuation, str) else item.continuation.__name__,
        }
    elif isinstance(item, NonNavigatingRequest):
        return {
            "type": "NonNavigatingRequest",
            "url": item.request.url,
        }
    elif isinstance(item, ArchiveRequest):
        return {
            "type": "ArchiveRequest",
            "url": item.request.url,
            "expected_type": item.expected_type,
        }
    elif item is None:
        return {"type": "None"}
    else:
        return {
            "type": type(item).__name__,
            "repr": repr(item)[:200],
        }
```

### 2.2 REST Endpoint

**Location**: Add to `juriscraper/scraper_driver/driver/dev_driver/web/routes/` (new file `debug.py`)

```python
"""REST API endpoints for debugging tools.

This module provides endpoints for:
- Diagnosing responses (re-running continuations with observation)
- XSD validation of responses
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from juriscraper.scraper_driver.driver.dev_driver.web.app import (
    RunManager,
    get_run_manager,
)

router = APIRouter(prefix="/api/runs/{run_id}/debug", tags=["debug"])


class DiagnoseResponse(BaseModel):
    """Response model for diagnose endpoint."""

    response_id: int
    continuation: str
    yields: list[dict]
    simple_tree: str
    observer_json: list[dict]
    error: str | None = None


class XsdValidationResult(BaseModel):
    """Response model for XSD validation."""

    continuation: str
    total_responses: int
    failed_count: int
    failed_response_ids: list[int]
    errors: list[dict]  # [{response_id, error_message}, ...]


class CustomValidationRequest(BaseModel):
    """Request model for custom XSD or XPath validation."""

    xsd_content: str | None = Field(
        None, description="Custom XSD content to validate against"
    )
    xpath: str | None = Field(
        None, description="XPath to check element counts"
    )
    xpath_min: int | None = Field(
        None, ge=0, description="Minimum expected element count for XPath"
    )
    xpath_max: int | None = Field(
        None, ge=0, description="Maximum expected element count for XPath"
    )


async def _get_driver_for_run(run_id: str, manager: RunManager):
    """Get driver instance for a loaded run."""
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
    return run_info.driver


@router.get("/diagnose/{response_id}", response_model=DiagnoseResponse)
async def diagnose_response(
    run_id: str,
    response_id: int,
    speculation_cap: int = Query(default=3, ge=0, le=10),
    manager: Annotated[RunManager, Depends(get_run_manager)] = None,
) -> DiagnoseResponse:
    """Re-run a continuation against a stored response with XPath observation.

    This endpoint retrieves a stored response and re-runs its continuation
    method with an XPathObserver active. Returns information about what
    XPath/CSS queries were made, their match counts, and what was yielded.

    Useful for debugging "zero results" issues where the HTML structure
    may have changed or XPath queries are incorrect.

    Args:
        run_id: The run identifier.
        response_id: The database ID of the response to diagnose.
        speculation_cap: Maximum SpeculativeRequests to follow (default 3).

    Returns:
        Diagnosis results including yields and XPath observation data.
    """
    driver = await _get_driver_for_run(run_id, manager)

    try:
        result = await driver.diagnose(response_id, speculation_cap)
        return DiagnoseResponse(**result.to_dict())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Diagnosis failed: {e}",
        ) from e


@router.get("/xsd-validation/{continuation}", response_model=XsdValidationResult)
async def validate_xsd(
    run_id: str,
    continuation: str,
    manager: Annotated[RunManager, Depends(get_run_manager)] = None,
) -> XsdValidationResult:
    """Validate all responses for a continuation against its XSD schema.

    Finds the XSD file attached to the step function (via @step(xsd="..."))
    and validates each stored response against it.

    Args:
        run_id: The run identifier.
        continuation: The continuation method name.

    Returns:
        Validation results with list of failing response IDs.
    """
    driver = await _get_driver_for_run(run_id, manager)

    # Get XSD path from step metadata
    from juriscraper.scraper_driver.common.decorators import get_step_metadata

    try:
        method = driver.scraper.get_continuation(continuation)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Continuation '{continuation}' not found",
        )

    metadata = get_step_metadata(method)
    if metadata is None or metadata.xsd is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Continuation '{continuation}' has no XSD schema attached",
        )

    # Resolve XSD path relative to scraper module
    import inspect
    from pathlib import Path

    scraper_module = inspect.getmodule(type(driver.scraper))
    if scraper_module is None or scraper_module.__file__ is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not determine scraper module location",
        )

    scraper_dir = Path(scraper_module.__file__).parent
    xsd_path = scraper_dir / metadata.xsd

    if not xsd_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"XSD file not found: {xsd_path}",
        )

    # Load XSD
    from lxml import etree

    with open(xsd_path, "rb") as f:
        xsd_doc = etree.parse(f)
    xsd_schema = etree.XMLSchema(xsd_doc)

    # Validate all responses for this continuation
    return await _validate_responses_against_xsd(
        driver, continuation, xsd_schema
    )


@router.post("/xsd-validation/{continuation}", response_model=XsdValidationResult)
async def validate_xsd_custom(
    run_id: str,
    continuation: str,
    request: CustomValidationRequest,
    manager: Annotated[RunManager, Depends(get_run_manager)] = None,
) -> XsdValidationResult:
    """Validate responses with custom XSD or XPath criteria.

    Allows running validation with:
    - A custom XSD schema (provided in request body)
    - An XPath check with min/max element counts

    Args:
        run_id: The run identifier.
        continuation: The continuation method name.
        request: Custom validation parameters.

    Returns:
        Validation results with list of failing response IDs.
    """
    driver = await _get_driver_for_run(run_id, manager)

    if request.xsd_content:
        # Validate with custom XSD
        from lxml import etree
        from io import BytesIO

        try:
            xsd_doc = etree.parse(BytesIO(request.xsd_content.encode()))
            xsd_schema = etree.XMLSchema(xsd_doc)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid XSD: {e}",
            )

        return await _validate_responses_against_xsd(
            driver, continuation, xsd_schema
        )

    elif request.xpath:
        # Validate with XPath count check
        return await _validate_responses_xpath_count(
            driver,
            continuation,
            request.xpath,
            request.xpath_min or 0,
            request.xpath_max,
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either xsd_content or xpath",
        )


async def _validate_responses_against_xsd(
    driver, continuation: str, xsd_schema
) -> XsdValidationResult:
    """Validate all responses for a continuation against an XSD schema."""
    from lxml import etree, html as lxml_html

    db = driver._db
    cursor = await db.execute(
        """
        SELECT r.id, r.content_compressed, r.compression_dict_id
        FROM responses r
        WHERE r.continuation = ?
        """,
        (continuation,),
    )
    rows = await cursor.fetchall()

    failed_ids = []
    errors = []

    for response_id, compressed, dict_id in rows:
        try:
            content = await driver.get_response_content(response_id)
            if not content:
                continue

            # Parse as HTML, convert to proper XML for validation
            doc = lxml_html.fromstring(content)
            # XSD expects XML - convert
            xml_str = etree.tostring(doc, encoding="unicode", method="xml")
            xml_doc = etree.fromstring(xml_str.encode())

            if not xsd_schema.validate(xml_doc):
                failed_ids.append(response_id)
                errors.append({
                    "response_id": response_id,
                    "error_message": str(xsd_schema.error_log),
                })

        except Exception as e:
            failed_ids.append(response_id)
            errors.append({
                "response_id": response_id,
                "error_message": f"Parse error: {e}",
            })

    return XsdValidationResult(
        continuation=continuation,
        total_responses=len(rows),
        failed_count=len(failed_ids),
        failed_response_ids=failed_ids,
        errors=errors,
    )


async def _validate_responses_xpath_count(
    driver,
    continuation: str,
    xpath: str,
    min_count: int,
    max_count: int | None,
) -> XsdValidationResult:
    """Validate responses by checking XPath element counts."""
    from lxml import html as lxml_html

    db = driver._db
    cursor = await db.execute(
        """
        SELECT r.id, r.content_compressed, r.compression_dict_id
        FROM responses r
        WHERE r.continuation = ?
        """,
        (continuation,),
    )
    rows = await cursor.fetchall()

    failed_ids = []
    errors = []

    for response_id, compressed, dict_id in rows:
        try:
            content = await driver.get_response_content(response_id)
            if not content:
                continue

            doc = lxml_html.fromstring(content)
            results = doc.xpath(xpath)
            count = len(results)

            if count < min_count:
                failed_ids.append(response_id)
                errors.append({
                    "response_id": response_id,
                    "error_message": f"XPath '{xpath}' returned {count} elements, expected at least {min_count}",
                })
            elif max_count is not None and count > max_count:
                failed_ids.append(response_id)
                errors.append({
                    "response_id": response_id,
                    "error_message": f"XPath '{xpath}' returned {count} elements, expected at most {max_count}",
                })

        except Exception as e:
            failed_ids.append(response_id)
            errors.append({
                "response_id": response_id,
                "error_message": f"XPath error: {e}",
            })

    return XsdValidationResult(
        continuation=continuation,
        total_responses=len(rows),
        failed_count=len(failed_ids),
        failed_response_ids=failed_ids,
        errors=errors,
    )
```

---

## 3. Web UI Enhancements

### 3.1 Request Queue Summary View

Replace the current flat request list with a summary table:

| Continuation | Pending | In Progress | Completed | Failed | Held |
|--------------|---------|-------------|-----------|--------|------|
| `parse_court_year_page` | 5 | 1 | 123 | 2 | 0 |
| `parse_audio_player_page` | 0 | 0 | 45 | 0 | 0 |

Each cell links to a modal showing the detailed request list for that status/continuation combination.

**API Endpoint**: `GET /api/runs/{run_id}/requests/summary`

```python
@router.get("/summary")
async def get_request_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> list[dict]:
    """Get request summary grouped by continuation and status.

    Returns a pivot table of request counts by continuation and status.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute("""
        SELECT
            continuation,
            status,
            COUNT(*) as count
        FROM requests
        GROUP BY continuation, status
        ORDER BY continuation, status
    """)
    rows = await cursor.fetchall()

    # Pivot the data
    summary = {}
    for continuation, status, count in rows:
        if continuation not in summary:
            summary[continuation] = {
                "continuation": continuation,
                "pending": 0,
                "in_progress": 0,
                "completed": 0,
                "failed": 0,
                "held": 0,
                "cancelled": 0,
            }
        summary[continuation][status] = count

    return list(summary.values())
```

### 3.2 Compression Stats per Continuation

Enhance the compression statistics section to show:

1. **Per-continuation breakdown**:
   - Continuation name
   - Response count
   - Total original size
   - Total compressed size
   - Compression ratio
   - Dictionary version used

2. **Action buttons**:
   - "Train Dict" - calls `POST /api/runs/{run_id}/compression/train-dict`
   - "Recompress" - calls `POST /api/runs/{run_id}/compression/recompress`

**API Endpoint**: `GET /api/runs/{run_id}/compression/stats-by-continuation`

```python
@router.get("/stats-by-continuation")
async def get_compression_stats_by_continuation(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> list[dict]:
    """Get compression statistics broken down by continuation and dictionary version.

    Returns:
        List of stats per continuation, including dictionary version info.
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute("""
        SELECT
            r.continuation,
            r.compression_dict_id,
            d.version as dict_version,
            COUNT(*) as response_count,
            SUM(r.content_size_original) as total_original,
            SUM(r.content_size_compressed) as total_compressed
        FROM responses r
        LEFT JOIN compression_dicts d ON r.compression_dict_id = d.id
        GROUP BY r.continuation, r.compression_dict_id
        ORDER BY r.continuation, d.version
    """)
    rows = await cursor.fetchall()

    return [
        {
            "continuation": row[0],
            "dict_id": row[1],
            "dict_version": row[2],
            "response_count": row[3],
            "total_original_bytes": row[4] or 0,
            "total_compressed_bytes": row[5] or 0,
            "compression_ratio": round((row[4] or 0) / (row[5] or 1), 2),
        }
        for row in rows
    ]
```

### 3.3 Data/Results Statistics and Export

Add a "Data" block under Statistics showing scraped results by type and validity.

#### 3.3.1 Results Summary Endpoint

**API Endpoint**: `GET /api/runs/{run_id}/results/summary`

```python
class ResultTypeSummary(BaseModel):
    """Summary of results for a single data type."""
    result_type: str
    valid_count: int
    invalid_count: int
    total_count: int


class ResultsSummaryResponse(BaseModel):
    """Response model for results summary."""
    total_valid: int
    total_invalid: int
    total: int
    by_type: list[ResultTypeSummary]


@router.get("/summary", response_model=ResultsSummaryResponse)
async def get_results_summary(
    run_id: str,
    manager: Annotated[RunManager, Depends(get_run_manager)],
) -> ResultsSummaryResponse:
    """Get summary of results grouped by type and validity.

    Returns counts of valid and invalid results broken down by result_type
    (Pydantic model class name like ConnOpinionCluster, ConnOralArgument, etc.)
    """
    db = await _get_db_for_run(run_id, manager)

    cursor = await db.execute("""
        SELECT
            result_type,
            SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) as valid_count,
            SUM(CASE WHEN is_valid = 0 THEN 1 ELSE 0 END) as invalid_count,
            COUNT(*) as total_count
        FROM results
        GROUP BY result_type
        ORDER BY result_type
    """)
    rows = await cursor.fetchall()

    by_type = [
        ResultTypeSummary(
            result_type=row[0],
            valid_count=row[1],
            invalid_count=row[2],
            total_count=row[3],
        )
        for row in rows
    ]

    total_valid = sum(r.valid_count for r in by_type)
    total_invalid = sum(r.invalid_count for r in by_type)

    return ResultsSummaryResponse(
        total_valid=total_valid,
        total_invalid=total_invalid,
        total=total_valid + total_invalid,
        by_type=by_type,
    )
```

#### 3.3.2 Paginated Results List Endpoint

**API Endpoint**: `GET /api/runs/{run_id}/results`

Enhance the existing results endpoint to include request_id and validation errors:

```python
class ResultDetailItem(BaseModel):
    """Detailed result item for listing."""
    id: int
    request_id: int | None
    result_type: str
    data: dict  # The actual scraped data
    is_valid: bool
    validation_errors: list[dict] | None
    created_at: str | None


class ResultsListResponse(BaseModel):
    """Paginated response for results listing."""
    items: list[ResultDetailItem]
    total: int
    offset: int
    limit: int
    has_more: bool


@router.get("/", response_model=ResultsListResponse)
async def list_results(
    run_id: str,
    result_type: str | None = Query(None, description="Filter by result type"),
    is_valid: bool | None = Query(None, description="Filter by validity"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    manager: Annotated[RunManager, Depends(get_run_manager)] = None,
) -> ResultsListResponse:
    """List results with optional filters and pagination.

    Args:
        run_id: The run identifier.
        result_type: Filter by result type (e.g., "ConnOpinionCluster").
        is_valid: Filter by validity (True/False).
        offset: Pagination offset.
        limit: Maximum results per page (max 500).

    Returns:
        Paginated list of results with full data and validation errors.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query with optional filters
    conditions = []
    params: list[Any] = []

    if result_type:
        conditions.append("result_type = ?")
        params.append(result_type)
    if is_valid is not None:
        conditions.append("is_valid = ?")
        params.append(is_valid)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Get total count
    count_query = f"SELECT COUNT(*) FROM results {where_clause}"
    cursor = await db.execute(count_query, params)
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Get page of results
    data_query = f"""
        SELECT
            id,
            request_id,
            result_type,
            data_json,
            is_valid,
            validation_errors_json,
            created_at
        FROM results
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    cursor = await db.execute(data_query, params + [limit, offset])
    rows = await cursor.fetchall()

    import json
    items = [
        ResultDetailItem(
            id=row[0],
            request_id=row[1],
            result_type=row[2],
            data=json.loads(row[3]) if row[3] else {},
            is_valid=bool(row[4]),
            validation_errors=json.loads(row[5]) if row[5] else None,
            created_at=row[6],
        )
        for row in rows
    ]

    return ResultsListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )
```

#### 3.3.3 JSONL Export Endpoint

**API Endpoint**: `GET /api/runs/{run_id}/results/export.jsonl`

```python
from fastapi.responses import StreamingResponse
import json


@router.get("/export.jsonl")
async def export_results_jsonl(
    run_id: str,
    result_type: str | None = Query(None, description="Filter by result type"),
    is_valid: bool | None = Query(None, description="Filter by validity"),
    manager: Annotated[RunManager, Depends(get_run_manager)] = None,
) -> StreamingResponse:
    """Export all results as JSONL (newline-delimited JSON).

    Each line is a JSON object containing:
    - id: Result database ID
    - request_id: Associated request ID
    - result_type: The Pydantic model class name
    - data: The actual scraped data
    - is_valid: Whether validation passed
    - validation_errors: List of validation errors (if any)
    - created_at: Timestamp

    Args:
        run_id: The run identifier.
        result_type: Optional filter by result type.
        is_valid: Optional filter by validity.

    Returns:
        Streaming JSONL response with Content-Disposition for download.
    """
    db = await _get_db_for_run(run_id, manager)

    # Build query with optional filters
    conditions = []
    params: list[Any] = []

    if result_type:
        conditions.append("result_type = ?")
        params.append(result_type)
    if is_valid is not None:
        conditions.append("is_valid = ?")
        params.append(is_valid)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            id,
            request_id,
            result_type,
            data_json,
            is_valid,
            validation_errors_json,
            created_at
        FROM results
        {where_clause}
        ORDER BY created_at
    """

    async def generate_jsonl():
        cursor = await db.execute(query, params)
        async for row in cursor:
            record = {
                "id": row[0],
                "request_id": row[1],
                "result_type": row[2],
                "data": json.loads(row[3]) if row[3] else {},
                "is_valid": bool(row[4]),
                "validation_errors": json.loads(row[5]) if row[5] else None,
                "created_at": row[6],
            }
            yield json.dumps(record) + "\n"

    # Generate filename
    filename_parts = [run_id, "results"]
    if result_type:
        filename_parts.append(result_type)
    if is_valid is not None:
        filename_parts.append("valid" if is_valid else "invalid")
    filename = "_".join(filename_parts) + ".jsonl"

    return StreamingResponse(
        generate_jsonl(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
```

#### 3.3.4 UI Updates for Data Section

Add to `run_detail.html` Statistics section:

```html
<!-- In stats-grid, add new stat-card -->
<div class="stat-card">
    <h3>Data</h3>
    <div id="data-stats">Loading...</div>
</div>
```

```javascript
// Add to JavaScript section
async function loadDataStats() {
    try {
        const response = await fetch(`/api/runs/${runId}/results/summary`);
        if (!response.ok) {
            document.getElementById('data-stats').innerHTML = '<p class="error">Failed to load</p>';
            return;
        }
        const stats = await response.json();

        let html = `
            <p>Total: ${stats.total}</p>
            <p class="valid">Valid: ${stats.total_valid}</p>
            <p class="invalid">Invalid: ${stats.total_invalid}</p>
        `;

        // Add breakdown by type
        if (stats.by_type.length > 0) {
            html += '<div class="type-breakdown">';
            for (const t of stats.by_type) {
                const validClass = t.invalid_count > 0 ? 'has-invalid' : '';
                html += `
                    <div class="type-row ${validClass}" onclick="showResultsForType('${t.result_type}')">
                        <span class="type-name">${t.result_type}</span>
                        <span class="counts">${t.valid_count}/${t.total_count}</span>
                    </div>
                `;
            }
            html += '</div>';
        }

        // Add export button
        html += `
            <div class="export-actions">
                <button class="btn btn-sm btn-secondary" onclick="downloadResults()">
                    Download JSONL
                </button>
            </div>
        `;

        document.getElementById('data-stats').innerHTML = html;
    } catch (error) {
        console.error('Failed to load data stats:', error);
    }
}

function showResultsForType(resultType) {
    // Open modal with results filtered by type
    openResultsModal(resultType, null);
}

function downloadResults() {
    // Direct download of JSONL file
    window.location.href = `/api/runs/${runId}/results/export.jsonl`;
}

async function openResultsModal(resultType, isValid) {
    // Show modal with paginated results
    document.getElementById('results-modal').classList.add('active');
    document.getElementById('results-modal-content').innerHTML = 'Loading...';

    let url = `/api/runs/${runId}/results?limit=20`;
    if (resultType) url += `&result_type=${encodeURIComponent(resultType)}`;
    if (isValid !== null) url += `&is_valid=${isValid}`;

    try {
        const response = await fetch(url);
        const data = await response.json();

        let html = `
            <div class="results-header">
                <span>Showing ${data.items.length} of ${data.total} results</span>
                <button class="btn btn-sm btn-secondary" onclick="downloadFilteredResults('${resultType || ''}', ${isValid})">
                    Download Filtered
                </button>
            </div>
            <div class="results-list">
        `;

        for (const item of data.items) {
            const validClass = item.is_valid ? 'valid' : 'invalid';
            html += `
                <div class="result-item ${validClass}">
                    <div class="result-header">
                        <span class="result-type">${item.result_type}</span>
                        <span class="result-id">#${item.id}</span>
                        <span class="validity ${validClass}">${item.is_valid ? '✓ Valid' : '✗ Invalid'}</span>
                    </div>
                    <pre class="result-data">${escapeHtml(JSON.stringify(item.data, null, 2))}</pre>
                    ${item.validation_errors ? `
                        <div class="validation-errors">
                            <h4>Validation Errors:</h4>
                            <pre>${escapeHtml(JSON.stringify(item.validation_errors, null, 2))}</pre>
                        </div>
                    ` : ''}
                </div>
            `;
        }

        html += '</div>';
        document.getElementById('results-modal-content').innerHTML = html;

    } catch (error) {
        document.getElementById('results-modal-content').innerHTML =
            `<p class="error">Failed to load results: ${error.message}</p>`;
    }
}

function downloadFilteredResults(resultType, isValid) {
    let url = `/api/runs/${runId}/results/export.jsonl`;
    const params = [];
    if (resultType) params.push(`result_type=${encodeURIComponent(resultType)}`);
    if (isValid !== null) params.push(`is_valid=${isValid}`);
    if (params.length > 0) url += '?' + params.join('&');
    window.location.href = url;
}

// Add to initial load
loadDataStats();

// Add to auto-refresh interval
setInterval(() => {
    // ... existing refreshes ...
    loadDataStats();
}, 5000);
```

Add a results modal to the HTML:

```html
<!-- Results Modal -->
<div id="results-modal" class="modal">
    <div class="modal-content" style="max-width: 900px;">
        <div class="modal-header">
            <h2>Results</h2>
            <button class="close-btn" onclick="closeResultsModal()">&times;</button>
        </div>
        <div class="modal-body" id="results-modal-content" style="padding: 1.5rem; max-height: 70vh; overflow-y: auto;">
            Loading...
        </div>
    </div>
</div>
```

### 3.4 UI Templates Update

Update `run_detail.html` to include:

1. **Request Queue Summary**:
   - Summary table as default view
   - Click on cell to open modal with filtered requests
   - Toggle to switch between summary and flat list views

2. **Compression Section**:
   - Per-continuation stats table
   - Train Dict / Recompress buttons per continuation
   - Show dictionary version info

3. **Data Section** (NEW):
   - Summary showing valid/invalid counts by result type
   - Click on type to view results in modal
   - Download JSONL button (all or filtered)

4. **Diagnose Modal**:
   - Select a response to diagnose
   - Show XPath observation tree
   - Show yields list
   - Link to highlight elements in response HTML

---

## 4. Summary: Coverage of DEBUG_WANTS.md

| Want | Solution |
|------|----------|
| "What did the parser yield?" | `diagnose()` returns list of all yields with type and key attributes |
| "Why did parsing stop early?" | `diagnose()` captures errors with full traceback |
| "What XPath/regex matches occurred?" | `XPathObserver.simple_tree()` and `.json()` show all queries with match counts |
| "Show me the actual HTML structure" | `observer_json` provides data for highlighting in UI; combined with existing response viewer |

### Additional Benefits

1. **XSD Validation Endpoint** - Batch validate responses against schema without re-running scraper
2. **Custom XPath Checks** - Quick validation of specific structural assumptions
3. **Request Queue Summary** - Better visibility into where requests are stuck
4. **Compression Stats** - Per-continuation metrics help optimize dictionary training

---

## 5. Implementation Order

1. **Phase 1: XPathObserver** (core infrastructure)
   - Create `xpath_observer.py`
   - Integrate with `CheckedHtmlElement`
   - Unit tests

2. **Phase 2: Diagnose Method** (driver capability)
   - Add `diagnose()` to `LocalDevDriver`
   - Add REST endpoint
   - Integration tests

3. **Phase 3: Web UI - Request Queue** (visibility improvement)
   - Add summary endpoint
   - Update `run_detail.html` with summary table
   - Add modal for filtered requests

4. **Phase 4: Web UI - Compression** (efficiency tooling)
   - Add stats-by-continuation endpoint
   - Update UI with per-continuation stats
   - Add action buttons

5. **Phase 5: Web UI - Data/Results** (data visibility)
   - Add results summary endpoint
   - Add enhanced results list endpoint with validation errors
   - Add JSONL export endpoint with streaming
   - Update UI with Data stats card and results modal

6. **Phase 6: XSD Validation** (structural verification)
   - Add validation endpoints
   - Integration with step metadata
   - UI integration

---

## 6. Open Questions

1. **Regex Observation**: Should `XPathObserver` also capture regex operations? Would require explicit instrumentation of regex calls in scrapers.

2. **Persistence**: Should diagnose results be persisted to DB for historical comparison?

3. **Response HTML Highlighting**: The `observer_json` provides element IDs for highlighting. Should we add a dedicated endpoint that returns the HTML with highlight markers injected?

4. **Performance**: For large responses, XPath observation adds overhead. Should there be a "lightweight" mode that skips sample capture?
