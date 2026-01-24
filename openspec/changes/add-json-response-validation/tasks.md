# Implementation Tasks

## 1. Decorator Metadata (Core Change)

- [ ] 1.1 Add `json_model: str | None = None` parameter to `StepMetadata` dataclass
- [ ] 1.2 Add `json_model` parameter to `@step` decorator signature
- [ ] 1.3 Pass json_model to StepMetadata in decorator
- [ ] 1.4 Update decorator docstring with json_model documentation

## 2. SQLManager Diagnostic Function

- [ ] 2.1 Add `validate_json_responses(continuation: str, model: type[BaseModel]) -> list[int]` method
- [ ] 2.2 Query responses table for all responses with matching continuation
- [ ] 2.3 Decompress response bodies using existing compression infrastructure
- [ ] 2.4 Parse JSON and validate against provided model
- [ ] 2.5 Return list of request_ids for responses that failed validation

## 3. Tests

- [ ] 3.1 Add test for json_model metadata storage and retrieval via `get_step_metadata()`
- [ ] 3.2 Add test verifying json_model=None by default
- [ ] 3.3 Add test for `validate_json_responses` with valid responses (returns empty list)
- [ ] 3.4 Add test for `validate_json_responses` with invalid responses (returns request_ids)
- [ ] 3.5 Add test for `validate_json_responses` with no responses (returns empty list)

## 4. Example Scraper (Optional)

- [ ] 4.1 Create `api/` directory for one existing JSON API scraper
- [ ] 4.2 Write Pydantic model for an existing API response
- [ ] 4.3 Add `json_model` annotation to corresponding step
