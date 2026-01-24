## ADDED Requirements

### Requirement: Soft Failure Detection for Speculative Requests

The system SHALL provide a mechanism for scrapers to detect hidden error states in HTTP responses that return successful status codes, specifically for speculative request handling.

#### Scenario: Scraper implements fails_successfully check
- **WHEN** a scraper defines a `fails_successfully(response: Response) -> bool` method
- **AND** a `SpeculativeRequest` receives a response
- **THEN** the driver SHALL call `fails_successfully()` with the response before invoking `on_speculation_response`

#### Scenario: Soft failure detected sets status code 555
- **WHEN** `fails_successfully()` returns `False` for a speculative response
- **THEN** the driver SHALL set `response.status_code = 555`
- **AND** then invoke `on_speculation_response` with the modified response

#### Scenario: Successful check preserves response
- **WHEN** `fails_successfully()` returns `True` for a speculative response
- **THEN** the driver SHALL invoke `on_speculation_response` with the response unchanged

#### Scenario: Scraper without fails_successfully override
- **WHEN** a scraper does not override the `fails_successfully` method
- **THEN** the default implementation SHALL return `True` for all responses
- **AND** behavior SHALL be identical to the current system
