# Change: Add JSON Response Validation via Pydantic Models

## Why

When scraping JSON APIs, responses can change structure without warning. We need a way to document expected API response shapes and validate stored responses post-hoc to identify when APIs have changed. This parallels the existing `xsd` parameter which documents expected HTML/XML structure.

## What Changes

- Add `json_model` parameter to `@step` decorator (parallel to existing `xsd`)
- Store json_model path in `StepMetadata` for retrieval by post-hoc validation tools
- Pydantic response models stored in `api/` subdirectory per scraper (parallel to `xsds/`)
- Add `validate_json_responses()` diagnostic function to SQLManager

**Key architectural point**: Like `xsd`, validation is **never done during scraping**. The decorator captures metadata. Validation is performed post-hoc by SQLManager diagnostic functions after a scrape completes.

## Design Decisions

### Model Path Format
String paths like `"api.publications.PublicationsResponse"` resolved relative to the scraper package. This matches how `xsd` uses relative paths like `"xsds/parse_publications.xsd"`.

### Storage Structure
```
juriscraper/sd/state/alabama/publicportal_alappeals_gov/
├── scraper.py
├── xsds/                          # Existing: HTML/XML structure docs
│   └── parse_publications_list.xsd
└── api/                           # NEW: JSON response models
    └── publications.py            # Pydantic models for API responses
```

### SQLManager Diagnostic Function
```python
async def validate_json_responses(
    self,
    continuation: str,
    model: type[BaseModel]
) -> list[int]:
    """Validate all stored JSON responses for a continuation.

    Returns list of request_ids for responses that failed validation.
    """
```

## Impact

- Affected specs: [scraper-driver](../../specs/scraper-driver/spec.md)
- Affected code:
  - `juriscraper/scraper_driver/common/decorators.py` - Add json_model parameter to @step and StepMetadata
  - `juriscraper/scraper_driver/driver/dev_driver/sql_manager.py` - Add validate_json_responses() method
  - Individual scrapers - Add `api/` directories with Pydantic models as needed
