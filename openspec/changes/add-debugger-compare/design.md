# Design: Dry-Run Comparison

## Context

The LocalDevDriver debugger stores complete execution history including responses, requests, and results. When a developer modifies a continuation method, they need to understand what would change without re-running the entire scrape. This feature enables that by replaying stored responses through modified code.

## Goals / Non-Goals

**Goals:**
- Compare new continuation code against stored execution results
- Identify request generation changes (new URLs, modified parameters)
- Identify data extraction changes (field value differences)
- Pair results between old and new runs for comparison
- Enable focused debugging of specific requests

**Non-Goals:**
- Re-execute actual HTTP requests
- Support continuations that depend on external state
- Provide real-time change detection during development
- Replace unit tests for scraper logic

## Decisions

### Decision: DryRunDriver as minimal mock

The `DryRunDriver` will be a minimal implementation that captures yields without network I/O.

**Rationale:** Scraper continuations are generator functions that yield requests/data. By providing a driver that simply collects these yields, we can capture exactly what the continuation would produce without any side effects.

**Implementation:**
```python
class DryRunDriver:
    """Captures continuation output without network execution."""

    def __init__(self, speculation_outcomes: dict[int, bool] | None = None):
        self.captured_requests: list[CapturedRequest] = []
        self.captured_data: list[CapturedData] = []
        self.captured_errors: list[CapturedError] = []
        self._speculation_outcomes = speculation_outcomes or {}

    async def run_continuation(
        self,
        scraper: Any,
        continuation: str,
        response_content: bytes,
        context: ReplayContext,
    ) -> None:
        """Execute continuation and capture all yields."""
        method = getattr(scraper, continuation)
        response = self._build_mock_response(response_content, context)

        try:
            gen = method(response)
            for item in gen:
                if isinstance(item, ParsedData):
                    self.captured_data.append(CapturedData(item.data))
                elif isinstance(item, BaseRequest):
                    self.captured_requests.append(CapturedRequest.from_request(item))
        except Exception as e:
            self.captured_errors.append(CapturedError(type(e).__name__, str(e)))
```

### Decision: Levenshtein distance for result pairing

Use Levenshtein distance on JSON-serialized results to **pair** equivalent items between original and new output before comparison.

**Rationale:**
- Yield order is not guaranteed to be meaningful
- We need to align "corresponding" results before comparing them
- JSON serialization provides stable string representation
- Minimum distance pairing finds the most similar pairs

**Algorithm:**
1. Serialize each result to sorted-key JSON
2. Build a distance matrix between all original and new results
3. Use greedy minimum-distance assignment to pair results:
   - Find the pair with smallest Levenshtein distance
   - Remove both from consideration
   - Repeat until one set is exhausted
4. Paired results: do exact Python dict comparison, report field differences
5. Unpaired original results: "removed" in new code
6. Unpaired new results: "added" in new code

**Example:**
```
Original yields: [DocketEntry(id=1, text="Motion"), DocketEntry(id=2, text="Order")]
New yields: [DocketEntry(id=2, text="Order amended"), DocketEntry(id=1, text="Motion")]

Pairing by Levenshtein:
  Original[0] ↔ New[1] (both have id=1, "Motion")
  Original[1] ↔ New[0] (both have id=2, text differs)

Result:
  Pair 1: Identical
  Pair 2: text changed "Order" → "Order amended"
```

### Decision: Transitive tree via parent_request_id

Traverse child requests using the `parent_request_id` column.

**Rationale:** The database already tracks request ancestry. We can recursively query:
```sql
WITH RECURSIVE children AS (
    SELECT * FROM requests WHERE parent_request_id = ?
    UNION ALL
    SELECT r.* FROM requests r
    JOIN children c ON r.parent_request_id = c.id
)
SELECT * FROM children;
```

### Decision: Terminal step sampling

When `--sample N` is used, sample from terminal requests (those that produced no child requests).

**Rationale:** Terminal requests represent complete execution paths. Sampling them gives representative coverage of the scraper's output, while sampling non-terminal requests would miss downstream effects.

**Implementation:**
```sql
SELECT id FROM requests r
WHERE continuation = ?
AND status = 'completed'
AND NOT EXISTS (
    SELECT 1 FROM requests child
    WHERE child.parent_request_id = r.id
)
ORDER BY RANDOM()
LIMIT ?
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Large databases slow comparison | `--limit` and `--sample` options bound work |
| Impure continuations produce inconsistent results | Document that continuations must be pure; undefined behavior is user's problem |
| Scraper class import may fail | Clear error message pointing to run metadata scraper_name |
| Pairing algorithm O(n*m) for n original, m new results | Acceptable for typical result counts per request; could optimize with Hungarian algorithm if needed |

## Migration Plan

No migration required - this is a new feature adding to the debugger CLI.
