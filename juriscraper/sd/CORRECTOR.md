# Scraper Correction Guide

This document lists common issues to look for and fix when reviewing or revising scrapers.

## JSON Parsing

### Use `json_content` parameter instead of manual parsing

**Bad:**
```python
@step()
def parse_api_response(
    self,
    lxml_tree: CheckedHtmlElement,
    response: Response,
    accumulated_data: dict,
) -> Generator[...]:
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        return

    results = data.get("items", [])
    ...
```

**Good:**
```python
@step()
def parse_api_response(
    self,
    json_content: dict,
    accumulated_data: dict,
) -> Generator[...]:
    results = json_content.get("items", [])
    ...
```

The `@step` decorator automatically injects `json_content: dict` when declared as a parameter. This:
- Eliminates boilerplate try/except blocks
- Removes the need to import `json`
- Removes unused `lxml_tree` and `CheckedHtmlElement` imports for JSON APIs
- Handles JSON parsing errors consistently

### When to use which parameter

| Parameter | Use When |
|-----------|----------|
| `json_content: dict` | Parsing JSON API responses |
| `lxml_tree: CheckedHtmlElement` | Parsing HTML pages |
| `text: str` | Raw text processing |
| `response: Response` | Need URL, headers, or status code |
| `accumulated_data: dict` | Passing data between steps |

## Import Cleanup

After converting to `json_content`, check for and remove unnecessary imports:

```python
# Remove if no longer needed:
import json
from kent.common.checked_html import CheckedHtmlElement
```
