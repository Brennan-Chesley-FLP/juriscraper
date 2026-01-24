## MODIFIED Requirements

### Requirement: Step Metadata

The system SHALL allow metadata configuration via decorator arguments.

#### Scenario: Priority override
- **WHEN** `@step(priority=3)` is applied
- **THEN** requests yielded from this method SHALL use priority 3 instead of default

#### Scenario: Encoding specification
- **WHEN** `@step(encoding="latin-1")` is applied
- **THEN** response content SHALL be decoded using latin-1 encoding

#### Scenario: XSD schema reference
- **WHEN** `@step(xsd="xsds/parse_page.xsd")` is applied
- **THEN** the XSD path SHALL be stored in `StepMetadata.xsd`
- **AND** post-hoc validation tools MAY use this to validate stored HTML/XML responses

#### Scenario: JSON model reference
- **WHEN** `@step(json_model="api.publications.PublicationsResponse")` is applied
- **THEN** the model path SHALL be stored in `StepMetadata.json_model`
- **AND** the path SHALL be accessible via `get_step_metadata(method).json_model`
- **AND** post-hoc validation tools MAY use this to validate stored JSON responses against the Pydantic model

#### Scenario: Speculative step configuration
- **WHEN** `@step(speculative=True)` is applied
- **THEN** the step SHALL accept a `speculative_id` parameter
- **AND** consumers MAY configure the starting ID via params

## ADDED Requirements

### Requirement: Post-Hoc JSON Response Validation

The system SHALL provide a diagnostic function on SQLManager to validate stored JSON responses against declared Pydantic models.

#### Scenario: Validate responses for a continuation
- **WHEN** `validate_json_responses(continuation, model)` is called
- **THEN** the function SHALL retrieve all stored responses for that continuation
- **AND** decompress each response body
- **AND** parse each response as JSON
- **AND** validate each JSON document against the provided Pydantic model
- **AND** return a list of `request_id` values for responses that failed validation

#### Scenario: All responses valid
- **WHEN** all stored responses for a continuation validate successfully
- **THEN** the function SHALL return an empty list

#### Scenario: Some responses invalid
- **WHEN** some stored responses fail validation
- **THEN** the function SHALL return the `request_id` for each invalid response
- **AND** validation errors SHALL be accessible for debugging

#### Scenario: No responses for continuation
- **WHEN** no stored responses exist for the specified continuation
- **THEN** the function SHALL return an empty list
